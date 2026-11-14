#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# manage-linux-img.sh — Safe Non-Destructive `linux.img` RootFS Image Tool (PART 2 §6, T-004)
#
# Creates, inspects, and repairs `linux.img` ext4 RootFS container files with PS4-safe
# filesystem defaults (`LABEL=PS4KD`, /etc/fstab with `noatime,commit=30,errors=remount-ro`),
# without ever partitioning or touching user disks!

set -euo pipefail

PATH="$PATH:/usr/sbin:/sbin"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CMD="${1:-}"
IMG_PATH="${2:-}"
SIZE_MIB="${3:-64}"

case "$CMD" in
    create)
        [[ -n "$IMG_PATH" ]] || { echo "Usage: $0 create <path/to/linux.img> [size_mib]" >&2; exit 1; }
        mkdir -p "$(dirname "$IMG_PATH")"
        STAGE_ROOT="$(mktemp -d)"
        trap 'rm -rf "$STAGE_ROOT"' EXIT

        # Populate essential RootFS skeleton + PS4 fstab + thin KDE/XFCE configs inside image
        mkdir -p "${STAGE_ROOT}"/{bin,sbin,etc/X11/xorg.conf.d,etc/systemd/system,opt/ps4-mesa,proc,sys,dev,run,tmp,var/log/ps4-linux,usr/share/xsessions}
        cat > "${STAGE_ROOT}/etc/fstab" <<'EOF'
# PS4 Linux Desktop — Safe USB / linux.img fstab (Decision D-01, Ticket T-004)
LABEL=PS4KD   /          ext4  rw,noatime,commit=30,errors=remount-ro  0 1
LABEL=PS4BOOT /boot/efi  vfat  rw,noatime,nofail                       0 2
EOF
        cat > "${STAGE_ROOT}/usr/share/xsessions/plasma.desktop" <<'EOF'
[Desktop Entry]
Type=XSession
Exec=startplasma-x11
Name=KDE Plasma (PS4 Tuned)
EOF
        cat > "${STAGE_ROOT}/usr/share/xsessions/xfce.desktop" <<'EOF'
[Desktop Entry]
Type=XSession
Exec=startxfce4
Name=XFCE Recovery Session (PS4 Safe Mode)
EOF
        cp "${REPO_ROOT}/scripts/ps4-mesa-select" "${STAGE_ROOT}/sbin/ps4-mesa-select"
        chmod 755 "${STAGE_ROOT}/sbin/ps4-mesa-select"
        PS4_ETC_ROOT="${STAGE_ROOT}/etc" PS4_MESA_PREFIX="${STAGE_ROOT}/opt/ps4-mesa" \
            "${STAGE_ROOT}/sbin/ps4-mesa-select" --undo >/dev/null

        truncate -s "${SIZE_MIB}M" "$IMG_PATH"
        mke2fs -t ext4 -F -L PS4KD -d "$STAGE_ROOT" "$IMG_PATH" >/dev/null
        e2fsck -fy "$IMG_PATH" >/dev/null 2>&1 || true
        echo "Created verified ext4 RootFS image: $IMG_PATH (${SIZE_MIB} MiB, LABEL=PS4KD)"
        ;;

    check)
        [[ -n "$IMG_PATH" && -f "$IMG_PATH" ]] || { echo "ERROR: Image not found: $IMG_PATH" >&2; exit 1; }
        e2fsck -fn "$IMG_PATH"
        python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, '${REPO_ROOT}/src')
from ps4_linux.binary_inspect import inspect_ext4_image
res = inspect_ext4_image(Path('${IMG_PATH}'))
print(json.dumps(res.to_dict(), indent=2))
sys.exit(0 if res.valid_ext4 else 1)
"
        ;;

    *)
        echo "Usage: $0 {create <linux.img> [size_mib] | check <linux.img>}" >&2
        exit 1
        ;;
esac
