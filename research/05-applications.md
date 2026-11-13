# 05 — Applications: what actually runs, and what to configure

Every row below is a **product claim** the project will make. If it is not in this table with a
confidence tag, the project must not promise it.

---

## 1. Summary table

| App | Works? | Config that makes it work | Main risk |
|---|---|---|---|
| Firefox | ✅ | software video decode; consider `MOZ_X11_EGL=1`; limit content processes | CPU on modern sites |
| Chromium/Chrome | ✅ with flags | `--use-gl=egl`, `--enable-features=VaapiVideoDecodeLinuxGL` **only if** UVD proven | VA-API not ready → 100 % CPU |
| Steam client | ✅ | use **Proton ≤ 11** (DXVK 2.7.1); disable shader pre-caching; Big Picture at 720p | DXVK 3.x → GPU hang [S08][S12] |
| Dolphin (emulator) | ✅ GC / ⚠️ Wii | use PS4-native fork + per-game recommended settings | CPU-bound; some titles crash |
| VLC | ✅ (H.264/MPEG-4) | `--avcodec-hw=none`; output `gl` or `xcb_xv` | no HW decode for VP9/AV1 |
| mpv | ✅ | `vo=gpu`, `hwdec=no` | same codec limits |
| LibreOffice | ✅ | disable Java, disable OpenCL, disable "use OpenGL" if unstable | slow cold start |
| GIMP / Krita | ⚠️ | GIMP ok for light work; Krita slow on Jaguar | CPU |
| VS Code / Electron | ⚠️ | works but heavy; `--disable-gpu-compositing` sometimes needed | memory |
| Docker/KVM | ✅ | kernels ship cgroups/KVM in some branches; Kali/VM use documented [S03][S30] | nested perf |
| RetroArch | ✅ | GL core, Use `gl` driver; 2 GB VRAM payload helps | shader compile on RADV |
| Any AVX2 binary (new emulators, AI tools) | ❌ | will SIGILL | `-march=btver2` rebuild needed [S32] |

## 2. Browser — the real "desktop" workload

The README's first promise is a web browser; on this hardware the browser *is* the benchmark.

**Findings and rules**

1. **Do not enable hardware video decoding by default.** UVD/H.264 is experimental, only on one board
   family, and Chromium/Firefox flags for VA-API are fragile on AMD + Wayland [S18][S36].
2. Prefer **H.264/AAC** sources (YouTube "stats for nerds" → avc1). VP9/AV1 at 1080p will drop frames on
   8 Jaguar cores [ESTIMATE, EXP-004].
3. Cap parallel content: Firefox `dom.ipc.processCount=2`, disable pocket/telemetry, keep GPU process off if
   it causes RADV crashes.
4. Use a **lighter front end** for heavy sites: skip Electron-based "apps", prefer plain web tabs.
5. Test protocol EXP-004 (Speedometer/JS score + 1080p H.264 playback CPU%).

**Realistic user experience:** 1080p90 scrolling is fine; a modern heavy SPA (Teams/Discord web) will
feel like a 2013 laptop; video calls are CPU-limited (software encoding, 640×480–720p max).

## 3. Steam — conditional but achievable

Evidence chain:
- Steam + Big Picture + Vulkan/RADV reported working on PS4 Linux (FW 14.00 report) [S15].
- The blocker is **not** Steam; it is the *Vulkan floor* of the D3D translation layer.
- Proton 11.0 ships DXVK **2.7.1** (Vulkan 1.3) → compatible [S13].
- Proton Experimental ships DXVK master (3.x, Vulkan 1.4) → **incompatible** [S12][S13].
- GCN 1.0/1.1 are on their way to *more* upstream attention (kernel 6.19 makes amdgpu default) but
  Vulkan stays 1.3 [S12][S09].

**Recommended Steam profile for PS4**
```
Proton: 11.0 (forced) or 9.0-4 for older D3D9 titles
DXVK: ≤ 2.7.1 (bundled)
Launch options: -force-d3d11 for D3D9+ games; -windowed -w 1280 -h 720 for first run
Settings: shader pre-caching OFF (disk+CPU), Texture filtering low, VSync ON (screen tearing on HDMI)
Steam Play: enabled for all titles
Avoid: D3D12 (VKD3D), anti-cheat games, launchers with AVX2 (some EA/Ubisoft installers)
```

**What to play:** 2D indies, older 3D (Portal 2, Half-Life 2, L4D2, Sonic Generations, Cuphead, Hades),
emulation front-ends. **What not to promise:** Cyberpunk/Elden Ring/FPS titles.

## 4. Dolphin (GameCube/Wii) — evidence exists on this exact hardware

A PS4-native Dolphin fork (Vulkan on the PS4 GPU, PSP-style XMB UI) publishes per-game FPS on PS4:

| Title | Result |
|---|---|
| Super Smash Bros. Melee | 36–60 fps |
| Mario Kart: Double Dash!! | 60 fps (Pro) |
| Super Mario Sunshine / RE4 / Twilight Princess | their native 30 fps |
| Super Mario Galaxy (Wii) | 40–60 fps |
| Mario Kart Wii | 40–50 fps |
| Wii Sports | ~40 fps |

Source: [S28]. The fork notes the **CPU is the bottleneck, not the GPU**, and recommends
"Emulated CPU clock = Auto" and "Frame limit Auto (60/30)" for smoothness.
**Project rule:** ship this fork's recommended settings as defaults; do not promise Wii at full speed.

## 5. Media (VLC/mpv) — codec reality

- UVD (hardware H.264 decode) is under active bring-up (900-frame reference match on one board) [S18];
  until it is on the target board, assume **software decode**.
- 1080p30 H.264 in software is feasible; 1080p60 H.265 is not; 4K is not.
- Use `vaapi` only after `vainfo` proves a driver; otherwise force software to avoid bad fallbacks.
- HDMI audio may require kernel branch with HDMI audio patches; **USB audio is the safe default** [S30].

## 6. LibreOffice / office work

- Runs; startup ~8–15 s cold on USB + Jaguar [ESTIMATE].
- Disable: Java runtime, OpenCL, "use OpenGL for rendering" (unless proven), auto-spellcheck on huge docs.
- Writer + Calc are fine for typical documents; Impress animations should be simple.
- Print: CUPS works; test a USB printer if the user needs it.

## 7. Peripherals (acceptance matrix → EXP-010)

| Device | Expected | Notes |
|---|---|---|
| USB keyboard/mouse (wired) | ✅ | |
| Wireless dongle (Logitech Unifying etc.) | ✅ | generic HID |
| DualShock 4 (USB cable) | ✅ | hid-playstation; usable as gamepad/mouse |
| DualShock 4 (Bluetooth) | ⚠️ re-pair every boot | pairing keys not carried over; manual workaround exists [S16] |
| USB headset/mic | ✅ | `CONFIG_SND_USB_AUDIO` in modern configs [S03] |
| USB flash / external SSD | ✅ | rootfs lives here |
| USB printer/scanner | ✅/⚠️ | CUPS/sane, test unit |
| Webcam | ✅ | v4l2; higher CPU for software encoding [S03] |
| Controllers with proprietary drivers | ❌ | Xbox 360 wireless needs xpad + dongle, mostly works |

## 8. Applications that must be **explicitly unsupported** in the docs

- Anything requiring AVX2/FMA (most 2024+ emulators, LLM runtimes, some installers)
- Waydroid (needs modern kernels/containers + CPU features)
- HD/4K streaming DRM (Widevine L3 only; Netflix 1080p unlikely)
- Modern AAA Steam games, anti-cheat multiplayer
- Video editing (Kdenlive/Shotcut) beyond 720p proxies
- Virtualisation of Windows 11 (KVM exists in some kernels [S03], but CPU features/performance make it a demo, not a feature)
