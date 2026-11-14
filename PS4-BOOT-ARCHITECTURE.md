# PS4-BOOT-ARCHITECTURE — Complete 14-Step Lifecycle, Root-Cause Matrix & 11-Stage Safe Boot Engine

**Target Hardware:** Sony PlayStation 4 Fat (`CUH-10xx` / `CUH-11xx` Aeolia & `CUH-12xx` Belize; plus `CUH-20xx/21xx/22xx` Slim Baikal compatibility guards)  
**Safety Invariants:** `D-01` (Internal PS4 HDD untouched; Linux runs strictly from external USB) · `D-02` (PS4 Orbis firmware frozen; never update)

---

## 1. End-to-End 14-Step PS4 Linux Boot Lifecycle

Unlike a standard PC with UEFI GOP/VESA BIOS framebuffers, a PlayStation 4 transitions into Linux through **in-memory `kexec` from a running FreeBSD-derived Orbis OS** while peripheral ASICs (Aeolia/Belize/Baikal Southbridge, EMC microcontroller, and Panasonic HDMI encoder) remain in whatever state Orbis left them.

### 1.1 Control-Transfer Diagram

```text
[01. PS4 Orbis OS (FreeBSD 9 derivative)]
  │  User disables HDR & Deep Color in Orbis Settings; internal encrypted HDD remains untouched (D-01)
  ▼
[02. Userland / Kernel Exploit (PPPwn / WebKit / BD-J on frozen FW <=13.52 / <=11.00)]
  │  Achieves ring-0 execution in Orbis kernel without modifying flash/HDD (D-02)
  ▼
[03. GoldHEN Runtime]
  │  Opens BinLoader TCP listener (default :9090; legacy :9020/:9021)
  ▼
[04. Linux Payload ELF (e.g., linux-1024mb.elf sent via `ps4-send-payload`)]
  │  Carves unified GDDR5: 1024 MiB VRAM + ~7 GiB System RAM (D-03); reads single exclusive boot layout (D-08)
  ▼
[05. ps4-linux-loader (In-Kernel Orbis Stage)]
  │  CRITICAL: Extracts copyrighted Liverpool/Gladius GPU microcode (pfp/me/ce/mec/mec2/rlc/sdma)
  │  from live Orbis memory into a synthetic CPIO archive prepended *ahead* of initramfs.cpio.gz,
  │  loads bzImage + bootargs.txt + vram.txt, and triggers kexec_load -> jumping to Linux x86_64 entry!
  ▼
[06. Linux Kernel Early Boot (bzImage: feeRnt/ps4-linux-12xx 7.0-Clean for Fat Aeolia/Belize)]
  │  Initializes 8x AMD Jaguar (`btver2`) cores, APIC, IOMMU, Aeolia/Belize PCIe + ICC (`char 73`) + XHCI USB
  ▼
[07. Early KMS & Firmware Hand-off]
  │  Kernel unpacks [Loader GPU Microcode CPIO] + [initramfs.cpio.gz] into rootfs tmpfs
  │  (TRAP: If initramfs.cpio.gz contains `lib/firmware/amdgpu/*`, it overwrites the loader's CPIO -> BLACK SCREEN!)
  ▼
[08. AMDGPU Driver Initialization (`CONFIG_DRM_AMDGPU=y` built-in)]
  │  `gfx_v7_0_init_microcode()` loads `liverpool_{pfp,me,ce,mec,mec2,rlc}.bin`; initializes Sea Islands CIK (`gfx7`) rings
  ▼
[09. DRM / KMS Subsystem Registration]
  │  Creates `/dev/dri/card0`, `/dev/dri/renderD128`, `/dev/ps4-mesa-lock`, and `card0-HDMI-A-1`
  ▼
[10. Physical HDMI Encoder & Sink Handshake]
  │  • CUH-10xx/11xx (`0x9920`): Panasonic MN86471A HDMI transmitter
  │  • CUH-12xx Belize (`0x9922`/`0x9923`): Native DP -> Panasonic MN864729 DP-to-HDMI bridge over `/dev/icc` (`0x10`)
  │    (TRAP: MN864729 drops `0x1e00` bit 0 / asserts `0x705f` bit 7 mute during mode switch unless explicitly unmuted!)
  ▼
[11. EDID Read & Safe KMS Mode Selection (`ps4_hdmi_guard` -> `ps4-display-protector`)]
  │  Reads `/sys/class/drm/card0-HDMI-A-1/edid`, verifies 128-byte checksum & CEA-861 timings,
  │  NEVER forces blind 1080p@60Hz; falls back cleanly (`1280x720@60` -> `1024x768@60` -> `800x600@60` -> `640x480@60`)
  ▼
[12. Initramfs `/init` Execution (`initramfs/init`)]
  │  Runs `ps4_hdmi_guard --once`, waits up to `ps4_rootwait=30s` for USB storage (`PS4LINUX` ext4 or `PS4KD` + `linux.img`),
  │  runs `e2fsck -p`, mounts rootfs cleanly; on ANY error saves `dmesg` + DRM state to `PS4BOOT/ps4-linux-fail-*.log`!
  ▼
[13. RootFS `switch_root` & systemd Services]
  │  Starts `ps4-hdmi-protector.service` (continuous MN864729 unmute + EDID log), `ps4-thermal-guard.service` (`temp1_crit=72°C`),
  │  masks `sleep.target`/`suspend.target` (`SYS-001`), runs `ps4-mesa-select` before Display Manager starts
  ▼
[14. Display Manager (SDDM) -> KDE Plasma X11 Desktop (or XFCE Safe Recovery)]
     • If `/opt/ps4-mesa` (`0x9920/0x9922/0x9923` + patches `0001..0003`) is verified -> `glamor` + `radeonsi` GPU acceleration
     • If `/opt/ps4-mesa` is absent/broken -> `modesetting` + `ShadowFB` (`AccelMethod "none"`) or `ps4-rescue-desktop` (XFCE)
     • Reboot returns cleanly to untouched PS4 Orbis OS (`BOOT-008`)
```

---

## 2. PS4 Hardware Compatibility Matrix (Focus: PS4 Fat)

| Console Revision | CUH Model | APU Codename | GPU PCI ID (`00:01.0`) | Southbridge | HDMI Transmitter | Required Kernel Branch (`14-pinned-inputs.lock.yaml`) | Special Hardware Quirks |
|---|---|---|---|---|---|---|---|
| **PS4 Fat (Launch)** | `CUH-10xxA` | Liverpool (8x Jaguar + 18 CU GCN2 `gfx7`) | `1002:9920` | **Aeolia** (`104d:909e`) | Panasonic **MN86471A** | `feeRnt/ps4-linux-12xx` @ `7.0-Clean` (`8ec5c28`) *(fallback: `6.15.4-aeolia-belize` `3cba9d4`)* | Needs Aeolia PCIe/ICC/XHCI driver; Orbis HDR/Deep Color off |
| **PS4 Fat (2nd rev)** | `CUH-11xxA` | Liverpool (`gfx7`) | `1002:9920` | **Aeolia** | Panasonic **MN86471A** | `feeRnt/ps4-linux-12xx` @ `7.0-Clean` (`8ec5c28`) | Same as CUH-10xx; slightly revised VRM/board |
| **PS4 Fat (C-Chassis)** | `CUH-12xxA/B` | Liverpool (`gfx7`) | `1002:9922` or `1002:9923` | **Belize** | **Panasonic MN864729** (DP→HDMI via ICC `0x10`) | `feeRnt/ps4-linux-12xx` @ `7.0-Clean` (`8ec5c28`) | **CRITICAL:** MN864729 mutes HDMI on KMS transition unless `0x1e00`/`0x1e02`/`0x705f` are healed via `/dev/icc`; some units need `AMD_DEBUG=notiling` (`GFX-003`) |
| *PS4 Slim (Guard)* | `CUH-20xx/21xx/22xx` | Liverpool shrink | `1002:9924` | **Baikal** (`104d:90c9`) | Panasonic **MN864729** | `5.4.247-baikal-dfaus` (`1fdfbd9`) | Booting an Aeolia/Belize Fat kernel on Baikal causes steady White LED (`BOOT-001`); blocked by `ps4-kernel-writer` |
| *PS4 Pro (Guard)* | `CUH-70xx/71xx/72xx` | **Gladius** (36 CU) | `1002:9924` | **Belize** / **Baikal** | Panasonic **MN864729** | Southbridge-matched branch + Gladius register fixes | Out of primary target scope, but PCI IDs & Mesa patches `0001..0003` include `CHIP_GLADIUS` |

---

## 3. Evidence-Based Black Screen Root-Cause Matrix (9 Verified Mechanisms)

| # | Defect ID / Layer | Exact Failure Mechanism | Observable Symptom | Deterministic Fix Implemented in Repository |
|---|---|---|---|---|
| 1 | `BOOT-001` (Southbridge ↔ Kernel) | Booting a Baikal kernel on Aeolia/Belize PS4 Fat (or vice-versa) leaves Southbridge UART/XHCI/ICC uninitialized | Console LED stays steady white; USB drives never blink; no log written | `src/ps4_linux/boot_writer.py` (`ps4-kernel-writer`) maps `cuh_model`/`southbridge` strictly to pinned kernel track |
| 2 | `BOOT-003` (Dual Boot Layout) | Stale `bzImage`/`bootargs.txt` present simultaneously on USB `PS4BOOT` and internal `/data/linux/boot/` | Loader boots unexpected old kernel/cmdline; intermittent black screen | `ps4-kernel-writer` enforces `D-08` single-layout exclusivity (`usb_fat32` OR `internal_ftp`, never both) + `manifest.json` SHA-256 |
| 3 | **Initramfs GPU Firmware Overwrite Trap** | Shipping `lib/firmware/amdgpu/*` inside `initramfs.cpio.gz` shadows or overwrites the microcode CPIO injected in RAM by `ps4-linux-loader` | Kernel boots, USB mounts, `dmesg` shows `Direct firmware load for amdgpu/liverpool_pfp.bin failed with error -2` -> Black screen | `bin/ps4-initramfs-tool audit` & `ps4-doctor` scan `initramfs.cpio.gz` and reject any archive containing `lib/firmware/amdgpu/*` |
| 4 | Late `amdgpu=m` / Broken `EXTRA_FIRMWARE_DIR` | Upstream `feeRnt` raw config hardcodes `/home/rmux/ps4_testing/.../extra_firmware`; modular `amdgpu` races initramfs | Build failure or KMS never attaches to `fbcon` | `configs/kernel/ps4-desktop-fat.config` + `scripts/build-kernel-safe.sh` enforce `CONFIG_DRM_AMDGPU=y`, `CONFIG_DRM_AMDGPU_SI=y`, `CONFIG_DRM_AMDGPU_CIK=y`, and sanitized `EXTRA_FIRMWARE_DIR` |
| 5 | **Panasonic MN864729 DP→HDMI Auto-Mute** | On PS4 Fat `CUH-12xx` (`0x9922`/`0x9923`), KMS mode change clears `0x1e00` bit 0 or sets `0x705f` bit 7 (`VMUTECNT`) on MN864729 | Kernel & X11 run normally in background, but TV shows `"No Signal"` black screen | Dual-layer unmute: freestanding C `initramfs/bin/ps4_hdmi_guard` in Stage 6 + Python `src/ps4_linux/hdmi_bridge.py` (`ps4-hdmi-protector.service`) |
| 6 | **Blind `1920x1080@60` Out-of-Range / Deep Color** (`BOOT-006`) | Hardcoding `video=HDMI-A-1:1920x1080@60D` on 720p/1366x768/50Hz/HDMI-to-VGA monitors, or leaving Orbis HDR/Deep Color enabled | Monitor OSD shows `"Out of Range"` / `"Unsupported Mode"` or blank sync loss | `src/ps4_linux/edid.py` + `display_protector.py` verify EDID & CEA-861 timings first; strip unverified `1920x1080@60` in `boot_writer.py`; cascade to `720p60 -> 1024x768 -> 800x600 -> 640x480` |
| 7 | **Unpatched Mesa / Premature X11 `glamor`** (`GFX-001`, `GFX-005`) | Upstream Mesa lacks PS4 PCI IDs `0x9920/0x9922/0x9923` and `/dev/ps4-mesa-lock` handshake; forcing `glamor` without `/opt/ps4-mesa` crashes SDDM/Xorg | Black screen with blinking cursor or frozen SDDM login | `scripts/ps4-mesa-select` runs before SDDM: enables `glamor` + `radeonsi` ONLY when `/opt/ps4-mesa` + `/dev/dri/card0` pass; otherwise writes `AccelMethod "none"` + `ShadowFB "true"` |
| 8 | **RADV HiZ (`HTILE`) & ACO `FLAT` Ring Hang** (`GFX-002`) | Liverpool `gfx7` hangs `gfx` ring on HiZ depth compression and ACO `flat_store_dwordx4` instructions | Sudden black screen + `Ring gfx timeout` 1–20s after launching Vulkan/DXVK/compositor | Mirrored & SHA-256 verified `patches/mesa/0001..0003` (`0002-radv-ps4-no-hiz.patch` + `0003-aco-ps4-no-flat-global.patch`) |
| 9 | **Jaguar `SIGILL` (`AVX2` / `FMA` / `BMI2`)** (`APP-003`) | AMD Jaguar (`btver2`) supports AVX1 (`128-bit`) + BMI1 + F16C, **NOT** AVX2/FMA/BMI2; binaries or static libc IFUNCs using AVX2 crash | Immediate `Illegal instruction (core dumped)` in initramfs or desktop | Freestanding `-nostdlib -march=btver2 -mno-avx2 -mno-fma -mno-bmi2` compilation verified by `objdump -d` (`0` illegal opcodes) |

---

## 4. The 11-Stage Safe Boot Architecture (`BOOT STAGE 1` .. `BOOT STAGE 11`)

Implemented in `src/ps4_linux/safe_boot.py` (`bin/ps4-safe-boot`) for userspace & pre-boot verification and `initramfs/init` for early-userspace boot execution:

| Stage | Name | Verification Gate | Failure Action / Fallback | Log Destination |
|---|---|---|---|---|
| **BOOT STAGE 1** | Payload Verification | Validates GoldHEN payload `.elf` ELF64 `x86_64` header & non-zero size | Abort network send before touching PS4 | `stage-01-payload.log` |
| **BOOT STAGE 2** | Kernel Hand-off & Southbridge Match | Verifies `bzImage` `HdrS` magic, single boot layout (`D-08`), `vram.txt` in MB (`1024`), and `cuh_model` ↔ kernel track | Refuse mixed boot directory (`BOOT-003`) | `stage-02-kernel-handoff.log` |
| **BOOT STAGE 3** | Early Kernel Logs | Parses `dmesg` for Jaguar `btver2`, memory map, PCIe `00:01.0`, and Southbridge IRQ init | Capture early panic/PCI error markers | `stage-03-early-kernel.log` |
| **BOOT STAGE 4** | GPU & Microcode Check | Verifies `amdgpu` bound to `1002:9920/9922/9923` and zero `-ENOENT` microcode load failures | Flag outdated loader or initramfs firmware conflict | `stage-04-gpu-check.log` |
| **BOOT STAGE 5** | DRM Check | Confirms `/sys/class/drm/card0`, `/dev/dri/card0`, and connector nodes exist | Trigger safe nomodeset/fbdev diagnostic log | `stage-05-drm-check.log` |
| **BOOT STAGE 6** | HDMI Sink & Bridge Check | Runs `ps4_hdmi_guard --once` (initramfs) & `hdmi_bridge.py` to unmute MN864729 (`0x1e00`/`0x1e02`/`0x705f`) | Re-issue ICC `0x10` unmute + HPD reprobe | `stage-06-hdmi-check.log` |
| **BOOT STAGE 7** | Safe Mode Selection | Decodes EDID; picks verified progressive mode or safe cascade (`1280x720@60` → `640x480@60`) | Block unsupported modes; never force blind 1080p60 | `stage-07-safe-mode.log` |
| **BOOT STAGE 8** | RootFS Check (`USB` / `linux.img`) | Waits up to `30s` (`BOOT-002`), runs `e2fsck -p`, mounts `LABEL=PS4LINUX` or `LABEL=PS4KD` + `linux.img` loop; verifies internal PS4 `/dev/sda` untouched (`D-01`) | Persist full `dmesg` + DRM dump to FAT32 `PS4BOOT/ps4-linux-fail-*.log` | `stage-08-rootfs-check.log` |
| **BOOT STAGE 9** | Display Server Check | Executes `scripts/ps4-mesa-select` to configure X11 (`glamor` + `/opt/ps4-mesa` vs safe `ShadowFB`) | Automatic fallback to `modesetting` `ShadowFB` | `stage-09-display-server.log` |
| **BOOT STAGE 10** | Desktop Startup | Launches KDE Plasma (`kwinrc` XRender/safe compositor, Baloo disabled, sleep masked) | One-command fallback via `scripts/ps4-rescue-desktop` to XFCE (`D-05`) | `stage-10-desktop-startup.log` |
| **BOOT STAGE 11** | Post-Boot Health Check | Runs `ps4-doctor`, verifies USB keyboard/mouse (`/proc/bus/input/devices`), `ps4-thermal-guard` (`<=72°C`), zram swap, and `timesyncd` | Emit actionable JSON/Markdown diagnostic summary | `stage-11-post-boot-health.log` |
