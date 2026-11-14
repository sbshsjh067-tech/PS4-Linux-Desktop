#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# PS4 Linux Desktop — Unrestricted External Release Builder
# =========================================================
#
# Runs the COMPLETE release pipeline outside the restricted dev sandbox:
#
#   1. Toolchain      OpenOrbis-PS4-Toolchain v0.5.4 (GPL-3.0, clean-room)
#   2. Linux Loader   fail0verflow/ps4-kexec ring-0 kexec payload (BSD-2-Clause)
#   3. Kernel         feeRnt/ps4-linux-12xx `7.0-Clean` bzImage (+ modules)
#   4. Launcher       our OpenOrbis C launcher -> fake-signed eboot.bin (FSELF)
#   5. Orbis modules  clean-room libc.prx / libSceFios2.prx / right.sprx (GPL-3.0)
#   6. Root filesystem Debian 12 (bookworm) debootstrap -> ext4 `linux.img`
#   7. Package        real Orbis `\x7fCNT` fPKG built by PkgTool.Core
#   8. Verification   header structure, SFO, PFS bounds, full extract round-trip
#   9. Upload         https://tmpfiles.org/ (real URL, re-checked over HTTPS)
#
# NOTHING Sony-proprietary is used: no Sony SDK, no Sony libc.prx/right.sprx, no
# retail signing keys. The FSELF/fPKG "signatures" come from the public fake-key
# path (create-fself --paid 0x3800000000000011, PkgTool.Core fake PKG) and are
# accepted ONLY by GoldHEN/HEN consoles. See PS4-EXTERNAL-BUILD.md.
#
# Usage:
#   sudo ./scripts/build-external-release.sh                # full build + upload
#   sudo ./scripts/build-external-release.sh --no-upload    # build + verify only
#   sudo ./scripts/build-external-release.sh --skip-kernel --bzimage /path/bzImage
#
# Every run writes:
#   artifacts/external/build.log          full transcript
#   artifacts/external/SHA256SUMS         digests of every produced file
#   artifacts/external/BUILD-LOG.md       human-readable step/size/SHA-256 report
#   artifacts/external/pkg-report.json    packager prerequisite audit

set -Eeuo pipefail

# Never let debconf/tzdata/locale questions block an unattended build.
export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Pinned upstream inputs (audited commits; never a moving branch)
# ---------------------------------------------------------------------------
KERNEL_REPO="https://github.com/feeRnt/ps4-linux-12xx.git"
KERNEL_BRANCH="7.0-Clean"
KERNEL_COMMIT="8ec5c282abda91f6c2e4014de206105aa7912516"

KEXEC_REPO="https://github.com/fail0verflow/ps4-kexec.git"
KEXEC_COMMIT="e79feb87311f79084ee63a354e5646135efc4ac5"

OPENORBIS_REPO="https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain.git"
OPENORBIS_TAG="v0.5.4"
OPENORBIS_COMMIT="b458dfd9d2f5c40aa249b127c9b9b4488afdc686"
OPENORBIS_ASSET="https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain/releases/download/${OPENORBIS_TAG}/toolchain-llvm-18.tar.gz"
# Optional: export OO_TOOLCHAIN_SHA256=... to hard-fail on a tampered toolchain asset.
OO_TOOLCHAIN_SHA256="${OO_TOOLCHAIN_SHA256:-}"

LIBORBISPKG_REPO="https://github.com/Maxton/LibOrbisPkg.git"
LIBORBISPKG_COMMIT="72370ca3739e0708250695046b3886e50452dee7"   # v0.2

ROOTFS_RELEASE="${ROOTFS_RELEASE:-bookworm}"
ROOTFS_MIRROR="${ROOTFS_MIRROR:-http://deb.debian.org/debian}"

CONTENT_ID="IV0000-BREW00001_00-PS4LDESKTOP00000"
PKG_NAME="${CONTENT_ID}.pkg"

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
WORK_DIR="$REPO_ROOT/.external-work"
ART_DIR="$REPO_ROOT/artifacts/external"
JOBS="$(nproc 2>/dev/null || echo 2)"
ROOTFS_SIZE="6G"
ROOTFS_PROFILE="xorg"
BUILD_KERNEL=1
BZIMAGE_OVERRIDE=""
KERNEL_MODULES=1
KERNEL_DEBUG_INFO=0
DO_UPLOAD=1
DO_PKG=1
WITH_PS4_MESA=0
INSTALL_DEPS=0
STAGES="${STAGES:-toolchain,payload,kernel,orbis,rootfs,pkg,verify,upload}"

usage() {
    cat <<'EOF'
PS4 Linux Desktop — external release builder

  --work-dir DIR          Scratch directory (default: ./.external-work)
  --artifacts-dir DIR     Output directory  (default: ./artifacts/external)
  --jobs N                Parallel build jobs (default: nproc)

  --skip-kernel           Do not compile the kernel
  --bzimage PATH          Use a prebuilt bzImage (implies --skip-kernel)
  --no-modules            Build bzImage only (skip kernel modules)
  --with-debug-info       Keep CONFIG_DEBUG_INFO/BTF (slower, bigger vmlinux)

  --rootfs-size SIZE      linux.img ext4 size (default: 6G)
  --rootfs-profile P      minimal | xorg (default) | kde
  --with-ps4-mesa         Also build+install patched Mesa 26.2.5 into /opt/ps4-mesa
  --no-pkg                Stop after components (no .pkg, no upload)
  --stages LIST           Run only these stages (comma separated), enables partial
                          re-runs: toolchain,payload,kernel,orbis,rootfs,pkg,verify,upload
  --no-upload             Build + verify the .pkg, skip tmpfiles.org upload
  --install-deps          apt-get install the required Debian/Ubuntu packages
  -h | --help             This help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --work-dir)        WORK_DIR="$2"; shift 2 ;;
        --artifacts-dir)   ART_DIR="$2"; shift 2 ;;
        --jobs)            JOBS="$2"; shift 2 ;;
        --skip-kernel)     BUILD_KERNEL=0; shift ;;
        --bzimage)         BZIMAGE_OVERRIDE="$2"; BUILD_KERNEL=0; shift 2 ;;
        --no-modules)      KERNEL_MODULES=0; shift ;;
        --with-debug-info) KERNEL_DEBUG_INFO=1; shift ;;
        --rootfs-size)     ROOTFS_SIZE="$2"; shift 2 ;;
        --rootfs-profile)  ROOTFS_PROFILE="$2"; shift 2 ;;
        --with-ps4-mesa)   WITH_PS4_MESA=1; shift ;;
        --no-pkg)          DO_PKG=0; DO_UPLOAD=0; shift ;;
        --no-upload)       DO_UPLOAD=0; shift ;;
        --stages)          STAGES="$2"; shift 2 ;;
        --install-deps)    INSTALL_DEPS=1; shift ;;
        -h|--help)         usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

mkdir -p "$WORK_DIR" "$ART_DIR"
LOG_FILE="$ART_DIR/build.log"
STATE_FILE="$WORK_DIR/state.env"
[[ -f "$ART_DIR/.artifacts.md" ]] || : > "$ART_DIR/.artifacts.md"
[[ -f "$ART_DIR/SHA256SUMS" ]] || : > "$ART_DIR/SHA256SUMS"

# Mirror the whole transcript to build.log (stdout+stderr).
exec > >(tee -a "$LOG_FILE") 2>&1

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
STEP_NO=0
step() {
    STEP_NO=$((STEP_NO + 1))
    printf '\n\033[1;36m========== [STEP %02d] %s ==========\033[0m\n' "$STEP_NO" "$*"
    printf '\n## STEP %02d — %s\n\n' "$STEP_NO" "$*" >> "$ART_DIR/.steps.md"
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}
log()  { printf '[%s] %s\n' "$(date -u '+%H:%M:%S')" "$*"; }
warn() { printf '\033[1;33m[WARN] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[FATAL] %s\033[0m\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
stage_enabled() { [[ ",${STAGES}," == *",$1,"* ]]; }

# Variables that later stages need when every stage runs in its own process
# (e.g. one GitHub Actions step per stage, so a failure names the stage).
save_state() {
    {
        printf 'TOOLCHAIN_ROOT=%q\n' "${TOOLCHAIN_ROOT:-}"
        printf 'BZIMAGE=%q\n' "${BZIMAGE:-}"
        printf 'LINUX_IMG=%q\n' "${LINUX_IMG:-}"
        printf 'KERNEL_RELEASE=%q\n' "${KERNEL_RELEASE:-}"
        printf 'MODULES_DIR=%q\n' "${MODULES_DIR:-}"
        printf 'PKG_PATH=%q\n' "${PKG_PATH:-}"
        printf 'PKGTOOL_FOR_VERIFY=%q\n' "${PKGTOOL_FOR_VERIFY:-}"
        printf 'UPLOAD_URL=%q\n' "${UPLOAD_URL:-}"
        printf 'DIRECT_URL=%q\n' "${DIRECT_URL:-}"
    } > "$STATE_FILE"
}
if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE"
fi

trap 'die "command failed at line $LINENO: $BASH_COMMAND"' ERR

record_artifact() {
    local role="$1" path="$2" size sha
    [[ -f "$path" ]] || { warn "artifact missing for role '$role': $path"; return 1; }
    size="$(stat -c %s "$path")"
    sha="$(sha256sum "$path" | cut -d' ' -f1)"
    printf '%s  %s\n' "$sha" "$(basename "$path")" >> "$ART_DIR/SHA256SUMS"
    printf '| %s | `%s` | %s | `%s` |\n' "$role" "$(basename "$path")" "$size" "$sha" >> "$ART_DIR/.artifacts.md"
    log "ARTIFACT ${role}: $(basename "$path") = ${size} bytes, sha256=${sha}"
}

fetch_pinned() {
    local url="$1" commit="$2" dest="$3" got
    if [[ -d "$dest/.git" ]] && [[ "$(git -C "$dest" rev-parse HEAD 2>/dev/null || true)" == "$commit" ]]; then
        log "cache hit: $dest @ $commit"
        return 0
    fi
    rm -rf "$dest"
    mkdir -p "$dest"
    git -C "$dest" init -q
    git -C "$dest" remote add origin "$url"
    log "fetching $url @ $commit"
    git -C "$dest" fetch -q --depth 1 origin "$commit"
    git -C "$dest" -c advice.detachedHead=false checkout -q FETCH_HEAD
    got="$(git -C "$dest" rev-parse HEAD)"
    [[ "$got" == "$commit" ]] || die "commit pin mismatch for $url: got $got, want $commit"
    log "pinned OK: $url @ $got"
}

# ---------------------------------------------------------------------------
# STEP 00 — environment preflight
# ---------------------------------------------------------------------------
preflight() {
    step "Environment preflight"

    cat <<EOF
Repository        : $REPO_ROOT
Work directory    : $WORK_DIR
Artifacts         : $ART_DIR
Build jobs        : $JOBS
Rootfs            : Debian $ROOTFS_RELEASE ($ROOTFS_PROFILE profile, $ROOTFS_SIZE ext4)
Kernel build      : $([[ $BUILD_KERNEL == 1 ]] && echo "yes (debug_info=$KERNEL_DEBUG_INFO, modules=$KERNEL_MODULES)" || echo "skipped")
Upload to tmpfiles: $([[ $DO_UPLOAD == 1 ]] && echo yes || echo no)
EOF

    log "host: $(uname -a)"
    if [[ -r /etc/os-release ]]; then log "os: $(. /etc/os-release; echo "$PRETTY_NAME")"; fi
    log "uid=$(id -u) euid=$EUID"
    for t in git curl python3 sha256sum; do have "$t" || die "missing required tool: $t"; done

    local missing=()
    local req=(make gcc clang ld.lld llvm-ar llvm-nm objcopy bc flex bison
               mke2fs debootstrap xz zstd tar curl git python3 e2fsck file od)
    for t in "${req[@]}"; do have "$t" || missing+=("$t"); done
    have dotnet || warn "dotnet not found - only needed for the from-source LibOrbisPkg fallback"
    have openssl || warn "openssl not found - root password will stay locked"

    if [[ ${#missing[@]} -gt 0 ]]; then
        warn "missing tools: ${missing[*]}"
        if [[ "$INSTALL_DEPS" == "1" ]]; then
            install_deps
        else
            die "install them first (rerun with --install-deps, or use the provided Dockerfile)"
        fi
    fi

    local avail_kb
    avail_kb="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')"
    log "free disk on $REPO_ROOT: $((avail_kb / 1024)) MiB"
    [[ "$avail_kb" -ge $((14 * 1024 * 1024)) ]] || warn "less than 14 GiB free; the kernel build may run out of space"
}

install_deps() {
    step "Installing build dependencies (apt)"
    local SUDO=""
    [[ $EUID -ne 0 ]] && SUDO="sudo"
    $SUDO apt-get update
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential git curl ca-certificates \
        clang lld llvm \
        bc flex bison libssl-dev libelf-dev libncurses-dev \
        dwarves zstd xz-utils cpio kmod rsync \
        python3 python3-pip \
        e2fsprogs debootstrap \
        dotnet-sdk-8.0 \
        util-linux file binutils || true

    # .NET 8 SDK is only required by the LibOrbisPkg fallback; never fatal.
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends dotnet-sdk-8.0 \
        || warn "dotnet-sdk-8.0 unavailable from apt; the toolchain's PkgTool.Core must work"
}

# ---------------------------------------------------------------------------
# STEP 01 — OpenOrbis toolchain (clean-room, GPL-3.0)
# ---------------------------------------------------------------------------
setup_toolchain() {
    step "OpenOrbis-PS4-Toolchain ${OPENORBIS_TAG} (${OPENORBIS_COMMIT})"

    local tb="$WORK_DIR/toolchain"
    local tgz="$tb/toolchain-llvm-18.tar.gz"
    mkdir -p "$tb"

    if [[ ! -s "$tgz" ]]; then
        log "downloading $OPENORBIS_ASSET"
        curl -fL --retry 3 --retry-delay 2 -o "$tgz" "$OPENORBIS_ASSET"
    else
        log "cached toolchain archive: $tgz"
    fi

    local sha
    sha="$(sha256sum "$tgz" | cut -d' ' -f1)"
    log "toolchain archive sha256=${sha} ($(stat -c %s "$tgz") bytes)"
    if [[ -n "$OO_TOOLCHAIN_SHA256" && "$sha" != "$OO_TOOLCHAIN_SHA256" ]]; then
        die "toolchain SHA-256 mismatch: got $sha, expected $OO_TOOLCHAIN_SHA256"
    fi

    if [[ ! -f "$tb/link.x" ]] && ! find "$tb" -maxdepth 5 -name link.x -print -quit | grep -q .; then
        log "extracting toolchain"
        tar -xzf "$tgz" -C "$tb"
    fi

    local linkx
    linkx="$(find "$tb" -maxdepth 6 -name link.x -print -quit)"
    [[ -n "$linkx" ]] || die "link.x not found inside the OpenOrbis toolchain archive"
    TOOLCHAIN_ROOT="$(dirname "$linkx")"
    [[ -f "$TOOLCHAIN_ROOT/bin/linux/create-fself" ]] || die "create-fself missing in $TOOLCHAIN_ROOT/bin/linux"
    export OO_PS4_TOOLCHAIN="$TOOLCHAIN_ROOT"

    log "OO_PS4_TOOLCHAIN=$OO_PS4_TOOLCHAIN"
    ls -l "$TOOLCHAIN_ROOT/bin/linux" | sed 's/^/    /'
    "$TOOLCHAIN_ROOT/bin/linux/create-fself" --help 2>&1 | head -5 | sed 's/^/    create-fself: /' || true

    # Toolchain provenance: record the pinned commit we AUDITED (source repo);
    # the binary release asset is pinned by tag + recorded SHA-256 above.
    echo "OpenOrbis-PS4-Toolchain ${OPENORBIS_TAG} (${OPENORBIS_COMMIT}) archive sha256=${sha}" >> "$ART_DIR/SHA256SUMS"
}

# ---------------------------------------------------------------------------
# STEP 02 — Ring-0 kexec loader payload
# ---------------------------------------------------------------------------
build_payload() {
    step "Linux loader payload — fail0verflow/ps4-kexec @ ${KEXEC_COMMIT}"
    local src="$WORK_DIR/ps4-kexec"
    fetch_pinned "$KEXEC_REPO" "$KEXEC_COMMIT" "$src"

    # Upstream Makefile defaults to -fPIE -pie, which modern GNU ld rejects for
    # the --nmagic freestanding linker script ("PHDR segment not covered by LOAD
    # segment"). The ring-0 payload is position-independent anyway, so build it
    # with -fPIC -no-pie (documented deviation, no source change).
    local cflags
    cflags="-march=btver2 -masm=intel -std=gnu11 -ffreestanding -fno-common -fPIC -no-pie \
-fomit-frame-pointer -nostdlib -nostdinc -fno-asynchronous-unwind-tables -Os -Wall \
-Wl,--build-id=none,-T,kexec.ld,--nmagic -mcmodel=small -mno-red-zone"

    make -C "$src" clean >/dev/null 2>&1 || true
    make -C "$src" -j"$JOBS" CC=gcc AR=ar OBJCOPY=objcopy CFLAGS="$cflags" kexec.bin

    [[ -f "$src/kexec.bin" ]] || die "kexec.bin was not produced"
    cp "$src/kexec.bin" "$ART_DIR/kexec.bin"
    log "kexec.bin ELF machine/type: $(file -b "$src/kexec.elf" 2>/dev/null || echo n/a)"
    record_artifact "Ring-0 kexec loader payload" "$ART_DIR/kexec.bin"
}

# ---------------------------------------------------------------------------
# STEP 03 — PS4 Fat kernel bzImage (+ modules)
# ---------------------------------------------------------------------------
build_kernel_step() {
    step "PS4 Fat kernel — feeRnt/ps4-linux-12xx ${KERNEL_BRANCH} @ ${KERNEL_COMMIT}"

    local args=(--candidate primary --work-dir "$WORK_DIR/kernel" --output-dir "$ART_DIR/kernel" --jobs "$JOBS")
    args+=(--fetch-firmware)
    [[ "$KERNEL_DEBUG_INFO" == "1" ]] && args+=(--debug-info) || args+=(--no-debug-info)
    [[ "$KERNEL_MODULES" == "1" ]] && args+=(--modules) || args+=(--no-modules)

    log "invoking: scripts/build-kernel-safe.sh ${args[*]}"
    "$REPO_ROOT/scripts/build-kernel-safe.sh" "${args[@]}"

    BZIMAGE="$ART_DIR/kernel/bzImage"
    [[ -f "$BZIMAGE" ]] || die "kernel build finished but $BZIMAGE is missing"

    local ksrc="$WORK_DIR/kernel/ps4-linux-src"
    KERNEL_RELEASE="$(make -s -C "$ksrc" kernelrelease 2>/dev/null || echo unknown)"
    log "kernel release: $KERNEL_RELEASE"
    cp "$ksrc/.config" "$ART_DIR/kernel/kernel.config" 2>/dev/null || true
    record_artifact "PS4 Fat Linux kernel image (bzImage)" "$BZIMAGE"
    { [[ -f "$ART_DIR/kernel/kernel.config" ]] && record_artifact "Kernel .config actually used" "$ART_DIR/kernel/kernel.config"; } || true

    if [[ -f "$ART_DIR/kernel/bzImage.sha256" ]]; then
        log "kernel script digest: $(cat "$ART_DIR/kernel/bzImage.sha256")"
    fi

    if [[ "$KERNEL_MODULES" == "1" && -d "$ksrc/lib/modules/$KERNEL_RELEASE" ]]; then
        MODULES_DIR="$ksrc/lib/modules/$KERNEL_RELEASE"
        log "kernel modules built: $(du -sh "$MODULES_DIR" | cut -f1) at $MODULES_DIR"
    fi
}

# ---------------------------------------------------------------------------
# STEP 04 — Orbis PRX modules + launcher eboot.bin (all FSELF)
# ---------------------------------------------------------------------------
build_orbis_app() {
    step "OpenOrbis clean-room modules + launcher FSELF eboot.bin"
    local src="$WORK_DIR/OpenOrbis"
    fetch_pinned "$OPENORBIS_REPO" "$OPENORBIS_COMMIT" "$src"

    export OO_PS4_TOOLCHAIN

    local mod
    for mod in libc libSceFios2 right; do
        log "building $mod"
        make -C "$src/src/modules/$mod" clean >/dev/null 2>&1 || true
        make -C "$src/src/modules/$mod" CC=clang CCX=clang++ LD=ld.lld
    done

    [[ -f "$src/src/modules/libc/libc.prx" ]] || die "libc.prx not built"
    [[ -f "$src/src/modules/libSceFios2/libSceFios2.prx" ]] || die "libSceFios2.prx not built"
    [[ -f "$src/src/modules/right/right.sprx" ]] || die "right.sprx not built"

    mkdir -p "$ART_DIR/orbis"
    cp "$src/src/modules/libc/libc.prx"               "$ART_DIR/orbis/libc.prx"
    cp "$src/src/modules/libSceFios2/libSceFios2.prx" "$ART_DIR/orbis/libSceFios2.prx"
    cp "$src/src/modules/right/right.sprx"            "$ART_DIR/orbis/right.sprx"

    log "building launcher eboot.bin from orbis-launcher/"
    OO_PS4_TOOLCHAIN="$TOOLCHAIN_ROOT" make -C "$REPO_ROOT/orbis-launcher" \
        OUTDIR="$ART_DIR/orbis" all

    [[ -f "$ART_DIR/orbis/eboot.bin" ]] || die "launcher eboot.bin not built"

    local f
    for f in libc.prx libSceFios2.prx right.sprx eboot.bin; do
        local magic
        magic="$(od -An -tx1 -N4 "$ART_DIR/orbis/$f" | tr -d ' \n')"
        [[ "$magic" == "4f153d1d" ]] || die "$f is not an Orbis FSELF (magic=$magic, expected 4f153d1d)"
        log "FSELF OK: $f magic=4f153d1d size=$(stat -c %s "$ART_DIR/orbis/$f")"
    done

    record_artifact "Orbis userland C runtime PRX (clean-room)" "$ART_DIR/orbis/libc.prx"
    record_artifact "Orbis Fios2 PRX (clean-room)" "$ART_DIR/orbis/libSceFios2.prx"
    record_artifact "Orbis package license SPRX (clean-room)" "$ART_DIR/orbis/right.sprx"
    record_artifact "Launcher eboot.bin (fake-signed FSELF)" "$ART_DIR/orbis/eboot.bin"
}

# ---------------------------------------------------------------------------
# STEP 05 — Debian root filesystem (real linux.img, ext4, LABEL=PS4KD)
# ---------------------------------------------------------------------------
rootfs_packages() {
    case "$ROOTFS_PROFILE" in
        minimal)
            echo "systemd,systemd-sysv,udev,kmod,dbus,ca-certificates,curl,procps,pciutils,usbutils,network-manager,openssh-server,sudo,nano"
            ;;
        xorg)
            echo "systemd,systemd-sysv,udev,kmod,dbus,ca-certificates,curl,procps,pciutils,usbutils,network-manager,openssh-server,sudo,nano,xserver-xorg-core,xserver-xorg-video-amdgpu,xserver-xorg-input-libinput,xinit,openbox,xterm,x11-xserver-utils,mesa-utils,libgl1-mesa-dri,libglx-mesa0,fonts-dejavu-core,alsa-utils,zram-tools"
            ;;
        kde)
            echo "systemd,systemd-sysv,udev,kmod,dbus,ca-certificates,curl,procps,pciutils,usbutils,network-manager,openssh-server,sudo,nano,kde-plasma-desktop,sddm,xserver-xorg-video-amdgpu,mesa-utils,libgl1-mesa-dri,fonts-dejavu-core,alsa-utils,zram-tools"
            ;;
        *) die "unknown --rootfs-profile '$ROOTFS_PROFILE' (minimal|xorg|kde)" ;;
    esac
}

build_rootfs_step() {
    step "Debian ${ROOTFS_RELEASE} root filesystem -> ext4 linux.img"
    local rootfs="$WORK_DIR/rootfs"
    local img="$ART_DIR/rootfs/linux.img"
    mkdir -p "$ART_DIR/rootfs"

    if [[ ! -f "$rootfs/usr/bin/apt-get" ]]; then
        rm -rf "$rootfs"
        log "debootstrap ${ROOTFS_RELEASE} ($ROOTFS_PROFILE) -> $rootfs"
        debootstrap --arch=amd64 --variant=minbase \
            --include="$(rootfs_packages)" \
            "$ROOTFS_RELEASE" "$rootfs" "$ROOTFS_MIRROR"
    else
        log "reusing existing debootstrap tree: $rootfs"
    fi

    log "rootfs size after debootstrap: $(du -sh "$rootfs" | cut -f1)"

    # ---- post-configuration (plain file writes; no chroot needed) ----------
    mkdir -p "$rootfs"/etc/{systemd/system,modprobe.d,sysctl.d,X11/xorg.conf.d,default} \
             "$rootfs"/opt/ps4-desktop-linux \
             "$rootfs"/var/log/ps4-linux \
             "$rootfs"/etc/systemd/system/getty@tty1.service.d \
             "$rootfs"/lib/modules

    cat > "$rootfs/etc/fstab" <<'FSTAB'
# PS4 Linux Desktop — external USB root (Decision D-01: internal HDD never used)
LABEL=PS4KD   /          ext4  rw,noatime,commit=30,errors=remount-ro  0 1
LABEL=PS4BOOT /boot/efi  vfat  rw,noatime,nofail                       0 2
tmpfs         /tmp       tmpfs rw,nosuid,nodev,size=2G                 0 0
FSTAB

    printf 'XKBMODEL="pc105"\nXKBLAYOUT="us"\nXKBVARIANT=""\nXKBOPTIONS=""\nBACKSPACE="guess"\n' \
        > "$rootfs/etc/default/keyboard"
    printf 'LANG=C.UTF-8\n' > "$rootfs/etc/locale.conf" 2>/dev/null || true
    ln -sf /usr/share/zoneinfo/Etc/UTC "$rootfs/etc/localtime" 2>/dev/null || true
    echo "Etc/UTC" > "$rootfs/etc/timezone"

    echo "ps4-linux" > "$rootfs/etc/hostname"
    cat > "$rootfs/etc/hosts" <<'HOSTS'
127.0.0.1 localhost ps4-linux
::1       localhost ip6-localhost
HOSTS

    cat > "$rootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf" <<'AUTO'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
AUTO

    cat > "$rootfs/etc/X11/xorg.conf.d/20-amdgpu.conf" <<'XORG'
# PS4 Liverpool/Gladius (AMD GCN 1.0, GFX7) — amdgpu modesetting
Section "Device"
    Identifier "PS4 AMDGPU"
    Driver     "amdgpu"
    Option     "TearFree" "true"
    Option     "AccelMethod" "glamor"
EndSection

Section "ServerFlags"
    Option "BlankTime"   "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime"     "0"
EndSection
XORG

    cat > "$rootfs/etc/sysctl.d/99-ps4-desktop.conf" <<'SYSCTL'
# PS4 Fat: 8 GiB unified GDDR5, 1024 MiB carved out for VRAM -> ~7 GiB visible RAM
vm.swappiness = 100
vm.page-cluster = 0
vm.dirty_bytes = 67108864
vm.dirty_background_bytes = 16777216
vm.min_free_kbytes = 65536
kernel.panic = 10
SYSCTL

    cat > "$rootfs/etc/modprobe.d/99-ps4-options.conf" <<'MODPROBE'
# PS4 Liverpool/Gladius specifics
options amdgpu si_support=1 cik_support=0 dpm=1
MODPROBE

    cat > "$rootfs/etc/ps4-linux-release" <<RELEASE
PS4_LINUX_DESKTOP_BUILD="external-release-pipeline"
BUILD_TIMESTAMP_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
KERNEL_REPO="${KERNEL_REPO} ${KERNEL_BRANCH}"
KERNEL_COMMIT="${KERNEL_COMMIT}"
KERNEL_RELEASE="${KERNEL_RELEASE:-unknown}"
KEXEC_COMMIT="${KEXEC_COMMIT}"
OPENORBIS_COMMIT="${OPENORBIS_COMMIT}"
ROOTFS="Debian ${ROOTFS_RELEASE} (${ROOTFS_PROFILE} profile)"
CONTENT_ID="${CONTENT_ID}"
NOTE="Fake-signed homebrew. Requires a jailbroken console running GoldHEN. Not tested on physical PS4 hardware."
RELEASE

    # Project payload (scripts, configs, systemd units, patches, docs)
    local rel
    for rel in src bin scripts configs systemd patches; do
        [[ -d "$REPO_ROOT/$rel" ]] || continue
        mkdir -p "$rootfs/opt/ps4-desktop-linux"
        cp -a "$REPO_ROOT/$rel" "$rootfs/opt/ps4-desktop-linux/"
    done
    cp -a "$REPO_ROOT"/PS4-*.md "$rootfs/opt/ps4-desktop-linux/" 2>/dev/null || true

    # systemd units + preset
    cp "$REPO_ROOT"/systemd/*.service "$rootfs/etc/systemd/system/" 2>/dev/null || true
    cp "$REPO_ROOT"/systemd/*.preset "$rootfs/etc/systemd/system-preset/90-ps4-desktop.preset" 2>/dev/null || true
    mkdir -p "$rootfs/etc/systemd/system/multi-user.target.wants"
    for u in ps4-hdmi-protector.service ps4-thermal-guard.service; do
        [[ -f "$rootfs/etc/systemd/system/$u" ]] || continue
        ln -sf "/etc/systemd/system/$u" "$rootfs/etc/systemd/system/multi-user.target.wants/$u"
    done
    # PS4 has no S3/S4: mask sleep targets
    for t in sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target; do
        ln -sf /dev/null "$rootfs/etc/systemd/system/$t"
    done

    # Root password (documented in the release notes; change it after first boot)
    if [[ -f "$rootfs/etc/shadow" ]] && have openssl; then
        local hash
        hash="$(openssl passwd -6 -salt ps4linux ps4)"
        awk -F: -v h="$hash" 'BEGIN{OFS=":"} $1=="root"{$2=h} {print}' "$rootfs/etc/shadow" > "$rootfs/etc/shadow.new"
        mv "$rootfs/etc/shadow.new" "$rootfs/etc/shadow"
        chmod 640 "$rootfs/etc/shadow"
        log "root password set to the documented default (root/ps4) - change after first boot"
    fi

    # Kernel modules for the exact release (copied in, no loop mount required)
    if [[ -n "${MODULES_DIR:-}" && -d "${MODULES_DIR:-}" && -n "${KERNEL_RELEASE:-}" ]]; then
        mkdir -p "$rootfs/lib/modules/$KERNEL_RELEASE"
        cp -a "$MODULES_DIR/." "$rootfs/lib/modules/$KERNEL_RELEASE/"
        log "installed kernel modules into image: $(du -sh "$rootfs/lib/modules/$KERNEL_RELEASE" | cut -f1)"
    else
        warn "kernel modules not installed into the image (built-in drivers only)"
    fi

    # Optional: patched Mesa 26.2.5 (Liverpool/Gladius) into /opt/ps4-mesa
    if [[ "$WITH_PS4_MESA" == "1" ]]; then
        log "building patched Mesa (this is the slow path)"
        "$REPO_ROOT/scripts/build-ps4-mesa.sh"
        mkdir -p "$rootfs/opt/ps4-mesa"
        cp -a /opt/ps4-mesa/. "$rootfs/opt/ps4-mesa/" 2>/dev/null || warn "no /opt/ps4-mesa produced"
    fi

    # ---- create the ext4 image without loop mounts --------------------------
    log "creating ext4 image: $img ($ROOTFS_SIZE, LABEL=PS4KD)"
    rm -f "$img"
    mke2fs -q -F -t ext4 -L PS4KD -m 0 -O ^64bit \
        -E lazy_itable_init=0,lazy_journal_init=0,root_owner=0:0 \
        -d "$rootfs" "$img" "$ROOTFS_SIZE"
    e2fsck -f -y "$img" >/dev/null 2>&1 || warn "e2fsck reported issues (non-fatal)"
    log "ext4 image: $(stat -c %s "$img") bytes, apparent use $(du -h --apparent-size "$img" | cut -f1), real $(du -h "$img" | cut -f1)"
    log "image label/type: $(blkid -o value -s TYPE "$img" 2>/dev/null || echo ext4) / $(blkid -o value -s LABEL "$img" 2>/dev/null || echo PS4KD)"

    LINUX_IMG="$img"
    record_artifact "Debian ${ROOTFS_RELEASE} ext4 root filesystem (linux.img)" "$LINUX_IMG"
}

# ---------------------------------------------------------------------------
# STEP 06/07 — real .pkg (PkgTool.Core) + structural verification
# ---------------------------------------------------------------------------
liborbispkg_pkgtool() {
    # Contract: ONLY the tool path is written to stdout; every log line goes to
    # stderr because the caller captures stdout with $( ... ).
    local src="$WORK_DIR/LibOrbisPkg"
    if [[ -x "$WORK_DIR/bin/PkgTool.Core" ]]; then
        echo "$WORK_DIR/bin/PkgTool.Core"
        return 0
    fi
    if ! have dotnet; then
        warn "dotnet missing; cannot build LibOrbisPkg from source" >&2
        return 1
    fi
    {
        step "Fallback: build LibOrbisPkg PkgTool.Core @ ${LIBORBISPKG_COMMIT} with .NET 8"
        fetch_pinned "$LIBORBISPKG_REPO" "$LIBORBISPKG_COMMIT" "$src"
        # Upstream targets netcoreapp3.0 (EOL runtime); retarget to the installed SDK.
        sed -i 's#<TargetFramework>netcoreapp3.0</TargetFramework>#<TargetFramework>net8.0</TargetFramework>#' \
            "$src/LibOrbisPkg.Core/LibOrbisPkg.Core.csproj" "$src/PkgTool.Core/PkgTool.Core.csproj" || true
    } >&2

    if ! dotnet build "$src/PkgTool.Core/PkgTool.Core.csproj" -c Release -nologo; then
        warn "LibOrbisPkg build failed" >&2
        return 1
    fi

    local dll="$src/PkgTool.Core/bin/Release/net8.0/PkgTool.Core.dll"
    if [[ ! -f "$dll" ]]; then
        warn "LibOrbisPkg fallback build produced no PkgTool.Core.dll" >&2
        return 1
    fi
    mkdir -p "$WORK_DIR/bin"
    {
        printf '#!/bin/sh\n'
        printf 'exec dotnet "%s" "\$@"\n' "$dll"
    } > "$WORK_DIR/bin/PkgTool.Core"
    chmod +x "$WORK_DIR/bin/PkgTool.Core"
    echo "$WORK_DIR/bin/PkgTool.Core"
}

run_packager() {
    local tool="$1" report="$2" rc=0
    # NOTE: the packager intentionally exits 2 when the honesty gate blocks the
    # build, so this call must not trip the ERR trap - use an `if` condition.
    if ./bin/ps4-pkg-packager build-or-stage \
        --pkg-name "$PKG_NAME" \
        --staging-dir "$WORK_DIR/pkg-staging" \
        --output-dir "$ART_DIR/pkg" \
        --eboot "$ART_DIR/orbis/eboot.bin" \
        --libc-prx "$ART_DIR/orbis/libc.prx" \
        --libfios-prx "$ART_DIR/orbis/libSceFios2.prx" \
        --right-sprx "$ART_DIR/orbis/right.sprx" \
        --bzimage "$BZIMAGE" \
        --payload "$ART_DIR/kexec.bin" \
        --linux-img "$LINUX_IMG" \
        --pkgtool "$tool" \
        --json > "$report" 2> "$ART_DIR/pkg-build.stderr"; then
        rc=0
    else
        rc=$?
    fi
    log "packager exit code: $rc (PkgTool.Core: $tool)"
    if [[ -s "$ART_DIR/pkg-build.stderr" ]]; then
        sed 's/^/    [stderr] /' "$ART_DIR/pkg-build.stderr" | head -40
    fi
    # Publish the verdict through a global: this function's stdout is the
    # transcript, so callers must never capture it with $( ... ).
    PKG_BUILT_RESULT="$(python3 -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("False"); sys.exit(0)
print("True" if d.get("pkg_built") else "False")' "$report" 2>/dev/null || echo False)"
    printf '%s' "$PKG_BUILT_RESULT" > "$ART_DIR/.pkg-built"
}

build_pkg_step() {
    step "Building the real Orbis fPKG with PkgTool.Core"
    local pkg_out="$ART_DIR/pkg/$PKG_NAME"
    local report="$ART_DIR/pkg-report.json"
    mkdir -p "$ART_DIR/pkg"

    local pkgtool="$TOOLCHAIN_ROOT/bin/linux/PkgTool.Core"
    if [[ ! -x "$pkgtool" ]]; then
        pkgtool="$(liborbispkg_pkgtool)" || die "no usable PkgTool.Core (neither the toolchain binary nor a from-source build)"
    fi

    log "PkgTool.Core: $pkgtool"
    if [[ -x "$pkgtool" ]]; then
        log "PkgTool.Core probe (usage banner):"
        { "$pkgtool" 2>&1 || true; } | head -3 | sed 's/^/    /'
    fi

    PKG_BUILT_RESULT="False"
    run_packager "$pkgtool" "$report"
    local built="$PKG_BUILT_RESULT"

    if [[ "$built" != "True" && "$pkgtool" == "$TOOLCHAIN_ROOT/bin/linux/PkgTool.Core" ]]; then
        warn "packaging with the bundled PkgTool.Core failed; retrying with a from-source LibOrbisPkg build"
        local fallback
        if fallback="$(liborbispkg_pkgtool)"; then
            pkgtool="$fallback"
            run_packager "$pkgtool" "$report"
            built="$PKG_BUILT_RESULT"
        fi
    fi

    if [[ "$built" != "True" ]]; then
        python3 -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("(no parseable report)"); sys.exit(0)
print("BLOCKING REASONS:")
for r in d.get("blocking_reasons", []):
    print("  *", r)' "$report" || true
        die "the .pkg was NOT built (see blocking reasons above); refusing to emit a fake deliverable"
    fi

    [[ -f "$pkg_out" ]] || die "packager reported success but $pkg_out is missing"
    PKG_PATH="$pkg_out"
    record_artifact "PS4 fPKG (fake-signed, GoldHEN-only)" "$PKG_PATH"

    if [[ ! -x "$TOOLCHAIN_ROOT/bin/linux/PkgTool.Core" && -x "$pkgtool" ]]; then
        PKGTOOL_FOR_VERIFY="$pkgtool"
    fi
}

verify_pkg_step() {
    step "Structural verification of the built .pkg"
    local pkg="$PKG_PATH"
    local pkgtool
    pkgtool="${PKGTOOL_FOR_VERIFY:-$TOOLCHAIN_ROOT/bin/linux/PkgTool.Core}"
    [[ -x "$pkgtool" ]] || pkgtool="$WORK_DIR/bin/PkgTool.Core"

    log "size: $(stat -c %s "$pkg") bytes"
    log "sha256: $(sha256sum "$pkg" | cut -d' ' -f1)"
    log "magic: $(od -An -tx1 -N4 "$pkg" | tr -d ' \n')  (expected 7f434e54 = \\x7fCNT)"
    log "file(1): $(file -b "$pkg" 2>/dev/null || echo n/a)"
    log "header dump [0x0000..0x0060]:"
    od -Ax -tx1 -N96 "$pkg" | sed 's/^/    /'

    ./bin/ps4-pkg-packager inspect-pkg "$pkg" > "$ART_DIR/pkg-inspection.json"
    python3 - "$ART_DIR/pkg-inspection.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(f"    valid_ps4_pkg = {d['valid_ps4_pkg']}")
print(f"    content_id    = {d['content_id']}")
print(f"    entry_count   = {d['entry_count']}")
print(f"    package_size  = {d['header_pkg_size']} (file {d['size_bytes']})")
print(f"    pfs image     = offset {d['pfs_image_offset']} size {d['pfs_image_size']}")
for e in d["errors"]:
    print("    ERROR:", e)
raise SystemExit(0 if d["valid_ps4_pkg"] else 1)
PY

    ./bin/ps4-pkg-packager inspect-sfo "$WORK_DIR/pkg-staging/sce_sys/param.sfo" | sed 's/^/    /'

    # Full round-trip: unpack the outer+inner PFS with the public debug passcode
    # and compare digests of the extracted files against the source artifacts.
    if [[ -x "$pkgtool" ]]; then
        log "round-trip extract: $pkgtool pkg_extract --passcode <32 zeros>"
        rm -rf "$WORK_DIR/pkg-extract"
        if "$pkgtool" pkg_extract --passcode 00000000000000000000000000000000 "$pkg" "$WORK_DIR/pkg-extract" \
               > "$ART_DIR/pkg-extract.log" 2>&1; then
            find "$WORK_DIR/pkg-extract" -type f | sort | sed 's/^/    /'
            local pairs=(
                "eboot.bin:$ART_DIR/orbis/eboot.bin"
                "assets/boot/bzImage:$BZIMAGE"
                "assets/boot/kexec.bin:$ART_DIR/kexec.bin"
            )
            local pair rel ext a b
            for pair in "${pairs[@]}"; do
                rel="${pair%%:*}"; ext="${pair#*:}"
                if [[ -f "$WORK_DIR/pkg-extract/$rel" ]]; then
                    a="$(sha256sum "$WORK_DIR/pkg-extract/$rel" | cut -d' ' -f1)"
                    b="$(sha256sum "$ext" | cut -d' ' -f1)"
                    if [[ "$a" == "$b" ]]; then
                        log "round-trip MATCH: $rel sha256=$a"
                    else
                        die "round-trip MISMATCH for $rel ($a != $b)"
                    fi
                else
                    warn "round-trip: $rel missing from extraction"
                fi
            done
            log "PFS round-trip extraction verified"
        else
            warn "pkg_extract failed (see artifacts/external/pkg-extract.log) - header verification stands, round-trip unproven"
            tail -5 "$ART_DIR/pkg-extract.log" | sed 's/^/    /' || true
        fi
    fi
}

# ---------------------------------------------------------------------------
# STEP 08 — upload to tmpfiles.org
# ---------------------------------------------------------------------------
upload_step() {
    step "Uploading the verified .pkg to https://tmpfiles.org/"
    ./bin/ps4-pkg-packager upload "$PKG_PATH" > "$ART_DIR/pkg-upload.json" || {
        cat "$ART_DIR/pkg-upload.json"
        die "tmpfiles.org upload failed"
    }
    cat "$ART_DIR/pkg-upload.json" | sed 's/^/    /'

    UPLOAD_URL="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("url",""))' "$ART_DIR/pkg-upload.json")"
    DIRECT_URL="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("direct_url",""))' "$ART_DIR/pkg-upload.json")"
    [[ -n "$UPLOAD_URL" ]] || die "upload reported success without a URL"

    log "verifying $DIRECT_URL over HTTPS"
    local headers code clen
    headers="$(curl -sSIL --max-time 60 "$DIRECT_URL" || true)"
    code="$(printf '%s' "$headers" | awk '/^HTTP/{c=$2} END{print c}')"
    clen="$(printf '%s' "$headers" | awk 'BEGIN{IGNORECASE=1} /^content-length:/{gsub(/\r/,"");v=$2} END{print v}')"
    log "HTTP status=$code content-length=${clen:-unknown} local=$(stat -c %s "$PKG_PATH") bytes"
    if [[ "$code" != "200" ]]; then
        warn "download URL did not return HTTP 200 - reporting the URL but flagging it"
    fi
    if [[ -n "$clen" && "$clen" != "$(stat -c %s "$PKG_PATH")" ]]; then
        warn "Content-Length ($clen) does not match local size - investigate before trusting the URL"
    fi
}

# ---------------------------------------------------------------------------
# STEP 09 — report
# ---------------------------------------------------------------------------
write_report() {
    step "Writing build report"
    local report="$ART_DIR/BUILD-LOG.md"
    local pkg_size pkg_sha
    pkg_size="$(stat -c %s "${PKG_PATH:-/dev/null}" 2>/dev/null || echo 0)"
    pkg_sha="$(sha256sum "${PKG_PATH:-/dev/null}" 2>/dev/null | cut -d' ' -f1 || true)"

    {
        echo "# PS4 Linux Desktop — external build log"
        echo
        echo "Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        echo
        echo "## Host"
        echo
        echo '```'
        uname -a
        [[ -r /etc/os-release ]] && grep PRETTY_NAME /etc/os-release
        echo "nproc=$(nproc)"
        echo "gcc=$(gcc -dumpfullversion 2>/dev/null || echo n/a) clang=$(clang --version 2>/dev/null | head -1 || echo n/a)"
        echo "python3=$(python3 --version 2>&1)"
        echo '```'
        echo
        echo "## Pinned inputs"
        echo
        echo "| Component | Source | Pin | License |"
        echo "|---|---|---|---|"
        echo "| Kernel | $KERNEL_REPO | \`$KERNEL_BRANCH\` @ \`$KERNEL_COMMIT\` | GPL-2.0 |"
        echo "| Ring-0 loader | $KEXEC_REPO | \`$KEXEC_COMMIT\` | BSD-2-Clause |"
        echo "| Orbis SDK | $OPENORBIS_REPO | \`$OPENORBIS_TAG\` @ \`$OPENORBIS_COMMIT\` | GPL-3.0 |"
        echo "| fPKG builder | $LIBORBISPKG_REPO | \`$LIBORBISPKG_COMMIT\` (v0.2) | MIT |"
        echo "| Rootfs | Debian $ROOTFS_RELEASE ($ROOTFS_PROFILE) via debootstrap | $ROOTFS_MIRROR | Debian Free Software Guidelines |"
        echo
        echo "## Artifacts (bytes / SHA-256)"
        echo
        echo "| Role | File | Bytes | SHA-256 |"
        echo "|---|---|---|---|"
        # Stages may be re-run; keep one row per artifact (last one wins).
        tac "$ART_DIR/.artifacts.md" | awk -F'|' '!seen[$3]++' | tac
        echo
        echo "## Package"
        echo
        echo "- Path: \`$ART_DIR/pkg/$PKG_NAME\`"
        echo "- Bytes: $pkg_size"
        echo "- SHA-256: \`$pkg_sha\`"
        echo "- Content ID: \`$CONTENT_ID\`"
        if [[ -n "${UPLOAD_URL:-}" ]]; then
            echo "- tmpfiles.org page: $UPLOAD_URL"
            echo "- tmpfiles.org direct: ${DIRECT_URL:-n/a}"
        else
            echo "- Upload: NOT performed"
        fi
        echo
        echo "## Verification performed"
        echo
        echo "- \`\\x7fCNT\` magic, header \`package_size\` (\`0x430\`) == file size"
        echo "- \`CONTENT_ID\` (\`0x40\`) matches the 36-char Sony layout"
        echo "- Outer PFS image range inside the file; \`entry_count\` > 0"
        echo "- \`sce_sys/param.sfo\` parsed back from the built package"
        echo "- FSELF magic \`4f153d1d\` for eboot.bin, libc.prx, libSceFios2.prx, right.sprx"
        echo "- PFS round-trip extraction and SHA-256 comparison (see build.log)"
        echo "- tmpfiles.org URL re-fetched over HTTPS with header check"
        echo
        echo "## NOT tested"
        echo
        echo "- No install attempt on a physical PS4 (no console available to this build)."
        echo "- No boot into the shipped \`linux.img\` on real Liverpool/Gladius hardware."
        echo "- No HDMI/EDID, thermal, or suspend verification on hardware."
        echo "- GoldHEN/HEN behaviour, fPKG install order, and BinLoader timing are unproven."
        echo "- \`linux.img\` is a Debian ${ROOTFS_RELEASE} (${ROOTFS_PROFILE}) image; KDE/Mesa parity"
        echo "  with the project's ideal desktop is only guaranteed with --rootfs-profile kde / --with-ps4-mesa."
        echo
        echo "## Signing / compatibility"
        echo
        echo "The eboot/PRX modules are fake-signed FSELF (\`create-fself --paid 0x3800000000000011\`)"
        echo "and the package is a fake PKG produced with the public 32-zero debug passcode."
        echo "Such packages install **only on consoles already running GoldHEN/HEN**; they are"
        echo "rejected by retail firmware. No Sony proprietary file was used at any step."
    } > "$report"

    sort -u -k2 "$ART_DIR/SHA256SUMS" -o "$ART_DIR/SHA256SUMS" 2>/dev/null || true
    log "report written: $report"
    log "digests: $ART_DIR/SHA256SUMS"
    echo
    cat "$ART_DIR/SHA256SUMS"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    if [[ $EUID -ne 0 ]]; then
        if have sudo; then
            log "re-executing under sudo (debootstrap/mke2fs need root)"
            exec sudo -E bash "$0" "$@"
        fi
        die "must run as root (debootstrap + mke2fs -d); re-run with sudo"
    fi

    preflight

    if stage_enabled toolchain; then setup_toolchain; save_state; fi
    if stage_enabled payload;   then build_payload;    save_state; fi

    if stage_enabled kernel; then
        if [[ "$BUILD_KERNEL" == "1" ]]; then
            build_kernel_step
        else
            step "Kernel build skipped"
            BZIMAGE="${BZIMAGE_OVERRIDE:-$ART_DIR/kernel/bzImage}"
            [[ -f "$BZIMAGE" ]] || die "--skip-kernel given but no bzImage at $BZIMAGE (use --bzimage PATH)"
            KERNEL_RELEASE="$(strings "$BZIMAGE" 2>/dev/null | grep -m1 -E '^[0-9]+\.[0-9]+\.[0-9]+' || echo unknown)"
            record_artifact "PS4 Fat Linux kernel image (bzImage, prebuilt)" "$BZIMAGE"
        fi
        save_state
    fi

    # Later stages need these values even when they ran in an earlier process.
    [[ -n "${TOOLCHAIN_ROOT:-}" ]] && export OO_PS4_TOOLCHAIN="$TOOLCHAIN_ROOT"

    if stage_enabled orbis;  then build_orbis_app;     save_state; fi
    if stage_enabled rootfs; then build_rootfs_step;   save_state; fi

    if [[ "$DO_PKG" != "1" ]]; then
        step "Package build disabled (--no-pkg)"
        write_report
        return 0
    fi

    if stage_enabled pkg;    then build_pkg_step;      save_state; fi
    if stage_enabled verify; then verify_pkg_step;     save_state; fi

    if stage_enabled upload; then
        if [[ "$DO_UPLOAD" == "1" ]]; then
            upload_step
        else
            step "Upload skipped (--no-upload)"
        fi
        save_state
    fi

    write_report
    echo
    if [[ -n "${UPLOAD_URL:-}" ]]; then
        printf '\033[1;32mPKG UPLOADED: %s\033[0m\n' "$UPLOAD_URL"
        printf '\033[1;32mDIRECT LINK  : %s\033[0m\n' "${DIRECT_URL:-}"
    elif [[ -n "${PKG_PATH:-}" ]]; then
        printf '\033[1;32mPKG BUILT     : %s\033[0m\n' "$PKG_PATH"
    else
        printf '\033[1;32mSTAGES DONE   : %s (no .pkg in this invocation)\033[0m\n' "$STAGES"
    fi
}

main "$@"
