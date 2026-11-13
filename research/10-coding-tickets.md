# 10 — Coding tickets (hand-off to the implementation chat)

These are **specifications**, not code. Each ticket is self-contained: goal, inputs, constraints, acceptance
criteria, and the experiment that proves it. The coding chat may choose any implementation; it may not
change the acceptance criteria without a new research decision in `decisions.md`.

Priority: `P0` = blocks the project, `P1` = needed for the product, `P2` = polish.

| ID | Prio | Title | Depends on |
|---|---|---|---|
| T-001 | P0 | Profile collector & first-boot hardware probe | — |
| T-002 | P0 | Kernel selection matrix + boot-file writer | T-001 |
| T-003 | P0 | VRAM policy: `vram.txt` + effective-value verification | T-002 |
| T-004 | P0 | Rootfs on USB: partition layout, labels, mount options | — |
| T-005 | P0 | `ps4-doctor` diagnostic tool | T-001, T-006 |
| T-006 | P0 | Pinned PS4-patched Mesa bundle + selector | T-004 |
| T-007 | P1 | Package-version freeze (Mesa/libdrm/LLVM/DXVK/Proton) | T-006 |
| T-008 | P1 | KDE Plasma thin profile (defaults, services off) | T-006 |
| T-009 | P1 | XFCE recovery session + rescue tooling | T-008 |
| T-010 | P1 | Graphics acceptance self-test (GL/VK/gpu-hang quick check) | T-006 |
| T-011 | P1 | Network defaults (Ethernet-first, NM Wi-Fi quirks) | T-004 |
| T-012 | P1 | Thermal & fan profile with safety limits | T-002 |
| T-013 | P2 | Boot progress indicator (LED/beep) | T-002 |
| T-014 | P2 | Payload delivery helper (phone/PC, one command) | — |
| T-015 | P1 | Application defaults (browser/Steam/Dolphin/Office) | T-008 |
| T-016 | P1 | Locale, RTL & Arabic font set, timesync | T-008 |
| T-017 | P2 | Reproducible image build + mirrors + checksums | T-004 |
| T-018 | P1 | User-facing install & troubleshooting guide | T-005…T-016 |

---

## T-001 — Profile collector & first-boot hardware probe (P0)

**Goal:** fill `profile.example.yaml` automatically on first boot.

**Inputs:** running Linux on PS4.
**Must collect:** `/etc/os-release`, `uname -a`, `lscpu` flags (assert no avx2/fma/bmi2), `lspci -nnk`
(VGA + network), southbridge hint, `free -h`, `/proc/cmdline`, `glxinfo -B`, `vulkaninfo --summary`,
`sensors`, `lsblk -f`, Wi-Fi chip via `lspci`/`dmesg`.
**Outputs:** `~/.config/ps4/profile.yaml` + `~/ps4-report.txt` (shareable, no secrets).
**Constraints:** no network required; must run from XFCE and Plasma; must not require root for read-only parts.
**Acceptance:** on a fresh install, running it produces a valid YAML matching the schema in `profile.example.yaml`;
doctor (T-005) consumes it.
**Verify:** EXP-001.

## T-002 — Kernel selection matrix + boot-file writer (P0)

**Goal:** eliminate BOOT-001 by making the kernel choice explicit and verifiable.

**Spec (amended 2026-11-13, see `13-…` Q1/Q3 + D-08):**
- Candidate table, pinned in `14-pinned-inputs.lock.yaml`: Aeolia/Belize → `feeRnt@7.0-Clean#8ec5c28` (A) and
  `feeRnt@6.15.4-crashniels#3cba9d4` (B); Baikal → `feeRnt@5.4.247-dfaus#1fdfbd9`. **No** candidate from the
  404 repos. The source tree's own `config` file is used as the base (kernel build scripts expect it).
- A **layout validator/writer** for the two supported layouts (`usb_fat32` | `internal_ftp`), chosen from
  `profile.yaml`, with `bootargs.txt` from a template and sha256 verification after writing.
- A pre-flight that **refuses** a set with a `bzImage` in both locations (BOOT-003, rewritten), and prints the
  sha256 of the kernel it will boot.
- Write `kernel_repo`, `kernel_branch`, `kernel_commit`, `kernel_release` into the image manifest.
**Acceptance:** 3/3 boots with the generated set (EXP-002); wrong-kernel case produces the documented
white-light symptom with a clear message.
**Verify:** EXP-002.

## T-003 — VRAM policy (P0)

**Spec:** `vram.txt` in **MB**, validated against an allow-list {32,64,128,256,512,1024,2048,3072,4096};
write it, then after boot compare `/proc/cmdline` + driver-reported VRAM with the requested value; on mismatch,
surface `BOOT-004` with the actual effective value.
**Acceptance:** 3 payloads tested (512/1024/2048) → effective == requested 3/3.
**Verify:** EXP-001 + EXP-003 per payload.

## T-004 — Rootfs on USB (P0)

**Spec:** ext4 (or btrfs optional), label `PS4KD`, mount `noatime,commit=30,errors=remount-ro`;
`/etc/fstab` by `LABEL`; fsck on boot; grow partition on first boot; **never** touch internal devices
(guard: refuse if target is `/dev/sda` internal or has PS4 partitions).
**Acceptance:** boots on both FAT32-boot-partition USB and whole-device layouts; power-loss test recovers.
**Verify:** EXP-013.

## T-005 — `ps4-doctor` (P0)

**Behaviour:** `ps4-doctor` runs ordered checks and prints **registry IDs** with fixes:
renderer != llvmpipe (GFX-001), Vulkan API ≤ 1.3 (GFX-004), kernel matches southbridge (BOOT-001),
root mounted R/W (SYS-004), sleep masked (SYS-001), thermal readable (SYS-002), network up (NET-00x),
DS4 detected (EXP-010), DXVK/Proton versions pinned (APP-001), AVX2 package audit (APP-003).
**Output:** human table + `--json` for tickets. Exit code non-zero if any blocker check fails.
**Acceptance:** on a healthy system exit 0; on a simulated llvmpipe session, prints GFX-001 and exits 1.

## T-006 — Pinned PS4 Mesa bundle (P0)

**Spec (amended 2026-11-13, see `13-…` Q2 + D-07):** build **Mesa 26.2.5 + libdrm 2.4.134** with patches
`0001` (Liverpool/Gladius PCI IDs, GFX7 mapping, raster config `0x2a00161a`, RADV fast-clear predication) and
`0002` (**RADV HiZ off** — the actual fix for GFX-002), into `/opt/ps4-mesa`, builder `debian:trixie` with
LLVM 19. Verify both tarball SHA256s (in the lock file) before building. Select with the proven mechanism
(`/etc/ld.so.conf.d/00-ps4-mesa.conf`, `VK_DRIVER_FILES=<icd>`, Xorg `modesetting`+`glamor`+`DRI 3`) and a
`--undo`. Build **25.3.5** in parallel as the EXP-009 control. Document that the bundle has **no VA-API**.
**Constraints:** do **not** replace distro Mesa; do not ship binaries built against glibc < 2.38 or > distro ABI.
**Acceptance:** `glxinfo -B` shows LIVERPOOL; `vulkaninfo` shows 1.3; EXP-009 passes on the chosen version.
**Verify:** EXP-001, EXP-003, EXP-009.

## T-007 — Version freeze (P1)

Pin/exclude: `mesa`, `libdrm`, `llvm-libs`, `lib32-*` equivalents; provide a DXVK ≤ 2.7.1 artefact and a
Proton ≤ 11.0 launcher path; block VKD3D-Proton by default (GFX-004). Include an audit command in doctor.
**Acceptance:** `pacman -Syu` (or equivalent) cannot silently change the pinned set; doctor reports versions.

## T-008 — Plasma thin profile (P1)

Ship as *defaults*, not suggestions: KWin animations instant, blur/transparency off, Baloo off, Akonadi absent,
Discover autoupdate off, session X11 default + Wayland option, 1080p60 forced, autologin, `systemd-timesyncd`,
sleep masked, power button = poweroff.
**Acceptance:** `04` §7 table all green.

## T-009 — XFCE recovery (P1)

Second session that always works, plus a "safe mode" GRUB-less entry via `systemd.unit=multi-user.target`
alias script; doctor available in TTY.

## T-010 — Graphics self-test (P1)

Fast test (<30 s): `glxinfo`, `vulkaninfo`, 5-second `vkcube`-equivalent offscreen draw, DXVK version read,
Mesa version read; prints a single PASS/FAIL with the responsible registry ID.
**Acceptance:** detects the deliberately broken Mesa (system one) reliably.

## T-011 — Network defaults (P1)

Ethernet first; NM config to disable MAC randomization and prefer WPA2/2.4 GHz; `ethtool` link-negotiation
helper for GbE↔100 Mb; document Orbis-Wi-Fi-association quirk (NET-004) in first-boot screen.

## T-012 — Thermal & fan (P1)

Expose temperature via `sensors`; install fan control (ICC) with **default target 70–75 °C**, hard floor 65 °C,
warning if the kernel exposes no fan node (SYS-002). Optional quiet profile only if EXP-012 proves it.
**Acceptance:** EXP-012 pass.

## T-013 — Boot progress indicator (P2)

LED/beep sequence at initramfs start and at DM start, so the 1–2 min black screen is not ambiguous (BOOT-005).

## T-014 — Payload delivery helper (P2)

One-command send from phone/PC (`nc`/curl wrapper, auto-detect PS4 IP via mDNS/ARP scan), plus optional
local HTTP host page for the jailbreak step. **No** exploit code is shipped; only delivery of the loader ELF
the user already has. Legal note in `11`.

## T-015 — Application defaults (P1)

Firefox profile (`dom.ipc.processCount=2`, telemetry off), Chromium flags, Steam launch options template,
Proton pin, DolphinPS4 recommended settings, LibreOffice tuned profile, VLC/mpv config.
**Acceptance:** EXP-004, EXP-009, EXP-014, EXP-015 green or documented as unsupported.

## T-016 — Locale/RTL (P1)

Arabic + English fonts (`noto-fonts`, `noto-fonts-arabic`), RTL-friendly Plasma defaults, keyboard layouts,
timezone, timesync, locale generation. Must not break on non-Arabic installs.

## T-017 — Reproducible build (P2)

Scripted image build (docker/podman), pinned inputs, SHA256SUMS, mirrors of kernel/loader/Mesa sources,
`results/` excluded from the image, build metadata in `/etc/ps4-build.json`.

## T-018 — User guide (P1)

One-page install, a troubleshooting table generated **from `06-issues-registry.md`** (single source of truth),
and a "what not to expect" section matching `05` §8.

---

## Hand-off protocol

1. Research updates `06` + `10` + `backlog.yaml` first.
2. Coding picks tickets in priority order, opens a branch per ticket, and links the experiment result in the PR.
3. A ticket is **closed** only by a `results/INDEX.md` row.
