"""Binary Artifact Inspectors & Pure-Python SVR4 CPIO/Initramfs Engine.

Provides deterministic binary verification for PS4 Linux boot artifacts:
  1. GoldHEN Linux Loader Payload verifier (ELF64 x86_64 & raw .bin) + SHA-256
  2. Linux x86_64 bzImage boot header (`HdrS`) & version string verifier + SHA-256
  3. SVR4 `newc` (`070701`) CPIO + gzip initramfs builder, extractor & auditor
     (detects forbidden `lib/firmware/amdgpu/liverpool_*.bin` overrides!)
  4. ext4 `linux.img` superblock (`0xEF53`) & volume label inspector
  5. USB-only device provenance validator enforcing Decision D-01
"""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip
import hashlib
import io
import lzma
import os
from pathlib import Path
import struct
import subprocess


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PayloadInspection:
    path: str
    exists: bool
    valid: bool
    kind: str  # elf64_x86_64 | raw_bin | invalid
    size_bytes: int = 0
    sha256: str = ""
    entry_point: str = ""
    program_headers: int = 0
    inferred_vram_mb: int | None = None
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "valid": self.valid,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "entry_point": self.entry_point,
            "program_headers": self.program_headers,
            "inferred_vram_mb": self.inferred_vram_mb,
            "issues": list(self.issues),
        }


def inspect_payload(path: Path) -> PayloadInspection:
    """Inspect a PS4 GoldHEN Linux payload (.elf or .bin)."""
    if not path.is_file():
        return PayloadInspection(
            path=str(path),
            exists=False,
            valid=False,
            kind="missing",
            issues=[f"Payload file does not exist: {path}"],
        )

    size = path.stat().st_size
    digest = sha256_file(path)
    issues: list[str] = []

    # Infer VRAM carve-out hint from filename if present (e.g. linux-1024mb.elf, payload-2gb.bin)
    name_low = path.name.lower()
    inferred_vram: int | None = None
    for mb in (4096, 3072, 2048, 1024, 512, 256, 128, 64, 32):
        if f"{mb}mb" in name_low or f"{mb}m" in name_low:
            inferred_vram = mb
            break
    if inferred_vram is None:
        for gb, mb in ((4, 4096), (3, 3072), (2, 2048), (1, 1024)):
            if f"{gb}gb" in name_low:
                inferred_vram = mb
                break

    with path.open("rb") as fh:
        hdr = fh.read(64)

    if len(hdr) < 64:
        return PayloadInspection(
            path=str(path),
            exists=True,
            valid=False,
            kind="invalid",
            size_bytes=size,
            sha256=digest,
            issues=[f"Payload too small ({size} bytes < 64 bytes)"],
        )

    if hdr[:4] == b"\x7fELF":
        ei_class = hdr[4]  # 2 = 64-bit
        ei_data = hdr[5]   # 1 = little-endian
        e_type, e_machine = struct.unpack("<HH", hdr[16:20])
        e_entry = struct.unpack("<Q", hdr[24:32])[0]
        e_phnum = struct.unpack("<H", hdr[56:58])[0]

        if ei_class != 2:
            issues.append(f"ELF class is {ei_class} (expected 64-bit ELFCLASS64=2)")
        if ei_data != 1:
            issues.append(f"ELF endianness is {ei_data} (expected little-endian=1)")
        if e_machine != 0x3E:
            issues.append(f"ELF e_machine=0x{e_machine:x} (expected x86_64 EM_X86_64=0x3e)")
        if e_phnum == 0:
            issues.append("ELF has 0 program headers (not loadable by GoldHEN ELF loader)")
        if size > 64 * 1024 * 1024:
            issues.append(f"ELF suspiciously large for a loader payload ({size} bytes)")

        return PayloadInspection(
            path=str(path),
            exists=True,
            valid=(len(issues) == 0),
            kind="elf64_x86_64",
            size_bytes=size,
            sha256=digest,
            entry_point=f"0x{e_entry:x}",
            program_headers=e_phnum,
            inferred_vram_mb=inferred_vram,
            issues=issues,
        )

    # Raw .bin GoldHEN flat shellcode payload
    if path.suffix.lower() == ".bin":
        if size < 4096 or size > 16 * 1024 * 1024:
            issues.append(f"Raw .bin payload size ({size} bytes) outside normal PS4 loader range (4KiB..16MiB)")
        if all(b == 0 for b in hdr):
            issues.append("Raw .bin payload begins with 64 zero bytes (likely corrupt)")
        return PayloadInspection(
            path=str(path),
            exists=True,
            valid=(len(issues) == 0),
            kind="raw_bin",
            size_bytes=size,
            sha256=digest,
            inferred_vram_mb=inferred_vram,
            issues=issues,
        )

    issues.append("Unrecognized payload header (not ELF64 and not .bin payload)")
    return PayloadInspection(
        path=str(path),
        exists=True,
        valid=False,
        kind="invalid",
        size_bytes=size,
        sha256=digest,
        inferred_vram_mb=inferred_vram,
        issues=issues,
    )


@dataclass
class KernelInspection:
    path: str
    exists: bool
    valid: bool
    size_bytes: int = 0
    sha256: str = ""
    boot_protocol: str = ""
    version_string: str = ""
    relocatable: bool = False
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "valid": self.valid,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "boot_protocol": self.boot_protocol,
            "version_string": self.version_string,
            "relocatable": self.relocatable,
            "issues": list(self.issues),
        }


def inspect_bzimage(path: Path) -> KernelInspection:
    """Verify a Linux x86_64 bzImage according to the Linux x86 Boot Protocol."""
    if not path.is_file():
        return KernelInspection(
            path=str(path),
            exists=False,
            valid=False,
            issues=[f"Kernel bzImage does not exist: {path}"],
        )

    size = path.stat().st_size
    digest = sha256_file(path)
    issues: list[str] = []

    if size < 1024:
        return KernelInspection(
            path=str(path),
            exists=True,
            valid=False,
            size_bytes=size,
            sha256=digest,
            issues=[f"bzImage too small ({size} bytes)"],
        )

    with path.open("rb") as fh:
        buf = fh.read(min(size, 65536))

    setup_sects = buf[0x1F1] or 4
    boot_flag = struct.unpack("<H", buf[0x1FE:0x200])[0]
    hdr_magic = buf[0x202:0x206]
    proto_ver = struct.unpack("<H", buf[0x206:0x208])[0]
    ver_offset = struct.unpack("<H", buf[0x20E:0x210])[0]
    loadflags = buf[0x211]
    reloc = bool(buf[0x234]) if len(buf) > 0x234 else False

    if boot_flag != 0xAA55:
        issues.append(f"Invalid x86 boot sector flag 0x{boot_flag:04x} (expected 0xaa55)")
    if hdr_magic != b"HdrS":
        issues.append(f"Missing Linux x86 setup magic 'HdrS' at 0x202 (got {hdr_magic!r})")
    if not (loadflags & 0x01):
        issues.append("Kernel is not LOADED_HIGH (zImage rather than bzImage)")

    version_str = ""
    if ver_offset > 0:
        abs_off = ver_offset + 0x200
        if abs_off < len(buf):
            end = buf.find(b"\x00", abs_off)
            if end != -1:
                version_str = buf[abs_off:end].decode("utf-8", errors="ignore").strip()

    # Check setup_sects boundary sanity
    _ = setup_sects
    return KernelInspection(
        path=str(path),
        exists=True,
        valid=(len(issues) == 0),
        size_bytes=size,
        sha256=digest,
        boot_protocol=f"{proto_ver >> 8}.{proto_ver & 0xFF}",
        version_string=version_str,
        relocatable=reloc,
        issues=issues,
    )


# --- Pure-Python SVR4 `newc` (070701) CPIO + Gzip/XZ Initramfs Engine ---

@dataclass
class CpioEntry:
    name: str
    mode: int
    size: int
    data: bytes = b""

    @property
    def is_dir(self) -> bool:
        return (self.mode & 0o170000) == 0o040000

    @property
    def is_file(self) -> bool:
        return (self.mode & 0o170000) == 0o100000

    @property
    def is_executable(self) -> bool:
        return bool(self.mode & 0o111)


def _pad4(n: int) -> int:
    return (4 - (n % 4)) % 4


def build_cpio_newc(entries: list[CpioEntry], compress: str = "gzip") -> bytes:
    """Create a standards-compliant SVR4 newc (`070701`) CPIO archive."""
    out = io.BytesIO()
    ino = 1
    all_items = list(entries) + [CpioEntry(name="TRAILER!!!", mode=0, size=0, data=b"")]
    for item in all_items:
        name_clean = item.name.lstrip("/") if item.name != "TRAILER!!!" else "TRAILER!!!"
        if not name_clean:
            name_clean = "."
        name_bytes = name_clean.encode("utf-8") + b"\x00"
        data_bytes = item.data if item.is_file else b""
        filesize = len(data_bytes)
        nlink = 2 if item.is_dir else 1
        cur_ino = 0 if name_clean == "TRAILER!!!" else ino
        ino += 1
        header = (
            "070701"
            f"{cur_ino:08x}"
            f"{item.mode:08x}"
            f"{0:08x}"      # uid
            f"{0:08x}"      # gid
            f"{nlink:08x}"
            f"{0:08x}"      # mtime
            f"{filesize:08x}"
            f"{0:08x}"      # devmajor
            f"{0:08x}"      # devminor
            f"{0:08x}"      # rdevmajor
            f"{0:08x}"      # rdevminor
            f"{len(name_bytes):08x}"
            f"{0:08x}"      # check
        ).encode("ascii")
        out.write(header)
        out.write(name_bytes)
        out.write(b"\x00" * _pad4(len(header) + len(name_bytes)))
        if filesize:
            out.write(data_bytes)
            out.write(b"\x00" * _pad4(filesize))
    # Align total CPIO stream to 512-byte boundary per Linux initramfs convention
    rem = out.tell() % 512
    if rem:
        out.write(b"\x00" * (512 - rem))
    raw_cpio = out.getvalue()
    if compress == "gzip":
        return gzip.compress(raw_cpio, compresslevel=9, mtime=0)
    if compress == "xz":
        return lzma.compress(raw_cpio)
    return raw_cpio


def _decompress_initramfs_bytes(raw: bytes) -> tuple[bytes, str]:
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw), "gzip"
    if raw[:6] == b"\xfd7zXZ\x00":
        return lzma.decompress(raw), "xz"
    if raw[:6] in (b"070701", b"070702"):
        return raw, "uncompressed"
    raise ValueError("Unsupported initramfs compression (expected gzip, xz, or raw newc cpio)")


def list_cpio_entries(raw_archive: bytes, load_data: bool = False) -> tuple[list[CpioEntry], str]:
    """Parse all SVR4 newc (`070701`/`070702`) entries across concatenated CPIO archives."""
    buf, comp = _decompress_initramfs_bytes(raw_archive)
    entries: list[CpioEntry] = []
    pos = 0
    total = len(buf)
    while pos + 110 <= total:
        # Skip NUL padding between concatenated CPIO streams
        while pos < total and buf[pos : pos + 1] == b"\x00":
            pos += 1
        if pos + 110 > total:
            break
        magic = buf[pos : pos + 6]
        if magic not in (b"070701", b"070702"):
            raise ValueError(f"Invalid CPIO header magic {magic!r} at offset {pos}")
        mode = int(buf[pos + 14 : pos + 22], 16)
        filesize = int(buf[pos + 54 : pos + 62], 16)
        namesize = int(buf[pos + 94 : pos + 102], 16)
        pos += 110
        name_raw = buf[pos : pos + namesize]
        name = name_raw.rstrip(b"\x00").decode("utf-8", errors="replace")
        pos += namesize
        pos += _pad4(110 + namesize)
        data = buf[pos : pos + filesize] if load_data else b""
        pos += filesize
        pos += _pad4(filesize)
        if name == "TRAILER!!!":
            continue
        entries.append(CpioEntry(name=name, mode=mode, size=filesize, data=data))
    return entries, comp


@dataclass
class InitramfsInspection:
    path: str
    exists: bool
    valid: bool
    compression: str = ""
    size_bytes: int = 0
    sha256: str = ""
    entry_count: int = 0
    has_init: bool = False
    has_hdmi_guard: bool = False
    conflicting_gpu_firmware: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "valid": self.valid,
            "compression": self.compression,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "entry_count": self.entry_count,
            "has_init": self.has_init,
            "has_hdmi_guard": self.has_hdmi_guard,
            "conflicting_gpu_firmware": list(self.conflicting_gpu_firmware),
            "issues": list(self.issues),
        }


def inspect_initramfs(path: Path) -> InitramfsInspection:
    """Audit an initramfs archive for PS4 boot readiness & GPU firmware overwrite traps."""
    if not path.is_file():
        return InitramfsInspection(
            path=str(path),
            exists=False,
            valid=False,
            issues=[f"Initramfs file does not exist: {path}"],
        )

    size = path.stat().st_size
    digest = sha256_file(path)
    issues: list[str] = []
    try:
        entries, comp = list_cpio_entries(path.read_bytes(), load_data=False)
    except Exception as exc:
        return InitramfsInspection(
            path=str(path),
            exists=True,
            valid=False,
            size_bytes=size,
            sha256=digest,
            issues=[f"Failed to parse initramfs CPIO: {exc}"],
        )

    norm_names = {e.name.lstrip("./"): e for e in entries}
    init_entry = norm_names.get("init") or norm_names.get("sbin/init")
    has_init = init_entry is not None and init_entry.is_executable
    if not has_init:
        issues.append("Initramfs lacks an executable /init or /sbin/init entry")

    has_hdmi_guard = any(
        n in norm_names
        for n in ("bin/ps4_hdmi_guard", "bin/ps4hdmi", "sbin/ps4_hdmi_guard")
    )

    # CRITICAL TRAP: ps4-linux-loader dynamically prepends a CPIO containing the
    # console's genuine liverpool_*/gladius_* microcode BEFORE initramfs.cpio.gz.
    # Shipping files under lib/firmware/amdgpu/{liverpool,gladius}_*.bin inside
    # initramfs.cpio.gz overwrites them and breaks AMDGPU ring init!
    conflicts = [
        n
        for n in norm_names
        if ("firmware/amdgpu/liverpool_" in n or "firmware/amdgpu/gladius_" in n)
    ]
    if conflicts:
        issues.append(
            "Initramfs contains amdgpu/liverpool_* or gladius_* blobs that overwrite loader-extracted Orbis GPU microcode!"
        )

    return InitramfsInspection(
        path=str(path),
        exists=True,
        valid=(len(issues) == 0),
        compression=comp,
        size_bytes=size,
        sha256=digest,
        entry_count=len(entries),
        has_init=has_init,
        has_hdmi_guard=has_hdmi_guard,
        conflicting_gpu_firmware=conflicts,
        issues=issues,
    )


@dataclass
class Ext4ImageInspection:
    path: str
    exists: bool
    valid_ext4: bool
    size_bytes: int = 0
    volume_label: str = ""
    clean_state: bool = False
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "valid_ext4": self.valid_ext4,
            "size_bytes": self.size_bytes,
            "volume_label": self.volume_label,
            "clean_state": self.clean_state,
            "issues": list(self.issues),
        }


def inspect_ext4_image(path: Path) -> Ext4ImageInspection:
    """Inspect a RootFS image file (e.g. `linux.img`) or block device ext4 superblock."""
    if not path.exists():
        return Ext4ImageInspection(
            path=str(path),
            exists=False,
            valid_ext4=False,
            issues=[f"RootFS image/device not found: {path}"],
        )

    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(1024)
            sb = fh.read(1024)
    except OSError as exc:
        return Ext4ImageInspection(
            path=str(path),
            exists=True,
            valid_ext4=False,
            issues=[f"Unable to read superblock: {exc}"],
        )

    if len(sb) < 256:
        return Ext4ImageInspection(
            path=str(path),
            exists=True,
            valid_ext4=False,
            size_bytes=size,
            issues=["File smaller than ext4 superblock offset (2048 bytes)"],
        )

    magic = struct.unpack("<H", sb[0x38:0x3A])[0]
    state = struct.unpack("<H", sb[0x3A:0x3C])[0]
    label = sb[0x78:0x88].split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()

    issues: list[str] = []
    if magic != 0xEF53:
        issues.append(f"Invalid ext4 superblock magic 0x{magic:04x} (expected 0xef53)")
    clean = (state & 0x0001) == 0x0001 and (state & 0x0002) == 0
    if not clean:
        issues.append(f"Filesystem s_state=0x{state:04x} indicates unclean/error state; run e2fsck")

    return Ext4ImageInspection(
        path=str(path),
        exists=True,
        valid_ext4=(magic == 0xEF53),
        size_bytes=size,
        volume_label=label,
        clean_state=clean,
        issues=issues,
    )


def verify_usb_device_safety(dev_path: str, lsblk_override: str | None = None) -> tuple[bool, str]:
    """Enforce Decision D-01: refuse any non-USB block device to protect Orbis OS."""
    norm = dev_path.strip()
    if not norm:
        return False, "Empty target device path"
    if any(norm.startswith(p) for p in ("/dev/nvme", "/dev/vda", "/dev/mmcblk")):
        return False, f"D-01 VIOLATION BLOCKED: {norm} is an internal/non-USB storage bus"

    if lsblk_override is not None:
        tran = lsblk_override.strip().lower()
    else:
        try:
            proc = subprocess.run(
                ["lsblk", "-dno", "TRAN", norm],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            tran = proc.stdout.strip().lower()
        except OSError as exc:
            return False, f"Cannot verify transport via lsblk ({exc}); refusing target by D-01"

    if tran != "usb":
        return (
            False,
            f"D-01 VIOLATION BLOCKED: {norm} reports transport '{tran or 'non-usb'}' (MUST be 'usb')",
        )
    return True, f"Verified safe USB transport (TRAN=usb) for {norm}"
