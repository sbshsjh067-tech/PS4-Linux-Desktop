# PS4-DISPLAY-DIAGNOSTICS — HDMI Display Protection Engine & Diagnostic Engine

**Primary Modules:**
- `src/ps4_linux/edid.py` — Pure-Python EDID 1.3/1.4 + CEA-861 Extension Parser & Deep-Color Hazard Detector
- `src/ps4_linux/hdmi_bridge.py` — Panasonic MN864729 (`0x9922/0x9923/0x9924`) & MN86471A (`0x9920`) ICC Hardware Controller
- `src/ps4_linux/display_protector.py` + `bin/ps4-display-protector` — Safe Mode Selector, Anti-Out-of-Range Guard & Auto-Recovery Engine
- `initramfs/src/ps4_hdmi_guard.c` (`initramfs/bin/ps4_hdmi_guard`) — Freestanding `8.9 KiB` Jaguar-Safe Early-Boot Bridge Guard
- `src/ps4_linux/doctor.py` + `bin/ps4-doctor` — 12-Subsystem Diagnostic Engine & Black-Screen Stage Pinpointer
- `systemd/ps4-hdmi-protector.service` — Continuous systemd HDMI Keep-Alive & Recovery Service

---

## 1. HDMI Display Protection Engine Architecture

### 1.1 Hardware Layer: Panasonic MN86471A vs MN864729 (`hdmi_bridge.py` & `ps4_hdmi_guard.c`)

PlayStation 4 Fat consoles ship with **two distinct HDMI transmitter architectures**:
1. **PS4 Fat `CUH-10xx` / `CUH-11xx` (`1002:9920`, Aeolia):** Uses the Panasonic **MN86471A** HDMI transmitter.
2. **PS4 Fat `CUH-12xx` (`1002:9922` / `1002:9923`, Belize) & Slim/Pro (`1002:9924`):** Liverpool/Gladius outputs native DisplayPort into an on-board **Panasonic MN864729** DP-to-HDMI bridge controlled through the Southbridge ICC character device `/dev/icc` (`major 73, minor 0`, ICC service `0x10`).

**Why `CUH-12xx` PS4 Fat Goes Black on KMS Hand-off:**  
During `kexec` from Orbis into Linux KMS, `amdgpu` retrains the DisplayPort link. The MN864729 reacts to link retraining by clearing its HDMI output enable (`0x1e00` bit `0`), dropping TMDS lane enables (`0x1e02` bits `4..6`), or asserting video mute (`0x705f` bit `7` `VMUTECNT`). Linux believes `card0-HDMI-A-1` is `connected` and renders KDE Plasma normally, while the television displays **"No Signal"**.

**Dual-Stage Hardware Unmute Sequence:**
1. **Early Initramfs (`BOOT STAGE 6`):** `/init` runs `/bin/ps4_hdmi_guard --once` (`8.9 KiB` freestanding binary) immediately after mounting `/sys` and `/dev`.
2. **Userspace Daemon (`BOOT STAGE 9..11`):** `ps4-hdmi-protector.service` polls `0x1e00` and `0x705f`. Whenever `!(reg_0x1e00 & 0x01)` or `(reg_0x705f & 0x80)` is detected, it issues two ICC `0x10` register transactions:
   - Masked write: `0x1e02 |= 0x70` (enable TMDS lanes) and `0x1e00 |= 0x01` (enable HDMI output).
   - Direct write: `0x705f = 0x10` (clear `VMUTECNT` bit 7 video mute).

---

### 1.2 Sink Layer: EDID 1.3/1.4 + CEA-861 Parser (`src/ps4_linux/edid.py`)

`parse_edid(raw_bytes)` performs full structural and timing validation without requiring external `edid-decode`:
- Verifies the 8-byte EDID magic header (`00 ff ff ff ff ff ff 00`) and modulo-256 checksum across the 128-byte base block and every 128-byte extension block.
- Decodes PnP 3-letter manufacturer ID (`0x08..0x09`), product code, serial, and monitor name descriptor (`tag 0xFC`) + range limits (`tag 0xFD`).
- Extracts **all** sink modes across four timing tables:
  1. **Established Timings I & II** (`640x480@60`, `800x600@60`, `1024x768@60`, etc.)
  2. **Standard Timings** (`0x26..0x35`: 16:9, 16:10, 4:3, 5:4 ratios)
  3. **Detailed Timing Descriptors (DTDs)** (`0x36..0x7D` + extension DTDs: exact pixel clock, active pixels/lines, interlacing flag, preferred/native mode bit)
  4. **CEA-861 Extension Short Video Descriptors (SVDs)** (`VIC 1..107`, including `1920x1080@60/50`, `1280x720@60/50`, `720x576@50`, `720x480@60`, and 4K VICs)
- Parses **HDMI Vendor-Specific Data Block (`OUI 00-0C-03`)** & **HF-VSDB (`OUI C4-5D-D8`)** to detect `DC_30bit`/`DC_36bit`/`DC_48bit` Deep Color flags and emit proactive `BOOT-006` warnings reminding users to keep Orbis Deep Color / HDR disabled before `kexec`.

---

### 1.3 Policy Layer: Safe Mode Selection & Anti-Out-of-Range Guard (`display_protector.py`)

The mode selector (`select_safe_display_mode`) strictly enforces **MASTER ENGINEERING PROMPT V3** display rules:

1. **NEVER Force Blind `1080p@60Hz`:**  
   If a user or stale `bootargs.txt` requests `1920x1080@60`, it is **blocked and logged in `rejected_modes`** unless the monitor's verified EDID (or kernel DRM mode list) explicitly advertises `1920x1080` progressive at `59–61 Hz`.
2. **Block Unsafe / Out-of-Scope Timings on PS4 Fat:**
   - Modes exceeding pixel/dimension cap `> 1920x1200` (e.g., `3840x2160` 4K modes advertised by 4K TVs over HDMI 1.4) are rejected for desktop stability on Liverpool `gfx7` + 1024 MiB VRAM.
   - Refresh rates `> 60.5 Hz` (e.g., `120 Hz` / `144 Hz`) and interlaced modes (`1080i`) are deprioritized/rejected in favor of progressive `60 Hz` / `50 Hz`.
3. **Deterministic 4-Tier Safe Fallback Cascade:**  
   When EDID is unreadable (broken DDC pin on cheap HDMI-to-VGA adapter, KVM switch, or slow TV handshake), the engine never guesses `1080p60`; it walks a deterministic progressive VESA/CEA safe cascade:
   - **Tier 0:** `1280x720@60Hz` (`video=HDMI-A-1:1280x720@60D`)
   - **Tier 1:** `1024x768@60Hz` (`video=HDMI-A-1:1024x768@60D`)
   - **Tier 2:** `800x600@60Hz` (`video=HDMI-A-1:800x600@60D`)
   - **Tier 3:** `640x480@60Hz` (`video=HDMI-A-1:640x480@60D` — mandatory CEA-861 VIC 1 universal baseline)

---

### 1.4 Recovery Layer: Automated Display Self-Healing (`recover_display`)

When invoked via `ps4-display-protector --recover` (or automatically on hotplug/mute detection), `recover_display()` executes a single-pass atomic recovery cascade:
1. Checks `/dev/icc` MN864729 registers and unmutes `0x1e00`/`0x1e02`/`0x705f` if muted, recording `"Unmuted MN864729 HDMI bridge over ICC"` in `recovery_actions`.
2. Triggers a kernel KMS connector hotplug/EDID reprobe (`echo detect > /sys/class/drm/card0-HDMI-A-1/status`).
3. Applies the verified safe mode in the active display server (`kscreen-doctor` on KDE Wayland, `wlr-randr` on wlroots, or `xrandr` on X11 with automatic rollback to `decision.fallback_mode` if primary mode fails).

---

## 2. The 12-Subsystem Diagnostic Engine (`bin/ps4-doctor`)

`ps4-doctor` (`src/ps4_linux/doctor.py`) inspects live PS4 systems **or** offline synthetic/captured diagnostic bundles (`--sysfs-root`, `--boot-dir`, `--usb-mount`, `--internal-boot-dir`, `--dmesg-file`, `--json`) across all 12 required engineering domains:

| # | Subsystem Check | What `ps4-doctor` Inspects | Defect Codes Caught |
|---|---|---|---|
| 1 | **Kernel & Southbridge** | `uname -r` / `bzImage` header vs `Aeolia` (`0x9920`), `Belize` (`0x9922/0x9923`), `Baikal` (`0x9924`) | `BOOT-001` |
| 2 | **GPU Firmware & Initramfs Trap** | `dmesg` microcode load status + scans `initramfs.cpio.gz` for forbidden `lib/firmware/amdgpu/*` entries | Microcode `-2` black screen |
| 3 | **GoldHEN & Payload Readiness** | Payload ELF64 header, `vram.txt` unit sanity (`1024` vs `1` GB bug) | `BOOT-004`, `SYS-005` |
| 4 | **AMDGPU Kernel Driver** | Driver bound to `0000:00:01.0`, ring timeouts, `/dev/ps4-mesa-lock` device node | `GFX-002`, `GFX-003` |
| 5 | **DRM Subsystem** | `/sys/class/drm/card0`, `/dev/dri/card0`, `/dev/dri/renderD128` | Stage 5 failure |
| 6 | **HDMI Connector & MN864729 Bridge** | `card0-HDMI-A-1/status` + MN864729 mute state (`0x1e00`, `0x705f`) | `CUH-12xx` "No Signal" |
| 7 | **EDID Integrity & Deep Color** | 128-byte checksum, PnP ID, CEA-861 extensions, Deep Color hazard flags | `BOOT-006` |
| 8 | **Display Modes & Mesa Renderer** | Verified safe mode vs `bootargs.txt`; checks `/opt/ps4-mesa` vs `llvmpipe` software fallback | `GFX-001`, `GFX-005` |
| 9 | **Initramfs Integrity** | Compression format, executable `/init`, presence of Jaguar-safe `/bin/ps4_hdmi_guard` | Broken Stage 6/8 |
| 10 | **RootFS, `linux.img` & `D-01` Guard** | Verifies USB rootfs (`PS4LINUX` or `PS4KD`+`linux.img`) and proves internal PS4 HDD is **not** mounted RW | `BOOT-002`, `SYS-004`, `D-01` |
| 11 | **Boot Arguments & Layout Exclusivity** | Enforces `D-08` (refuses simultaneous USB + internal `bzImage`), checks `ps4_rootwait`, blocks blind `1920x1080@60` | `BOOT-003` |
| 12 | **Thermal, Sleep Mask & Logs** | `ps4-fan` `hwmon` `temp1_crit` (`65–75°C`), `sleep.target` mask, persistent `PS4BOOT/ps4-linux-fail-*.log` | `SYS-001`, `SYS-002` |

### Black-Screen Post-Mortem Stage Pinpointer (`pinpoint_black_screen_stage`)
Whenever a black screen occurs, running `ps4-doctor` against the USB `PS4BOOT` partition (or live system) executes `run_safe_boot_pipeline` across `BOOT STAGE 1`..`BOOT STAGE 11` and outputs exact forensic coordinates:
- `last_succeeded_stage` (e.g., `BOOT STAGE 5: DRM Check`)
- `first_failed_stage` (e.g., `BOOT STAGE 6: HDMI Check` or `BOOT STAGE 4: GPU Check`)
- Exact root-cause explanation and single-command remediation.
