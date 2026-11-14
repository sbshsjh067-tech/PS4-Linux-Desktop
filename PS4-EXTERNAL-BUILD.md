# PS4 Linux Desktop — Unrestricted External Build

This document is the executable counterpart of the sandbox reports (`PS4-PROJECT-STATUS.md`,
`PS4-TEST-REPORT.md`). The development sandbox used during early work could reach only
`github.com` / `pypi.org` / `npmjs.org`, so `deb.debian.org`, the GitHub release CDN and
`tmpfiles.org` were unreachable there. **Everything below runs outside that sandbox**
(local Ubuntu/Debian, the provided Docker image, or GitHub Actions `ubuntu-latest`) and
produces the real deliverables:

| Deliverable | Produced by | Where |
|---|---|---|
| `bzImage` (PS4 Fat kernel, Linux 7.0 `7.0-Clean`) | `scripts/build-kernel-safe.sh` | `artifacts/external/kernel/bzImage` |
| `kexec.bin` (ring-0 Linux loader payload) | `fail0verflow/ps4-kexec` | `artifacts/external/kexec.bin` |
| `eboot.bin`, `libc.prx`, `libSceFios2.prx`, `right.sprx` (FSELF) | OpenOrbis toolchain + `orbis-launcher/` | `artifacts/external/orbis/` |
| `linux.img` (Debian 12 ext4 rootfs, `LABEL=PS4KD`) | `debootstrap` + `mke2fs -d` | `artifacts/external/rootfs/linux.img` |
| `IV0000-BREW00001_00-PS4LDESKTOP00000.pkg` (real `\x7fCNT`) | `PkgTool.Core` via `bin/ps4-pkg-packager` | `artifacts/external/pkg/` |
| Full log (steps, byte sizes, SHA-256) | the pipeline itself | `artifacts/external/BUILD-LOG.md` |

---

## 1. Honest scope and limitations (read this first)

* **No Sony proprietary file is used or redistributed.** There is no Sony SDK, no Sony
  `libc.prx` / `right.sprx`, no Sony PRX, no retail signing key. The Orbis import stubs,
  the toolchain, the PRX modules and the package builder are all open source (see §2).
* **The produced `.pkg` is a "fake PKG" (fPKG) with fake-signed FSELF modules.**
  `create-fself --paid 0x3800000000000011` and `PkgTool.Core`'s public 32-zero debug
  passcode are the community fake-key path. Such packages:
  * install **only on a console already running GoldHEN (or a compatible HEN)**;
  * are **rejected by retail / non-jailbroken firmware**;
  * were **not** tested against real Orbis validation, because that would require a console.
  An open-source toolchain does **not** produce a retail-installable package, and this
  project does not claim otherwise.
* **Nothing here was executed on physical PS4 hardware.** See §7 for the honest list.
* **`linux.img` is not uploaded to tmpfiles.org**: a real Debian image is hundreds of MB
  and tmpfiles.org caps uploads at 100 MB. The `.pkg` is small (kernel + initramfs +
  overlay + FSELF modules) and is the uploadable deliverable. `linux.img` is reproducible
  locally with the same one command (§3).

---

## 2. Pinned, audited inputs

| Component | Repository | Pin | License |
|---|---|---|---|
| PS4 kernel (Fat: Aeolia/Belize) | `https://github.com/feeRnt/ps4-linux-12xx` | branch `7.0-Clean` @ `8ec5c282abda91f6c2e4014de206105aa7912516` | GPL-2.0 |
| Ring-0 kexec payload | `https://github.com/fail0verflow/ps4-kexec` | `master` @ `e79feb87311f79084ee63a354e5646135efc4ac5` | BSD-2-Clause |
| Orbis SDK / toolchain / clean-room modules | `https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain` | `v0.5.4` @ `b458dfd9d2f5c40aa249b127c9b9b4488afdc686` | GPL-3.0 |
| fPKG builder (`PkgTool.Core`) | `https://github.com/Maxton/LibOrbisPkg` | `v0.2` @ `72370ca3739e0708250695046b3886e50452dee7` | MIT |
| Toolchain release asset | `toolchain-llvm-18.tar.gz` (158,688,666 bytes) | tag `v0.5.4`, SHA-256 recorded on every run | GPL-3.0 |
| Root filesystem | `debootstrap bookworm` from `http://deb.debian.org/debian` | Debian 12 (bookworm) | DFSG |

Kernel firmware blobs listed in `CONFIG_EXTRA_FIRMWARE` (Marvell/MediaTek Wi-Fi, not Sony
code) are fetched from the public `linux-firmware` mirror; the mirror ref is resolved to an
exact commit SHA at build time and each blob's SHA-256 is written to
`extra_firmware/FIRMWARE.lock`. Nothing is fetched from a moving branch silently.

---

## 3. Quick start

### Option A — Docker (recommended, hermetic)

```bash
cd PS4-Linux-Desktop
docker build -t ps4-linux-desktop/build:external .
docker run --rm -it \
    -v "$PWD/artifacts:/repo/artifacts" \
    ps4-linux-desktop/build:external            # full build + upload
```

Variants:

```bash
# build and verify, do not upload
docker run --rm -it -v "$PWD/artifacts:/repo/artifacts" \
    ps4-linux-desktop/build:external --no-upload

# smaller/faster rootfs (no X11), smaller image
docker run --rm -it -v "$PWD/artifacts:/repo/artifacts" \
    ps4-linux-desktop/build:external --rootfs-profile minimal --rootfs-size 4G
```

### Option B — bare Ubuntu 24.04 / Debian 12+

```bash
sudo apt-get update
sudo apt-get install -y build-essential git curl ca-certificates \
    clang lld llvm bc flex bison libssl-dev libelf-dev libncurses-dev \
    dwarves zstd xz-utils cpio kmod rsync python3 e2fsprogs debootstrap \
    util-linux file binutils openssl
# optional (only for the LibOrbisPkg fallback):
sudo apt-get install -y dotnet-sdk-8.0

sudo ./scripts/build-external-release.sh            # full pipeline + upload
```

`--install-deps` performs the `apt-get` step for you. The script re-executes itself under
`sudo` because `debootstrap` and `mke2fs -d` need root; no loop devices or mounts are used.

### Option C — GitHub Actions

`.github/workflows/external-build.yml` runs the entire pipeline on `ubuntu-latest`
(7 vCPU / 14 GB RAM) and publishes `BUILD-LOG.md`, the boot assets and the `.pkg`.
Trigger it with **Actions → External Build → Run workflow**, or push a change to
`scripts/build-external-release.sh`, `orbis-launcher/**` or the workflow itself.

---

## 4. What the pipeline does, step by step

| # | Step | Concrete command / mechanism | Output |
|---|---|---|---|
| 0 | Preflight | tool + disk audit, host/OS/compiler versions logged | `build.log` header |
| 1 | Toolchain | pinned `toolchain-llvm-18.tar.gz`, archive SHA-256 recorded | `OO_PS4_TOOLCHAIN` |
| 2 | kexec payload | `make -C ps4-kexec CC=gcc CFLAGS="… -fPIC -no-pie …"` | `kexec.bin` |
| 3 | Kernel | pinned clone + config repair + firmware fetch + `make LLVM=1 ARCH=x86_64 bzImage modules` with `KCFLAGS=-march=btver2 -mtune=btver2` | `bzImage`, `kernel.config`, `lib/modules/<ver>` |
| 4 | Launcher | `clang --target=x86_64-pc-freebsd12-elf …` + `ld.lld -pie --script link.x` + `create-fself --eboot` | `eboot.bin` (FSELF) |
| 5 | Orbis modules | `make -C src/modules/{libc,libSceFios2,right}` (clean-room C stubs) | `libc.prx`, `libSceFios2.prx`, `right.sprx` |
| 6 | Rootfs | `debootstrap --variant=minbase --include=… bookworm` → post-config files → `mke2fs -d` | `linux.img` (ext4, `LABEL=PS4KD`) |
| 7 | Package | `bin/ps4-pkg-packager build-or-stage … --pkgtool PkgTool.Core --json` | `*.pkg` + `pkg.gp4` + `staging-manifest.json` |
| 8 | Verify | `inspect-pkg`, `inspect-sfo`, header dump, `PkgTool.Core pkg_extract` round-trip | `pkg-inspection.json`, `pkg-extract.log` |
| 9 | Upload | `bin/ps4-pkg-packager upload` → `tmpfiles.org/api/v1/upload`, URL re-fetched with `curl -I` | `pkg-upload.json`, printed URL |

Notes and deliberate deviations, all logged:

* The `ps4-kexec` upstream `Makefile` defaults to `-fPIE -pie`, which GNU `ld` 2.40 rejects
  for the `--nmagic` freestanding linker script (`PHDR segment not covered by LOAD segment`).
  The payload is position independent, so it is built with `-fPIC -no-pie`. No source edit.
* The upstream kernel `config` hard-codes
  `CONFIG_EXTRA_FIRMWARE_DIR="/home/rmux/…"`; `scripts/build-kernel-safe.sh` rewrites it to
  the in-tree `extra_firmware/`. `build.sh` does the same, so both paths agree.
* Release builds pass `--no-debug-info` (drops `CONFIG_DEBUG_INFO`/BTF). `bzImage` never
  contains debug info; this only removes build time and multi-GB `vmlinux` artefacts. Use
  `--with-debug-info` if you need `vmlinux` for crash analysis.
* `mke2fs -d <dir>` builds the ext4 image **without loop mounts or partitioning**, so the
  host's disks are never touched (Decision D-01).

---

## 5. Verification the pipeline performs

Automated, and any failure aborts the run (it will never publish an unverified `.pkg`):

1. `\x7fCNT` magic at offset `0x0000` (rejects ZIP/ELF/renamed tarballs).
2. `package_size` at `0x430` equals the real file size (this offset was corrected against
   LibOrbisPkg `PkgWriter.WriteHeader`; `0x418` is `pfs_image_size`).
3. `content_id` at `0x40` is the mandatory 36-char `XX9999-ABCDE12345_00-<16 ALNUM>`.
4. `entry_count > 0` and the outer PFS range `[pfs_image_offset, +pfs_image_size)` lies
   inside the file.
5. `sce_sys/param.sfo` is re-parsed from the built staging tree (`\x00PSF`, sorted keys,
   `APP_TYPE=1`, `CATEGORY=gd`, `PUBTOOLVER`).
6. FSELF magic `4f 15 3d 1d` for `eboot.bin`, `libc.prx`, `libSceFios2.prx`, `right.sprx`
   *before* packaging (the honesty gate in `pkg_builder.py` repeats it).
7. Full `PkgTool.Core pkg_extract --passcode 000…0` round-trip: the extracted
   `eboot.bin`, `assets/boot/bzImage` and `assets/boot/kexec.bin` must match the source
   SHA-256 digests byte for byte.
8. The tmpfiles.org URL is re-fetched over HTTPS (HTTP status + `Content-Length`).

What verification **cannot** prove: that Orbis' own installer, GoldHEN's installer, the
PFS crypto, or the PS4 boot ROM will accept the result. That needs a console (§7).

---

## 6. Runtime design (what the package actually does on the console)

`eboot.bin` (`orbis-launcher/main.c`) runs as a normal Orbis app under GoldHEN:

1. logs a banner to the kernel log (`sceKernelDebugOutText`),
2. creates `/mnt/usb0/PS4LINUX/` on the **external USB stick only**,
3. copies `assets/boot/{bzImage,initramfs.cpio.gz,bootargs.txt,vram.txt,kexec.bin}`
   from its own read-only package mount (`/app0/…`) to the stick,
4. streams `kexec.bin` to GoldHEN's BinLoader on `127.0.0.1:9090`,
5. exits; the console kexecs the Linux kernel from USB.

Decision **D-01** is structurally enforced: the launcher contains no write path to any
internal device, never calls a format/unlink on `/dev/sda*`, `/user/`, or Orbis partitions,
and the root filesystem is only ever mounted from external USB.

---

## 7. What was NOT tested on a physical PS4 (explicitly)

* No install of the produced `.pkg` on a console (retail **or** GoldHEN).
* No boot of the produced `bzImage` + `linux.img` on Liverpool/Gladius hardware.
* No HDMI/EDID, MN864729 bridge, thermal, fan-curve or suspend verification on hardware.
* No Wi-Fi/BT firmware behaviour check with the fetched Marvell/MediaTek blobs.
* No confirmation that GoldHEN's BinLoader accepts the payload at this size/timing.
* No confirmation that Orbis' `SceAppInstUtil` accepts this fPKG's PlayGo/chunk metadata.
* No Mesa/KDE parity: `linux.img` ships the Debian `xorg` profile by default
  (`--rootfs-profile kde` and `--with-ps4-mesa` are opt-in and were not part of the
  uploaded build).

Hardware checklist for the first person with a console (Aeolia/Belize PS4 Fat, firmware
≤ 9.00 recommended, GoldHEN installed, external USB ≥ 32 GB):

1. Copy `linux.img` to the USB stick (or write it with `dd`, then grow the filesystem).
2. Install `IV0000-BREW00001_00-PS4LDESKTOP00000.pkg` with GoldHEN's package installer.
3. Launch *PS4 Linux Desktop Launcher*; confirm the USB assets appear under `PS4LINUX/`.
4. Confirm `kexec` in the GoldHEN log, then capture the kernel log over UART if the boot stalls.
5. Report back the exact failing stage — `initramfs/init` persists diagnostics to
   `LABEL=PS4BOOT` for offline analysis with `bin/ps4-doctor`.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `curl: (35) … release-assets.githubusercontent.com` | restricted network | run on a normal host, in Docker, or in Actions |
| `PHDR segment not covered by LOAD segment` | upstream `-fPIE -pie` + `--nmagic` | already handled (`-fPIC -no-pie`) |
| `No rule to make target '…/extra_firmware/mrvl/…'` | firmware blobs missing | drop `--no-firmware`, or check the mirror |
| `debootstrap: command not found` | missing dep | rerun with `--install-deps` |
| `.pkg` not produced, blocking reasons printed | a real component is missing | fix the listed component; the honesty gate refuses fake packages |
| `PkgTool.Core` fails with a .NET runtime error | bundled binary needs a runtime | script falls back to building LibOrbisPkg (net8.0 retarget) |
| `tmpfiles.org` upload fails | network egress blocked | run on a host with egress, or use `--no-upload` and upload manually |

---

## 9. Licence summary

The pipeline only downloads GPL-2.0 (kernel), BSD-2-Clause (`ps4-kexec`), GPL-3.0
(OpenOrbis toolchain/modules) and MIT (LibOrbisPkg) sources, plus Debian packages under
the DFSG. The generated `eboot.bin`, PRX modules and `.pkg` therefore carry the licences of
their sources; the `.pkg` contains no Sony code.
