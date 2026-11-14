"""PS4 Boot File Writer, Kernel Selection Matrix & VRAM Policy Engine (T-002, T-003).

Enforces:
  - D-03: `vram.txt` strictly in MiB against allow-list {32..4096}, default 1024.
  - D-07: Kernel matrix pinned to verified SHAs in `14-pinned-inputs.lock.yaml`.
  - D-08 / BOOT-003: Explicit layout (`usb_fat32` vs `internal_ftp`); refuses any
    configuration where `bzImage` exists in BOTH locations simultaneously.
  - PART 1 §3: Never injects blind `video=HDMI-A-1:1920x1080@60D` unless explicitly
    verified by sink EDID or requested as an opt-in override.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shutil

from . import ALLOWED_VRAM_MB, DEFAULT_DESKTOP_VRAM_MB, PINNED_KERNELS
from .binary_inspect import inspect_bzimage, inspect_initramfs, sha256_file


@dataclass
class KernelCandidate:
    key: str
    repo: str
    branch: str
    commit: str
    version: str
    southbridges: tuple[str, ...]
    fan_driver: str
    mesa_lock: bool


def select_kernel_for_southbridge(southbridge: str, prefer_fallback: bool = False) -> KernelCandidate:
    sb = southbridge.strip().lower()
    if sb == "baikal":
        raw = PINNED_KERNELS["baikal_5_4"]
    elif sb in ("aeolia", "belize"):
        key = "fallback_fat_6_15" if prefer_fallback else "primary_fat_7_0"
        raw = PINNED_KERNELS[key]
    else:
        raise ValueError(f"Unknown PS4 southbridge '{southbridge}' (expected aeolia, belize, or baikal)")

    return KernelCandidate(
        key=raw["id"],
        repo=raw["repo"],
        branch=raw["branch"],
        commit=raw["commit"],
        version=raw["version"],
        southbridges=tuple(raw["southbridges"].split(",")),
        fan_driver=raw["fan_driver"],
        mesa_lock=(raw["mesa_lock"] == "true"),
    )


def validate_vram_mb(value: int | str) -> tuple[bool, int, str]:
    """Validate `vram.txt` value in MiB (catches classic `1`..`4` GB footgun BOOT-004)."""
    raw_str = str(value).strip()
    if not raw_str.isdigit():
        return False, 0, f"BOOT-004: Non-numeric vram.txt value '{raw_str}' (must be integer MiB in {ALLOWED_VRAM_MB})"
    num = int(raw_str)
    if num in (1, 2, 3, 4):
        return (
            False,
            num,
            f"BOOT-004: vram.txt='{num}' uses legacy GB unit! Loader v25+ expects MiB (write '{num * 1024}', not '{num}').",
        )
    if num not in ALLOWED_VRAM_MB:
        return (
            False,
            num,
            f"BOOT-004: vram.txt='{num}' not in allowed MiB set {ALLOWED_VRAM_MB}.",
        )
    return True, num, f"Valid VRAM carve-out: {num} MiB"


def write_vram_file(target_dir: Path, vram_mb: int = DEFAULT_DESKTOP_VRAM_MB) -> Path:
    ok, validated, msg = validate_vram_mb(vram_mb)
    if not ok:
        raise ValueError(msg)
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / "vram.txt"
    out.write_text(f"{validated}\n", encoding="utf-8")
    return out


def verify_effective_vram_postboot(
    requested_vram_mb: int,
    memtotal_kib: int | None = None,
    dmesg_text: str = "",
) -> tuple[bool, int | None, str]:
    """Compare requested VRAM carve-out against effective system RAM / AMDGPU VRAM (T-003)."""
    # 1. Check explicit AMDGPU VRAM log line in dmesg if present (e.g. "amdgpu: 1024M of VRAM memory ready")
    m = re.search(r"amdgpu:.*?\b(\d+)M of VRAM memory ready", dmesg_text, flags=re.IGNORECASE)
    if m:
        observed = int(m.group(1))
        if abs(observed - requested_vram_mb) <= 64:
            return True, observed, f"Effective AMDGPU VRAM ({observed} MiB) matches requested ({requested_vram_mb} MiB)."
        return (
            False,
            observed,
            f"BOOT-004: Effective AMDGPU VRAM is {observed} MiB, expected {requested_vram_mb} MiB!",
        )

    # 2. Estimate from 8192 MiB unified GDDR5 minus MemTotal if on PS4
    if memtotal_kib is not None and 2_000_000 <= memtotal_kib <= 8_200_000:
        sys_ram_mib = memtotal_kib // 1024
        # PS4 Orbis/kernel overhead is ~250..550 MiB in addition to VRAM carve-out
        estimated_vram = max(0, 8192 - sys_ram_mib - 384)
        if abs(estimated_vram - requested_vram_mb) <= 512:
            return (
                True,
                estimated_vram,
                f"System MemTotal={sys_ram_mib} MiB consistent with ~{requested_vram_mb} MiB VRAM carve-out.",
            )
        return (
            False,
            estimated_vram,
            f"BOOT-004: MemTotal={sys_ram_mib} MiB implies ~{estimated_vram} MiB carve-out, mismatching requested {requested_vram_mb} MiB!",
        )

    return True, None, "Post-boot VRAM telemetry unavailable on non-PS4 host (deferred to hardware EXP-001)."


def generate_safe_bootargs(
    verified_hdmi_mode: str | None = None,
    enable_uart: bool = True,
    root_label: str = "PS4KD",
    rootwait_sec: int = 30,
    extra_args: str = "",
) -> str:
    """Generate safe PS4 kernel command line without forcing unverified 1080p@60Hz."""
    parts = [
        "panic=0",
        "clocksource=tsc",
        "consoleblank=0",
        "net.ifnames=0",
        "radeon.dpm=0",
        "amdgpu.dpm=0",
        "drm.debug=0x4",
        "log_buf_len=4M",
        f"ps4_root=LABEL={root_label}",
        f"ps4_rootwait={rootwait_sec}",
    ]
    if enable_uart:
        parts.append("console=uart8250,mmio32,0xd0340000")
        parts.append("console=ttyS0,115200n8")
    parts.append("console=tty0")

    # CRITICAL RULE (PART 1 §3): Only append video=HDMI-A-1:... if mode was verified
    # against sink EDID or safe fallback; NEVER hardcode 1920x1080@60D blindly!
    if verified_hdmi_mode:
        parts.append(f"video=HDMI-A-1:{verified_hdmi_mode}")

    if extra_args.strip():
        parts.append(extra_args.strip())

    return " ".join(parts)


@dataclass
class BootLayoutCheck:
    layout: str
    valid: bool
    usb_bzimage_present: bool
    internal_bzimage_present: bool
    issues: list[str] = field(default_factory=list)


def check_dual_kernel_conflict(
    declared_layout: str,
    usb_boot_dir: Path | None,
    internal_boot_dir: Path | None,
) -> BootLayoutCheck:
    """Enforce Decision D-08 & rewritten BOOT-003: refuse mixed dual-location bzImage."""
    issues: list[str] = []
    if declared_layout not in ("usb_fat32", "internal_ftp"):
        issues.append(
            f"Invalid boot.layout '{declared_layout}' (must be 'usb_fat32' or 'internal_ftp')"
        )

    usb_has = bool(usb_boot_dir and (usb_boot_dir / "bzImage").is_file())
    int_has = bool(internal_boot_dir and (internal_boot_dir / "bzImage").is_file())

    if usb_has and int_has:
        issues.append(
            "BOOT-003 CONFLICT: bzImage exists in BOTH USB PS4BOOT and /data/linux/boot! "
            "Remove the non-authoritative kernel so boot selection is deterministic."
        )
    elif declared_layout == "usb_fat32" and not usb_has:
        issues.append("Declared layout is 'usb_fat32', but bzImage is missing on USB PS4BOOT.")
    elif declared_layout == "internal_ftp" and not int_has:
        issues.append("Declared layout is 'internal_ftp', but bzImage is missing in /data/linux/boot.")

    return BootLayoutCheck(
        layout=declared_layout,
        valid=(len(issues) == 0),
        usb_bzimage_present=usb_has,
        internal_bzimage_present=int_has,
        issues=issues,
    )


def stage_boot_files(
    layout: str,
    southbridge: str,
    bzimage_src: Path,
    initramfs_src: Path,
    dest_dir: Path,
    other_layout_dir: Path | None = None,
    vram_mb: int = DEFAULT_DESKTOP_VRAM_MB,
    verified_hdmi_mode: str | None = None,
    root_label: str = "PS4KD",
) -> dict[str, object]:
    """Validate and write bzImage, initramfs.cpio.gz, bootargs.txt, vram.txt, and kernel.manifest.json."""
    if layout not in ("usb_fat32", "internal_ftp"):
        raise ValueError(f"Unsupported layout '{layout}' (expected usb_fat32 or internal_ftp)")

    if other_layout_dir and (other_layout_dir / "bzImage").is_file():
        raise RuntimeError(
            f"BOOT-003: Refusing to stage boot files while {other_layout_dir / 'bzImage'} exists!"
        )

    k_info = inspect_bzimage(bzimage_src)
    if not k_info.valid:
        raise ValueError(f"Refusing invalid bzImage: {'; '.join(k_info.issues)}")

    i_info = inspect_initramfs(initramfs_src)
    if not i_info.valid:
        raise ValueError(f"Refusing invalid initramfs: {'; '.join(i_info.issues)}")

    cand = select_kernel_for_southbridge(southbridge)
    dest_dir.mkdir(parents=True, exist_ok=True)

    bz_dst = dest_dir / "bzImage"
    ir_dst = dest_dir / "initramfs.cpio.gz"
    shutil.copy2(bzimage_src, bz_dst)
    shutil.copy2(initramfs_src, ir_dst)

    # Post-write SHA-256 readback verification (catches counterfeit/corrupt flash media)
    if sha256_file(bz_dst) != k_info.sha256:
        raise RuntimeError("SHA-256 mismatch after copying bzImage to destination!")
    if sha256_file(ir_dst) != i_info.sha256:
        raise RuntimeError("SHA-256 mismatch after copying initramfs.cpio.gz to destination!")

    bootargs = generate_safe_bootargs(
        verified_hdmi_mode=verified_hdmi_mode,
        root_label=root_label,
    )
    bootargs_dst = dest_dir / "bootargs.txt"
    bootargs_dst.write_text(bootargs + "\n", encoding="utf-8")

    vram_dst = write_vram_file(dest_dir, vram_mb=vram_mb)

    manifest = {
        "layout": layout,
        "southbridge": southbridge,
        "kernel_repo": cand.repo,
        "kernel_branch": cand.branch,
        "kernel_commit": cand.commit,
        "kernel_expected_version": cand.version,
        "bzimage_version_header": k_info.version_string,
        "bzimage_sha256": k_info.sha256,
        "bzimage_size": k_info.size_bytes,
        "initramfs_sha256": i_info.sha256,
        "initramfs_size": i_info.size_bytes,
        "vram_mb": vram_mb,
        "bootargs": bootargs,
    }
    manifest_dst = dest_dir / "kernel.manifest.json"
    manifest_dst.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
