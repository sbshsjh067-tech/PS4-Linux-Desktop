# 07 — Upstream landscape: what exists, what to reuse, what to avoid

The PS4 Linux scene is **small, fast-moving, and has a bus factor of one or two people per project**.
This document is the map the coding chat must consult before writing anything from scratch.

Last audit: **2026-11-13**.

---

## 1. Tier 1 — boot + kernel (must-have dependencies)

| Project | What it gives us | Status 2026-11 | Licence | Risk |
|---|---|---|---|---|
| `ps4-linux/ps4-linux-loader` (Firmware-Agnostic PS4 Linux Loader) | Payloads 32 MB→4 GB VRAM; runtime FW + southbridge + Pro detection; unified ELF/BIN | Active (pushed 2026-11-12), ~115★ | GPL-family (check) | Repo returned **404** to our sandbox on 2026-11-13 → **mirror it** |
| `ps4-linux/linux` (kernel tree) | Kernel source with PS4 patches | Active (pushed 2026-11-12) | GPL-2.0 | same 404/visibility issue → mirror |
| `sony-jaguar-devs/ps4-linux` (`7.0-Clean`) | Kernel with LED thermal mode, fan hwmon, `/dev/ps4-mesa-lock`, extra firmware | Active-ish | GPL-2.0 | README unreachable 2026-11-13 (known via search index + downstream citations) |
| `meerzulee/linux-psx` | 7.x kernels for PS4/PS5, diagnostics suite, UVD research | **Very active** (pushed 2026-11-11) | GPL-2.0 | one-person project; excellent evidence quality |
| `feeRnt/ps4-linux-12xx` | 6.15.4 Aeolia/Belize + 5.4.247 Baikal with Wi-Fi/BT/black-screen/Gladius fixes | Active (2026-10-30), 48★ | GPL-2.0 | branch-based releases; 6.15 generation |
| `blue0x1/ps4-multiboot` | Installer + boot menu + **self-contained `ps4-mesa` bundle** | Active | GPL-2.0 | performs internal-image installs — we only use its Mesa bundle + kernel patches |
| `X-F1REBALL-X/PS4-Linux` | Ready Arch+KDE USB image, kernels 7.1.7 (Belize) / 7.0.8 (Baikal), verified on Pro & Slim | Active (2026-10-23) | check repo | closest existing answer to *our* README goal → **read its whole guide** |
| `meerzulee/omarchy-ps4` / `omarchy-psx` | Wayland/Hyprland desktop on PS4, FPKG-based boot manager, USB-first install flow | Active (2026-11-11) | check | different DE, but the **boot/install UX is the best in the scene** |

## 2. Tier 2 — graphics userspace

| Project | Role | Use |
|---|---|---|
| `DionKill/ps4-video-archlinux` | Patched Mesa/libdrm/xf86-video-amdgpu for Arch (`[ps4-video]` repo) | reference PKGBUILDs → we build our own pinned Mesa |
| `centi07/arch-ps4-aur` | Archived Jan 2026 | **do not depend** |
| `Abrahamqb/Vulkan-Fix-PS4` | Documents the DXVK↔RADV gfx7 hang + working Mesa versions | **read `reports/ps4-vulkan-diagnosis.md`** → answers GFX-002 |
| `Ps3itaTeam/ps4linux-video-drivers`, `fail0verflow/ps4-radeon-patches` | Canonical patch set | patch source of truth |
| `blue0x1/EmuFive`, `alechurri/nx-on-orbis` | Evidence that RADV on PS4 gets Vulkan 1.3 + sparse (`RADV_EXPERIMENTAL=sparse`) | feature-flag reference |

## 3. Tier 3 — applications with PS4 builds

| Project | Notes |
|---|---|
| `iHaiDeeZ/DolphinPS4` | Dolphin port with Vulkan-on-PS4 + per-game FPS table (see APP-005) |
| RetroArch / EmulationStation forks (`danyboy666/ps4-retrobox`) | `amdgpu_shim.so` trick: reports `ACCEL_WORKING` so Mesa uses radeonsi — **study before inventing our own** |
| `GoldHEN/GoldHEN` | The jailbreak host we depend on; FTP + payload loader |

## 4. What we should NOT rebuild

- ❌ A kernel fork. We consume a maintained tree + our config + our patches (`T-002`).
- ❌ A loader. We consume the firmware-agnostic loader, mirrored and checksummed.
- ❌ A Mesa fork with a new driver. We patch an upstream tag with the known 4-hunk patch set.
- ❌ An installer that repartitions the internal disk. Out of scope by policy D-01.
- ❌ An emulator. We use DolphinPS4/RetroArch and publish settings.

## 5. Healthy-dependency rules (research → coding)

1. **Pin by commit**, never by branch: `kernel@<sha>`, `loader@<sha>`, `mesa@<tag>+patches`.
2. **Mirror** every artefact we build on into our own storage; a 404 today is a broken build tomorrow.
3. **Record licence** of every reused component in `11-risks-legal.md` §5 before shipping an image.
4. **One integration test per upstream bump** (`EXP-002`, `EXP-003`, `EXP-008`, `EXP-009`).
5. Prefer upstream fixes: if we patch something, open/link an upstream issue first (the scene merges fast).

## 6. Gap analysis — what nobody has done yet (our opportunity)

| Gap | Why it matters | Owning ticket |
|---|---|---|
| A **reproducible KDE Plasma image** with pinned Mesa + doctor script | Every existing image is hand-built and silently breaks on updates | T-006, T-009 |
| A **hardware profile file** (model/southbridge/FW/VRAM/Wi-Fi chip) shipped with the image | 60 % of support questions are "which kernel/payload do I use?" | T-003 |
| **Failure diagnosis tooling** (`ps4-doctor`) mapping symptoms → BOOT/GFX/NET IDs | Cuts support load, makes this handbook executable | T-005 |
| **Automatic payload delivery** from a phone/PC after jailbreak | Removes the `nc`/payloader step from the UX | T-014 |
| **Thermal-aware profile** (fan curve + governor) | Safety + noise; kernels differ wildly | T-012 |
| Region/locale-correct desktop (Arabic, RTL, timesync) | The README targets a global audience; nobody ships this | T-016 |
