"""HDMI Display Protection Engine for PS4 Linux Desktop (PART 1 §3).

Implements all 10 required HDMI protection subsystems:
  1. HDMI connector discovery (`/sys/class/drm/card*-HDMI-A-*`)
  2. Binary EDID reading & integrity verification
  3. Supported resolution enumeration
  4. Supported refresh-rate enumeration
  5. Safe compatible mode selection (NEVER blindly forces 1920x1080@60Hz!)
  6. Multi-tier safe fallback cascade (`1280x720@60` -> `1024x768@60` -> `720x480@60` -> `640x480@60`)
  7. Active rejection of unsupported / out-of-range modes (4K, >165 MHz TMDS, >max_vrate_hz)
  8. DRM / KMS / AMDGPU / PS4-Bridge error scanner & structured logger
  9. Continuous HDMI link & MN86471A/MN864729 bridge health monitor
  10. Automated display recovery & mode rollback mechanism
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from . import (
    PS4_FAT_MAX_HEIGHT,
    PS4_FAT_MAX_PIXEL_CLOCK_KHZ,
    PS4_FAT_MAX_REFRESH_HZ,
    PS4_FAT_MAX_WIDTH,
)
from .edid import DisplayMode, EdidInfo, parse_edid
from .hdmi_bridge import BridgeHealth, BridgeTransport, check_and_heal_hdmi_bridge

# Ordered universal fallback cascade when EDID is unreadable or handshake fails
FALLBACK_MODE_CASCADE: tuple[DisplayMode, ...] = (
    DisplayMode(1280, 720, 60, False, False, 74_250, "fallback_tier1_cea_720p60"),
    DisplayMode(1024, 768, 60, False, False, 65_000, "fallback_tier2_vesa_xga60"),
    DisplayMode(720, 480, 60, False, False, 27_000, "fallback_tier3_cea_480p60"),
    DisplayMode(640, 480, 60, False, False, 25_175, "fallback_tier4_safe_vga60"),
)

# Critical DRM / KMS / AMDGPU log patterns mapped to research/06-issues-registry.md IDs
DRM_ERROR_SIGNATURES: tuple[tuple[str, str, str], ...] = (
    (r"ring gfx timeout|GPU reset|amdgpu_job_timedout", "GFX-002", "critical"),
    (r"Failed to load firmware.*(liverpool|gladius)|Failed to validate ucode", "BOOT-001", "critical"),
    (r"ps4-mesa-lock: kernel mismatch", "GFX-001", "critical"),
    (r"EDID checksum is invalid|EDID block .* is all zeroes", "BOOT-006", "high"),
    (r"ps4_bridge.*failed|bridge command failed", "BOOT-006", "high"),
    (r"\*ERROR\*.*(amdgpu|drm|dce|hdmi)", "BOOT-006", "high"),
    (r"Cannot find any crtc or sizes", "BOOT-006", "high"),
)


@dataclass
class ConnectorState:
    name: str
    sysfs_path: str
    status: str  # connected | disconnected | unknown
    enabled: str  # enabled | disabled
    dpms: str  # On | Off | Standby | Suspend
    drm_modes: list[str]
    edid_info: EdidInfo

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "sysfs_path": self.sysfs_path,
            "status": self.status,
            "enabled": self.enabled,
            "dpms": self.dpms,
            "drm_modes": list(self.drm_modes),
            "edid": self.edid_info.to_dict(),
        }


@dataclass
class ModeDecision:
    selected_mode: DisplayMode
    fallback_mode: DisplayMode
    used_fallback: bool
    reason: str
    rejected_modes: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def kernel_video_arg(self) -> str:
        # Never append 'D' (force digital on) if using unverified fallback unless requested;
        # use standard KMS mode specifier without forcing out-of-range clocks.
        m = self.selected_mode
        inter = "i" if m.interlaced else ""
        return f"video=HDMI-A-1:{m.width}x{m.height}{inter}@{m.refresh_hz}"

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_mode": self.selected_mode.kms_mode_str,
            "selected_source": self.selected_mode.source,
            "fallback_mode": self.fallback_mode.kms_mode_str,
            "used_fallback": self.used_fallback,
            "reason": self.reason,
            "kernel_video_arg": self.kernel_video_arg,
            "rejected_modes": list(self.rejected_modes),
            "warnings": list(self.warnings),
        }


@dataclass
class DrmErrorFinding:
    line: str
    issue_id: str
    severity: str


@dataclass
class DisplayProtectionReport:
    timestamp: str
    connectors: list[ConnectorState]
    active_connector: str | None
    supported_resolutions: list[str]
    supported_refresh_rates: list[int]
    decision: ModeDecision
    bridge_health: BridgeHealth
    drm_errors: list[DrmErrorFinding]
    recovery_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "active_connector": self.active_connector,
            "supported_resolutions": list(self.supported_resolutions),
            "supported_refresh_rates": list(self.supported_refresh_rates),
            "connectors": [c.to_dict() for c in self.connectors],
            "decision": self.decision.to_dict(),
            "bridge_health": self.bridge_health.to_dict(),
            "drm_errors": [
                {"issue_id": e.issue_id, "severity": e.severity, "line": e.line}
                for e in self.drm_errors
            ],
            "recovery_actions": list(self.recovery_actions),
        }


def _read_text_safe(p: Path, default: str = "unknown") -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore").strip() or default
    except OSError:
        return default


def discover_hdmi_connectors(sysfs_root: Path = Path("/sys")) -> list[ConnectorState]:
    """Scan `/sys/class/drm` for HDMI (and DP-bridge) connectors and parse their EDID."""
    drm_class = sysfs_root / "class/drm"
    results: list[ConnectorState] = []
    if not drm_class.is_dir():
        return results

    patterns = ("card*-HDMI-A-*", "card*-HDMI-B-*", "card*-DP-*")
    seen_paths: set[Path] = set()
    for pat in patterns:
        for conn in sorted(drm_class.glob(pat)):
            if conn in seen_paths or not conn.is_dir():
                continue
            seen_paths.add(conn)
            status = _read_text_safe(conn / "status", "unknown")
            enabled = _read_text_safe(conn / "enabled", "unknown")
            dpms = _read_text_safe(conn / "dpms", "unknown")
            modes_raw = _read_text_safe(conn / "modes", "")
            drm_modes = [ln.strip() for ln in modes_raw.splitlines() if ln.strip()]
            edid_bytes = b""
            edid_file = conn / "edid"
            if edid_file.is_file():
                try:
                    edid_bytes = edid_file.read_bytes()
                except OSError:
                    edid_bytes = b""
            edid_info = parse_edid(edid_bytes)
            results.append(
                ConnectorState(
                    name=conn.name,
                    sysfs_path=str(conn),
                    status=status,
                    enabled=enabled,
                    dpms=dpms,
                    drm_modes=drm_modes,
                    edid_info=edid_info,
                )
            )
    return results


def _parse_drm_mode_name(raw: str) -> tuple[int, int, bool] | None:
    m = re.match(r"^(\d+)x(\d+)(i?)$", raw.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), (m.group(3) == "i")


def is_mode_safe_for_ps4_fat(
    mode: DisplayMode,
    edid: EdidInfo | None = None,
) -> tuple[bool, str]:
    """Verify a candidate mode against PS4 Fat HDMI 1.4 limits and sink EDID limits."""
    if mode.width > PS4_FAT_MAX_WIDTH or mode.height > PS4_FAT_MAX_HEIGHT:
        return (
            False,
            f"Exceeds PS4 Fat HDMI 1.4 resolution ceiling ({PS4_FAT_MAX_WIDTH}x{PS4_FAT_MAX_HEIGHT})",
        )
    if mode.refresh_hz > PS4_FAT_MAX_REFRESH_HZ:
        return (
            False,
            f"Refresh rate {mode.refresh_hz}Hz exceeds PS4 Fat stable ceiling ({PS4_FAT_MAX_REFRESH_HZ}Hz)",
        )
    if mode.refresh_hz < 24:
        return False, f"Refresh rate {mode.refresh_hz}Hz below minimum HDMI floor (24Hz)"
    if mode.pixel_clock_khz > PS4_FAT_MAX_PIXEL_CLOCK_KHZ:
        return (
            False,
            f"Pixel clock {mode.pixel_clock_khz}kHz exceeds PS4 Fat single-link safe ceiling ({PS4_FAT_MAX_PIXEL_CLOCK_KHZ}kHz)",
        )
    if edid and edid.valid:
        if edid.range_limits:
            rl = edid.range_limits
            if rl.max_vrate_hz > 0 and mode.refresh_hz > rl.max_vrate_hz:
                return (
                    False,
                    f"Refresh rate {mode.refresh_hz}Hz exceeds monitor max V-rate ({rl.max_vrate_hz}Hz)",
                )
            if rl.min_vrate_hz > 0 and mode.refresh_hz < rl.min_vrate_hz:
                return (
                    False,
                    f"Refresh rate {mode.refresh_hz}Hz below monitor min V-rate ({rl.min_vrate_hz}Hz)",
                )
            if rl.max_pixel_clock_mhz > 0 and mode.pixel_clock_khz > (rl.max_pixel_clock_mhz * 1000):
                return (
                    False,
                    f"Pixel clock {mode.pixel_clock_khz // 1000}MHz exceeds monitor limit ({rl.max_pixel_clock_mhz}MHz)",
                )
        if edid.max_tmds_clock_mhz > 0 and mode.pixel_clock_khz > (edid.max_tmds_clock_mhz * 1000):
            return (
                False,
                f"Pixel clock {mode.pixel_clock_khz // 1000}MHz exceeds HDMI VSDB TMDS limit ({edid.max_tmds_clock_mhz}MHz)",
            )
    return True, "ok"


def select_safe_display_mode(
    connector: ConnectorState | None,
    requested_mode: DisplayMode | None = None,
    fallback_tier: int = 0,
) -> ModeDecision:
    """Select the safest verified display mode without blindly forcing 1080p@60Hz."""
    tier_idx = max(0, min(fallback_tier, len(FALLBACK_MODE_CASCADE) - 1))
    default_fallback = FALLBACK_MODE_CASCADE[tier_idx]
    rejected: list[dict[str, str]] = []
    warnings: list[str] = []

    if connector is None:
        return ModeDecision(
            selected_mode=default_fallback,
            fallback_mode=FALLBACK_MODE_CASCADE[min(tier_idx + 1, len(FALLBACK_MODE_CASCADE) - 1)],
            used_fallback=True,
            reason="No HDMI DRM connector detected in sysfs; selecting safe fallback mode.",
            warnings=["DRM connector absent; verify CONFIG_DRM_AMDGPU=y and Liverpool/Gladius firmware."],
        )

    edid = connector.edid_info
    if edid.deep_color_30bit or edid.deep_color_36bit:
        warnings.append(
            "Sink advertises HDMI Deep Color (30/36-bit); ensure Deep Color & HDR are OFF in PS4 Orbis Settings before kexec (BOOT-006)."
        )

    drm_res_set: set[tuple[int, int, bool]] = set()
    for dm in connector.drm_modes:
        parsed = _parse_drm_mode_name(dm)
        if parsed:
            drm_res_set.add(parsed)

    # Case 1: Valid EDID with parsed modes
    if edid.valid and edid.modes:
        safe_candidates: list[DisplayMode] = []
        for m in edid.modes:
            ok, why = is_mode_safe_for_ps4_fat(m, edid=edid)
            if not ok:
                rejected.append({"mode": m.kms_mode_str, "reason": why})
                continue
            if drm_res_set and (m.width, m.height, m.interlaced) not in drm_res_set:
                rejected.append(
                    {
                        "mode": m.kms_mode_str,
                        "reason": "Mode present in EDID but rejected/absent in kernel DRM connector modes",
                    }
                )
                continue
            safe_candidates.append(m)

        # Check explicit user-requested mode ONLY if proven supported by both EDID & PS4 limits
        if requested_mode is not None:
            req_ok, req_why = is_mode_safe_for_ps4_fat(requested_mode, edid=edid)
            matching = [
                c
                for c in safe_candidates
                if c.width == requested_mode.width
                and c.height == requested_mode.height
                and c.refresh_hz == requested_mode.refresh_hz
                and c.interlaced == requested_mode.interlaced
            ]
            if req_ok and matching:
                secondary = next(
                    (c for c in safe_candidates if c != matching[0] and not c.interlaced),
                    default_fallback,
                )
                return ModeDecision(
                    selected_mode=matching[0],
                    fallback_mode=secondary,
                    used_fallback=False,
                    reason=f"Requested mode {requested_mode.kms_mode_str} verified in sink EDID and DRM modes.",
                    rejected_modes=rejected,
                    warnings=warnings,
                )
            rejected.append(
                {
                    "mode": requested_mode.kms_mode_str,
                    "reason": req_why if not req_ok else "Requested mode NOT supported by sink EDID — blocked to prevent Black Screen",
                }
            )
            warnings.append(
                f"Blocked unsupported requested mode {requested_mode.kms_mode_str}; selecting EDID-verified mode instead."
            )

        if safe_candidates:
            # Prefer progressive modes; honour monitor's native preferred progressive mode if <= 1080p60,
            # otherwise highest safe progressive resolution, Preferring 60Hz then 50Hz.
            def _rank(m: DisplayMode) -> tuple[int, int, int, int]:
                prog_score = 0 if not m.interlaced else 1
                pref_score = 0 if (m.preferred and not m.interlaced) else 1
                hz_pref = 0 if m.refresh_hz in (60, 50) else 1
                return (prog_score, pref_score, -m.pixels, hz_pref)

            ordered = sorted(safe_candidates, key=_rank)
            chosen = ordered[0]
            backup = next(
                (
                    c
                    for c in ordered[1:]
                    if not c.interlaced and (c.width, c.height) != (chosen.width, chosen.height)
                ),
                default_fallback,
            )
            return ModeDecision(
                selected_mode=chosen,
                fallback_mode=backup,
                used_fallback=False,
                reason=f"Selected EDID-verified compatible mode {chosen.kms_mode_str} ({chosen.source}).",
                rejected_modes=rejected,
                warnings=warnings,
            )

    # Case 2: EDID missing/invalid, but kernel DRM connector lists modes
    if drm_res_set:
        warnings.append(
            f"EDID unavailable/invalid ({'; '.join(edid.errors) or 'no modes'}); intersecting DRM modes with safe fallback cascade."
        )
        for fb in FALLBACK_MODE_CASCADE[tier_idx:]:
            if (fb.width, fb.height, fb.interlaced) in drm_res_set:
                next_fb = FALLBACK_MODE_CASCADE[min(tier_idx + 1, len(FALLBACK_MODE_CASCADE) - 1)]
                return ModeDecision(
                    selected_mode=fb,
                    fallback_mode=next_fb,
                    used_fallback=True,
                    reason=f"EDID unreadable; chose safe fallback {fb.kms_mode_str} confirmed in DRM modes.",
                    rejected_modes=rejected,
                    warnings=warnings,
                )

    # Case 3: Blind handshake / broken DDC — use safe fallback tier (never blind 1080p60!)
    if requested_mode is not None and (requested_mode.width > 1280 or requested_mode.height > 720):
        rejected.append(
            {
                "mode": requested_mode.kms_mode_str,
                "reason": "Blocked unverified >720p mode because sink EDID could not be read",
            }
        )
    warnings.append(
        "Sink EDID and DRM mode list unavailable; engaging safe fallback cascade (never forcing unverified 1080p@60Hz)."
    )
    next_fb = FALLBACK_MODE_CASCADE[min(tier_idx + 1, len(FALLBACK_MODE_CASCADE) - 1)]
    return ModeDecision(
        selected_mode=default_fallback,
        fallback_mode=next_fb,
        used_fallback=True,
        reason=f"Emergency safe fallback {default_fallback.kms_mode_str} selected (EDID missing/corrupt).",
        rejected_modes=rejected,
        warnings=warnings,
    )


def scan_drm_kms_errors(log_text: str | None = None) -> list[DrmErrorFinding]:
    """Scan kernel dmesg / journal text for DRM, KMS, AMDGPU, and HDMI bridge errors."""
    if log_text is None:
        chunks: list[str] = []
        for cmd in (["dmesg"], ["journalctl", "-k", "-b", "--no-pager", "-n", "500"]):
            if shutil.which(cmd[0]):
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
                    if proc.stdout:
                        chunks.append(proc.stdout)
                        break
                except OSError:
                    pass
        log_text = "\n".join(chunks)

    findings: list[DrmErrorFinding] = []
    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for pattern, issue_id, severity in DRM_ERROR_SIGNATURES:
            if re.search(pattern, line, flags=re.IGNORECASE):
                findings.append(DrmErrorFinding(line=line, issue_id=issue_id, severity=severity))
                break
    return findings


def recover_display(
    connector: ConnectorState | None,
    decision: ModeDecision,
    sysfs_root: Path = Path("/sys"),
    bridge_transport: BridgeTransport | None = None,
    dry_run: bool = False,
) -> tuple[BridgeHealth, list[str]]:
    """Execute automated display recovery cascade (bridge unmute -> KMS reprobe -> session RandR)."""
    actions: list[str] = []

    # Step 1: Unmute MN864729 DP->HDMI bridge if muted (single atomic pass)
    bh = check_and_heal_hdmi_bridge(
        sysfs_root=sysfs_root,
        transport=bridge_transport,
        auto_unmute=(not dry_run),
    )
    if bh.unmute_applied:
        actions.append(f"Unmuted {bh.bridge_chip} HDMI bridge over ICC (restored 0x1e00/0x1e02, cleared 0x705f).")
    else:
        actions.append(f"Checked HDMI bridge ({bh.bridge_chip}): unmute_needed=False.")

    # Step 2: Re-trigger KMS connector hotplug detection if connector is disconnected/unknown
    if connector is not None:
        status_path = Path(connector.sysfs_path) / "status"
        if connector.status != "connected" and status_path.exists():
            if dry_run:
                actions.append(f"[dry-run] Would write 'detect' to {status_path} to force KMS hotplug probe.")
            elif os.geteuid() == 0:
                try:
                    status_path.write_text("detect\n", encoding="utf-8")
                    actions.append(f"Triggered KMS hotplug re-detection on {connector.name}.")
                except OSError as exc:
                    actions.append(f"KMS status probe failed on {connector.name}: {exc}")

    # Step 3: Apply safe verified mode (or fallback mode) in active display server if running
    target = decision.selected_mode
    out_name = connector.name.split("-", 1)[1] if (connector and "-" in connector.name) else "HDMI-A-1"
    display_env = os.environ.get("DISPLAY")
    wayland_env = os.environ.get("WAYLAND_DISPLAY")

    if wayland_env and shutil.which("kscreen-doctor"):
        cmd = [
            "kscreen-doctor",
            f"output.{out_name}.enable",
            f"output.{out_name}.mode.{target.width}x{target.height}@{target.refresh_hz}",
        ]
        if dry_run:
            actions.append(f"[dry-run] Would run: {' '.join(cmd)}")
        else:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            if res.returncode == 0:
                actions.append(f"Applied {target.kms_mode_str} via kscreen-doctor.")
            else:
                fb = decision.fallback_mode
                fb_cmd = [
                    "kscreen-doctor",
                    f"output.{out_name}.enable",
                    f"output.{out_name}.mode.{fb.width}x{fb.height}@{fb.refresh_hz}",
                ]
                subprocess.run(fb_cmd, capture_output=True, text=True, timeout=5, check=False)
                actions.append(f"Primary mode failed; stepped down to fallback {fb.kms_mode_str} via kscreen-doctor.")
    elif wayland_env and shutil.which("wlr-randr"):
        cmd = ["wlr-randr", "--output", out_name, "--on", "--mode", f"{target.width}x{target.height}@{target.refresh_hz}Hz"]
        if dry_run:
            actions.append(f"[dry-run] Would run: {' '.join(cmd)}")
        else:
            subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            actions.append(f"Applied {target.kms_mode_str} via wlr-randr.")
    elif display_env and shutil.which("xrandr"):
        cmd = [
            "xrandr",
            "--output",
            out_name,
            "--mode",
            f"{target.width}x{target.height}",
            "--rate",
            str(target.refresh_hz),
        ]
        if dry_run:
            actions.append(f"[dry-run] Would run: {' '.join(cmd)}")
        else:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            if res.returncode == 0:
                actions.append(f"Applied {target.kms_mode_str} via xrandr.")
            else:
                fb = decision.fallback_mode
                fb_cmd = [
                    "xrandr",
                    "--output",
                    out_name,
                    "--mode",
                    f"{fb.width}x{fb.height}",
                    "--rate",
                    str(fb.refresh_hz),
                ]
                subprocess.run(fb_cmd, capture_output=True, text=True, timeout=5, check=False)
                actions.append(f"Primary xrandr mode failed; rolled back to safe fallback {fb.kms_mode_str}.")
    else:
        actions.append(
            f"Prepared kernel/KMS safe mode {decision.kernel_video_arg} (fallback {decision.fallback_mode.kms_mode_str})."
        )

    return bh, actions


def run_display_protection_pass(
    sysfs_root: Path = Path("/sys"),
    requested_mode: DisplayMode | None = None,
    fallback_tier: int = 0,
    log_text: str | None = None,
    bridge_transport: BridgeTransport | None = None,
    perform_recovery: bool = False,
    dry_run: bool = False,
    log_dir: Path | None = None,
) -> DisplayProtectionReport:
    """Execute a complete HDMI Display Protection Engine inspection & optional recovery cycle."""
    connectors = discover_hdmi_connectors(sysfs_root=sysfs_root)
    active: ConnectorState | None = None
    for c in connectors:
        if c.status == "connected":
            active = c
            break
    if active is None and connectors:
        active = connectors[0]

    resolutions = active.edid_info.unique_resolutions() if (active and active.edid_info.valid) else (
        active.drm_modes if active else []
    )
    refresh_rates = active.edid_info.supported_refresh_rates() if (active and active.edid_info.valid) else []

    decision = select_safe_display_mode(
        connector=active,
        requested_mode=requested_mode,
        fallback_tier=fallback_tier,
    )
    drm_errors = scan_drm_kms_errors(log_text=log_text)
    recovery_actions: list[str] = []
    if perform_recovery:
        bridge_health, recovery_actions = recover_display(
            connector=active,
            decision=decision,
            sysfs_root=sysfs_root,
            bridge_transport=bridge_transport,
            dry_run=dry_run,
        )
    else:
        bridge_health = check_and_heal_hdmi_bridge(
            sysfs_root=sysfs_root,
            transport=bridge_transport,
            auto_unmute=False,
        )

    report = DisplayProtectionReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        connectors=connectors,
        active_connector=active.name if active else None,
        supported_resolutions=resolutions,
        supported_refresh_rates=refresh_rates,
        decision=decision,
        bridge_health=bridge_health,
        drm_errors=drm_errors,
        recovery_actions=recovery_actions,
    )

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        state_file = log_dir / "display-protection-state.json"
        state_file.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        log_file = log_dir / "display-protection.log"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(
                f"[{report.timestamp}] connector={report.active_connector} "
                f"selected={decision.selected_mode.kms_mode_str} "
                f"fallback={decision.fallback_mode.kms_mode_str} "
                f"used_fallback={decision.used_fallback} "
                f"drm_errors={len(drm_errors)}\n"
            )

    return report
