# 01 — Hardware & firmware facts

Everything here is a **constraint** for the rest of the project. No code decisions may contradict it.

## 1. The APU

| Item | Value | Confidence |
|---|---|---|
| CPU | AMD Jaguar, 8 cores (2 × quad-core modules), 1.6 GHz base | [VERIFIED] [S01] |
| CPU ISA | x86-64, AVX, SSE4.2, AES, F16C. **No AVX2, no FMA3, no BMI2** | [VERIFIED] [S32] |
| L2 cache | 2 MB per quad (4 MB total), no L3 | [VERIFIED] |
| GPU | "Liverpool" (PS4 / Slim), "Gladius" (Pro) — GCN, **18 CUs @ 800 MHz**, 1.84 TFLOPS | [VERIFIED] [S01] |
| GPU family | GFX7-class in Mesa/kernel terms (patched as Bonaire-like) | [VERIFIED] [S07][S08] |
| GPU PCI IDs | `0x9920`, `0x9922`, `0x9923` (Liverpool), `0x9924` (Gladius/Pro) | [VERIFIED] [S07] |
| Memory | 8 GB GDDR5 unified, 176 GB/s | [VERIFIED] [S01] |
| Video out | HDMI 1.4-class on Fat/Slim → **1080p60** is the target mode | [VERIFIED] |
| Storage bus | Internal SATA II (~300 MB/s cap), 2 × USB 3.0 | [VERIFIED] [S26] |
| Extra | Optical drive, Marvell/MediaTek Wi-Fi+BT combo, NEC/renesas USB, ICC (fan/thermal controller) | [REPORTED] [S03][S22] |

**Build implication:** any binary built for `x86-64-v2`/AVX2 crashes with *Illegal instruction*.
Use `-march=btver2` (Jaguar) or `-march=x86-64 -mtune=btver2`. This is exactly the trap that hit
KytyPS5/Eden ports on PS4 [S32].

**Expectation setting:** roughly a low-end 2013 laptop: 1080p desktop compositing is fine;
H.264 1080p30 software decode is fine; modern web apps are the real CPU limit; 3D games ≈ 2012–2014
titles at 720p–900p.

## 2. Console revisions → southbridge → kernel

The **southbridge** ("Aeolia", "Belize", "Baikal") is what selects the kernel. The model number alone is
not always enough (some Slims/Pros are Belize, some are Baikal).

| Model family | Name | Southbridge | Wi-Fi/BT chip | Kernel family needed |
|---|---|---|---|---|
| CUH-100x, 110x | Fat (launch) | **Aeolia** | Marvell 88W8797 (Torus 1) | Aeolia/Belize kernels (7.x patched) [S31][S16] |
| CUH-12xx | Fat (2015) | **Belize** | Marvell 88W8897 (Torus 2) | Belize 7.x (best supported) [S03][S31] |
| CUH-2xxx (Slim) | Slim | Belize **or** Baikal (motherboard dependent) | 88W8897 or MT7668 | match by chip, not by model [S31] |
| CUH-7xxx (Pro) | Pro | Belize (70xx) or Baikal | 88W8897 or MT7668 | Gladius GPU patch only exists for Pro [S03][S07] |

**How to check on the console:** Settings → System → System Information shows the model; the jailbreak
community tooling (loader v25+) detects southbridge and Pro at **runtime** [S14][S15].
Practical rule from the field: if the Belize kernel leaves a **steady white light** every time, try the
Baikal kernel [S16].

**Consequence for this project:** the README says "PS4 Fat". Two cases:
- **CUH-12xx (Belize)** → best possible case, everything in `03-graphics.md` applies as written.
- **CUH-10xx/11xx (Aeolia)** → supported by the Aeolia/Belize kernels (tested on CUH-1003 with feeRnt's
  6.15.4 [S03]); however the newest 7.x trees mark Aeolia as *not yet re-validated* in some projects
  (linux-psx lists Aeolia/Belize as pending for 7.2 [S18]). Plan for one extra kernel candidate.

## 3. Firmware & jailbreak state (must be re-checked before every release)

| Firmware | Status (2026-11-13) | Evidence |
|---|---|---|
| 5.05 | Old, jailbroken for years | [VERIFIED] |
| 7.00 – 13.52 | Public WebKit chain + GoldHEN 2.4b18.11/.12 | [VERIFIED] [S25] |
| 13.52 | Last "comfortable" version; GoldHEN support Sep 2026 | [VERIFIED] [S25] |
| **14.00** | Public **Afterglow** WebKit host + GoldHEN 2.4b18.13; described as **rough**, needs a PC serving pages | [REPORTED] [S24] |
| 14.02 | Video proof of HEN only; no packaged, community-blessed path | [UNVERIFIED] [S24] |
| > 14.02 | No public path | [REPORTED] |

**Rules derived:**
1. If the console is on ≤13.52 and jailbroken → **do not update**. PS4 firmware cannot be downgraded.
2. If on 14.00 → there is a path, but treat it as experimental and expect re-runs after reboot [S24].
3. GoldHEN is the required host: it provides the **FTP server (port 2121)** and the **payload loader**
   (ports 9020/9090) that the Linux loader needs [S16][S17].

## 4. Memory budget (VRAM carve-out)

The loader reserves VRAM out of the 8 GB GDDR5 pool *before* Linux boots:

| Payload | VRAM | System RAM available (approx.) | Use |
|---|---|---|---|
| `linux-32mb` … `512mb` | 32–512 MB | ~7.3–6.8 GB | headless/server, recovery shell [S14] |
| **`linux-1024mb`** | 1 GB | **~6.5–6.9 GB** [ESTIMATE] | **default desktop** [S16] |
| `linux-2048mb` | 2 GB | ~5.5–5.9 GB | Dolphin/Steam profile [S16] |
| `linux-4096mb` | 4 GB | ~4 GB | heavy 3D only; Plasma + browser will swap [S16] |

`vram.txt` on the USB is expressed in **MB** in loader v25+ (`1024`, not `1`). An invalid value silently
falls back to the compiled default [S14]. **This is a top-5 support-ticket generator.**

Mandatory measurement: EXP-001 (`free -h`, `/proc/meminfo`, `dmesg | grep -i memory`).

## 5. Thermal & power

- Fat PSU class ≈ 220–250 W; measured typical draw is far lower; fan is audible under load [S02][ESTIMATE].
- PS4 firmware controls the fan through the **ICC** interface; Linux needs a kernel with the PS4 ICC/fan
  driver plus a user tool (`ps4fancontrol`, threshold range 45–85 °C, default target ≈78 °C) [S22][S23].
- **Not all kernels expose the fan** (e.g. a 6.18.44 Baikal build reports temperature but "fan interface
  missing" [S18]); others add fan threshold + RPM via hwmon and a front LED thermal mode [S30].
- Setting the threshold far below what the cooler can achieve produces a permanent "jet engine"
  [S23] — i.e. the tool is only safe when driven by measured curves.

**Project rule:** thermal safety is a release gate. A kernel without readable temperature is not
acceptable for a desktop image.

## 6. Peripheral facts that shape the UX

| Peripheral | Behaviour | Source |
|---|---|---|
| DualShock 4 | Works wired out of the box (hid-playstation/hid-sony); Bluetooth pairing must be redone after each boot | [REPORTED] [S16] |
| USB keyboard/mouse | Work; recommended over Bluetooth for setup | [VERIFIED] [S16] |
| USB audio | Kernel configs include `CONFIG_SND_USB_AUDIO`; recommended when HDMI audio misbehaves | [REPORTED] [S03][S30] |
| HDMI audio | Possible in newer kernel trees but historically fragile | [REPORTED] [S30] |
| USB storage | Root filesystem on USB 3.0 is the supported path; Baikal units may still have USB write issues in some installers | [REPORTED] [S17] |
| Optical drive | Not usable as a Linux desktop feature; do not design around it | [ESTIMATE] |

## 7. What still must be measured on the user's console

1. Exact CUH model + southbridge + firmware version (fill `profile.example.yaml`).
2. Wi-Fi/BT chip variant (Marvell vs MediaTek) — decides kernel branch.
3. `free -h` total RAM with the chosen payload.
4. GPU identity as seen by the OS (`lspci -nnk`, `glxinfo -B`, `vulkaninfo --summary`).
5. Fan/temperature visibility (`sensors`, `/dev/icc` presence).
