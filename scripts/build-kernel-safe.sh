#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# PS4 Linux Desktop — Safe Pinned Kernel Builder & Config Repair Tool (T-002, PART 4 §11)
#
# Pinned Source of Record (research/14-pinned-inputs.lock.yaml, Decision D-07):
#   Primary  : https://github.com/feeRnt/ps4-linux-12xx @ 8ec5c282abda91f6c2e4014de206105aa7912516 (7.0-Clean)
#   Fallback : https://github.com/feeRnt/ps4-linux-12xx @ 3cba9d4db59422c8fc4dd55a39958def042e8816 (6.15.4)
#
# Fixes two upstream build hazards discovered during repository source audit:
#   1. Upstream `config` hardcodes CONFIG_EXTRA_FIRMWARE_DIR="/home/rmux/ps4_testing/ps4-linux-12xx/extra_firmware"
#      -> Automatically rewritten to "${KERNEL_SRC}/extra_firmware".
#   2. Upstream `build.sh` `general` profile disables CONFIG_OVERLAY_FS and requires LLVM/Clang LTO
#      -> Enforces configs/kernel/ps4-desktop-fat.config (CONFIG_DRM_AMDGPU=y, CONFIG_BLK_DEV_LOOP=y,
#         CONFIG_OVERLAY_FS=y) and `-march=btver2 -mtune=btver2` for AMD Jaguar.
#
# Extra switches used by the unrestricted external build (scripts/build-external-release.sh):
#   --fetch-firmware / --no-firmware   Download CONFIG_EXTRA_FIRMWARE blobs (linux-firmware mirror)
#   --no-debug-info                    Drop CONFIG_DEBUG_INFO/BTF (release bzImage, 2-3x faster)
#   --no-modules                       Build `bzImage` only (no `modules`)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRAGMENT="${REPO_ROOT}/configs/kernel/ps4-desktop-fat.config"

CANDIDATE="primary"
FETCH_FIRMWARE=1
DEBUG_INFO=1
BUILD_MODULES=1
JOBS="$(nproc)"
WORK_DIR="${REPO_ROOT}/.kernel-work"
OUTPUT_DIR="${REPO_ROOT}/artifacts/kernel"
DRY_RUN_AUDIT=0
CONFIG_TO_REPAIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --candidate)      CANDIDATE="$2"; shift 2 ;;
        --work-dir)       WORK_DIR="$2"; shift 2 ;;
        --output-dir)     OUTPUT_DIR="$2"; shift 2 ;;
        --repair-config)  CONFIG_TO_REPAIR="$2"; shift 2 ;;
        --dry-run-audit)  DRY_RUN_AUDIT=1; shift ;;
        --fetch-firmware) FETCH_FIRMWARE=1; shift ;;
        --no-firmware)    FETCH_FIRMWARE=0; shift ;;
        --no-debug-info)  DEBUG_INFO=0; shift ;;
        --debug-info)     DEBUG_INFO=1; shift ;;
        --jobs)           JOBS="$2"; shift 2 ;;
        --no-modules)     BUILD_MODULES=0; shift ;;
        --modules)        BUILD_MODULES=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

KERNEL_REPO="https://github.com/feeRnt/ps4-linux-12xx.git"
if [[ "$CANDIDATE" == "primary" ]]; then
    KERNEL_BRANCH="7.0-Clean"
    KERNEL_COMMIT="8ec5c282abda91f6c2e4014de206105aa7912516"
elif [[ "$CANDIDATE" == "fallback" ]]; then
    KERNEL_BRANCH="6.15.4-aeolia-belize-crashniels"
    KERNEL_COMMIT="3cba9d4db59422c8fc4dd55a39958def042e8816"
elif [[ "$CANDIDATE" == "baikal" ]]; then
    KERNEL_BRANCH="5.4.247-baikal-dfaus"
    KERNEL_COMMIT="1fdfbd9a4c5690602893f6d5f65e154c6d9ba711"
else
    echo "ERROR: Invalid --candidate '$CANDIDATE' (expected primary, fallback, baikal)" >&2
    exit 1
fi

repair_kernel_config_file() {
    local cfg_file="$1"
    local fw_dir="$2"
    [[ -f "$cfg_file" ]] || { echo "ERROR: Config file missing: $cfg_file" >&2; return 1; }
    cp "$cfg_file" "${cfg_file}.bak"

    # 1. Repair hardcoded upstream /home/rmux/... firmware directory path
    sed -i "s|^CONFIG_EXTRA_FIRMWARE_DIR=.*|CONFIG_EXTRA_FIRMWARE_DIR=\"${fw_dir}\"|" "$cfg_file"

    # 2. Merge PS4 Fat Desktop mandatory options
    while IFS= read -r line; do
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        key="${line%%=*}"
        val="${line#*=}"
        sed -i "/^${key}=/d; /^# ${key} is not set/d" "$cfg_file"
        echo "${key}=${val}" >> "$cfg_file"
    done < "$FRAGMENT"
}

# Upstream `build.sh` downloads every CONFIG_EXTRA_FIRMWARE blob from the public
# linux-firmware mirror. We do the same here, but resolve the mirror ref to an
# exact commit SHA and record per-blob SHA-256 digests in FIRMWARE.lock, so the
# kernel build is reproducible instead of tracking a moving branch.
fetch_extra_firmware() {
    local src="$1"
    local fw_dir="${src}/extra_firmware"
    local fw_ref="${LINUX_FIRMWARE_REF:-main}"
    local firmware_repo="${LINUX_FIRMWARE_REPO:-https://gitlab.com/kernel-firmware/linux-firmware.git}"
    local cfg_line blobs blob sha base_url lock

    cfg_line="$(grep -E '^CONFIG_EXTRA_FIRMWARE=' "${src}/.config" 2>/dev/null || true)"
    if [[ -z "$cfg_line" ]]; then
        echo "No CONFIG_EXTRA_FIRMWARE in .config -- nothing to fetch."
        return 0
    fi
    blobs="$(printf '%s\n' "$cfg_line" | sed 's/^CONFIG_EXTRA_FIRMWARE="\(.*\)"$/\1/' | tr ' ' '\n' | grep -v '^$' || true)"
    if [[ -z "$blobs" ]]; then
        echo "CONFIG_EXTRA_FIRMWARE is empty -- nothing to fetch."
        return 0
    fi

    sha="$(git ls-remote "${firmware_repo}" "${fw_ref}" 2>/dev/null | awk '{print $1}' | head -1)"
    if [[ -z "$sha" ]]; then
        echo "ERROR: could not resolve linux-firmware ref '${fw_ref}' from ${firmware_repo}" >&2
        return 1
    fi
    echo "linux-firmware ref '${fw_ref}' resolved to commit ${sha}"

    base_url="${firmware_repo%.git}/-/raw/${sha}"
    mkdir -p "${fw_dir}"
    lock="${fw_dir}/FIRMWARE.lock"
    : > "$lock"

    while IFS= read -r blob; do
        local dest="${fw_dir}/${blob}"
        mkdir -p "$(dirname "$dest")"
        if [[ -f "$dest" ]]; then
            echo "  [=] cached: ${blob}"
        else
            echo "  [downloading] ${blob}"
            if ! curl -fsSL --retry 3 --retry-delay 2 "${base_url}/${blob}" -o "$dest"; then
                echo "ERROR: failed to download firmware blob ${blob} from ${base_url}" >&2
                return 1
            fi
        fi
        printf '%s  %s  %s/%s\n' "$(sha256sum "$dest" | cut -d' ' -f1)" "$blob" "$base_url" "$blob" >> "$lock"
    done <<< "$blobs"

    echo "Recorded firmware digests: ${lock}"
}

# Standalone config repair mode (used by unit tests and pre-build validation)
if [[ -n "$CONFIG_TO_REPAIR" ]]; then
    repair_kernel_config_file "$CONFIG_TO_REPAIR" "$(dirname "$CONFIG_TO_REPAIR")/extra_firmware"
    echo "Repaired kernel config: $CONFIG_TO_REPAIR (backup at ${CONFIG_TO_REPAIR}.bak)"
    exit 0
fi

echo "=== PS4 KERNEL BUILD PRE-FLIGHT AUDIT (PART 4 §11) ==="
echo "Pinned Repo    : $KERNEL_REPO"
echo "Pinned Branch  : $KERNEL_BRANCH"
echo "Pinned Commit  : $KERNEL_COMMIT"
echo "Config Fragment: $FRAGMENT"

[[ -f "$FRAGMENT" ]] || { echo "ERROR: Missing $FRAGMENT" >&2; exit 1; }

AVAIL_KB="$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')"
echo "Available Disk : $((AVAIL_KB / 1024)) MiB"

MISSING_TOOLS=()
TOOL_LIST="git make gcc ld bc flex bison libssl-dev"
[[ "$FETCH_FIRMWARE" == "1" ]] && TOOL_LIST="${TOOL_LIST} curl"
for tool in $TOOL_LIST; do
    if [[ "$tool" == "libssl-dev" ]]; then
        [[ -f /usr/include/openssl/ssl.h ]] || MISSING_TOOLS+=("libssl-dev")
    else
        command -v "$tool" >/dev/null 2>&1 || MISSING_TOOLS+=("$tool")
    fi
done
if ! command -v clang >/dev/null 2>&1; then
    MISSING_TOOLS+=("clang/lld (required for ThinLTO in 7.0-Clean)")
fi

if [[ "$DRY_RUN_AUDIT" == "1" ]]; then
    echo "Missing Kernel Build Dependencies (${#MISSING_TOOLS[@]}): ${MISSING_TOOLS[*]:-NONE}"
    if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
        echo "AUDIT RESULT: BLOCKED_ON_HOST_DEPS (install via: sudo apt-get install -y clang lld llvm flex bison bc libssl-dev libelf-dev pahole cpio)"
        exit 0
    fi
    echo "AUDIT RESULT: READY_TO_BUILD"
    exit 0
fi

if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
    echo "ERROR: Missing kernel build dependencies: ${MISSING_TOOLS[*]}" >&2
    echo "Install on Debian/Ubuntu: sudo apt-get install -y clang lld llvm flex bison bc libssl-dev libelf-dev pahole cpio" >&2
    exit 2
fi

if [[ "$AVAIL_KB" -lt $((12 * 1024 * 1024)) ]]; then
    echo "ERROR: Kernel source + object build requires >= 12 GiB free disk space." >&2
    exit 3
fi

mkdir -p "$WORK_DIR" "$OUTPUT_DIR"
SRC="${WORK_DIR}/ps4-linux-src"
if [[ ! -d "${SRC}/.git" ]]; then
    git init "$SRC"
    git -C "$SRC" remote add origin "$KERNEL_REPO"
fi
git -C "$SRC" fetch --depth 1 origin "$KERNEL_COMMIT"
git -C "$SRC" checkout -f "$KERNEL_COMMIT"

ACTUAL_SHA="$(git -C "$SRC" rev-parse HEAD)"
if [[ "$ACTUAL_SHA" != "$KERNEL_COMMIT" ]]; then
    echo "ERROR: Commit pin mismatch ($ACTUAL_SHA != $KERNEL_COMMIT)" >&2
    exit 4
fi

cp "${SRC}/config" "${SRC}/.config"
repair_kernel_config_file "${SRC}/.config" "${SRC}/extra_firmware"

if [[ "$FETCH_FIRMWARE" == "1" ]]; then
    echo "=== FETCHING CONFIG_EXTRA_FIRMWARE BLOBS ==="
    fetch_extra_firmware "$SRC"
else
    echo "WARNING: --no-firmware given; CONFIG_EXTRA_FIRMWARE blobs must already exist."
fi

if [[ "$DEBUG_INFO" == "0" ]]; then
    echo "=== DISABLING CONFIG_DEBUG_INFO / BTF (release build) ==="
    "$SRC/scripts/config" --file "$SRC/.config" --disable DEBUG_INFO --disable DEBUG_INFO_BTF
    "$SRC/scripts/config" --file "$SRC/.config" --disable DEBUG_INFO_DWARF4
    "$SRC/scripts/config" --file "$SRC/.config" --disable DEBUG_INFO_BTF_MODULES
fi

export KCFLAGS="-march=btver2 -mtune=btver2 -mno-avx2 -mno-fma -mno-bmi2 -O2"
export KAFLAGS="-march=btver2 -mtune=btver2"

make -C "$SRC" LLVM=1 ARCH=x86_64 olddefconfig

MAKE_TARGETS=(bzImage)
if [[ "$BUILD_MODULES" == "1" ]]; then
    MAKE_TARGETS+=(modules)
fi
echo "Kernel make targets: ${MAKE_TARGETS[*]}"
make -C "$SRC" -j"${JOBS}" LLVM=1 ARCH=x86_64 "${MAKE_TARGETS[@]}"

BZ="${SRC}/arch/x86/boot/bzImage"
cp "$BZ" "${OUTPUT_DIR}/bzImage"
cp "${SRC}/.config" "${OUTPUT_DIR}/kernel.config"

echo "=== POST-BUILD VERIFICATION ==="
"${REPO_ROOT}/bin/ps4-safe-boot" --bzimage "${OUTPUT_DIR}/bzImage" --initramfs "${OUTPUT_DIR}/initramfs.cpio.gz" --json || true
sha256sum "${OUTPUT_DIR}/bzImage" | tee "${OUTPUT_DIR}/bzImage.sha256"
