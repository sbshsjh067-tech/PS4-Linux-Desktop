# 08 — Roadmap (milestones with exit criteria)

Indicative effort assumes **one person on hardware + one coding agent**. Dates are relative, not calendar.

---

## M0 — Reality & profiles  *(week 1)*
**Goal:** know exactly which console we have and what it can do.

| Deliverable | Exit criteria |
|---|---|
| Filled `profile.example.yaml` for the target console | model, southbridge, FW, Wi-Fi chip, PSU/fan state |
| Firmware freeze decision recorded | `11-risks-legal.md` §2 signed off by owner |
| EXP-001 executed (baseline facts) | `lscpu` flags show no AVX2; GPU PCI ID present; RAM/VRAM as expected |

**Blockers:** none. **Risk:** console on 14.00+ (see BOOT-007).

---

## M1 — Repeatable boot  *(weeks 1–2)*
**Goal:** boot to a text console **3/3 times** on demand.

| Deliverable | Exit criteria |
|---|---|
| Kernel matrix trial (Aeolia/Belize vs Baikal candidates) | one candidate boots 3/3, blue light, ≤ 25 s to console |
| USB rootfs (ext4, labelled, `noatime`) | `mount` shows ext4, R/W, `fsck` clean |
| Documented file set (`bzImage`, `initramfs`, `bootargs.txt`, `vram.txt=1024`) | EXP-002 pass, no stale UUID in `/proc/cmdline` |
| Mirror of pinned kernel + loader (checksums) | `mirrors/` contains SHAs equal to upstream |

**Blockers:** USB quality; exploit reliability per boot.
**Exit:** EXP-002 green.

---

## M2 — GPU acceleration  *(week 2)*
**Goal:** stop using software rendering forever.

| Deliverable | Exit criteria |
|---|---|
| Patched Mesa prefix installed (`/opt/ps4-mesa` or equivalent) | `glxinfo -B` → renderer contains **LIVERPOOL**/**GLADIUS** |
| Vulkan working | `vulkaninfo --summary` → API = **1.3**, device = PS4 GPU |
| Pinning mechanism | package manager ignores Mesa/libdrm/LLVM updates |
| Doctor check | fails loudly if llvmpipe is detected |

**Exit:** EXP-003 green, GPU hang test EXP-008 30 min without crash.

---

## M3 — KDE Plasma desktop  *(weeks 3–4)*
**Goal:** a usable "Windows-like" desktop.

| Deliverable | Exit criteria (`04` §7) |
|---|---|
| Plasma session at 1080p60, X11 first | idle RAM ≤ 900 MB; idle CPU ≤ 8 % |
| Tuned profile shipped as default | blur/animations/Baloo/Akonadi off |
| XFCE fallback session present | boots on every supported kernel |
| Autologin + timesync + no-suspend | `systemctl status` clean; clock correct after network |
| Cold boot → desktop | ≤ 120 s |

**Exit:** EXP-003 + EXP-008 green; screenshots recorded.

---

## M4 — Applications  *(weeks 4–6)*
**Goal:** the README's application list is either working or explicitly unsupported.

| App | Exit criteria |
|---|---|
| Firefox/Chromium | 1080p H.264 YouTube ≥ 24 fps, no dropped-audio (EXP-004) |
| Steam | client opens, Big Picture usable at 720p; **one D3D9 + one D3D11 title launch** with Proton ≤11 (EXP-009) |
| Dolphin | 3 reference titles at expected fps per `05` §4 (EXP-015) |
| VLC/mpv | 1080p H.264 file plays; audio via USB device |
| LibreOffice | Writer opens in ≤ 15 s cold (EXP-014) |
| Docs | `05-applications.md` table matches reality |

---

## M5 — System hardening  *(weeks 6–7)*
**Goal:** the console survives a week of desktop use.

| Deliverable | Exit criteria |
|---|---|
| Thermal profile + `ps4fancontrol` at 70–75 °C | 20 min full-load `stress-ng` → SoC < 80 °C, no shutdown, no USB dropouts (EXP-012) |
| USB resilience | `commit=30`, `noatime`, fsck-on-boot; simulated power loss recovers (EXP-013) |
| Audio | USB audio default; HDMI tracked |
| zram + swap policy | OOM never kills Plasma during browser+office workload |
| Network | Ethernet 5/5 cold boots; Wi-Fi documented per chip |

---

## M6 — Distribution & UX  *(weeks 7–9)*
**Goal:** someone else can install it without reading this repo.

| Deliverable | Exit criteria |
|---|---|
| USB image + one-page guide | fresh user reaches desktop in ≤ 5 steps and ≤ 15 min |
| `ps4-doctor` | maps 10 known symptoms to BOOT/GFX/NET/SYS IDs and prints the fix |
| Payload delivery helper | phone/PC script sends the ELF in one command (or auto-host) |
| Recovery | XFCE + rescue shell documented; no path requires internal-disk writes |

---

## M7 — Sustainability  *(continuous)*
- Upstream tracking digest (weekly): Mesa, DXVK, Proton, kernel trees, loader, GoldHEN.
- Version-upgrade gate: every bump runs EXP-002/003/008/009 before shipping.
- Bus-factor mitigation: mirrors, licences, build scripts in-repo (`T-017`).
- Community feedback loop: issues that map to registry IDs become experiments, then tickets.

---

## Timeline risk notes

| Risk | Effect on M-gate |
|---|---|
| Console on 14.00 firmware | +1 week (unstable exploit path), or hardware change |
| Aeolia unit + newest kernel | +2–5 days (extra kernel candidate) |
| MediaTek MT7668 Wi-Fi | Ethernet-only for v1; +1 week if Wi-Fi required |
| No Pro hardware available | Pro claims stay "untested" — do not advertise |
| USB stick of poor quality | re-purchase; test EXP-013 early |
