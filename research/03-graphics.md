# 03 — Graphics: the make-or-break subsystem

**One-line rule:** *stock Mesa cannot render on the PS4 GPU. Only PS4-patched Mesa recognises
Liverpool/Gladius (GFX7-class). If the desktop "feels slow", check this first.*

---

## 1. The stack on PS4

```
application (KDE / browser / game)
        │  OpenGL (GLX/EGL)         │ Vulkan
        ▼                           ▼
   RadeonSI (radeonsi_dri.so)   RADV (libvulkan_radeon.so)     ← userspace, Mesa
        │                           │
        └──────────► libdrm ◄───────┘
                        │
                  amdgpu kernel driver (DRM)                    ← must expose PS4 PCI IDs + clocks
                        │
                   Liverpool / Gladius GPU
```

Two independent gaps have to be closed:

| Gap | Symptom | Fix class |
|---|---|---|
| Kernel does not know the PS4 GPU/clocks | no DRM device, or hangs on init | PS4 kernel tree (out-of-tree patches) [S04][S29][S30] |
| Userspace has no PS4 PCI IDs → picks "llvmpipe"/software | desktop draws, but 100% CPU | **patched Mesa** (libdrm + Mesa + sometimes xf86-video) [S06][S07] |

The historical patches are trivial — *"mostly just add the PCI ID required and a new chip type with the
correct settings"* — which is why every distro needs its own Mesa build [S06].

## 2. Supported API levels (hard limits)

| API | Level on PS4 GPU | Notes |
|---|---|---|
| OpenGL | **4.5–4.6** (reported, e.g. 4.6 on 7.2 Baikal; 4.5 on Pro) | RadeonSI; ACO/LLVM both work [S18][S16] |
| Vulkan | **1.3** (max), RADV | RADV is Khronos-conformant on GFX6/GFX7 since Mesa 24.3 [S09] |
| Vulkan 1.4 | ❌ | GFX6/7 never gets 1.4 in RADV; GFX8+ only [S09] |
| Vulkan sparse resources | only with `RADV_EXPERIMENTAL=sparse` | needed by some emulators [S17][S18] |
| Video decode (UVD) | 🧪 experimental — H.264 1080p bring-up on one board | not a shipping feature [S18] |

### Consequence — the D3D/Proton ceiling

| Layer | Requires | Works on PS4? |
|---|---|---|
| DXVK 1.x | Vulkan 1.0/1.1 | ⚠️ legacy only |
| DXVK 2.x | **Vulkan 1.3** | ✅ |
| DXVK 3.x | **Vulkan 1.4** | ❌ **must not be used** [S12] |
| Proton 11.0 | bundles **DXVK 2.7.1** | ✅ [S13] |
| Proton Experimental (2026) | DXVK master (3.x) | ❌ unless overridden |
| VKD3D-Proton (D3D12) | modern Vulkan features | ⚠️ mostly out of reach; assume no D3D12 |

**Pin list for the coding chat:** `mesa = 25.3.5 or 26.0.4` (verified stable on gfx7 with DXVK),
`dxvk ≤ 2.7.1`, `proton ≤ 11.0`, `vkd3d-proton` excluded from default profile.

## 3. Mesa on PS4 — the known-good matrix

| Mesa version | Result on gfx7 Liverpool with DXVK | Evidence |
|---|---|---|
| System Mesa 26.0.8 (patched build) | GPU hang 10–20 s after first D3D frame (RADV pipeline compile) | [REPORTED] [S08] |
| **Mesa 25.3.5** | stable, 420 s tested, 33–52 FPS (title not published) | [REPORTED] [S08] |
| **Mesa 26.0.4** | stable, 240 s tested, 35–60 FPS | [REPORTED] [S08] |
| Mesa 26.2.x | `radeonsi` fix: "no longer loads for GCN1 / Pitcairn when using radeon driver" — not a PS4 issue but shows churn in old-GPU paths | [VERIFIED] [S10] |
| Mesa 26.3 | radeonsi black-screen fix in compositing path; relevant to Plasma | [VERIFIED] [S11] |

**Rules**
1. Never let a distro update replace the patched Mesa silently (`IgnorePkg`/pin) [S08][S26].
2. Two builds can coexist: `/opt/ps4-mesa` style prefix + `VK_ICD_FILENAMES`/`LD_LIBRARY_PATH` per app [S17][S08].
3. The "GPU hang" is a **RADV** problem, not the kernel and not the hardware: OpenGL and light Vulkan
   (vkcube) work on the same machine, only DXVK-triggered RADV pipelines explode [S08].

## 3-bis. Correction (2026-11-13): the real defect is HiZ, and the patch source moved

Field-proven versions in §3 remain true, but they are a *workaround*. The **root cause** is now known:
RADV enables **HiZ (HTILE)** on Liverpool/Gladius and HiZ hangs the `gfx` ring on the first DXVK frame.
The maintained fix is `ps4-multiboot`'s `patches/mesa/0002-radv-ps4-no-hiz.patch`
(`use_hiz = false` for `CHIP_LIVERPOOL`/`CHIP_GLADIUS`). Diagnostic without rebuilding:
`RADV_DEBUG=nohiz`. Authoritative patch set and pinned versions: `14-pinned-inputs.lock.yaml`.

## 4. Where to get patched Mesa

| Source | Form | Status | Notes |
|---|---|---|---|
| `DionKill/ps4-video-archlinux` | Arch binary repo + PKGBUILDs | active (2026) | `[ps4-video]` pacman repo; mesa-ps4, lib32-mesa-ps4, libdrm-ps4, xf86-video-amdgpu-ps4 [S07] |
| `centi07/arch-ps4-aur` | same lineage | **archived Jan 2026** | do not depend on it [S07] |
| `blue0x1/ps4-multiboot` (`ps4-mesa.tar.xz`) | self-contained bundle `/opt/ps4-mesa` | active | OpenGL 4.5 + Vulkan 1.3; **glibc floor is 2.41** (builder `debian:trixie`; the README's "2.38" is stale); tested on Pro [S17][S43] |
| `blue0x1/ps4-multiboot` → `patches/mesa/0001,0002` | **2 patches, blob-verified** | active (2026-11) | **primary patch source**: PCI IDs/GFX7 map + RADV HiZ disable [S43] |
| `ps4-linux/linux` (kernel repo) | — | **404 (unreadable)** | do not depend on it [S43] |
| `fail0verflow/ps4-radeon-patches` | original 2015 patches | historical | explains *why* it is just PCI IDs + chip type [S06] |

**Research recommendation (updated 2026-11-13):** build our own Mesa **26.2.5 + libdrm 2.4.134** with
multiboot's two patches into `/opt/ps4-mesa`, and select it with the `ps4-mesa-enable` mechanism
(`/etc/ld.so.conf.d/00-ps4-mesa.conf` + `VK_DRIVER_FILES` + Xorg `modesetting/glamor/DRI 3`), keeping the
distro's Mesa intact. `Ps3itaTeam` is historical reference only. Build **25.3.5** in parallel as the
EXP-009 control. Note the bundle is configured `-Dgallium-va=disabled -Dvideo-codecs=`: **no VA-API**. 

## 5. Kernel-side graphics requirements

From the active kernel trees, the graphics-relevant features that must be present:

- LIVERPOOL/GLADIUS identified as GFX7-family with correct raster config registers and Gladius registers
  (the Pro's "Gladius register fix" gave a large Pro performance boost) [S03][S07].
- Clock settings: without proper clock programming `amdgpu` refuses to load (crashniels' original finding) [S04].
- GLK/display bridge patches for HDMI hotplug and modeset on Slim/Pro [S29][S17].
- Optional: `AMD_DEBUG=notiling` workaround when tiled scan-out is corrupted on some Belize units
  (`nodcc` did **not** fix it) [S15].
- `/dev/ps4-mesa-lock` (present in `feeRnt@7.0-Clean`): the kernel and Mesa exchange a build token; on
  mismatch the write fails with `-EPERM` and dmesg prints `ps4-mesa-lock: kernel mismatch`. This **is** the
  kernel↔Mesa consistency check — do not invent another one [S43].

## 6. Performance envelope (what to promise users)

| Workload | Realistic target | Constraint |
|---|---|---|
| 1080p60 desktop compositing | ✅ | 18 CUs are plenty for Plasma at 1080p |
| 1080p H.264 video (software) | ✅ ~30–60 fps if CPU has headroom | Jaguar at 1.6 GHz is the limit [ESTIMATE] |
| 1080p VP9/AV1 | ❌/⚠️ | CPU-only decode is too slow at 1080p60 |
| Steam, 2010–2015 era 3D titles | ✅ 720p–900p, low preset | DXVK 2.x + GCN 18CU |
| Steam, 2018+ 3D titles | ⚠️ mostly unplayable | CPU + GFX7 limitations |
| Dolphin (GameCube) | ✅ many titles 30/60 fps | PS4-native fork data [S28] |
| Dolphin (Wii) | ⚠️ 40–50 fps typical | CPU-bound [S28] |
| Vulkan compute / LLM | ❌ | no ROCm for this part, no AVX2 on CPU |

## 7. Open questions (→ experiments)

1. EXP-004: baseline frame times of Plasma + Firefox on Mesa 25.3.5 vs 26.0.4.
2. EXP-005: does `amdgpu.dpm=1` (power management) work without hangs? If yes → cooler, quieter.
3. EXP-006: does enabling `AMD_DEBUG=notiling` help on the target unit's display?
4. EXP-007: what is the highest `MESA_GL_VERSION_OVERRIDE` that is *honest* for our GPU?
   (Answer: none — never lie to apps about GL/VK level.)
