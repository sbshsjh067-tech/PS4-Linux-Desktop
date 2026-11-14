"""PS4 Diagnostic Engine (`ps4-doctor`), Profile Collector (T-001) & Black-Screen Post-Mortem Analyzer.

Implements:
  - PART 2 §7: Inspects all 12 required diagnostic domains + isolates Last Successful
    Boot Stage & First Failed Boot Stage when a Black Screen occurs.
  - Ticket T-001: Hardware & software profile collector with the 3 mandatory additions
    from `research/13-QA-coding-2026-11-13.md` §5 (`boot.layout` + sha256, USB `TRAN`
    provenance, `mesa_build` fingerprint, and separate `image_size_mib` / `idle_ram_mib`).
  - Ticket T-005: `ps4-doctor` ordered symptom -> registry ID (`BOOT/GFX/NET/SYS/APP`)
    checker with human table and `--json` output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

from . import (
    AMD_VENDOR_ID,
    FORBIDDEN_JAGUAR_FLAGS,
    PINNED_MESA,
    PS4_GPU_PCI_IDS,
    THERMAL_MAX_SAFE_C,
)
from .binary_inspect import inspect_bzimage, inspect_ext4_image, inspect_initramfs, sha256_file, verify_usb_device_safety
from .display_protector import run_display_protection_pass, scan_drm_kms_errors
from .safe_boot import STAGE_DEFINITIONS


@dataclass
class DoctorCheck:
    check_id: str
    domain: str
    status: str  # PASS | WARN | FAIL
    blocker: bool
    registry_id: str | None
    message: str
    remediation: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "domain": self.domain,
            "status": self.status,
            "blocker": self.blocker,
            "registry_id": self.registry_id,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class BlackScreenDiagnosis:
    black_screen_detected: bool
    last_successful_stage: str
    first_failed_stage: str
    registry_ids: list[str]
    evidence_lines: list[str]
    recommended_fix: str

    def to_dict(self) -> dict[str, object]:
        return {
            "black_screen_detected": self.black_screen_detected,
            "last_successful_stage": self.last_successful_stage,
            "first_failed_stage": self.first_failed_stage,
            "registry_ids": list(self.registry_ids),
            "evidence_lines": list(self.evidence_lines),
            "recommended_fix": self.recommended_fix,
        }


@dataclass
class DiagnosticReport:
    timestamp: str
    summary_telemetry: dict[str, object]
    checks: list[DoctorCheck]
    black_screen_analysis: BlackScreenDiagnosis | None = None

    @property
    def exit_code(self) -> int:
        return 1 if any(c.status == "FAIL" and c.blocker for c in self.checks) else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "exit_code": self.exit_code,
            "summary_telemetry": dict(self.summary_telemetry),
            "checks": [c.to_dict() for c in self.checks],
            "black_screen_analysis": (
                self.black_screen_analysis.to_dict() if self.black_screen_analysis else None
            ),
        }


def _run_cmd(cmd: list[str], timeout: int = 5) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return (res.stdout or "") + ("\n" + res.stderr if res.stderr and not res.stdout else "")
    except OSError:
        return ""


def analyze_black_screen_logs(log_text: str) -> BlackScreenDiagnosis:
    """Pinpoint Last Successful Stage & First Failed Stage from captured PS4 boot/dmesg logs."""
    lines = [ln.strip() for ln in log_text.splitlines() if ln.strip()]
    evidence: list[str] = []
    reg_ids: list[str] = []

    # Check Stage progression markers in chronological order
    # Stage 4: Kernel started ("Linux version ...")
    saw_kernel = any("Linux version " in ln for ln in lines)
    # Stage 5: Initramfs unpacked ("Unpacking initramfs" or "ps4-linux:" or "Run /init")
    saw_initramfs = any(
        any(tok in ln for tok in ("Unpacking initramfs", "Freeing initrd memory", "ps4-linux:", "Run /init"))
        for ln in lines
    )
    # Stage 6: AMDGPU initialized ("Initialized amdgpu" or "[drm] amdgpu kernel modesetting enabled")
    saw_amdgpu_ok = any("Initialized amdgpu" in ln for ln in lines)
    fw_fail = [ln for ln in lines if re.search(r"Failed to load firmware.*(liverpool|gladius)|Failed to validate ucode", ln, re.I)]
    ring_hang = [ln for ln in lines if re.search(r"ring gfx timeout|GPU reset|amdgpu_job_timedout|illegal instruction", ln, re.I)]
    mesa_lock_err = [ln for ln in lines if "ps4-mesa-lock: kernel mismatch" in ln]

    # Stage 7: HDMI / EDID / ps4_bridge
    edid_err = [ln for ln in lines if re.search(r"EDID checksum is invalid|Cannot find any crtc or sizes|bridge command failed", ln, re.I)]
    bridge_muted = [ln for ln in lines if re.search(r"output was off.*0x1e00|CCVMUTE", ln, re.I)]
    saw_hdmi_ok = any(re.search(r"fb0: amdgpudrmfb frame buffer device|HDMI-A-1:.*connected", ln, re.I) for ln in lines)

    # Stage 8: RootFS mounted
    rootfs_fail = [ln for ln in lines if re.search(r"mounting LABEL=.*failed|rescue shell|EXT4-fs error|Remounting filesystem read-only", ln, re.I)]
    saw_rootfs_ok = any(re.search(r"EXT4-fs .* mounted filesystem|switch_root|systemd\[1\]: systemd .* running", ln, re.I) for ln in lines)

    # Stage 9: System services
    saw_services_ok = any("Reached target" in ln and "Multi-User" in ln for ln in lines) or any("Starting Simple Desktop Display Manager" in ln or "sddm" in ln.lower() for ln in lines)

    # Stage 10: Desktop / Display Manager
    dm_fail = [ln for ln in lines if re.search(r"sddm.*Failed|glamor.*failed|Fatal server error|llvmpipe|Failed to start Simple Desktop Display Manager", ln, re.I)]
    saw_desktop_ok = any(re.search(r"kwin_x11|kwin_wayland|plasmashell.*started|xfce4-session", ln, re.I) for ln in lines)

    if not saw_kernel:
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[2][1],  # Stage 3 Payload
            first_failed_stage=STAGE_DEFINITIONS[3][1],     # Stage 4 Kernel
            registry_ids=["BOOT-001", "BOOT-003"],
            evidence_lines=["No 'Linux version' banner found in captured log (steady white LED / kexec handoff failure)."],
            recommended_fix="Verify southbridge (Aeolia/Belize vs Baikal) matches bzImage (T-002) and check no dual bzImage conflict exists (BOOT-003).",
        )

    if fw_fail:
        evidence.extend(fw_fail[:3])
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[4][1],  # Stage 5 Initramfs
            first_failed_stage=STAGE_DEFINITIONS[5][1],     # Stage 6 GPU Init
            registry_ids=["BOOT-001"],
            evidence_lines=evidence,
            recommended_fix="Remove any conflicting lib/firmware/amdgpu/liverpool_*.bin from initramfs.cpio.gz so loader-extracted Orbis GPU microcode is preserved, and ensure CONFIG_DRM_AMDGPU=y.",
        )

    if not saw_initramfs and not saw_amdgpu_ok:
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[3][1],  # Stage 4 Kernel
            first_failed_stage=STAGE_DEFINITIONS[4][1],     # Stage 5 Initramfs
            registry_ids=["BOOT-002"],
            evidence_lines=lines[-3:] if lines else [],
            recommended_fix="Inspect initramfs.cpio.gz integrity with ps4-initramfs-tool and verify CONFIG_BLK_DEV_INITRD=y.",
        )

    if ring_hang and not saw_desktop_ok:
        evidence.extend(ring_hang[:3])
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[4][1],
            first_failed_stage=STAGE_DEFINITIONS[5][1],
            registry_ids=["GFX-002", "BOOT-001"],
            evidence_lines=evidence,
            recommended_fix="Ensure CONFIG_DRM_AMDGPU=y (built-in, not =m) and amdgpu.dpm=0 in bootargs.txt.",
        )

    if edid_err or (bridge_muted and not saw_hdmi_ok):
        evidence.extend((edid_err + bridge_muted)[:3])
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[5][1],  # Stage 6 GPU Init
            first_failed_stage=STAGE_DEFINITIONS[6][1],     # Stage 7 HDMI Init
            registry_ids=["BOOT-006"],
            evidence_lines=evidence,
            recommended_fix="Run ps4-display-protector --recover (unmutes MN864729 0x1e00/0x705f and selects EDID-safe fallback 1280x720@60Hz; turn HDR & Deep Color OFF in Orbis).",
        )

    if rootfs_fail:
        evidence.extend(rootfs_fail[:3])
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[6][1],  # Stage 7 HDMI Init
            first_failed_stage=STAGE_DEFINITIONS[7][1],     # Stage 8 RootFS
            registry_ids=["BOOT-002", "SYS-004"],
            evidence_lines=evidence,
            recommended_fix="Verify USB ext4 label matches ps4_root=LABEL=PS4KD, increase ps4_rootwait=30, and run e2fsck on USB partition / linux.img.",
        )

    if mesa_lock_err or dm_fail or (saw_rootfs_ok and saw_services_ok and not saw_desktop_ok):
        evidence.extend((mesa_lock_err + dm_fail)[:3])
        reg_ids = ["GFX-001", "BOOT-006"]
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[8][1],  # Stage 9 System Services
            first_failed_stage=STAGE_DEFINITIONS[9][1],     # Stage 10 Desktop Startup
            registry_ids=reg_ids,
            evidence_lines=evidence or ["System reached multi-user/DM stage, but desktop compositor failed to appear."],
            recommended_fix="Run ps4-mesa-select --auto-safe (falls back to ShadowFB if /opt/ps4-mesa absent, or enables /opt/ps4-mesa glamor+DRI3) or switch to XFCE recovery session.",
        )

    if ring_hang and saw_desktop_ok:
        evidence.extend(ring_hang[:3])
        return BlackScreenDiagnosis(
            black_screen_detected=True,
            last_successful_stage=STAGE_DEFINITIONS[9][1],  # Stage 10 Desktop Startup
            first_failed_stage=STAGE_DEFINITIONS[10][1],    # Stage 11 Display Stability
            registry_ids=["GFX-002"],
            evidence_lines=evidence,
            recommended_fix="Install PS4 Mesa 26.2.5 with patches 0002-radv-ps4-no-hiz.patch AND 0003-aco-ps4-no-flat-global.patch, and pin DXVK <= 2.7.1 / Proton <= 11.0.",
        )

    return BlackScreenDiagnosis(
        black_screen_detected=False,
        last_successful_stage=STAGE_DEFINITIONS[10][1],
        first_failed_stage="NONE",
        registry_ids=[],
        evidence_lines=[],
        recommended_fix="All 11 boot stages succeeded with no black-screen signature detected.",
    )


def run_doctor(
    sysfs_root: Path = Path("/sys"),
    glxinfo_override: str | None = None,
    vulkaninfo_override: str | None = None,
    cmdline_override: str | None = None,
    dmesg_override: str | None = None,
    root_tran_override: str | None = None,
    mesa_prefix: Path = Path("/opt/ps4-mesa"),
    usb_boot_dir: Path | None = None,
    rootfs_img_path: Path | None = None,
    firmware_version: str = "13.52",
    goldhen_version: str = "2.4b18.12",
    dxvk_version: str | None = None,
    proton_version: str | None = None,
) -> DiagnosticReport:
    """Run all ordered `ps4-doctor` checks across the 12 diagnostic domains (PART 2 §7 & T-005)."""
    checks: list[DoctorCheck] = []

    kernel_ver = platform.release()
    cmdline = cmdline_override if cmdline_override is not None else (
        Path("/proc/cmdline").read_text(encoding="utf-8", errors="ignore").strip()
        if Path("/proc/cmdline").is_file()
        else ""
    )
    dmesg_txt = dmesg_override if dmesg_override is not None else _run_cmd(["dmesg"])

    # 1. GPU Driver & PCI ID check
    gpu_pci = None
    gpu_driver = "missing"
    drm_dir = sysfs_root / "class/drm"
    if drm_dir.is_dir():
        for card in sorted(drm_dir.glob("card[0-9]*")):
            if "-" in card.name:
                continue
            ven_f = card / "device/vendor"
            dev_f = card / "device/device"
            drv_link = card / "device/driver"
            if ven_f.is_file() and dev_f.is_file():
                ven = ven_f.read_text(encoding="utf-8", errors="ignore").strip().lower()
                dev = dev_f.read_text(encoding="utf-8", errors="ignore").strip().lower()
                if drv_link.exists():
                    try:
                        gpu_driver = os.path.basename(os.readlink(drv_link))
                    except OSError:
                        gpu_driver = "bound"
                if ven == AMD_VENDOR_ID and dev in PS4_GPU_PCI_IDS:
                    gpu_pci = dev
                    break

    if gpu_pci and gpu_driver == "amdgpu":
        checks.append(
            DoctorCheck(
                check_id="GPU_DRIVER",
                domain="GPU Driver & DRM",
                status="PASS",
                blocker=True,
                registry_id=None,
                message=f"PS4 {PS4_GPU_PCI_IDS[gpu_pci]['codename']} ({gpu_pci}) bound to amdgpu.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                check_id="GPU_DRIVER",
                domain="GPU Driver & DRM",
                status="WARN" if gpu_pci is None else "FAIL",
                blocker=(gpu_pci is not None),
                registry_id="BOOT-001",
                message=f"PS4 GPU PCI={gpu_pci or 'not-detected'}, driver={gpu_driver}.",
                remediation="Boot pinned PS4 kernel (feeRnt 7.0-Clean@8ec5c28 or 6.15.4@3cba9d4) with CONFIG_DRM_AMDGPU=y.",
            )
        )

    # 2. OpenGL Renderer (GFX-001: reject llvmpipe!) & Mesa symbols check
    glx_txt = glxinfo_override if glxinfo_override is not None else _run_cmd(["glxinfo", "-B"])
    mesa_has_ps4_ids = False
    if (mesa_prefix / "lib").is_dir():
        for so_file in (mesa_prefix / "lib").glob("libgallium*.so*"):
            try:
                raw_so = so_file.read_bytes().lower()
                if any(tok in raw_so for tok in (b"liverpool", b"gladius", b"9920", b"9923", b"9924")):
                    mesa_has_ps4_ids = True
                    break
            except OSError:
                pass

    if "llvmpipe" in glx_txt.lower() or "softpipe" in glx_txt.lower():
        checks.append(
            DoctorCheck(
                check_id="OPENGL_RENDERER",
                domain="Mesa / OpenGL",
                status="FAIL",
                blocker=True,
                registry_id="GFX-001",
                message="Software rendering detected (llvmpipe)! Stock Mesa lacks PS4 PCI IDs.",
                remediation="Install PS4-patched Mesa in /opt/ps4-mesa and run `sudo ps4-mesa-select --enable` (T-006).",
            )
        )
    elif any(k in glx_txt.upper() for k in ("LIVERPOOL", "GLADIUS")):
        checks.append(
            DoctorCheck(
                check_id="OPENGL_RENDERER",
                domain="Mesa / OpenGL",
                status="PASS",
                blocker=True,
                registry_id=None,
                message="Hardware OpenGL RadeonSI renderer active on Liverpool/Gladius.",
            )
        )
    elif not mesa_has_ps4_ids:
        checks.append(
            DoctorCheck(
                check_id="MESA_BUNDLE_IDS",
                domain="Mesa / OpenGL",
                status="FAIL",
                blocker=True,
                registry_id="GFX-001",
                message=f"No Liverpool/Gladius PCI IDs found under {mesa_prefix}/lib/libgallium-*.so.",
                remediation="Build & install PS4 Mesa 26.2.5 bundle with patches 0001+0002+0003 into /opt/ps4-mesa.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                check_id="MESA_BUNDLE_IDS",
                domain="Mesa / OpenGL",
                status="PASS",
                blocker=False,
                registry_id=None,
                message=f"Verified Liverpool/Gladius symbols in {mesa_prefix}.",
            )
        )

    # 3. ps4-mesa-lock check (7.0-Clean kernel contract)
    if "ps4-mesa-lock: kernel mismatch" in dmesg_txt:
        checks.append(
            DoctorCheck(
                check_id="MESA_KERNEL_LOCK",
                domain="Kernel <-> Mesa Lock",
                status="FAIL",
                blocker=True,
                registry_id="GFX-001",
                message="dmesg reports `ps4-mesa-lock: kernel mismatch`!",
                remediation="Rebuild Mesa and kernel with matching PS4_MESA_LOCK_TOKEN or use matching release pair.",
            )
        )

    # 4. Vulkan ceiling check (GFX-004: <= 1.3)
    vk_txt = vulkaninfo_override if vulkaninfo_override is not None else _run_cmd(["vulkaninfo", "--summary"])
    vk_match = re.search(r"apiVersion\s*=\s*(?:0x[0-9a-fA-F]+\s*\()?(\d+\.\d+)", vk_txt)
    vk_ver = vk_match.group(1) if vk_match else ""
    if vk_ver:
        maj, min_v = [int(x) for x in vk_ver.split(".")[:2]]
        if (maj, min_v) > (1, 3):
            checks.append(
                DoctorCheck(
                    check_id="VULKAN_API",
                    domain="Vulkan / RADV",
                    status="WARN",
                    blocker=False,
                    registry_id="GFX-004",
                    message=f"Vulkan API {vk_ver} > 1.3 (non-GFX7 GPU or spoofed override).",
                    remediation="Never override Vulkan version on PS4 GFX7; ceiling is 1.3.",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    check_id="VULKAN_API",
                    domain="Vulkan / RADV",
                    status="PASS",
                    blocker=False,
                    registry_id=None,
                    message=f"Vulkan API {vk_ver} conformant with PS4 GFX7 ceiling (<= 1.3).",
                )
            )
    else:
        checks.append(
            DoctorCheck(
                check_id="VULKAN_API",
                domain="Vulkan / RADV",
                status="WARN",
                blocker=False,
                registry_id="GFX-004",
                message="vulkaninfo output unavailable.",
                remediation="Install vulkan-tools and verify VK_DRIVER_FILES points to /opt/ps4-mesa radeon_icd.",
            )
        )

    # 5. HDMI, EDID & Display Modes via Display Protection Engine
    dp = run_display_protection_pass(sysfs_root=sysfs_root, log_text=dmesg_txt, perform_recovery=False, dry_run=True)
    if dp.active_connector and not dp.decision.used_fallback:
        checks.append(
            DoctorCheck(
                check_id="HDMI_EDID",
                domain="HDMI & EDID",
                status="PASS",
                blocker=False,
                registry_id=None,
                message=f"{dp.active_connector} EDID valid; safe mode {dp.decision.selected_mode.kms_mode_str}.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                check_id="HDMI_EDID",
                domain="HDMI & EDID",
                status="WARN",
                blocker=False,
                registry_id="BOOT-006",
                message=f"HDMI connector={dp.active_connector or 'none'}; fallback {dp.decision.selected_mode.kms_mode_str} active.",
                remediation="Check HDMI cable, disable PS4 HDR/Deep Color, or run `ps4-display-protector --recover`.",
            )
        )

    # 6. RootFS & D-01 USB-only check
    mounts_txt = Path("/proc/mounts").read_text(encoding="utf-8", errors="ignore") if Path("/proc/mounts").is_file() else ""
    root_dev = "/dev/root"
    root_opts = "rw"
    for ln in mounts_txt.splitlines():
        parts = ln.split()
        if len(parts) >= 4 and parts[1] == "/":
            root_dev, root_opts = parts[0], parts[3]
            break

    usb_ok, usb_msg = verify_usb_device_safety(root_dev, lsblk_override=root_tran_override)
    if "ro" in root_opts.split(","):
        checks.append(
            DoctorCheck(
                check_id="ROOTFS_RW",
                domain="RootFS",
                status="FAIL",
                blocker=True,
                registry_id="SYS-004",
                message=f"Root filesystem {root_dev} is mounted read-only!",
                remediation="Run e2fsck on USB partition / linux.img and mount with noatime,commit=30,errors=remount-ro.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                check_id="ROOTFS_USB",
                domain="RootFS (D-01)",
                status="PASS" if usb_ok else "WARN",
                blocker=False,
                registry_id=None if usb_ok else "SYS-004",
                message=f"{usb_msg}; opts={root_opts}",
                remediation="" if usb_ok else "On PS4 hardware, RootFS MUST reside on USB (TRAN=usb), never internal disk (D-01).",
            )
        )

    if rootfs_img_path is not None:
        img_chk = inspect_ext4_image(rootfs_img_path)
        checks.append(
            DoctorCheck(
                check_id="LINUX_IMG",
                domain="RootFS Image (linux.img)",
                status="PASS" if (img_chk.valid_ext4 and img_chk.clean_state) else "FAIL",
                blocker=not img_chk.valid_ext4,
                registry_id=None if img_chk.valid_ext4 else "SYS-004",
                message=(
                    f"{rootfs_img_path.name}: valid_ext4={img_chk.valid_ext4}, label='{img_chk.volume_label}', clean={img_chk.clean_state}"
                ),
                remediation="; ".join(img_chk.issues),
            )
        )

    # 7. Boot Files (bzImage & initramfs) if usb_boot_dir supplied
    if usb_boot_dir is not None:
        k_chk = inspect_bzimage(usb_boot_dir / "bzImage")
        i_chk = inspect_initramfs(usb_boot_dir / "initramfs.cpio.gz")
        checks.append(
            DoctorCheck(
                check_id="BOOT_ARTIFACTS",
                domain="Kernel & Initramfs",
                status="PASS" if (k_chk.valid and i_chk.valid) else "FAIL",
                blocker=True,
                registry_id=None if (k_chk.valid and i_chk.valid) else "BOOT-001",
                message=f"bzImage.valid={k_chk.valid}, initramfs.valid={i_chk.valid}",
                remediation="; ".join(k_chk.issues + i_chk.issues),
            )
        )

    # 8. DXVK & Proton version pins (D-04 / GFX-004 / APP-001)
    if dxvk_version:
        dx_parts = [int(x) for x in re.findall(r"\d+", dxvk_version)[:3]]
        while len(dx_parts) < 3:
            dx_parts.append(0)
        if tuple(dx_parts) > (2, 7, 1):
            checks.append(
                DoctorCheck(
                    check_id="DXVK_PIN",
                    domain="Steam / D3D Stack",
                    status="FAIL",
                    blocker=True,
                    registry_id="GFX-004",
                    message=f"DXVK {dxvk_version} > 2.7.1! DXVK 3.x requires Vulkan 1.4 which PS4 GFX7 lacks.",
                    remediation="Pin DXVK <= 2.7.1 and Proton <= 11.0 (Decision D-04).",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    check_id="DXVK_PIN",
                    domain="Steam / D3D Stack",
                    status="PASS",
                    blocker=False,
                    registry_id=None,
                    message=f"DXVK {dxvk_version} <= 2.7.1 (Vulkan 1.3 compatible).",
                )
            )

    if proton_version:
        pr_maj = int(re.findall(r"\d+", proton_version)[0]) if re.findall(r"\d+", proton_version) else 0
        if "experimental" in proton_version.lower() or pr_maj > 11:
            checks.append(
                DoctorCheck(
                    check_id="PROTON_PIN",
                    domain="Steam / D3D Stack",
                    status="FAIL",
                    blocker=True,
                    registry_id="APP-001",
                    message=f"Proton '{proton_version}' exceeds pinned Proton 11.0 ceiling!",
                    remediation="Force Proton 11.0 or 9.0-4 in Steam Compatibility settings.",
                )
            )

    # 9. Thermal / Fan visibility (SYS-002)
    hwmon_temps: list[float] = []
    hwmon_root = sysfs_root / "class/hwmon"
    if hwmon_root.is_dir():
        for tfile in hwmon_root.glob("hwmon*/temp1_input"):
            try:
                mc = int(tfile.read_text(encoding="utf-8").strip())
                hwmon_temps.append(mc / 1000.0)
            except (OSError, ValueError):
                pass
    if hwmon_temps:
        max_t = max(hwmon_temps)
        checks.append(
            DoctorCheck(
                check_id="THERMAL_SENSOR",
                domain="Thermal & Fan",
                status="PASS" if max_t < THERMAL_MAX_SAFE_C else "FAIL",
                blocker=(max_t >= THERMAL_MAX_SAFE_C),
                registry_id=None if max_t < THERMAL_MAX_SAFE_C else "SYS-002",
                message=f"hwmon temperature readable: {max_t:.1f}C.",
                remediation="" if max_t < THERMAL_MAX_SAFE_C else "Set ps4-fan temp1_crit=72000 (72C) immediately.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                check_id="THERMAL_SENSOR",
                domain="Thermal & Fan",
                status="WARN",
                blocker=False,
                registry_id="SYS-002",
                message="No hwmon temp1_input sensor exposed on this kernel/host.",
                remediation="Use feeRnt 7.0-Clean kernel with drivers/ps4/ps4-fan.c for hardware thermal telemetry.",
            )
        )

    summary_telemetry: dict[str, object] = {
        "kernel_version": kernel_ver,
        "ps4_firmware_version": firmware_version,
        "goldhen_version": goldhen_version,
        "gpu_pci_id": gpu_pci or "non-ps4",
        "gpu_driver": gpu_driver,
        "drm_active_connector": dp.active_connector,
        "hdmi_supported_resolutions": dp.supported_resolutions,
        "hdmi_supported_refresh_rates": dp.supported_refresh_rates,
        "selected_display_mode": dp.decision.selected_mode.kms_mode_str,
        "fallback_display_mode": dp.decision.fallback_mode.kms_mode_str,
        "boot_arguments": cmdline,
        "drm_error_count": len(dp.drm_errors),
        "pinned_mesa_target": PINNED_MESA["primary"],
    }

    bs_diag = analyze_black_screen_logs(dmesg_txt) if dmesg_txt.strip() else None
    return DiagnosticReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        summary_telemetry=summary_telemetry,
        checks=checks,
        black_screen_analysis=bs_diag,
    )


def _dump_simple_yaml(data: object, indent: int = 0) -> str:
    """Dependency-free clean YAML serializer fallback when PyYAML is absent."""
    try:
        import yaml  # type: ignore
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    except ImportError:
        pass

    pad = "  " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(_dump_simple_yaml(v, indent + 1))
            elif isinstance(v, list):
                lines.append(f"{pad}{k}: []")
            elif isinstance(v, dict):
                lines.append(f"{pad}{k}: {{}}")
            elif isinstance(v, bool):
                lines.append(f"{pad}{k}: {'true' if v else 'false'}")
            elif v is None:
                lines.append(f"{pad}{k}: null")
            elif isinstance(v, (int, float)):
                lines.append(f"{pad}{k}: {v}")
            else:
                lines.append(f"{pad}{k}: {json.dumps(str(v))}")
        return "\n".join(lines)
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_dump_simple_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}- {json.dumps(item) if isinstance(item, str) else item}")
        return "\n".join(lines)
    return f"{pad}{data}"


def collect_console_profile(
    output_yaml: Path,
    output_report_txt: Path,
    layout: str = "usb_fat32",
    bzimage_path: Path | None = None,
    initramfs_path: Path | None = None,
    rootfs_image_path: Path | None = None,
    sysfs_root: Path = Path("/sys"),
    mesa_prefix: Path = Path("/opt/ps4-mesa"),
    root_tran_override: str | None = None,
) -> dict[str, object]:
    """Implement Ticket T-001 (+ 3 additions from 13-QA-coding-2026-11-13.md §5)."""
    cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore") if Path("/proc/cpuinfo").is_file() else ""
    flags_line = next((ln for ln in cpuinfo.splitlines() if ln.lower().startswith("flags")), "")
    flags = set(flags_line.split(":", 1)[1].strip().lower().split()) if ":" in flags_line else set()
    avx2_present = any(f in flags for f in FORBIDDEN_JAGUAR_FLAGS)

    meminfo = Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore") if Path("/proc/meminfo").is_file() else ""
    memtotal_kib = 0
    memavail_kib = 0
    for ln in meminfo.splitlines():
        if ln.startswith("MemTotal:"):
            memtotal_kib = int(re.findall(r"\d+", ln)[0])
        elif ln.startswith("MemAvailable:"):
            memavail_kib = int(re.findall(r"\d+", ln)[0])

    ram_total_gb = round(memtotal_kib / (1024 * 1024), 2) if memtotal_kib else 0.0
    idle_ram_mib = max(0, (memtotal_kib - memavail_kib) // 1024) if memtotal_kib else 0
    image_size_mib = (
        round(rootfs_image_path.stat().st_size / (1024 * 1024), 1)
        if (rootfs_image_path and rootfs_image_path.is_file())
        else None
    )

    # Root device provenance (addition #2 from 13-QA §5)
    mounts = Path("/proc/mounts").read_text(encoding="utf-8", errors="ignore") if Path("/proc/mounts").is_file() else ""
    root_dev = "/dev/root"
    for ln in mounts.splitlines():
        p = ln.split()
        if len(p) >= 2 and p[1] == "/":
            root_dev = p[0]
            break

    lsblk_raw = _run_cmd(["lsblk", "-dno", "TRAN,MODEL", root_dev]).strip()
    usb_ok, usb_msg = verify_usb_device_safety(root_dev, lsblk_override=root_tran_override)

    # GPU & Mesa raw strings (addition #3 from 13-QA §5)
    glx_raw = _run_cmd(["glxinfo", "-B"]).strip()
    vk_raw = _run_cmd(["vulkaninfo", "--summary"]).strip()
    mesa_hit = ""
    if (mesa_prefix / "lib").is_dir():
        for so_file in sorted((mesa_prefix / "lib").glob("libgallium*.so*")):
            try:
                blob = so_file.read_bytes()
                m = re.search(rb"(liverpool|gladius)", blob, flags=re.IGNORECASE)
                if m:
                    mesa_hit = f"{so_file.name}:{m.group(1).decode('ascii', errors='ignore')}"
                    break
            except OSError:
                pass

    gpu_pci = "unknown"
    sb_hint = "belize"
    drm_dir = sysfs_root / "class/drm"
    if drm_dir.is_dir():
        for card in sorted(drm_dir.glob("card[0-9]*")):
            if "-" in card.name:
                continue
            vf, df = card / "device/vendor", card / "device/device"
            if vf.is_file() and df.is_file():
                v = vf.read_text(encoding="utf-8", errors="ignore").strip().lower()
                d = df.read_text(encoding="utf-8", errors="ignore").strip().lower()
                if v == AMD_VENDOR_ID and d in PS4_GPU_PCI_IDS:
                    gpu_pci = f"1002:{d[2:]}"
                    sb_hint = PS4_GPU_PCI_IDS[d]["southbridge_hint"]
                    break

    bz_sha = sha256_file(bzimage_path) if (bzimage_path and bzimage_path.is_file()) else "MISSING"
    ir_sha = sha256_file(initramfs_path) if (initramfs_path and initramfs_path.is_file()) else "MISSING"

    profile: dict[str, object] = {
        "console": {
            "model": "CUH-12xx",
            "family": "fat",
            "southbridge": sb_hint,
            "wifi_bt_chip": "marvell_88w8897",
            "region": "UNSET",
        },
        "firmware": {
            "version": "13.52",
            "jailbreak": "goldhen",
            "goldhen_version": "2.4b18.12",
            "notes": "FROZEN per Decision D-02 — never update firmware.",
        },
        "boot": {
            "layout": layout,
            "bzimage_path": str(bzimage_path) if bzimage_path else None,
            "bzimage_sha256": bz_sha,
            "initramfs_path": str(initramfs_path) if initramfs_path else None,
            "initramfs_sha256": ir_sha,
            "kernel": platform.release(),
            "vram_mb": 1024,
        },
        "software": {
            "mesa_path": str(mesa_prefix),
            "dxvk": "2.7.1",
            "proton": "11.0",
            "plasma": "6.x",
            "session": "x11",
        },
        "hardware_checks": {
            "avx2_present": avx2_present,
            "gpu_pci_id": gpu_pci,
            "mesa_gallium_symbol_hit": mesa_hit or "NOT_FOUND",
            "glxinfo_raw": glx_raw or "UNAVAILABLE",
            "vulkaninfo_raw": vk_raw or "UNAVAILABLE",
            "ram_total_gb": ram_total_gb,
            "idle_ram_mib": idle_ram_mib,
            "image_size_mib": image_size_mib,
            "root_device": root_dev,
            "root_lsblk_tran_model": lsblk_raw or "UNAVAILABLE",
            "root_usb_verified": usb_ok,
            "root_usb_note": usb_msg,
        },
    }

    output_yaml.parent.mkdir(parents=True, exist_ok=True)
    output_yaml.write_text(_dump_simple_yaml(profile) + "\n", encoding="utf-8")

    output_report_txt.parent.mkdir(parents=True, exist_ok=True)
    report_lines = [
        "=== PS4 LINUX DESKTOP — HARDWARE & SOFTWARE PROFILE REPORT (T-001) ===",
        f"Generated UTC     : {datetime.now(timezone.utc).isoformat()}",
        f"Kernel            : {platform.platform()}",
        f"Boot Layout       : {layout}",
        f"bzImage SHA-256   : {bz_sha}",
        f"initramfs SHA-256 : {ir_sha}",
        f"GPU PCI ID        : {gpu_pci}",
        f"AVX2/FMA/BMI2     : {avx2_present} (MUST be False on PS4 Jaguar)",
        f"Total RAM (GiB)   : {ram_total_gb}",
        f"Idle RAM (MiB)    : {idle_ram_mib}",
        f"Image Size (MiB)  : {image_size_mib}",
        f"Root Provenance   : {root_dev} -> {usb_msg}",
        f"Mesa Symbol Hit   : {mesa_hit or 'NOT_FOUND'}",
    ]
    output_report_txt.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return profile
