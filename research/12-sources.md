# 12 — Sources

Every claim in this handbook carries a tag like `[S07]`. This file is the index.
Accessed **2026-11-13** unless stated. A source is "primary" when it is the project's own repository,
release notes, or official documentation; community forums are secondary and marked `[REPORTED]` when used.

> **Note on link rot:** several well-known PS4 Linux repositories move, get renamed, or go private.
> During the 2026-11-13 audit, `github.com/ps4-linux/ps4-linux-loader`, `github.com/ps4-linux/linux` and
> `github.com/sony-jaguar-devs/ps4-linux` returned **404** from our sandbox while their GitHub API records
> were still visible. Treat them as *referenced but currently unreachable*: replicate anything we depend on
> (kernel patches, loader) into our own storage before building on it. See `11-risks-legal.md` §5.

## Kernel / boot

| ID | Source | Type | Used for |
|---|---|---|---|
| S03 | `feeRnt/ps4-linux-12xx` — releases + README (6.15.4 Aeolia/Belize, 5.4.247 Baikal, 5.15.15 Belize) | Primary | Wi-Fi/BT fixes, blackscreen-at-DM fix, Gladius register fix, bootargs sample, tested models |
| S04 | ps4linux.com — "Kernel 6.6 for PS4 Linux with AMDGPU support, by crashniels" (2025-02-11) | Article | AMDGPU clock issue, radeon-vs-amdgpu history, IRQ/ACPIe caveat for 6.8+ |
| S14 | `meerzulee/omarchy-ps4` — `knowledge/2026-08-10/FW-12.02-PAYLOAD-CHAIN.md` | Primary | Loader v25 runtime southbridge detection, file precedence, `vram.txt` MB semantics, legacy stale bootargs |
| S15 | `ps4-linux/ps4-linux-loader` — issue #15 (14.00 CUH-2016A, v25.2) | Primary (issue thread) | Root cause of "payload wedges console", `AMD_DEBUG=notiling` for tiled scan-out, OpenGL 4.6 + Vulkan 1.3 on Belize |
| S16 | `X-F1REBALL-X/PS4-Linux` — README | Primary | Model→kernel matrix, white vs blue light, payload VRAM table, "no suspend", no `bzImage` on USB, KDE image tested on Pro/Slim |
| S17 | `blue0x1/ps4-multiboot` — README | Primary | Boot menu + installer, internal image files vs USB, `ps4-mesa` bundle (GL 4.5 / VK 1.3), HDMI keep-alive service, Wi-Fi NM workarounds, `ps4_rootwait` |
| S18 | `meerzulee/linux-psx` — README | Primary | 7.2 Baikal boot, UVD H.264 experimental (900-frame match), OpenGL 4.6 1080p60, fan interface missing on 6.18.44 |
| S29 | `sony-jaguar-devs/ps4-linux` — README (7.0-Clean status) | Primary | Front-panel LED driver w/ thermal mode, fan threshold + RPM hwmon driver, lower min fan threshold, `/dev/ps4-mesa-lock`, in-tree firmware blobs |
| S30 | `feeRnt/ps4-linux-12xx` — release notes (config updates) | Primary | HDMI audio support status, USB audio/MIDI support, USB-BT support, webcam/media configs |
| S31 | `Hakkuraifu/PS4Linux-Documentation` — README | Primary (legacy) | Southbridge naming, driver package names (`mesa-ps4`, `xf86-video-amdgpu-ps4`), HDMI refresh workaround |

## Graphics

| ID | Source | Type | Used for |
|---|---|---|---|
| S05 | ps4linux.com — "WiFi and Bluetooth fix with blackscreen fix for PS4 Linux on CUH-12XX" (feeRnt kernels) | Article | Marvell 8897 Torus 2 Wi-Fi/BT fix lineage, tested models CUH-1215/1216, 5.15/6.15 branches |
| S06 | `fail0verflow/ps4-radeon-patches` + `Ps3itaTeam/ps4linux-video-drivers` (`mesa.patch`) | Primary (patches) | PS4 PCI IDs `0x9920/22/23/24`, LIVERPOOL/GLADIUS as GFX7-class, raster config constants, "just PCI ID + chip type" |
| S07 | `DionKill/ps4-video-archlinux` — README | Primary | `[ps4-video]` Arch repo, packages `mesa-ps4 free`, `libdrm-ps4`, `xf86-video-amdgpu-ps4`; notes `centi07/arch-ps4-aur` archived 2026-01-12 |
| S08 | `Abrahamqb/Vulkan-Fix-PS4` — README (ES/EN) | Primary | Mesa 26.0.8 RADV hang with DXVK on gfx7; Mesa 25.3.5 & 26.0.4 verified stable with FPS ranges; OpenGL + vkcube unaffected; PS4 patch only adds LIVERPOOL/GLADIUS as GFX7 |
| S09 | Mesa docs — RADV supported hardware + Phoronix "RADV delivers conformant Vulkan 1.3 for GFX6/GFX7" (2024-11) | Primary/official | Vulkan 1.3 max on GFX6-7; Vulkan 1.4 only GFX8+; conformance since Mesa 24.3 |
| S10 | Mesa 26.2.2 release notes (2026-09-02) | Primary | `radeonsi` no longer loads for GCN1/Pitcairn on radeon driver (loader predicate) |
| S11 | Mesa 26.3.0 release notes / GamingOnLinux (2026-11-10) | Primary | radeonsi black-screen fix in compositing path (picom), Doom3 BFG, NGG culling hangs |
| S12 | DXVK 3.0 release coverage — Phoronix (2026-06-25) + linuxcompatible | Article | DXVK 3.0 **requires Vulkan 1.4**; Mesa 25.0 min; descriptor heaps; DXBC→SPIR-V |
| S13 | r/linux_gaming — "Proton 11.0-2 is out" (2026-08) | Community | Proton 11 ships DXVK **2.7.1** (Vulkan 1.3) → PS4-compatible; Experimental tracks DXVK master |

## Desktop / system

| ID | Source | Type | Used for |
|---|---|---|---|
| S01 | Digital Foundry — "Spec Analysis: PlayStation 4" | Reference | Jaguar 8-core 1.6 GHz, 18 CU @ 800 MHz, 1.84 TFLOPS, 176 GB/s |
| S02 | PlayStation official tech specs page | Primary | PS4 250 W max / Slim 165 W / Pro 310 W, 8 GB GDDR5, USB layout |
| S19 | `meerzulee/omarchy-ps4` — README + `docs/GETTING-STARTED.md` | Primary | Hyprland/Wayland on PS4, no usable RTC → timesyncd, HDR/Deep Colour/RGB must be off (Pro black screen), FPKG-managed boot set |
| S20 | `meerzulee/omarchy-psx` — README | Primary | Roadmap, USB flash→launch→setup flow, PCIe/native Ethernet work |
| S21 | `dionkill/ps4-linux-tutorial` — issues / postinstall pages | Primary (guide) | MediaTek Wi-Fi needs specific kernel fixes, Wayland start commands, BT key copying limitation, driver pinning, zram instructions |
| S26 | `dionkill` postinstall guide (zram + package pinning) | Guide | zram-generator config, excluding PS4-patched Mesa/libdrm/LLVM from updates (dnf `exclude=`, pacman repo) |
| S33 | r/PS4 — external SSD / SATA-II megathread | Community | Internal bus is SATA II on Fat/Slim (SATA III on Pro); USB 3.0 often faster than stock HDD |
| S34 | KDE/Plasma minimum requirements summaries (KDE neon wiki quotations) | Secondary | Plasma 6: ~2 GB RAM min, GL 2.0 min, 4 GB+ recommended |
| S35 | r/kde — Plasma 5.21 compositor latency preset thread | Community | "Low latency" vs "smooth" animation preset matters on weak GPUs |
| S36 | Brave issue #16392 + r/linuxquestions VA-API thread | Community | Browser VA-API decoding is fragile/unreliable on Linux; do not promise HW decode |

## Thermal / power / peripherals

| ID | Source | Type | Used for |
|---|---|---|---|
| S22 | `JKeyRandom/ps4fancontrol` — README | Primary | ICC-based fan threshold CLI, range 45–85 °C, `/dev/icc`, root |
| S23 | r/ps4homebrew — "PS4 Linux Fan Control" thread | Community | Default target ≈78 °C; too-low thresholds cause permanent max fan |
| S27 | r/ps4homebrew — "Run Linux off internal HDD" (mircoho et al.) | Community | Internal installation requires reinstalling Orbis every reboot; SATA swap trick |
| S37 | r/ps4homebrew — "For those who installed PSXitARCH linux…" (Wi-Fi association across kexec) | Community | Wi-Fi module keeps Orbis association → interface dead in Linux until reboot |
| S38 | `dionkill` tutorial — Bluetooth section | Guide | Pairing keys must be copied from PS4 OS; known unsolved |
| S39 | r/ps4homebrew — "Is your ethernet connection working on psxitarch?" | Community | GbE negotiation issues → force 100 Mb/s / manual link negotiation |

## Firmware / jailbreak

| ID | Source | Type | Used for |
|---|---|---|---|
| S24 | onejailbreak (2026-11-02) — "PS4 14.00 Browser Jailbreak Loads Latest GoldHEN" (Afterglow host, m0zz, GoldHEN 2.4b18.13) | Article | 14.00 public path exists but is rough, requires PC-served pages; documented failure mode leaving console stuck until cold start |
| S25 | superpsx (2026-09-20) + doctorglitch (2026-10) — GoldHEN 2.4b18.11/.12 for 13.52/13.02-13.50 | Article | Firmware → GoldHEN support matrix; 14.00 released 2026-09-16 |
| S28 | `iHaiDeeZ/DolphinPS4` — README | Primary | Per-game FPS table on launch PS4 (GC 30/60, MK Wii 40–50, Galaxy 40–60); "CPU is the bottleneck" |
| S32 | `blue0x1/EmuFive` — README + TechPowerUp coverage (2026-11-12) | Primary/Article | Jaguar lacks AVX2/FMA/BMI2 → `-march=btver2` builds; official AVX2 binaries die with "Illegal instruction" |

## Community hubs (context, not evidence)

| ID | Source | Notes |
|---|---|---|
| S40 | ps4linux.com — downloads page, kernel list, comment threads | Best single index of distros/kernels; comments are the de-facto support forum |
| S41 | `Hakkuraifu/PS4Linux-Documentation` (2022) | Historical baseline; still the clearest description of the 2016–2021 era |
| S42 | r/ps4homebrew — black-screen troubleshooting threads | Field data for HDMI/EDID behaviour (TV vs monitor) |

---

### How sources were verified in this audit

1. Repository files were read through the GitHub API (`readme` endpoint, raw contents) and via page fetch.
2. Version-specific claims (Mesa, DXVK, Proton, GoldHEN) were checked against release notes, not blog
   summaries, wherever the release notes were reachable.
3. Claims that only exist in community threads are tagged `[REPORTED]` and are never used to justify a
   *blocking* design decision without an experiment in `09-experiments.md`.
4. Anything we could not reach (404 / dead host) is recorded as such above and must not be a build
   dependency without mirroring.
