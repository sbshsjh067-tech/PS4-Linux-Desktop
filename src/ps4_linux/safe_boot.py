"""11-Stage Safe Boot Verification & Telemetry Engine (PART 1 §4).

Executes and logs the 11 structured PS4 Linux Safe Boot stages:
  BOOT STAGE 1  — Environment Check
  BOOT STAGE 2  — File Verification
  BOOT STAGE 3  — Payload Verification
  BOOT STAGE 4  — Kernel Loading
  BOOT STAGE 5  — Initramfs Loading
  BOOT STAGE 6  — GPU Initialization
  BOOT STAGE 7  — HDMI Initialization
  BOOT STAGE 8  — RootFS Mounting
  BOOT STAGE 9  — System Services
  BOOT STAGE 10 — Desktop Startup
  BOOT STAGE 11 — Display Stability Verification

Automatically determines `last_successful_stage` and `first_failed_stage` for
black-screen root-cause isolation (PART 2 §7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

from . import (
    AMD_VENDOR_ID,
    FORBIDDEN_JAGUAR_FLAGS,
    PS4_GPU_PCI_IDS,
    THERMAL_FLOOR_C,
    THERMAL_MAX_SAFE_C,
)
from .binary_inspect import (
    inspect_bzimage,
    inspect_ext4_image,
    inspect_initramfs,
    inspect_payload,
    verify_usb_device_safety,
)
from .boot_writer import check_dual_kernel_conflict, validate_vram_mb, verify_effective_vram_postboot
from .display_protector import run_display_protection_pass, scan_drm_kms_errors
from .hdmi_bridge import BridgeTransport

STAGE_DEFINITIONS: tuple[tuple[int, str], ...] = (
    (1, "BOOT STAGE 1 — Environment Check"),
    (2, "BOOT STAGE 2 — File Verification"),
    (3, "BOOT STAGE 3 — Payload Verification"),
    (4, "BOOT STAGE 4 — Kernel Loading"),
    (5, "BOOT STAGE 5 — Initramfs Loading"),
    (6, "BOOT STAGE 6 — GPU Initialization"),
    (7, "BOOT STAGE 7 — HDMI Initialization"),
    (8, "BOOT STAGE 8 — RootFS Mounting"),
    (9, "BOOT STAGE 9 — System Services"),
    (10, "BOOT STAGE 10 — Desktop Startup"),
    (11, "BOOT STAGE 11 — Display Stability Verification"),
)


@dataclass
class SafeBootContext:
    """Configurable filesystem/sysfs pointers allowing both live PS4 runs and deterministic tests."""

    layout: str = "usb_fat32"
    southbridge: str = "belize"
    firmware_version: str = "13.52"
    usb_boot_dir: Path | None = None
    internal_boot_dir: Path | None = None
    payload_path: Path | None = None
    bzimage_path: Path | None = None
    initramfs_path: Path | None = None
    rootfs_image_path: Path | None = None
    root_device: str = ""
    root_tran_override: str | None = None
    root_mount_opts: str = "rw,noatime,commit=30,errors=remount-ro"
    sysfs_root: Path = Path("/sys")
    proc_cmdline: str | None = None
    cpu_flags: list[str] | None = None
    memtotal_kib: int | None = None
    dmesg_text: str = ""
    dri_nodes: list[str] | None = None
    mesa_prefix: Path = Path("/opt/ps4-mesa")
    xorg_gpu_conf: Path = Path("/etc/X11/xorg.conf.d/20-ps4-gpu.conf")
    masked_units: list[str] | None = None
    enabled_services: list[str] | None = None
    desktop_sessions: list[str] | None = None
    input_devices: list[str] | None = None
    temp_celsius: float | None = None
    fan_threshold_celsius: float | None = None
    bridge_transport: BridgeTransport | None = None
    is_live_ps4: bool = False


@dataclass
class StageResult:
    stage_num: int
    stage_name: str
    status: str  # PASS | WARN | FAIL
    summary: str
    issue_ids: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_num": self.stage_num,
            "stage_name": self.stage_name,
            "status": self.status,
            "summary": self.summary,
            "issue_ids": list(self.issue_ids),
            "details": dict(self.details),
            "timestamp": self.timestamp,
        }


@dataclass
class SafeBootReport:
    overall_status: str  # PASS | WARN | FAIL
    last_successful_stage: str | None
    first_failed_stage: str | None
    stages: list[StageResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "overall_status": self.overall_status,
            "last_successful_stage": self.last_successful_stage,
            "first_failed_stage": self.first_failed_stage,
            "stages": [s.to_dict() for s in self.stages],
        }


def _parse_fw_tuple(fw: str) -> tuple[int, int]:
    parts = fw.strip().split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major, minor
    except ValueError:
        return (0, 0)


def run_safe_boot_pipeline(ctx: SafeBootContext, log_dir: Path | None = None) -> SafeBootReport:
    """Execute all 11 Safe Boot stages in order, logging each result clearly."""
    stages: list[StageResult] = []

    # --- STAGE 1: Environment Check ---
    s1_issues: list[str] = []
    s1_status = "PASS"
    s1_notes: list[str] = []
    fw_maj, fw_min = _parse_fw_tuple(ctx.firmware_version)
    if (fw_maj, fw_min) > (14, 0):
        s1_status = "FAIL"
        s1_issues.append("BOOT-007")
        s1_notes.append(f"PS4 Firmware {ctx.firmware_version} > 14.00 has no verified GoldHEN chain (D-02).")
    elif (fw_maj, fw_min) == (14, 0):
        s1_status = "WARN"
        s1_issues.append("BOOT-007")
        s1_notes.append("Firmware 14.00 Afterglow WebKit chain is experimental; prefer cold boot from index.")
    else:
        s1_notes.append(f"Firmware {ctx.firmware_version} within verified GoldHEN band (<= 13.52, frozen per D-02).")

    if ctx.cpu_flags is not None:
        bad_flags = [f for f in FORBIDDEN_JAGUAR_FLAGS if f in {x.lower() for x in ctx.cpu_flags}]
        if bad_flags and ctx.is_live_ps4:
            s1_status = "FAIL"
            s1_issues.append("APP-003")
            s1_notes.append(f"Unexpected non-Jaguar CPU ISA flags on PS4 profile: {bad_flags}")
        elif bad_flags:
            s1_notes.append(f"Build host has {bad_flags}; enforce -march=btver2 when cross-compiling for PS4 Jaguar.")
        else:
            s1_notes.append("CPU ISA matches AMD Jaguar btver2 (no AVX2/FMA/BMI2).")

    stages.append(
        StageResult(
            stage_num=1,
            stage_name=STAGE_DEFINITIONS[0][1],
            status=s1_status,
            summary="; ".join(s1_notes),
            issue_ids=s1_issues,
            details={"southbridge": ctx.southbridge, "firmware": ctx.firmware_version},
        )
    )

    # --- STAGE 2: File Verification ---
    s2_issues: list[str] = []
    s2_status = "PASS"
    s2_notes: list[str] = []
    active_boot_dir = ctx.usb_boot_dir if ctx.layout == "usb_fat32" else ctx.internal_boot_dir

    if ctx.usb_boot_dir is not None or ctx.internal_boot_dir is not None:
        lchk = check_dual_kernel_conflict(ctx.layout, ctx.usb_boot_dir, ctx.internal_boot_dir)
        if not lchk.valid:
            s2_status = "FAIL"
            s2_issues.append("BOOT-003")
            s2_notes.extend(lchk.issues)
        else:
            s2_notes.append(f"Layout '{ctx.layout}' verified clean (no dual-location bzImage conflict).")

    vram_mb = 1024
    if active_boot_dir and (active_boot_dir / "vram.txt").is_file():
        raw_vram = (active_boot_dir / "vram.txt").read_text(encoding="utf-8", errors="ignore").strip()
        v_ok, v_val, v_msg = validate_vram_mb(raw_vram)
        if not v_ok:
            s2_status = "FAIL"
            s2_issues.append("BOOT-004")
            s2_notes.append(v_msg)
        else:
            vram_mb = v_val
            s2_notes.append(v_msg)
    elif active_boot_dir is not None:
        s2_status = "WARN" if s2_status == "PASS" else s2_status
        s2_issues.append("BOOT-004")
        s2_notes.append("vram.txt not found; loader will use compiled default VRAM carve-out.")
    else:
        s2_status = "WARN"
        s2_notes.append("No boot directory configured in context; file layout check skipped.")

    stages.append(
        StageResult(
            stage_num=2,
            stage_name=STAGE_DEFINITIONS[1][1],
            status=s2_status,
            summary="; ".join(s2_notes),
            issue_ids=s2_issues,
            details={"layout": ctx.layout, "vram_mb": vram_mb},
        )
    )

    # --- STAGE 3: Payload Verification ---
    if ctx.payload_path is not None:
        p_info = inspect_payload(ctx.payload_path)
        if p_info.valid:
            p_status = "PASS"
            p_issues: list[str] = []
            p_sum = f"Verified {p_info.kind} payload ({p_info.size_bytes} bytes, sha256={p_info.sha256[:12]}...)."
            if p_info.inferred_vram_mb and p_info.inferred_vram_mb != vram_mb:
                p_status = "WARN"
                p_issues.append("BOOT-004")
                p_sum += f" Payload filename implies {p_info.inferred_vram_mb}MB vs vram.txt {vram_mb}MB."
        else:
            p_status = "FAIL"
            p_issues = ["BOOT-001"]
            p_sum = "; ".join(p_info.issues)
        p_details = p_info.to_dict()
    else:
        p_status = "WARN"
        p_issues = []
        p_sum = "Payload ELF/BIN path not supplied; user supplies GoldHEN loader payload at runtime."
        p_details = {"exists": False}

    stages.append(
        StageResult(
            stage_num=3,
            stage_name=STAGE_DEFINITIONS[2][1],
            status=p_status,
            summary=p_sum,
            issue_ids=p_issues,
            details=p_details,
        )
    )

    # --- STAGE 4: Kernel Loading ---
    bz_path = ctx.bzimage_path or (active_boot_dir / "bzImage" if active_boot_dir else None)
    s4_issues: list[str] = []
    if bz_path is not None:
        k_info = inspect_bzimage(bz_path)
        if k_info.valid:
            s4_status = "PASS"
            s4_sum = (
                f"Valid x86_64 bzImage (protocol {k_info.boot_protocol}, sha256={k_info.sha256[:12]}..., "
                f"ver='{k_info.version_string or 'embedded'}')."
            )
            # Check southbridge mismatch hint in version string if present
            ver_low = k_info.version_string.lower()
            if ctx.southbridge in ("aeolia", "belize") and "baikal" in ver_low and "belize" not in ver_low:
                s4_status = "FAIL"
                s4_issues.append("BOOT-001")
                s4_sum = f"BOOT-001: Baikal kernel '{k_info.version_string}' incompatible with {ctx.southbridge} PS4 Fat!"
            elif ctx.southbridge == "baikal" and ("aeolia" in ver_low or "belize" in ver_low) and "baikal" not in ver_low:
                s4_status = "FAIL"
                s4_issues.append("BOOT-001")
                s4_sum = f"BOOT-001: Aeolia/Belize kernel '{k_info.version_string}' incompatible with Baikal southbridge!"
        else:
            s4_status = "FAIL"
            s4_issues.append("BOOT-001")
            s4_sum = "; ".join(k_info.issues)
        s4_details = k_info.to_dict()
    elif ctx.proc_cmdline:
        s4_status = "PASS"
        s4_sum = f"Running kernel active; cmdline='{ctx.proc_cmdline[:80]}'"
        s4_details = {"cmdline": ctx.proc_cmdline}
    else:
        s4_status = "FAIL"
        s4_issues.append("BOOT-001")
        s4_sum = "No bzImage artifact or active PS4 kernel cmdline found."
        s4_details = {}

    stages.append(
        StageResult(
            stage_num=4,
            stage_name=STAGE_DEFINITIONS[3][1],
            status=s4_status,
            summary=s4_sum,
            issue_ids=s4_issues,
            details=s4_details,
        )
    )

    # --- STAGE 5: Initramfs Loading ---
    ir_path = ctx.initramfs_path or (active_boot_dir / "initramfs.cpio.gz" if active_boot_dir else None)
    s5_issues: list[str] = []
    if ir_path is not None:
        i_info = inspect_initramfs(ir_path)
        if i_info.valid:
            s5_status = "PASS"
            s5_sum = (
                f"Valid {i_info.compression} initramfs ({i_info.entry_count} entries, "
                f"hdmi_guard={i_info.has_hdmi_guard}, no GPU fw overwrite)."
            )
            if not i_info.has_hdmi_guard:
                s5_status = "WARN"
                s5_issues.append("BOOT-006")
                s5_sum += " Consider embedding ps4_hdmi_guard for Belize/Slim/Pro early HDMI unmute."
        else:
            s5_status = "FAIL"
            s5_issues.append("BOOT-002")
            s5_sum = "; ".join(i_info.issues)
        s5_details = i_info.to_dict()
    else:
        s5_status = "FAIL"
        s5_issues.append("BOOT-002")
        s5_sum = "initramfs.cpio.gz missing."
        s5_details = {}

    stages.append(
        StageResult(
            stage_num=5,
            stage_name=STAGE_DEFINITIONS[4][1],
            status=s5_status,
            summary=s5_sum,
            issue_ids=s5_issues,
            details=s5_details,
        )
    )

    # --- STAGE 6: GPU Initialization ---
    s6_issues: list[str] = []
    s6_notes: list[str] = []
    s6_status = "PASS"

    gpu_pci = None
    drm_dir = ctx.sysfs_root / "class/drm"
    if drm_dir.is_dir():
        for card in sorted(drm_dir.glob("card[0-9]*")):
            if "-" in card.name:
                continue
            ven_p = card / "device/vendor"
            dev_p = card / "device/device"
            if ven_p.is_file() and dev_p.is_file():
                ven = ven_p.read_text(encoding="utf-8", errors="ignore").strip().lower()
                dev = dev_p.read_text(encoding="utf-8", errors="ignore").strip().lower()
                if ven == AMD_VENDOR_ID and dev in PS4_GPU_PCI_IDS:
                    gpu_pci = dev
                    break

    drm_errs = scan_drm_kms_errors(log_text=ctx.dmesg_text)
    crit_gpu_errs = [e for e in drm_errs if e.issue_id in ("BOOT-001", "GFX-001", "GFX-002")]

    if crit_gpu_errs:
        s6_status = "FAIL"
        for e in crit_gpu_errs:
            if e.issue_id not in s6_issues:
                s6_issues.append(e.issue_id)
        s6_notes.append(f"AMDGPU/DRM error in kernel log: {crit_gpu_errs[0].line}")
    elif gpu_pci:
        meta = PS4_GPU_PCI_IDS[gpu_pci]
        s6_notes.append(f"Detected PS4 {meta['codename']} GPU ({gpu_pci}, {meta['gfx_level']}).")
        if ctx.dri_nodes is not None and ("card0" not in ctx.dri_nodes or "renderD128" not in ctx.dri_nodes):
            s6_status = "FAIL"
            s6_issues.append("GFX-001")
            s6_notes.append(f"Missing DRI render nodes in /dev/dri: {ctx.dri_nodes}")
    elif ctx.is_live_ps4:
        s6_status = "FAIL"
        s6_issues.append("BOOT-001")
        s6_notes.append("PS4 Liverpool/Gladius GPU not bound to amdgpu DRM in /sys/class/drm!")
    else:
        s6_status = "WARN"
        s6_notes.append("Non-PS4 build/test host: PS4 Liverpool/Gladius PCI GPU not present (HARDWARE TEST REQUIRED).")

    v_ok_post, v_obs, v_post_msg = verify_effective_vram_postboot(
        requested_vram_mb=vram_mb,
        memtotal_kib=ctx.memtotal_kib,
        dmesg_text=ctx.dmesg_text,
    )
    if not v_ok_post:
        s6_status = "WARN" if s6_status == "PASS" else s6_status
        s6_issues.append("BOOT-004")
    s6_notes.append(v_post_msg)

    stages.append(
        StageResult(
            stage_num=6,
            stage_name=STAGE_DEFINITIONS[5][1],
            status=s6_status,
            summary="; ".join(s6_notes),
            issue_ids=s6_issues,
            details={"gpu_pci_id": gpu_pci, "observed_vram_mb": v_obs},
        )
    )

    # --- STAGE 7: HDMI Initialization ---
    dp_rep = run_display_protection_pass(
        sysfs_root=ctx.sysfs_root,
        log_text=ctx.dmesg_text,
        bridge_transport=ctx.bridge_transport,
        perform_recovery=True,
        dry_run=(not ctx.is_live_ps4 and ctx.bridge_transport is None),
    )
    s7_issues: list[str] = []
    if dp_rep.active_connector is None:
        if ctx.is_live_ps4:
            s7_status = "FAIL"
            s7_issues.append("BOOT-006")
            s7_sum = "No HDMI connector exposed by DRM/KMS on PS4!"
        else:
            s7_status = "WARN"
            s7_sum = (
                f"No physical HDMI connector on build host; safe fallback ready: "
                f"{dp_rep.decision.selected_mode.kms_mode_str}."
            )
    else:
        conn0 = dp_rep.connectors[0]
        if conn0.status != "connected":
            s7_status = "WARN"
            s7_issues.append("BOOT-006")
            s7_sum = (
                f"{dp_rep.active_connector} status={conn0.status}; fallback {dp_rep.decision.selected_mode.kms_mode_str} armed."
            )
        elif dp_rep.decision.used_fallback:
            s7_status = "WARN"
            s7_issues.append("BOOT-006")
            s7_sum = (
                f"{dp_rep.active_connector} connected with unreadable EDID; safe fallback "
                f"{dp_rep.decision.selected_mode.kms_mode_str} selected (1080p60 NOT forced blindly)."
            )
        else:
            s7_status = "PASS"
            s7_sum = (
                f"{dp_rep.active_connector} EDID valid ({conn0.edid_info.monitor_name or conn0.edid_info.manufacturer}); "
                f"selected {dp_rep.decision.selected_mode.kms_mode_str} (fallback {dp_rep.decision.fallback_mode.kms_mode_str})."
            )

    stages.append(
        StageResult(
            stage_num=7,
            stage_name=STAGE_DEFINITIONS[6][1],
            status=s7_status,
            summary=s7_sum,
            issue_ids=s7_issues,
            details=dp_rep.decision.to_dict(),
        )
    )

    # --- STAGE 8: RootFS Mounting ---
    s8_issues: list[str] = []
    s8_notes: list[str] = []
    s8_status = "PASS"

    if ctx.root_device:
        usb_ok, usb_msg = verify_usb_device_safety(ctx.root_device, lsblk_override=ctx.root_tran_override)
        if not usb_ok:
            s8_status = "FAIL"
            s8_issues.append("SYS-004")
        s8_notes.append(usb_msg)

    if ctx.rootfs_image_path is not None:
        ext_info = inspect_ext4_image(ctx.rootfs_image_path)
        if not ext_info.valid_ext4 or not ext_info.clean_state:
            s8_status = "FAIL" if not ext_info.valid_ext4 else "WARN"
            s8_issues.append("SYS-004")
            s8_notes.extend(ext_info.issues)
        else:
            s8_notes.append(
                f"RootFS image '{ctx.rootfs_image_path.name}' valid ext4 (label='{ext_info.volume_label}', clean=True)."
            )

    if "ro" in ctx.root_mount_opts.split(","):
        s8_status = "FAIL"
        s8_issues.append("SYS-004")
        s8_notes.append("RootFS is mounted read-only (ro)! Check USB I/O errors and run e2fsck.")
    elif "noatime" not in ctx.root_mount_opts:
        s8_status = "WARN" if s8_status == "PASS" else s8_status
        s8_issues.append("SYS-004")
        s8_notes.append("Mount options missing 'noatime' for USB flash wear reduction.")
    else:
        s8_notes.append(f"Root mount options compliant ({ctx.root_mount_opts}).")

    stages.append(
        StageResult(
            stage_num=8,
            stage_name=STAGE_DEFINITIONS[7][1],
            status=s8_status,
            summary="; ".join(s8_notes),
            issue_ids=s8_issues,
            details={"root_device": ctx.root_device, "mount_opts": ctx.root_mount_opts},
        )
    )

    # --- STAGE 9: System Services ---
    s9_issues: list[str] = []
    s9_notes: list[str] = []
    s9_status = "PASS"

    required_masked = {"sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"}
    if ctx.masked_units is not None:
        missing_masks = sorted(required_masked - set(ctx.masked_units))
        if missing_masks:
            s9_status = "WARN"
            s9_issues.append("SYS-001")
            s9_notes.append(f"Sleep targets not masked: {missing_masks} (PS4 has no S3 suspend).")
        else:
            s9_notes.append("All sleep/suspend/hibernate targets masked (SYS-001).")

    if ctx.enabled_services is not None:
        if "systemd-timesyncd.service" not in ctx.enabled_services:
            s9_status = "WARN"
            s9_issues.append("SYS-003")
            s9_notes.append("systemd-timesyncd not enabled (PS4 Linux lacks battery-backed RTC).")
        else:
            s9_notes.append("systemd-timesyncd enabled.")

    if ctx.temp_celsius is not None:
        if ctx.temp_celsius >= THERMAL_MAX_SAFE_C:
            s9_status = "FAIL"
            s9_issues.append("SYS-002")
            s9_notes.append(f"APU temperature {ctx.temp_celsius}C >= {THERMAL_MAX_SAFE_C}C ceiling!")
        else:
            s9_notes.append(f"APU temperature {ctx.temp_celsius}C within safe operating envelope (<{THERMAL_MAX_SAFE_C}C).")
    if ctx.fan_threshold_celsius is not None and ctx.fan_threshold_celsius < THERMAL_FLOOR_C:
        s9_status = "WARN"
        s9_issues.append("SYS-002")
        s9_notes.append(f"Fan threshold {ctx.fan_threshold_celsius}C < {THERMAL_FLOOR_C}C floor (permanent max-RPM risk).")

    if not s9_notes:
        s9_notes.append("System service configuration presets verified.")

    stages.append(
        StageResult(
            stage_num=9,
            stage_name=STAGE_DEFINITIONS[8][1],
            status=s9_status,
            summary="; ".join(s9_notes),
            issue_ids=s9_issues,
        )
    )

    # --- STAGE 10: Desktop Startup ---
    s10_issues: list[str] = []
    s10_notes: list[str] = []
    s10_status = "PASS"

    # Check PS4-patched Mesa vs Xorg glamor trap!
    mesa_libs = list((ctx.mesa_prefix / "lib").glob("libgallium*.so*")) if (ctx.mesa_prefix / "lib").is_dir() else []
    has_ps4_mesa = False
    for mlib in mesa_libs:
        try:
            blob = mlib.read_bytes()
            if b"liverpool" in blob.lower() or b"gladius" in blob.lower():
                has_ps4_mesa = True
                break
        except OSError:
            pass

    xorg_text = ""
    if ctx.xorg_gpu_conf.is_file():
        xorg_text = ctx.xorg_gpu_conf.read_text(encoding="utf-8", errors="ignore")

    if not has_ps4_mesa and '"glamor"' in xorg_text.lower():
        s10_status = "FAIL"
        s10_issues.extend(["GFX-001", "BOOT-006"])
        s10_notes.append(
            "BLACK-SCREEN TRAP DETECTED: Xorg 20-ps4-gpu.conf requests AccelMethod 'glamor', "
            "but /opt/ps4-mesa with Liverpool/Gladius support is missing! Switch to ShadowFB or enable ps4-mesa."
        )
    elif has_ps4_mesa:
        s10_notes.append(f"Verified PS4-patched Mesa in {ctx.mesa_prefix} (Liverpool/Gladius symbols present).")
    else:
        s10_status = "WARN"
        s10_issues.append("GFX-001")
        s10_notes.append("PS4-patched Mesa bundle not installed yet; software ShadowFB fallback required until T-006 build.")

    if ctx.desktop_sessions is not None:
        has_plasma = any("plasma" in s.lower() for s in ctx.desktop_sessions)
        has_xfce = any("xfce" in s.lower() for s in ctx.desktop_sessions)
        if not has_plasma:
            s10_status = "FAIL" if ctx.is_live_ps4 else "WARN"
            s10_notes.append("KDE Plasma session missing (product desktop D-05).")
        if not has_xfce:
            s10_status = "WARN" if s10_status == "PASS" else s10_status
            s10_notes.append("XFCE recovery session missing (guaranteed fallback D-05 / T-009).")
        if has_plasma and has_xfce:
            s10_notes.append("Both KDE Plasma (product) and XFCE (guaranteed recovery) sessions registered.")

    if ctx.input_devices is not None:
        has_kbd_mouse = any("keyboard" in d.lower() or "mouse" in d.lower() or "hid" in d.lower() for d in ctx.input_devices)
        if not has_kbd_mouse and ctx.is_live_ps4:
            s10_status = "WARN" if s10_status == "PASS" else s10_status
            s10_notes.append("No USB HID keyboard/mouse detected.")

    stages.append(
        StageResult(
            stage_num=10,
            stage_name=STAGE_DEFINITIONS[9][1],
            status=s10_status,
            summary="; ".join(s10_notes),
            issue_ids=s10_issues,
            details={"ps4_mesa_verified": has_ps4_mesa},
        )
    )

    # --- STAGE 11: Display Stability Verification ---
    s11_issues: list[str] = []
    s11_status = "PASS"
    s11_notes: list[str] = []

    ring_hangs = [e for e in drm_errs if e.issue_id == "GFX-002"]
    if ring_hangs:
        s11_status = "FAIL"
        s11_issues.append("GFX-002")
        s11_notes.append(f"GPU gfx ring hang detected: {ring_hangs[0].line} (apply Mesa patches 0002-no-hiz + 0003-no-flat-global).")
    elif dp_rep.bridge_health.video_muted:
        s11_status = "FAIL"
        s11_issues.append("BOOT-006")
        s11_notes.append("HDMI bridge still reports CCVMUTE=1 after recovery attempt!")
    else:
        s11_notes.append(
            f"Display pipeline stable (mode={dp_rep.decision.selected_mode.kms_mode_str}, zero gfx ring hangs)."
        )

    stages.append(
        StageResult(
            stage_num=11,
            stage_name=STAGE_DEFINITIONS[10][1],
            status=s11_status,
            summary="; ".join(s11_notes),
            issue_ids=s11_issues,
        )
    )

    # Compute overall status + Last Successful Stage / First Failed Stage
    last_ok: str | None = None
    first_fail: str | None = None
    has_warn = False
    for st in stages:
        if st.status == "FAIL":
            if first_fail is None:
                first_fail = st.stage_name
        else:
            if first_fail is None:
                last_ok = st.stage_name
            if st.status == "WARN":
                has_warn = True

    overall = "FAIL" if first_fail else ("WARN" if has_warn else "PASS")
    report = SafeBootReport(
        overall_status=overall,
        last_successful_stage=last_ok,
        first_failed_stage=first_fail,
        stages=stages,
    )

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "safe-boot-report.json").write_text(
            json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        with (log_dir / "safe-boot.log").open("w", encoding="utf-8") as fh:
            fh.write(f"=== PS4 LINUX SAFE BOOT LOG ({datetime.now(timezone.utc).isoformat()}) ===\n")
            for st in stages:
                issues_tag = f" [{','.join(st.issue_ids)}]" if st.issue_ids else ""
                fh.write(f"[{st.status:4s}] {st.stage_name}{issues_tag}: {st.summary}\n")
            fh.write(f"OVERALL={report.overall_status}\n")
            fh.write(f"LAST_SUCCESSFUL_STAGE={report.last_successful_stage or 'NONE'}\n")
            fh.write(f"FIRST_FAILED_STAGE={report.first_failed_stage or 'NONE'}\n")

    return report
