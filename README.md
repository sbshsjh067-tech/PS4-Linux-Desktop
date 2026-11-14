# PS4-Linux-Desktop

An ambitious project to transform the PlayStation 4 (PS4 Fat) into a fully functional Linux desktop computer
powered by KDE Plasma — a Windows-like desktop with a web browser, Steam, Dolphin Emulator, VLC, LibreOffice,
USB peripherals and more, **while keeping the original PS4 operating system (Orbis) intact**.

---

## How this repository is organised

This repository holds **research, not code**. It is the *search engine* of the project: it finds the
projects, finds the problems, and solves them **scientifically** — root cause, options, decision, and a
measurable verification test.

The actual implementation (kernel configs, images, scripts, packaging) is written in a **separate coding
workstream**, working from the specifications produced here.

```
.
├── README.md            ← you are here
├── AGENTS.md            ← operating rules for the research engine
└── research/            ← the research engine (start at research/README.md)
    ├── 00-executive-summary.md   feasibility verdict + hardware budget + top risks
    ├── 01-hardware-firmware.md   APU facts, console revisions, firmware state, memory budget
    ├── 02-boot-chain.md          jailbreak → loader → kernel → initramfs → desktop
    ├── 03-graphics.md            PS4 GPU, patched Mesa, Vulkan 1.3 ceiling, DXVK/Proton pins
    ├── 04-desktop.md             KDE Plasma configuration within the hardware budget
    ├── 05-applications.md        browser, Steam, Dolphin, VLC, LibreOffice, peripherals
    ├── 06-issues-registry.md     the problem → solution database (31 tracked issues)
    ├── 07-upstream-projects.md   existing projects: what to reuse, and in which version
    ├── 08-roadmap.md             milestones M0–M7 with exit criteria
    ├── 09-experiments.md         14 measurement protocols with pass/fail numbers
    ├── 10-coding-tickets.md      18 implementation-agnostic specs handed to the coding chat
    ├── 11-risks-legal.md         bricking, data loss, firmware policy, licences
    ├── 12-sources.md             every source, tagged [S01]…[S42]
    ├── backlog.yaml              machine-readable backlog (issues + tickets + experiments)
    ├── decisions.md              decision log (D-01 … D-06)
    ├── profile.example.yaml      per-console profile to fill before any test
    ├── glossary.md               vocabulary
    └── results/                  experiment outputs + INDEX.md
```

## Read this before proposing anything

1. **`research/00-executive-summary.md`** — what is feasible on this hardware and what is not.
2. **`research/06-issues-registry.md`** — if your problem is not there, add it with the template first.
3. **`research/AGENTS.md`** — the separation between research (this repo) and implementation (other chat).

## Reality check in three lines

- ✅ A jailbroken PS4 Fat boots Linux from USB with an accelerated desktop (OpenGL 4.6, Vulkan 1.3), KDE Plasma,
  browsers, media, office work and USB peripherals.
- ⚠️ Steam works **only** within pinned versions (DXVK ≤ 2.7.1, Proton ≤ 11): the GPU is GFX7-class and stops at
  Vulkan 1.3, so current DXVK 3.x is unusable. Dolphin is good for GameCube, mixed for Wii.
- ❌ No suspend, no 4K/H.265/AV1 playback, no modern AAA games, no AVX2 software — and **never** repartition
  the internal disk if you want to keep Orbis and your saves.

Full analysis and evidence: `research/00-executive-summary.md`.

---

## Engineering Implementation & Safe Display Architecture (V3)

Alongside the untouched `research/` specification corpus (`AGENTS.md`), this repository now contains the full **PS4 Fat Safe Linux Desktop Engineering Implementation**:

```text
├── src/ps4_linux/               Core Python engine (EDID 1.3/1.4+CEA-861, MN864729 HDMI bridge,
│                                Safe Mode Protector, 11-Stage Safe Boot, 12-Domain Doctor, CPIO tool)
├── bin/                         Executable CLIs (`ps4-display-protector`, `ps4-doctor`, `ps4-safe-boot`,
│                                `ps4-kernel-writer`, `ps4-initramfs-tool`, `ps4-send-payload`, `ps4-profile-collector`)
├── initramfs/                   Safe `/init` (Stages 5..8 + `PS4BOOT` failure log persistence) & freestanding
│                                8.9 KiB Jaguar-pure `ps4_hdmi_guard` (`-march=btver2 -mno-avx2 -static -nostdlib`)
├── patches/mesa/                Mirrored & SHA-256 verified PS4 Mesa patches (`0001`, `0002` no-HiZ, `0003` no-FLAT)
├── configs/                     Kernel (`ps4-desktop-fat.config`), KDE thin profile, network, freeze pins, zram/USB
├── scripts/                     `build-external-release.sh` (full external pipeline), `build-kernel-safe.sh`,
│                                `build-ps4-mesa.sh`, `ps4-mesa-select`, `make-ps4-usb-safe.sh`, `manage-linux-img.sh`
├── orbis-launcher/              OpenOrbis C launcher -> fake-signed `eboot.bin` (USB-only, D-01 compliant)
├── Dockerfile                   `ubuntu:24.04` build env (clang/lld/llvm, debootstrap, e2fsprogs, dotnet)
├── systemd/                     `ps4-hdmi-protector.service`, `ps4-thermal-guard.service`, `90-ps4-desktop.preset`
├── tests/test_ps4_suite.py      13 automated tests (`TEST A` through `TEST M`)
└── PS4-*.md                     6 root engineering reports (Status, Toolchain, Boot, Display, Tests, Next Steps)
```

### Unrestricted External Build (real kernel + `linux.img` + fPKG)

The sandbox that produced the reports above cannot reach `deb.debian.org`, the GitHub release
CDN or `tmpfiles.org`. The complete release build therefore runs outside it:

```bash
# Docker (hermetic, installs every dependency automatically)
docker build -t ps4-linux-desktop/build:external .
docker run --rm -it -v "$PWD/artifacts:/repo/artifacts" ps4-linux-desktop/build:external

# Bare Ubuntu 24.04 / Debian 12
sudo ./scripts/build-external-release.sh            # --no-upload to skip tmpfiles.org

# GitHub Actions
#   .github/workflows/external-build.yml  (Actions -> External Build -> Run workflow)
```

It compiles the pinned PS4 Fat kernel (`bzImage`), the `ps4-kexec` ring-0 loader payload, the
OpenOrbis fake-signed `eboot.bin` + clean-room `libc.prx`/`libSceFios2.prx`/`right.sprx`, a
Debian 12 ext4 `linux.img`, and builds + verifies a real `\x7fCNT` fPKG with `PkgTool.Core`,
then uploads it to `tmpfiles.org`. Full instructions, pinned commits, verification matrix and
the explicit **"not tested on real hardware"** list: [`PS4-EXTERNAL-BUILD.md`](PS4-EXTERNAL-BUILD.md).

### Quick Verification Commands

```bash
make test              # Compiles Jaguar HDMI guard, verifies Mesa patch SHA-256s, lints, and runs TEST A..TEST M
make pack-initramfs    # Packs verified artifacts/boot/initramfs.cpio.gz (zero GPU firmware shadowing)
./bin/ps4-doctor       # Runs full 12-subsystem diagnostic & black-screen stage pinpointer
```

### Master Engineering Reports
- [`PS4-PROJECT-STATUS.md`](PS4-PROJECT-STATUS.md) — Strict honesty matrix across all subsystems, artifacts, and tickets (`T-001`..`T-018`)
- [`PS4-TOOLCHAIN-REPORT.md`](PS4-TOOLCHAIN-REPORT.md) — Audited build host environment & installed/missing tool matrix
- [`PS4-BOOT-ARCHITECTURE.md`](PS4-BOOT-ARCHITECTURE.md) — 14-step PS4 Linux boot lifecycle, hardware matrix & 11-stage safe boot
- [`PS4-DISPLAY-DIAGNOSTICS.md`](PS4-DISPLAY-DIAGNOSTICS.md) — HDMI Display Protection Engine (EDID + MN864729 unmute) & `ps4-doctor`
- [`PS4-TEST-REPORT.md`](PS4-TEST-REPORT.md) — `TEST A`..`TEST M` execution results & 8-item engineering repair records
- [`PS4-NEXT-STEPS.md`](PS4-NEXT-STEPS.md) — Step-by-step workstation build (`bzImage` / Mesa) & physical PS4 Fat validation guide

