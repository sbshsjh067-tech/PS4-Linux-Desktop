#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# make-ps4-usb-safe.sh — Ironclad USB-Only Disk Preparation Tool (Ticket T-004, Decision D-01)
#
# Enforces Decision D-01:
#   NEVER writes to PS4 internal disk (/dev/sda on PS4, /dev/nvme*, /dev/vda) or any
#   block device whose lsblk transport is not strictly `usb`!
#
# Creates Layout A (self-contained USB):
#   Partition 1: 512 MiB FAT32, label `PS4BOOT` (boot flag) -> bzImage, initramfs.cpio.gz, bootargs.txt, vram.txt
#   Partition 2: Remainder ext4, label `PS4KD`              -> Linux RootFS (or linux.img host)
#   Includes counterfeit USB stick verification (re-verifies p1 FAT32 header after formatting p2).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DEV="${1:-}"
DRY_RUN="${2:-}"

if [[ -z "$TARGET_DEV" ]]; then
    echo "Usage: sudo $0 /dev/sdX [--dry-run]" >&2
    exit 1
fi

# Layer 1: Reject obvious non-USB buses immediately
case "$TARGET_DEV" in
    /dev/nvme*|/dev/vda*|/dev/mmcblk*|/dev/loop*)
        echo "CRITICAL D-01 VIOLATION BLOCKED: $TARGET_DEV is NOT a physical USB drive!" >&2
        exit 10
        ;;
esac

# Layer 2: Reject partition paths (must be whole disk)
if [[ "$TARGET_DEV" =~ [0-9]$ ]]; then
    echo "ERROR: Pass whole USB disk (e.g. /dev/sdb), not a partition ($TARGET_DEV)." >&2
    exit 11
fi

# Layer 3: Enforce lsblk TRAN=usb via Python verifier
python3 -c "
import sys
sys.path.insert(0, '${REPO_ROOT}/src')
from ps4_linux.binary_inspect import verify_usb_device_safety
ok, msg = verify_usb_device_safety('${TARGET_DEV}')
print(msg)
sys.exit(0 if ok else 12)
"

# Layer 4: Reject if device contains any Orbis / FreeBSD UFS / Sony partition signatures
if blkid "${TARGET_DEV}"* 2>/dev/null | grep -qiE "ufs|freebsd|orbis"; then
    echo "CRITICAL D-01 VIOLATION BLOCKED: $TARGET_DEV appears to hold Orbis/FreeBSD partitions!" >&2
    exit 13
fi

if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "[DRY-RUN] Verified $TARGET_DEV is a safe USB target. No partitions modified."
    exit 0
fi

[[ "$(id -u)" -eq 0 ]] || { echo "ERROR: Root privileges required to partition USB device." >&2; exit 1; }

# Layer 5: Refuse if any partition on target is currently mounted
if lsblk -no MOUNTPOINT "${TARGET_DEV}"* 2>/dev/null | grep -q '/'; then
    echo "ERROR: One or more partitions on $TARGET_DEV are currently mounted. Unmount first." >&2
    exit 14
fi

MODEL="$(lsblk -dno MODEL,SIZE "$TARGET_DEV" 2>/dev/null | tr -s ' ')"
echo "WARNING: About to format USB drive $TARGET_DEV ($MODEL)"
echo "  p1: 512 MiB FAT32 (LABEL=PS4BOOT)"
echo "  p2: Remainder ext4 (LABEL=PS4KD)"
read -r -p "Type exact device path '$TARGET_DEV' to confirm: " CONFIRM
[[ "$CONFIRM" == "$TARGET_DEV" ]] || { echo "Aborted."; exit 1; }

sfdisk "$TARGET_DEV" <<'EOF'
label: dos
,512M,c,*
,,L,-
EOF

partprobe "$TARGET_DEV" 2>/dev/null || true
sleep 2

mkfs.vfat -F 32 -n PS4BOOT "${TARGET_DEV}1"
mkfs.ext4 -F -L PS4KD -O ^metadata_csum_seed "${TARGET_DEV}2"

sync
blockdev --flushbufs "$TARGET_DEV" 2>/dev/null || true

# Layer 6: Counterfeit USB flash wrap-around check (re-verify p1 is still vfat!)
P1_TYPE="$(blkid -s TYPE -o value "${TARGET_DEV}1" 2>/dev/null || true)"
if [[ "$P1_TYPE" != "vfat" ]]; then
    echo "ERROR: Partition 1 is no longer vfat after formatting Partition 2 (counterfeit/faulty USB stick)!" >&2
    exit 15
fi

echo "SUCCESS: Prepared safe PS4 Linux USB drive on $TARGET_DEV (PS4BOOT + PS4KD)."
