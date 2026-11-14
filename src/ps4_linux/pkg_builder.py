"""PS4 Homebrew PKG (`\\x7fCNT`) Staging, Metadata Builder & Integrity Verifier.

Architectural truth enforced by this module:
1. A PS4 `.pkg` (`\\x7fCNT` container installed on Orbis OS under `/user/app/<TITLE_ID>`)
   is an **Orbis OS (FreeBSD 9) Homebrew Application** — typically a PS4 Linux Launcher
   that loads `ps4-linux-loader` + `bzImage` + `initramfs.cpio.gz` via `kexec` to boot
   the external USB Linux Desktop (`PS4LINUX` / `linux.img`, preserving `D-01`).
2. Packing Python/shell diagnostic scripts alone or creating a ZIP/TAR renamed `.pkg` is
   strictly forbidden: Orbis `SceAppInstUtil` requires a valid `\\x7fCNT` header, encrypted
   PFS image (`pfs_image.dat`), binary `sce_sys/param.sfo` (`\\x00PSF`), 512x512 24-bit
   `sce_sys/icon0.png`, Orbis FSELF `eboot.bin` (`4F 15 3D 1D`), and OpenOrbis PRX modules.
3. Sony's Content ID specification strictly requires **36 ASCII characters**:
   `XXYYYY-ABCD12345_00-0123456789ABCDEF` (16-char entitlement label after `_00-`).
   When a user specifies `IV0000-BREW00001_00-PS4LDESKTOP0000.pkg` (15-char label, 35 chars
   total), this module preserves the requested `.pkg` filename on disk while normalizing the
   internal `param.sfo` / `gp4` `CONTENT_ID` to 36 chars (`IV0000-BREW00001_00-PS4LDESKTOP00000`)
   and documenting the normalization explicitly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import zlib

from .binary_inspect import CpioEntry, build_cpio_newc, inspect_bzimage, inspect_initramfs
from .boot_writer import generate_safe_bootargs

SFO_MAGIC = b"\x00PSF"
SFO_VERSION = 0x00000101
SFO_FMT_UTF8 = 0x0204
SFO_FMT_INT32 = 0x0404

ORBIS_FSELF_MAGIC = b"\x4f\x15\x3d\x1d"
PS4_PKG_CNT_MAGIC = b"\x7fCNT"

CONTENT_ID_36_RE = re.compile(r"^([A-Z]{2}[0-9]{4})-([A-Z]{4}[0-9]{5})_00-([A-Z0-9]{16})$")
CONTENT_ID_PREFIX_RE = re.compile(r"^([A-Z]{2}[0-9]{4})-([A-Z]{4}[0-9]{5})_00-([A-Z0-9]{1,16})$")


@dataclass
class ContentIdNormalization:
    requested_stem: str
    normalized_content_id: str
    title_id: str
    was_padded: bool
    note: str


@dataclass
class PrerequisiteItem:
    name: str
    role: str
    path: str
    present: bool
    valid: bool
    detail: str


@dataclass
class StagingReport:
    requested_pkg_filename: str
    content_id_info: ContentIdNormalization
    staging_dir: str
    built_files: list[dict[str, object]] = field(default_factory=list)
    prerequisites: list[PrerequisiteItem] = field(default_factory=list)
    ready_to_build_pkg: bool = False
    pkg_built: bool = False
    pkg_path: str | None = None
    pkg_size_bytes: int = 0
    pkg_sha256: str | None = None
    blocking_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class PkgInspectionResult:
    path: str
    exists: bool
    valid_ps4_pkg: bool
    size_bytes: int = 0
    sha256: str = ""
    magic_hex: str = ""
    content_id: str = ""
    pkg_type: int = 0
    entry_count: int = 0
    header_pkg_size: int = 0
    pfs_image_offset: int = 0
    pfs_image_size: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_ps4_content_id(requested_name_or_id: str) -> ContentIdNormalization:
    """Validate and normalize a PS4 Content ID to the mandatory 36-character Orbis format."""
    stem = requested_name_or_id[:-4] if requested_name_or_id.lower().endswith(".pkg") else requested_name_or_id
    m_exact = CONTENT_ID_36_RE.match(stem)
    if m_exact:
        return ContentIdNormalization(
            requested_stem=stem,
            normalized_content_id=stem,
            title_id=m_exact.group(2),
            was_padded=False,
            note="Content ID matches strict 36-byte Sony Orbis specification.",
        )

    m_short = CONTENT_ID_PREFIX_RE.match(stem)
    if not m_short:
        raise ValueError(
            f"Invalid PS4 Content ID format '{stem}'; expected XXYYYY-ABCD12345_00-<16 ALNUM>."
        )
    service_prefix, title_id, label = m_short.group(1), m_short.group(2), m_short.group(3)
    padded_label = label.ljust(16, "0")
    normalized = f"{service_prefix}-{title_id}_00-{padded_label}"
    return ContentIdNormalization(
        requested_stem=stem,
        normalized_content_id=normalized,
        title_id=title_id,
        was_padded=True,
        note=(
            f"Requested stem '{stem}' is {len(stem)} chars (entitlement '{label}' is {len(label)} chars; "
            f"Orbis SceAppInstUtil requires 16 chars / 36 total). Internal param.sfo/GP4 CONTENT_ID "
            f"normalized to '{normalized}' while preserving outer filename '{stem}.pkg'."
        ),
    )


def build_param_sfo(
    content_id: str = "IV0000-BREW00001_00-PS4LDESKTOP00000",
    title_id: str = "BREW00001",
    title: str = "PS4 Linux Desktop Launcher",
    app_ver: str = "01.00",
    version: str = "01.00",
    system_ver: int = 0x05050000,
) -> bytes:
    """Build a byte-accurate Orbis OS `sce_sys/param.sfo` (`\\x00PSF` v1.1) binary."""
    cid_info = normalize_ps4_content_id(content_id)
    if cid_info.title_id != title_id:
        raise ValueError(f"title_id '{title_id}' does not match content_id '{cid_info.normalized_content_id}'")

    # Orbis SFO specifications: keys MUST be sorted lexicographically in ASCII order.
    # (key, fmt, max_len, value)
    raw_entries: list[tuple[str, int, int, int | str]] = [
        ("APP_TYPE", SFO_FMT_INT32, 4, 1),
        ("APP_VER", SFO_FMT_UTF8, 8, app_ver),
        ("ATTRIBUTE", SFO_FMT_INT32, 4, 0),
        ("CATEGORY", SFO_FMT_UTF8, 4, "gd"),
        ("CONTENT_ID", SFO_FMT_UTF8, 48, cid_info.normalized_content_id),
        ("DOWNLOAD_DATA_SIZE", SFO_FMT_INT32, 4, 0),
        ("FORMAT", SFO_FMT_UTF8, 4, "obs"),
        ("PARENTAL_LEVEL", SFO_FMT_INT32, 4, 1),
        ("PUBTOOLVER", SFO_FMT_UTF8, 8, "05.05"),
        ("SYSTEM_VER", SFO_FMT_INT32, 4, system_ver),
        ("TITLE", SFO_FMT_UTF8, 128, title),
        ("TITLE_ID", SFO_FMT_UTF8, 12, title_id),
        ("VERSION", SFO_FMT_UTF8, 8, version),
    ]
    raw_entries.sort(key=lambda item: item[0])

    key_blob = bytearray()
    data_blob = bytearray()
    index_rows: list[bytes] = []

    for key, fmt, max_len, val in raw_entries:
        key_off = len(key_blob)
        key_blob.extend(key.encode("ascii") + b"\x00")

        data_off = len(data_blob)
        if fmt == SFO_FMT_INT32:
            assert isinstance(val, int)
            encoded = struct.pack("<I", val)
            used_len = 4
            padded = encoded
        elif fmt == SFO_FMT_UTF8:
            assert isinstance(val, str)
            raw_utf8 = val.encode("utf-8") + b"\x00"
            if len(raw_utf8) > max_len:
                raise ValueError(f"SFO key '{key}' exceeds max_len={max_len}")
            used_len = len(raw_utf8)
            padded = raw_utf8.ljust(max_len, b"\x00")
        else:
            raise ValueError(f"Unsupported SFO format 0x{fmt:04x}")

        # 4-byte align each data entry
        while len(padded) % 4 != 0:
            padded += b"\x00"
        data_blob.extend(padded)

        index_rows.append(
            struct.pack(
                "<HHIII",
                key_off,
                fmt,
                used_len,
                max_len,
                data_off,
            )
        )

    while len(key_blob) % 4 != 0:
        key_blob.append(0)

    header_len = 20
    index_len = 16 * len(index_rows)
    key_table_offset = header_len + index_len
    data_table_offset = key_table_offset + len(key_blob)

    header = struct.pack(
        "<4sIIII",
        SFO_MAGIC,
        SFO_VERSION,
        key_table_offset,
        data_table_offset,
        len(index_rows),
    )
    return header + b"".join(index_rows) + bytes(key_blob) + bytes(data_blob)


def parse_param_sfo(data: bytes) -> dict[str, int | str]:
    """Parse and validate a binary Orbis `param.sfo` file."""
    if len(data) < 20 or data[:4] != SFO_MAGIC:
        raise ValueError("Invalid SFO magic (expected \\x00PSF)")
    _, version, key_table_off, data_table_off, count = struct.unpack("<4sIIII", data[:20])
    if version != SFO_VERSION:
        raise ValueError(f"Unexpected SFO version 0x{version:08x}")

    out: dict[str, int | str] = {}
    prev_key = ""
    for i in range(count):
        off = 20 + i * 16
        key_off, fmt, used_len, max_len, data_off = struct.unpack("<HHIII", data[off : off + 16])
        k_start = key_table_off + key_off
        k_end = data.index(b"\x00", k_start)
        key = data[k_start:k_end].decode("ascii")
        if key < prev_key:
            raise ValueError(f"SFO keys not sorted: '{key}' after '{prev_key}'")
        prev_key = key

        d_start = data_table_off + data_off
        if d_start + max_len > len(data):
            raise ValueError(f"SFO data out of bounds for key '{key}'")
        if fmt == SFO_FMT_INT32:
            out[key] = struct.unpack("<I", data[d_start : d_start + 4])[0]
        elif fmt == SFO_FMT_UTF8:
            raw_val = data[d_start : d_start + used_len]
            out[key] = raw_val.rstrip(b"\x00").decode("utf-8")
        else:
            out[key] = data[d_start : d_start + used_len].hex()
    return out


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def build_icon0_png(width: int = 512, height: int = 512) -> bytes:
    """Generate a valid Orbis-compliant 512x512 24-bit RGB non-interlaced PNG (`sce_sys/icon0.png`)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB, non-interlaced
    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)  # filter type 0 (None)
        # Clean PlayStation-blue dark gradient with subtle center badge border
        r_bg = 10 + (y * 18) // height
        g_bg = 28 + (y * 48) // height
        b_bg = 78 + (y * 90) // height
        in_border_y = 96 <= y < (height - 96)
        edge_y = y in (96, 97, height - 98, height - 97)
        row = bytearray(width * 3)
        for x in range(width):
            in_border_x = 96 <= x < (width - 96)
            edge_x = x in (96, 97, width - 98, width - 97)
            if in_border_x and in_border_y and (edge_x or edge_y):
                row[x * 3 : x * 3 + 3] = bytes((0, 200, 255))
            elif in_border_x and in_border_y:
                row[x * 3 : x * 3 + 3] = bytes((18, 44, 112))
            else:
                row[x * 3 : x * 3 + 3] = bytes((r_bg, g_bg, b_bg))
        scanlines.extend(row)

    compressed = zlib.compress(bytes(scanlines), level=9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def build_gp4_xml(
    content_id: str,
    files: list[tuple[str, str]],
    cdate: str = "2026-11-14 00:00:00",
) -> str:
    """Generate a valid LibOrbisPkg / Orbis Publishing Tools `.gp4` project XML."""
    cid_info = normalize_ps4_content_id(content_id)
    lines = [
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
        '<psproject fmt="gp4" version="1000">',
        "  <volume>",
        "    <volume_type>pkg_ps4_app</volume_type>",
        f"    <volume_ts>{cdate}</volume_ts>",
        f'    <package content_id="{cid_info.normalized_content_id}" passcode="00000000000000000000000000000000" storage_type="digital50" app_type="full" />',
        '    <chunk_info chunk_count="1" scenario_count="1">',
        "      <chunks>",
        '        <chunk id="0" layer_no="0" label="Chunk #0" />',
        "      </chunks>",
        '      <scenarios default_id="0">',
        '        <scenario id="0" type="sp" initial_chunk_count="1" label="Scenario #0">0</scenario>',
        "      </scenarios>",
        "    </chunk_info>",
        "  </volume>",
        "  <files img_no=\"0\">",
    ]
    for targ_path, orig_path in sorted(files, key=lambda t: t[0]):
        lines.append(f'    <file targ_path="{targ_path}" orig_path="{orig_path}" />')
    lines.extend(
        [
            "  </files>",
            '  <rootdir>',
            '    <dir targ_name="sce_sys">',
            '      <dir targ_name="about" />',
            "    </dir>",
            '    <dir targ_name="sce_module" />',
            '    <dir targ_name="assets">',
            '      <dir targ_name="boot" />',
            '      <dir targ_name="linux-overlay" />',
            "    </dir>",
            "  </rootdir>",
            "</psproject>",
            "",
        ]
    )
    return "\n".join(lines)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_orbis_fself(path: Path | None) -> tuple[bool, bool, str]:
    if path is None or not path.is_file():
        return False, False, "File missing"
    raw = path.read_bytes()[:32]
    if len(raw) >= 4 and raw[:4] == ORBIS_FSELF_MAGIC:
        return True, True, f"Valid Orbis FSELF header (4f153d1d), {path.stat().st_size} bytes"
    return True, False, f"Invalid Orbis FSELF magic (got {raw[:4].hex() if raw else 'empty'}, expected 4f153d1d)"


def inspect_ps4_pkg(pkg_path: Path) -> PkgInspectionResult:
    """Verify binary integrity of a real PS4 `.pkg` (`\\x7fCNT` format), rejecting ZIP/ELF/dummy files."""
    if not pkg_path.is_file():
        return PkgInspectionResult(
            path=str(pkg_path),
            exists=False,
            valid_ps4_pkg=False,
            errors=["PKG file does not exist"],
        )

    size = pkg_path.stat().st_size
    sha = _sha256_file(pkg_path)
    with pkg_path.open("rb") as fh:
        hdr = fh.read(0x440)

    magic_hex = hdr[:4].hex() if len(hdr) >= 4 else ""
    errors: list[str] = []

    if len(hdr) < 0x440:
        errors.append(f"File too small ({size} bytes) to contain a valid 0x440-byte PS4 CNT header")
        return PkgInspectionResult(
            path=str(pkg_path),
            exists=True,
            valid_ps4_pkg=False,
            size_bytes=size,
            sha256=sha,
            magic_hex=magic_hex,
            errors=errors,
        )

    if hdr[:4] != PS4_PKG_CNT_MAGIC:
        if hdr[:4] == b"PK\x03\x04":
            errors.append("File is a ZIP archive (PK\\x03\\x04), NOT a PS4 CNT PKG (\\x7fCNT)!")
        elif hdr[:4] == b"\x7fELF":
            errors.append("File is a raw ELF binary (\\x7fELF), NOT a PS4 CNT PKG (\\x7fCNT)!")
        else:
            errors.append(f"Invalid PS4 PKG magic 0x{magic_hex} (expected 0x7f434e54 '\\x7fCNT')")

    pkg_type = struct.unpack(">I", hdr[0x04:0x08])[0]
    entry_count = struct.unpack(">I", hdr[0x10:0x14])[0]
    raw_cid = hdr[0x40:0x64].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    # Orbis CNT header field map (verified against LibOrbisPkg `PkgWriter.WriteHeader`):
    #   0x410 u64 pfs_image_offset | 0x418 u64 pfs_image_size | 0x430 u64 package_size
    pfs_image_offset = struct.unpack(">Q", hdr[0x410:0x418])[0]
    pfs_image_size = struct.unpack(">Q", hdr[0x418:0x420])[0]
    header_pkg_size = struct.unpack(">Q", hdr[0x430:0x438])[0]

    if not CONTENT_ID_36_RE.match(raw_cid):
        errors.append(f"Header CONTENT_ID '{raw_cid}' does not match 36-char Sony specification")
    if entry_count == 0:
        errors.append("Header entry_count is 0")
    if header_pkg_size != size:
        errors.append(
            f"Header package_size @0x430 ({header_pkg_size}) does not match actual file size ({size})"
        )
    if pfs_image_size == 0:
        errors.append("Header pfs_image_size @0x418 is 0 (no encrypted PFS payload)")
    elif pfs_image_offset + pfs_image_size > size:
        errors.append(
            f"Outer PFS image [{pfs_image_offset}, {pfs_image_offset + pfs_image_size}) "
            f"extends past end of file ({size} bytes)"
        )

    return PkgInspectionResult(
        path=str(pkg_path),
        exists=True,
        valid_ps4_pkg=(len(errors) == 0),
        size_bytes=size,
        sha256=sha,
        magic_hex=magic_hex,
        content_id=raw_cid,
        pkg_type=pkg_type,
        entry_count=entry_count,
        header_pkg_size=header_pkg_size,
        pfs_image_offset=pfs_image_offset,
        pfs_image_size=pfs_image_size,
        errors=errors,
    )


def stage_and_optionally_build_pkg(
    repo_root: Path,
    staging_dir: Path,
    requested_pkg_name: str = "IV0000-BREW00001_00-PS4LDESKTOP0000.pkg",
    output_pkg_path: Path | None = None,
    cuh_model: str = "CUH-1215A",
    vram_mb: int = 1024,
    eboot_path: Path | None = None,
    libc_prx_path: Path | None = None,
    libfios_prx_path: Path | None = None,
    right_sprx_path: Path | None = None,
    bzimage_path: Path | None = None,
    payload_path: Path | None = None,
    linux_img_path: Path | None = None,
    pkgtool_bin: str | None = None,
) -> StagingReport:
    """Stage all real repository components and build the PKG ONLY if all mandatory binaries exist."""
    cid_info = normalize_ps4_content_id(requested_pkg_name)
    staging_dir.mkdir(parents=True, exist_ok=True)

    sce_sys = staging_dir / "sce_sys"
    sce_about = sce_sys / "about"
    sce_mod = staging_dir / "sce_module"
    boot_dir = staging_dir / "assets" / "boot"
    overlay_dir = staging_dir / "assets" / "linux-overlay"
    for d in (sce_sys, sce_about, sce_mod, boot_dir, overlay_dir):
        d.mkdir(parents=True, exist_ok=True)

    built_files: list[dict[str, object]] = []
    gp4_entries: list[tuple[str, str]] = []

    def _record(path: Path, targ_path: str | None = None) -> None:
        built_files.append(
            {
                "path": str(path.relative_to(staging_dir)),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
        if targ_path:
            gp4_entries.append((targ_path, str(path.relative_to(staging_dir))))

    # 1. Real binary sce_sys/param.sfo
    sfo_bytes = build_param_sfo(
        content_id=cid_info.normalized_content_id,
        title_id=cid_info.title_id,
        title="PS4 Linux Desktop Launcher",
    )
    sfo_path = sce_sys / "param.sfo"
    sfo_path.write_bytes(sfo_bytes)
    _record(sfo_path, "sce_sys/param.sfo")

    # 2. Real 512x512 24-bit sce_sys/icon0.png
    icon_path = sce_sys / "icon0.png"
    icon_path.write_bytes(build_icon0_png(512, 512))
    _record(icon_path, "sce_sys/icon0.png")

    # 3. Real initramfs.cpio.gz from repository initramfs/ tree (excluding C source dir)
    initramfs_src = repo_root / "initramfs"
    initramfs_out = boot_dir / "initramfs.cpio.gz"
    cpio_entries: list[CpioEntry] = []
    for root, dirs, files in os.walk(initramfs_src):
        dirs[:] = sorted(d for d in dirs if d != "src")
        files.sort()
        rel_root = Path(root).relative_to(initramfs_src).as_posix()
        if rel_root != ".":
            st_d = Path(root).stat()
            cpio_entries.append(CpioEntry(name=rel_root, mode=0o040000 | (st_d.st_mode & 0o777), size=0))
        for fname in files:
            fpath = Path(root) / fname
            rel_f = fpath.relative_to(initramfs_src).as_posix()
            st_f = fpath.stat()
            data = fpath.read_bytes()
            cpio_entries.append(
                CpioEntry(
                    name=rel_f,
                    mode=0o100000 | (st_f.st_mode & 0o777),
                    size=len(data),
                    data=data,
                )
            )
    initramfs_out.write_bytes(build_cpio_newc(cpio_entries, compress="gzip"))
    ir_info = inspect_initramfs(initramfs_out)
    if not ir_info.valid or ir_info.conflicting_gpu_firmware:
        raise RuntimeError(f"Generated initramfs failed safety check: {ir_info.issues}")
    _record(initramfs_out, "assets/boot/initramfs.cpio.gz")

    # 4. Real safe bootargs.txt + vram.txt (1024 MB, no blind 1080p60)
    bootargs_path = boot_dir / "bootargs.txt"
    bootargs_path.write_text(generate_safe_bootargs(root_label="PS4LINUX", rootwait_sec=30) + "\n", encoding="utf-8")
    _record(bootargs_path, "assets/boot/bootargs.txt")

    vram_path = boot_dir / "vram.txt"
    vram_path.write_text(f"{vram_mb}\n", encoding="utf-8")
    _record(vram_path, "assets/boot/vram.txt")

    # 5. Real repository overlay tarball (src, bin, scripts, configs, systemd, patches)
    overlay_tar = overlay_dir / "ps4-desktop-overlay.tar.gz"
    include_dirs = ("src", "bin", "scripts", "configs", "systemd", "patches")
    with tarfile.open(overlay_tar, "w:gz") as tf:
        for rel in include_dirs:
            p = repo_root / rel
            if p.exists():
                tf.add(p, arcname=rel, filter=lambda ti: None if "__pycache__" in ti.name else ti)
    _record(overlay_tar, "assets/linux-overlay/ps4-desktop-overlay.tar.gz")

    # 6. Strict audit of external prerequisites required for a genuine PS4 Linux PKG
    prereqs: list[PrerequisiteItem] = []
    blocking: list[str] = []

    for label, role, candidate, targ in [
        ("eboot.bin", "Orbis OS FSELF launcher executable (OpenOrbis)", eboot_path, "eboot.bin"),
        ("sce_module/libc.prx", "Orbis userland C runtime PRX module", libc_prx_path, "sce_module/libc.prx"),
        ("sce_module/libSceFios2.prx", "Orbis file I/O PRX module", libfios_prx_path, "sce_module/libSceFios2.prx"),
        ("sce_sys/about/right.sprx", "Orbis package license SPRX module", right_sprx_path, "sce_sys/about/right.sprx"),
    ]:
        present, valid, detail = _check_orbis_fself(candidate)
        prereqs.append(
            PrerequisiteItem(
                name=label,
                role=role,
                path=str(candidate) if candidate else "(not provided)",
                present=present,
                valid=valid,
                detail=detail,
            )
        )
        if present and valid and candidate is not None:
            dst = staging_dir / targ
            shutil.copy2(candidate, dst)
            _record(dst, targ)
        else:
            blocking.append(f"Missing valid {label} ({role}): {detail}")

    # Kernel bzImage check
    if bzimage_path and bzimage_path.is_file():
        bz_info = inspect_bzimage(bzimage_path)
        prereqs.append(
            PrerequisiteItem(
                name="bzImage",
                role=f"Compiled PS4 Fat Linux Kernel ({cuh_model})",
                path=str(bzimage_path),
                present=True,
                valid=bz_info.valid,
                detail=f"version={bz_info.version_string}" if bz_info.valid else "; ".join(bz_info.issues),
            )
        )
        if bz_info.valid:
            dst = boot_dir / "bzImage"
            shutil.copy2(bzimage_path, dst)
            _record(dst, "assets/boot/bzImage")
        else:
            blocking.append(f"Provided bzImage is invalid: {bz_info.issues}")
    else:
        prereqs.append(
            PrerequisiteItem(
                name="bzImage",
                role=f"Compiled PS4 Fat Linux Kernel ({cuh_model})",
                path=str(bzimage_path) if bzimage_path else "(not in repository)",
                present=False,
                valid=False,
                detail="Kernel source/build requires bc, flex, bison, libssl-dev (absent in container)",
            )
        )
        blocking.append("Missing compiled PS4 Linux kernel `bzImage` (feeRnt/ps4-linux-12xx 7.0-Clean)")

    # Payload check
    if payload_path and payload_path.is_file() and payload_path.stat().st_size >= 4096:
        dst = boot_dir / payload_path.name
        shutil.copy2(payload_path, dst)
        _record(dst, f"assets/boot/{payload_path.name}")
        prereqs.append(
            PrerequisiteItem(
                name="ps4-linux-loader payload",
                role="In-kernel Orbis kexec payload + GPU microcode extractor",
                path=str(payload_path),
                present=True,
                valid=True,
                detail=f"{payload_path.stat().st_size} bytes",
            )
        )
    else:
        prereqs.append(
            PrerequisiteItem(
                name="ps4-linux-loader payload",
                role="In-kernel Orbis kexec payload + GPU microcode extractor",
                path=str(payload_path) if payload_path else "(not in repository)",
                present=False,
                valid=False,
                detail="Not bundled in repository (per research/11-risks-legal.md §5)",
            )
        )
        blocking.append("Missing `ps4-linux-loader` Orbis kexec payload binary")

    # RootFS / linux.img check (architectural requirement for complete Linux Desktop)
    if linux_img_path and linux_img_path.is_file() and linux_img_path.stat().st_size >= 512 * 1024 * 1024:
        prereqs.append(
            PrerequisiteItem(
                name="linux.img (KDE Plasma + Patched Mesa RootFS)",
                role="Complete PS4 Linux Desktop ext4 root filesystem (external USB per D-01)",
                path=str(linux_img_path),
                present=True,
                valid=True,
                detail=f"{linux_img_path.stat().st_size} bytes",
            )
        )
    else:
        prereqs.append(
            PrerequisiteItem(
                name="linux.img (KDE Plasma + Patched Mesa RootFS)",
                role="Complete PS4 Linux Desktop ext4 root filesystem (external USB per D-01)",
                path=str(linux_img_path) if linux_img_path else "(not in repository)",
                present=False,
                valid=False,
                detail="Multi-GB Debian/Arch KDE Plasma + /opt/ps4-mesa rootfs absent; never faked with diagnostic scripts alone",
            )
        )
        blocking.append(
            "Missing complete KDE Plasma + patched `/opt/ps4-mesa` Linux RootFS (`linux.img` / USB `PS4LINUX`)"
        )

    # PkgTool.Core / orbis-pub-cmd check
    resolved_tool = shutil.which(pkgtool_bin) if pkgtool_bin else (
        shutil.which("PkgTool.Core") or shutil.which("orbis-pub-cmd")
    )
    prereqs.append(
        PrerequisiteItem(
            name="PkgTool.Core / orbis-pub-cmd",
            role="PS4 PFS + \\x7fCNT fPKG compiler",
            path=resolved_tool or "(not installed)",
            present=bool(resolved_tool),
            valid=bool(resolved_tool),
            detail="Installed" if resolved_tool else "Neither PkgTool.Core (.NET) nor orbis-pub-cmd is installed in sandbox",
        )
    )
    if not resolved_tool:
        blocking.append("Missing PS4 PKG compiler (`PkgTool.Core` / `orbis-pub-cmd`) to encrypt PFS & sign `\\x7fCNT`")

    # 7. Write pkg.gp4 project file & staging-manifest.json
    gp4_path = staging_dir / "pkg.gp4"
    gp4_path.write_text(build_gp4_xml(cid_info.normalized_content_id, gp4_entries), encoding="utf-8")
    _record(gp4_path, None)

    ready = len(blocking) == 0
    pkg_built = False
    final_pkg_str: str | None = None
    pkg_size = 0
    pkg_sha: str | None = None

    if ready and resolved_tool and output_pkg_path is not None:
        output_pkg_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = output_pkg_path.parent
        proc = subprocess.run(
            [resolved_tool, "pkg_build", str(gp4_path), str(tmp_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        generated_default = tmp_dir / f"{cid_info.normalized_content_id}.pkg"
        if proc.returncode == 0 and generated_default.is_file():
            if generated_default.resolve() != output_pkg_path.resolve():
                shutil.move(str(generated_default), str(output_pkg_path))
            insp = inspect_ps4_pkg(output_pkg_path)
            if insp.valid_ps4_pkg:
                pkg_built = True
                final_pkg_str = str(output_pkg_path)
                pkg_size = insp.size_bytes
                pkg_sha = insp.sha256
            else:
                blocking.extend(insp.errors)
        else:
            blocking.append(f"PkgTool.Core failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")

    report = StagingReport(
        requested_pkg_filename=requested_pkg_name,
        content_id_info=cid_info,
        staging_dir=str(staging_dir),
        built_files=built_files,
        prerequisites=prereqs,
        ready_to_build_pkg=ready,
        pkg_built=pkg_built,
        pkg_path=final_pkg_str,
        pkg_size_bytes=pkg_size,
        pkg_sha256=pkg_sha,
        blocking_reasons=blocking,
    )
    manifest_path = staging_dir / "staging-manifest.json"
    manifest_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


def upload_pkg_to_tmpfiles(pkg_path: Path, timeout_sec: int = 60) -> dict[str, object]:
    """Upload a verified PS4 `.pkg` to `https://tmpfiles.org/api/v1/upload` via curl.

    Never fabricates a URL; inspects the real PS4 CNT header before uploading and returns
    exact curl/TLS diagnostics if blocked by firewall.
    """
    insp = inspect_ps4_pkg(pkg_path)
    if not insp.valid_ps4_pkg:
        return {
            "uploaded": False,
            "url": None,
            "direct_url": None,
            "error": f"Refusing to upload invalid/missing PS4 PKG: {'; '.join(insp.errors)}",
        }

    proc = subprocess.run(
        [
            "curl",
            "-sS",
            "--fail-with-body",
            "--connect-timeout",
            "10",
            "--max-time",
            str(timeout_sec),
            "-F",
            f"file=@{pkg_path}",
            "https://tmpfiles.org/api/v1/upload",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "uploaded": False,
            "url": None,
            "direct_url": None,
            "error": f"curl failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}",
        }

    try:
        payload = json.loads(proc.stdout)
        page_url = str(payload.get("data", {}).get("url", ""))
    except json.JSONDecodeError as exc:
        return {
            "uploaded": False,
            "url": None,
            "direct_url": None,
            "error": f"Invalid JSON from tmpfiles.org: {exc}",
        }

    if not page_url.startswith("http"):
        return {
            "uploaded": False,
            "url": None,
            "direct_url": None,
            "error": f"tmpfiles.org did not return a valid URL: {proc.stdout[:200]}",
        }

    direct_url = page_url.replace("http://tmpfiles.org/", "https://tmpfiles.org/dl/").replace(
        "https://tmpfiles.org/", "https://tmpfiles.org/dl/"
    )
    return {
        "uploaded": True,
        "url": page_url,
        "direct_url": direct_url,
        "error": None,
    }
