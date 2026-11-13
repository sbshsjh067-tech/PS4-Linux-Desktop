# 04 — Desktop environment: KDE Plasma on a 2013 console APU

The README's promise is "Windows-like desktop". This document decides *how* that is achieved within
the hardware budget of `01-hardware-firmware.md`.

---

## 1. Choices considered

| DE | RAM idle (typical PC, 2026) | GPU needs | Windows-like | Verdict |
|---|---|---|---|---|
| **KDE Plasma 6.x** | ~0.8–2.0 GB depending on distro/tuning | GL 2.0+, better with GL 3.3+/Vulkan compositor | ✅ very | **Product default** (README requirement) |
| XFCE 4.18/4.20 | ~0.3–0.5 GB | GL 2.0 | ⚠️ classic | **Recovery / low-RAM profile** |
| LXQt | ~0.3 GB | GL 2.0 | ⚠️ | optional |
| GNOME | ~1.2–2.5 GB | GL 3.3+, heavy | ❌ | reject (memory + GPU) |
| Hyprland (tiling Wayland) | ~0.4–0.8 GB | GL 3.3, Wayland | ❌ not Windows-like | research only (Omarchy ports use it) [S19][S20] |

Official Plasma minimums are 2 GB RAM / OpenGL 2.0 [S34], but those numbers assume a normal PC with
discrete-class GPU behaviour. On PS4 the binding constraints are different: **GPU is fine, CPU and
memory bandwidth per core are not**, and half the RAM may have been carved out as VRAM (`01` §4).

## 2. Recommended target configuration

| Setting | Value | Reason |
|---|---|---|
| Resolution / refresh | 1920×1080 @ 60 Hz | only mode the PS4 display path is designed for [S02] |
| Scaling | 100 % only, never fractional | fractional scaling = extra GPU/RAM cost |
| Compositor | OpenGL 3.1 (RadeonSI), **not** software | software compositing is unusable at 1080p |
| Effects | blur, transparency, wobbly windows **off**; shadows on ("low latency" preset) | Plasma 5.21+ latency/animation preset matters on weak GPUs [S35] |
| Session | X11 first (fallback Wayland) | X11 has the most PS4 field reports; Wayland tested by Omarchy PS4 [S19] |
| KWin animations | "instant"/reduced | CRITICAL on Jaguar |
| Baloo (file indexer) | **disabled** | CPU + disk on USB |
| Akonadi/PIM | not installed by default | memory |
| KDE Connect, Discover auto-update | disabled | background CPU/IO |
| Font rendering | subpixel off, hinting slight | cheaper |
| Swap | zram (lz4) + optional small swapfile | trades CPU for RAM; Android-style zram is widely used on PS4 guides [S26] |
| Sleep/dim | all masked | suspend unsupported [S16] |

**Expected result:** ~600–900 MB idle RAM, smooth window drag, 1.5–2 s app cold starts [ESTIMATE, EXP-003].

## 3. Why not "just install the distro's KDE"

Because two things silently break the experience:

1. **Stock Mesa** → KWin falls back to software rendering; the desktop stutters and the CPU pegs
   (see `03-graphics.md` §1). Users then blame the console.
2. **Distro-default services** (Baloo, Akonadi, PackageKit, snapd/flatpak auto-update, tracker) consume
   the scarce CPU. A "resting" desktop must be quiet.

Both are packaging decisions, not philosophy: the image should ship the tuned profile by default.

## 4. Lightweight fallback path (must always exist)

A recovery desktop guarantees the user is never stranded when Plasma misbehaves on a specific
kernel/Mesa combination:

- `xfce4` + `lightdm` (or `sddm` with XFCE session option), ~350 MB idle.
- Documented in the user guide as: "if Plasma does not start, log into XFCE and run the doctor script".
- XFCE is also the profile for the 512 MB VRAM/server payload.

Precedent: PS4 Linux field guides explicitly recommend light DEs when 3D is not available, and distros
that ship KDE on PS4 exist (Arch+KDE image tested on Pro/Slim) [S16][S17].

## 5. Display manager and session plumbing

| Topic | Recommendation | Notes |
|---|---|---|
| DM | SDDM (Plasma-native) with autologin | autologin removes an extra compositor start |
| Fallback DM | lightdm (XFCE) present in image | selectable |
| Session start problems | `dbus-run-session -- startplasma-x11` from a TTY | standard rescue for black login screen [S21] |
| TTY switching | `Ctrl+Alt+F1…F7` | recover display after HDMI source switch [S03] |
| X config | `xf86-video-amdgpu-ps4` or modesetting | some PPAs need the patched DDX [S07] |
| Colors/Deep Color/HDR | **off** in PS4 settings before boot | Pro/Baikal black-screen reports fixed by this [S19] |

## 6. Locale, time, and the "feels like a PC" details

- No usable RTC on this Linux build → enable `systemd-timesyncd`; expect 1970 until network is up [S19].
- Keyboard layout / locale must be selectable at first boot (Arabic/Egypt context: RTL and Arabic fonts
  must be installed — `noto-fonts` with Arabic coverage; Plasma handles RTL).
- Audio: prefer USB audio device; HDMI audio may be absent depending on kernel branch [S30][S03].
- Power button behaviour: `HandlePowerKey=poweroff` (suspend is masked anyway).

## 7. Acceptance criteria for the desktop milestone (M3)

| Metric | Target | Tool |
|---|---|---|
| Idle RAM (Plasma, no apps) | ≤ 900 MB | `free -h`, `ps_mem` (EXP-003) |
| Idle CPU | ≤ 8 % average over 60 s | `vmstat 1 60` |
| Window drag / move smoothness | no visible tear/stutter at 1080p | manual + `kwin` perf overlay |
| App cold start (Dolphin/Konsole) | ≤ 2.5 s | `systemd-analyze`/manual |
| Cold boot → usable desktop | ≤ 120 s | EXP-002 |
| XFCE fallback boots on every supported kernel | 100 % | test matrix |
| Desktop survives 30 min idle without GPU hang | yes | EXP-008 |
