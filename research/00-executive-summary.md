# 00 — Executive summary (reality check)

**Date of analysis:** 2026-11-13 · **Scope:** PS4 Fat → Linux desktop with KDE Plasma, Orbis kept.

---

## 1. Verdict in one paragraph

The project is **technically feasible today**, but not at the performance level the README implies.
A jailbroken PS4 Fat can boot a maintained 6.x/7.x kernel from USB, drive the GPU through patched Mesa
(OpenGL 4.5–4.6, Vulkan 1.3), and run KDE Plasma, Firefox/Chromium, VLC, LibreOffice, a PlayStation
controller, Ethernet, and — with version pinning — Steam. What **cannot** be delivered is "modern PC"
gaming or video performance: the APU is a 2013 low-power design (8 Jaguar cores @1.6 GHz, ~1.84 TFLOPS
GCN GPU, 8 GB GDDR5 shared), and the PS4 GPU is a **GFX7-class** part whose Vulkan level stops at **1.3**,
which excludes current DXVK 3.x and therefore the newest Proton/D3D translation stack
[S01][S07][S09][S12].

**Recommended headline configuration:** PS4 Fat (Belize preferred, Aeolia supported but less travelled) +
GoldHEN on ≤13.52 firmware + firmware-agnostic loader with a **1024 MB VRAM** payload + 7.x PS4 kernel
(patched) + **pinned Mesa** + Arch-based rootfs on **USB 3.0, never internal** + KDE Plasma (thin profile)
or XFCE as the guaranteed fallback.

## 2. Goal-by-goal feasibility

| README goal | Verdict | Evidence / constraint | Notes for the coding chat |
|---|---|---|---|
| Boot Linux, keep Orbis | ✅ Feasible | Loader + kernel from `/data/linux/boot`, rootfs on USB; Orbis boots first on cold start [S14][S16][S17] | USB-only policy, never `mkfs` internal |
| KDE Plasma desktop, Windows-like | ✅ Feasible, tune heavily | Plasma on PS4 demonstrated (Arch+KDE image tested on Pro & Slim) [S16]; ~0.5–2 GB RAM idle [ESTIMATE, EXP-003] | Disable blur/effects, 1080p60, no fractional scaling |
| GPU acceleration | ✅ Feasible with patched Mesa | OpenGL 4.5–4.6, Vulkan 1.3 (RADV) [S07][S08][S17][S18] | Stock distro Mesa = software rendering (no PS4 PCI IDs) [S07] |
| Web browser | ✅ Feasible (720p–1080p) | Firefox/Chromium on radeonsi; HW video decode (UVD) still experimental → software decode [S18] | Avoid VP9/AV1-only paths; prefer H.264 sources [ESTIMATE, EXP-004] |
| Steam | ⚠️ Conditional | Steam + Big Picture + Vulkan/RADV reported working on PS4 Linux [S15]; **DXVK 3.x needs Vulkan 1.4 → forbidden** [S12]; Proton 11 ships DXVK 2.7.1 → allowed [S13] | Only D3D9/10/11-era, light titles; 720–900p |
| Dolphin (GameCube/Wii) | ✅ GameCube mostly; ⚠️ Wii mixed | PS4-native Dolphin fork: many GC titles 30/60 fps; Mario Kart Wii 40–50, Galaxy 40–60 [S28] | Use that fork's recommended per-game settings |
| VLC / media | ✅ with codec caveats | UVD H.264 bring-up is experimental on one model only [S18]; software decode otherwise | Cap 1080p30 H.264; no 4K, no AV1 |
| LibreOffice | ✅ | CPU-bound; slow cold start on Jaguar [ESTIMATE] | Disable Java/OpenCL, preload |
| USB peripherals | ⚠️ Mostly | DS4 over USB reliable; Bluetooth needs re-pairing each boot [S16]; USB audio recommended over HDMI audio [S30] | Test matrix in `09-experiments.md` EXP-010 |
| "Preserve Orbis" | ✅ by policy | USB root + no internal writes; firmware update policy frozen [S16][S27] | See `11-risks-legal.md` |

## 3. Hardware budget (the single most important table)

| Resource | Reality on PS4 Fat | Consequence |
|---|---|---|
| CPU | 8 × AMD Jaguar, 1.6 GHz, 2-wide, **no AVX2 / FMA / BMI2** | Build with `-march=btver2`; no modern LLM/AVX2 apps; emulation ~2013 laptop class [S01][S32] |
| GPU | 18 CUs @ 800 MHz, 1.84 TFLOPS, **GFX7-class** (Liverpool) | ≈ Radeon HD 7850/7790 class; OpenGL 4.6, Vulkan 1.3 max [S01][S07][S09] |
| Memory | 8 GB GDDR5 **shared**; loader carves VRAM out of it | VRAM 1 GB → ~6.5–7 GB system RAM; VRAM 4 GB → ~4 GB system RAM [S16][ESTIMATE] |
| Bandwidth | 176 GB/s unified | Good for iGPU, but CPU cache-starved |
| Storage | internal SATA II (~300 MB/s), USB 3.0 (5 Gb/s) | USB SSD ≥ internal; SATA II caps internal SSD [S33] |
| Video out | HDMI 1080p60 (no 4K on Fat) | 1080p60 is the design target |
| Power/heat | 250 W max PSU class; loud fan; Linux fan control optional | Thermal + noise are product features, not afterthoughts [S22][S23] |
| Suspend | **Not supported** | Treat as desktop that always cold-boots [S16] |

## 4. Top 10 risks (ranked)

| # | Risk | Impact | Mitigation (research) |
|---|---|---|---|
| 1 | Firmware updated past exploitability (14.00+ is early/rough) | Project dead on that console | Freeze firmware; `11-risks-legal.md` §2 [S24][S25] |
| 2 | Wrong kernel vs southbridge → no boot ("white light") | Wasted hours, user thinks console is bricked | Model→kernel matrix + profile file [S31][S16] |
| 3 | Mesa/RADV regression (GPU hang with DXVK) | Games crash / black screen | **Pin Mesa** (25.3.5 or 26.0.4 verified stable on gfx7) [S08] |
| 4 | Stock Mesa has no PS4 PCI IDs → silent software rendering | "Desktop feels slow" false diagnosis | Detect with `glxinfo -B`/`vulkaninfo`; install PS4 Mesa [S07][S06] |
| 5 | Internal-disk experiments wipe Orbis/game saves | Data loss | USB-only rule; `11-risks-legal.md` §3 [S27] |
| 6 | DXVK 3.x / future Proton silently raises Vulkan floor | Steam games stop launching | Pin Proton ≤11 / DXVK ≤2.7.x [S12][S13] |
| 7 | No suspend + no RTC | Clock drift, wrong "desktop PC" expectations | Mask sleep targets; timesyncd [S16][S19] |
| 8 | Wi-Fi/BT chip lottery (Marvell 8797/8897 vs MediaTek MT7668) | No network on some units | Kernel matrix + Ethernet-first policy [S03][S05][S21] |
| 9 | Fan/thermal management gaps in some kernels | Overheat, throttling, USB dropouts | Pick kernel with ICC/hwmon fan; `ps4fancontrol` [S22][S23][S30] |
| 10 | Upstream bus factor (tiny projects, one maintainer) | Project stalls | Track licences, fork-readiness, pin commits [S07][S29] |

## 5. Decisions already taken (research decisions, see `decisions.md`)

- **D-01** USB root only; internal disk read-only for the OS.
- **D-02** Firmware frozen at the jailbroken version; no updates without a written re-jailbreak path.
- **D-03** VRAM payload = 1024 MB for desktop, 2048 MB only for emulation/gaming profiles.
- **D-04** Mesa pinned; upgrades are experiments, not package updates.
- **D-05** KDE Plasma is the *product* desktop, **XFCE is the recovery/guaranteed** desktop.
- **D-06** Everything measurable is measured with `09-experiments.md` protocols.

## 6. What the next action is

Hand `10-coding-tickets.md` T-001…T-006 to the coding chat, and run EXP-001/EXP-002/EXP-003 on hardware
(see `09-experiments.md`) — these three experiments produce the numbers that every later decision depends on.
