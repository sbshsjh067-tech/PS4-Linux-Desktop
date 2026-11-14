# PS4-TOOLCHAIN-REPORT — Full Environment & Toolchain Audit

**Date:** 2026-11-14  
**Repository:** `sbshsjh067-tech/PS4-Linux-Desktop`  
**Branch:** `arena/d2ccd0a7-ps4-linux-desktop` (base `0bccc10ac7ba40af9b14acc1c5be173925ac3f45`)  
**Audit Standard:** MASTER ENGINEERING PROMPT V3 — Part 3 & Part 4 (Strict 9-Step Tool Usage Policy)

---

## 1. Host Environment Audit

All values below were measured directly inside the build sandbox via `uname -a`, `/etc/os-release`, `lscpu`, `free -h`, and `df -h`:

| Property | Measured Value | Engineering Impact |
|---|---|---|
| Kernel / Arch | `Linux 6.1.158+ x86_64` | Native `x86_64` — compiles PS4 Jaguar (`btver2`) binaries natively without cross-compiler prefix |
| Distro | `Debian GNU/Linux 12 (bookworm)` | Stable GNU toolchain (`gcc 12.2.0`, `binutils 2.40`, `python 3.11.2`) |
| Host CPU | `Intel Xeon @ 2.20GHz` (2 vCPUs) | Supports `-march=btver2 -mno-avx2 -mno-fma -mno-bmi2` code generation and host execution of Jaguar-targeted binaries |
| System RAM | `3.8 GiB` total (`~3.4 GiB` available) | Sufficient for userspace tools, initramfs CPIO packing, and Python/C test suites; full Mesa/Kernel LTO builds require `-j2` concurrency cap |
| Free Disk Space | `19.7 GiB` free (`19,716 MiB`) on `/` | Exceeds minimum `12 GiB` threshold for out-of-tree kernel compilation, though rootfs `.img` generation >16 GiB should use sparse files (`truncate -s`) |
| Outbound Network | Restricted allowlist (`github.com`, `codeload.github.com`, `api.github.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`) | Direct GitHub source/patch verification works; `apt.debian.org` and `archive.mesa3d.org` are unreachable from sandbox |

---

## 2. Complete Toolchain Matrix (Verified Installed vs Missing)

Every tool requested in Part 3 of the specification was probed via `command -v` and `<tool> --version`. Nothing is assumed or fabricated.

### 2.1 Core Development, VCS & Build Tools

| Tool | Status | Verified Version / Path | Role in PS4 Linux Desktop | Alternative / Mitigation Used |
|---|---|---|---|---|
| `git` | **INSTALLED** | `git version 2.39.5` (`/usr/bin/git`) | Repository management, patch verification, upstream commit inspection | — |
| `gh` | **INSTALLED** | `gh version 2.23.0` (`/usr/bin/gh`) | Authenticated GitHub API inspection of `feeRnt/ps4-linux-12xx` & `blue0x1/ps4-multiboot` | — |
| `bash` | **INSTALLED** | `GNU bash 5.2.15(1)-release` | Execution & `bash -n` syntax linting of all build/USB/rescue scripts | — |
| `python3` | **INSTALLED** | `Python 3.11.2` (`/usr/bin/python3`) | Core `ps4_linux` engine (`edid`, `hdmi_bridge`, `display_protector`, `safe_boot`, `doctor`, `boot_writer`, `binary_inspect`) | — |
| `pip` / `pytest` / `pyyaml` | **INSTALLED** | `pip 23.0.1`, `pytest 9.2.0`, `PyYAML 6.0.3` (`~/.local/bin/pytest`) | Automated `TEST A`..`TEST M` suite & YAML profile parsing | Also runs with zero third-party deps via `python3 -m unittest` |
| `gcc` / `g++` | **INSTALLED** | `gcc (Debian 12.2.0-14+deb12u1) 12.2.0` | Compiles freestanding Jaguar-pure `initramfs/bin/ps4_hdmi_guard` (`-march=btver2 -mno-avx2 -static -nostdlib`) | — |
| `make` | **INSTALLED** | `GNU Make 4.3` (`/usr/bin/make`) | Master build orchestration (`Makefile`: build, verify-patches, pack-initramfs, lint, test) | — |
| `clang` / `lld` | **MISSING** | Not installed | Optional LLVM kernel/Mesa compiler | `scripts/build-kernel-safe.sh` supports GNU `gcc` + `ld.bfd` fallback |
| `cmake` / `meson` / `ninja` | **MISSING** | Not installed | Required when compiling Mesa `26.2.5` (`build-ps4-mesa.sh`) | `scripts/build-ps4-mesa.sh --verify-patches` verifies mirrored patches offline; full Mesa build requires host `meson` + `ninja` |
| `bc` / `flex` / `bison` / `pahole` / `libssl-dev` | **MISSING** | Not installed | Required by Linux kernel Kbuild (`feeRnt/ps4-linux-12xx`) | `scripts/build-kernel-safe.sh --dry-run-audit` detects and reports exact missing packages cleanly before touching source |

### 2.2 Binary, Kernel & Disassembly Inspection Tools

| Tool | Status | Verified Version / Path | Role in PS4 Linux Desktop | Alternative / Mitigation Used |
|---|---|---|---|---|
| `objdump` | **INSTALLED** | `GNU objdump (Binutils) 2.40` | Disassembles compiled binaries in `TEST E` & CI to prove `0` AVX2/FMA/BMI2 opcodes | — |
| `readelf` / `nm` / `strings` / `strip` | **INSTALLED** | `GNU Binutils 2.40` | ELF header inspection, symbol stripping (`8.9 KiB` `ps4_hdmi_guard`), section auditing | — |
| `sha256sum` | **INSTALLED** | `GNU coreutils 9.1` | Verifies Mesa patches `0001..0003`, `bzImage`, `initramfs.cpio.gz`, and `manifest.json` | — |
| `file` | **MISSING** | Not installed | Magic-byte file identification | Implemented pure-Python magic/header inspector `src/ps4_linux/binary_inspect.py` (`bzImage` `HdrS` header, ELF64 `e_machine`, gzip/zstd/xz CPIO) |
| `kmod` (`modinfo`/`lsmod`) | **MISSING** | Not installed | Host kernel module inspection | `ps4-doctor` parses `/proc/modules`, `/sys/module/amdgpu`, and kernel config flags directly |

### 2.3 Archive, Initramfs & Filesystem Tools

| Tool | Status | Verified Version / Path | Role in PS4 Linux Desktop | Alternative / Mitigation Used |
|---|---|---|---|---|
| `gzip` / `xz` / `tar` | **INSTALLED** | `gzip 1.12`, `xz 5.4.1`, `tar 1.34` | Initramfs compression & rootfs tarball extraction | — |
| `mkfs.ext4` / `e2fsck` / `resize2fs` | **INSTALLED** | `e2fsprogs 1.47.0` (`/sbin/mkfs.ext4`, `/sbin/e2fsck`) | Creates, checks, and resizes `linux.img` ext4 rootfs containers (`scripts/manage-linux-img.sh`) | `mke2fs -d <dir>` populates ext4 images without needing root `mount`! |
| `losetup` / `blkid` / `lsblk` / `mount` / `chroot` | **INSTALLED** | `util-linux 2.38.1` (`/sbin/losetup`, `/sbin/blkid`, `/usr/sbin/chroot`) | Loopback inspection & target USB formatting on privileged Linux workstations | In unprivileged containers, `manage-linux-img.sh` falls back to rootless `e2fsck`/`debugfs`/`mke2fs -d` |
| `cpio` | **MISSING** | Not installed | Packing/unpacking `initramfs.cpio.gz` (`SVR4 newc`) | Implemented deterministic pure-Python `SVR4 newc` packer/auditor/extractor in `src/ps4_linux/binary_inspect.py` & `bin/ps4-initramfs-tool` |
| `mkinitramfs` / `dracut` | **MISSING** | Not installed | Host distro initramfs generators (unsuitable for PS4 anyway due to GPU firmware cpio trap) | Custom PS4-specific `initramfs/init` + `ps4_hdmi_guard` packed via `bin/ps4-initramfs-tool` (`make pack-initramfs`) |
| `zstd` | **MISSING** | Not installed | Zstandard archive compression | `gzip -9` used for `initramfs.cpio.gz` (universally supported by `CONFIG_RD_GZIP=y` across all PS4 kernels) |
| `fdisk` / `parted` / `mkfs.vfat` | **MISSING** | Not installed in sandbox | Partitioning physical USB media (`PS4BOOT` FAT32 + `PS4LINUX` ext4) | `scripts/make-ps4-usb-safe.sh` enforces strict pre-flight tool checks + `D-01` removable-USB guard before running on a physical Linux workstation |
| `rsync` | **MISSING** | Not installed | Rootfs tree sync | `cp -a` / `tar` pipeline used in scripts |

### 2.4 Display, Diagnostics & Quality Assurance Tools

| Tool | Status | Verified Version / Path | Role in PS4 Linux Desktop | Alternative / Mitigation Used |
|---|---|---|---|---|
| `jq` | **INSTALLED** | `jq-1.6` (`/usr/bin/jq`) | JSON inspection of `ps4-doctor --json`, `ps4-display-protector --json`, and `manifest.json` | — |
| `edid-decode` / `modetest` / `xrandr` / `drm_info` | **MISSING** (headless container) | Not installed; no physical `/dev/dri/card0` in container | Sink EDID decoding & KMS mode probing | Implemented RFC-compliant pure-Python EDID 1.3/1.4 + CEA-861 parser (`src/ps4_linux/edid.py`) + sysfs DRM connector inspector + runtime `xrandr`/`kscreen-doctor`/`wlr-randr` integration on target PS4 |
| `qemu-system-x86_64` | **MISSING** | Not installed | Full VM boot simulation (note: QEMU lacks Liverpool GPU, Aeolia/Belize ICC char `73`, and Panasonic MN864729 bridge anyway) | Built deterministic sysfs/ICC hardware simulation harnesses in `tests/test_ps4_suite.py` (`TEST A`..`TEST M`) |
| `shellcheck` | **MISSING** | Not installed | Static shell analysis | `bash -n` syntax validation enforced across every shell script and `/init` via `make lint` |

---

## 3. Compliance with the 9-Step Tool Usage Policy

Every tool invocation in this engineering cycle followed the mandatory 9-step discipline:
1. **Verified existence** (`command -v`) before relying on any binary.
2. **Recorded exact versions** (`gcc 12.2.0`, `binutils 2.40`, `python 3.11.2`, `e2fsprogs 1.47.0`, `pytest 9.2.0`).
3. **Defined exact purpose** (see Tables 2.1–2.4 above).
4. **Executed deterministic commands** (`make build-initramfs-guard`, `make verify-patches`, `make pack-initramfs`, `make lint`, `pytest -v tests/`).
5. **Inspected raw outputs** — catching two real defects during verification (`vpbroadcast` pulled in from glibc static `libc.a` IFUNC stubs, and double bridge unmute in `run_display_protection_pass`), rather than assuming success.
6. **Analyzed outputs** (`objdump -d` proved `ps4_hdmi_guard.o` had `0` AVX2 instructions while `libc.a` introduced `vpbroadcast`).
7. **Built clean engineering alternatives** where sandbox binaries were missing (`bin/ps4-initramfs-tool` for `cpio`, `src/ps4_linux/binary_inspect.py` for `file`, `src/ps4_linux/edid.py` for `edid-decode`) without weakening safety or accuracy.
8. **Zero fabricated results** — `build-kernel-safe.sh --dry-run-audit` explicitly reports `BLOCKED` on missing `bc`/`flex`/`bison`/`libssl-dev` in this container rather than pretending a `bzImage` was compiled here.
9. **Logged every tool check and verification artifact** in this report and `PS4-TEST-REPORT.md`.
