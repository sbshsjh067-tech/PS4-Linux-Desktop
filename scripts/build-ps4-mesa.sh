#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# PS4 Linux Desktop — Pinned PS4 Mesa 26.2.5 + libdrm 2.4.134 Builder (Ticket T-006)
#
# Applies all THREE verified PS4 Liverpool/Gladius patches from patches/mesa/:
#   1. 0001-ps4-liverpool-gladius.patch  (PCI IDs 0x9920/22/23/24, GFX7, raster_config)
#   2. 0002-radv-ps4-no-hiz.patch        (Disables RADV HiZ -> fixes GFX-002 ring gfx timeout)
#   3. 0003-aco-ps4-no-flat-global.patch (Replaces ACO FLAT ops with MUBUF addr64 -> prevents GPU hang)
#
# Built strictly with `-march=btver2 -mno-avx2 -mno-fma -mno-bmi2` for PS4 AMD Jaguar
# and `-Dgallium-va=disabled -Dvideo-codecs=` (VA-API compiled out per research/13-QA §1 Q2).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_DIR="${REPO_ROOT}/patches/mesa"

MESA_VER="26.2.5"
MESA_SHA256="794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5"
DRM_VER="2.4.134"
DRM_SHA256="ac5e74d157830eb8bee44c6a6bf3ad49774ef0dd2a72bdad74a8f20308b52a95"
PREFIX="/opt/ps4-mesa"

VERIFY_PATCHES_ONLY=0
if [[ "${1:-}" == "--verify-patches" ]]; then
    VERIFY_PATCHES_ONLY=1
fi

EXPECTED_PATCHES=(
    "10b9778bd8f44a30e1787568f95a8a804c01d5a296cca8dff93ded1afbdfd318  ${PATCH_DIR}/0001-ps4-liverpool-gladius.patch"
    "cef4aa15d0329050368dafd724969f4c01ff2329bd297cbb5db7c55ad6a77b97  ${PATCH_DIR}/0002-radv-ps4-no-hiz.patch"
    "b3fcbac66a89aef9040017cac3b000b6e4074914ac6f0fb23ad5e0b02f489e03  ${PATCH_DIR}/0003-aco-ps4-no-flat-global.patch"
)

echo "=== VERIFYING MIRRORED PS4 MESA PATCHES (SHA-256) ==="
for entry in "${EXPECTED_PATCHES[@]}"; do
    echo "$entry" | sha256sum -c -
done

if [[ "$VERIFY_PATCHES_ONLY" == "1" ]]; then
    echo "All 3 PS4 Mesa patches verified intact."
    exit 0
fi

for cmd in curl tar xz meson ninja patch pkg-config; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: Missing build tool '$cmd' for Mesa build (recommended container: debian:trixie with llvm-19-dev)." >&2
        exit 2
    fi
done

WORK="${REPO_ROOT}/.mesa-work"
STAGE="${WORK}/stage"
mkdir -p "${WORK}/src" "$STAGE"

fetch_verified() {
    local url="$1"
    local sha="$2"
    local dst="${WORK}/src/$(basename "$url")"
    [[ -f "$dst" ]] || curl -fsSL -o "$dst" "$url"
    echo "${sha}  ${dst}" | sha256sum -c -
}

fetch_verified "https://dri.freedesktop.org/libdrm/libdrm-${DRM_VER}.tar.xz" "$DRM_SHA256"
fetch_verified "https://archive.mesa3d.org/mesa-${MESA_VER}.tar.xz" "$MESA_SHA256"

export CFLAGS="-O2 -march=btver2 -mtune=btver2 -mno-avx2 -mno-fma -mno-bmi2"
export CXXFLAGS="$CFLAGS"

rm -rf "${WORK}/libdrm-${DRM_VER}" "${WORK}/mesa-${MESA_VER}" "${WORK}/b-drm" "${WORK}/b-mesa"
tar -C "$WORK" -xf "${WORK}/src/libdrm-${DRM_VER}.tar.xz"
tar -C "$WORK" -xf "${WORK}/src/mesa-${MESA_VER}.tar.xz"

cat >> "${WORK}/libdrm-${DRM_VER}/data/amdgpu.ids" <<'EOF'
9920,	00,	AMD Liverpool (PlayStation 4)
9922,	00,	AMD Liverpool (PlayStation 4)
9923,	00,	AMD Liverpool (PlayStation 4)
9924,	11,	AMD Gladius (PlayStation 4 Pro)
EOF

meson setup "${WORK}/b-drm" "${WORK}/libdrm-${DRM_VER}" \
    --prefix="$PREFIX" --libdir=lib --buildtype=release \
    -Damdgpu=enabled -Dradeon=enabled \
    -Dintel=disabled -Dnouveau=disabled -Dvmwgfx=disabled -Dtests=false
ninja -C "${WORK}/b-drm"
DESTDIR="$STAGE" ninja -C "${WORK}/b-drm" install

for p in "${PATCH_DIR}"/0*.patch; do
    patch -d "${WORK}/mesa-${MESA_VER}" -p1 < "$p"
done

export PKG_CONFIG_PATH="${STAGE}${PREFIX}/lib/pkgconfig"
sed -i "s|^prefix=.*|prefix=${STAGE}${PREFIX}|" "${STAGE}${PREFIX}/lib/pkgconfig/"*.pc

meson setup "${WORK}/b-mesa" "${WORK}/mesa-${MESA_VER}" \
    --prefix="$PREFIX" --libdir=lib --buildtype=release \
    -Db_ndebug=true -Dstrip=true \
    -Dgallium-drivers=radeonsi,zink,llvmpipe \
    -Dvulkan-drivers=amd \
    -Dplatforms=x11,wayland \
    -Dglx=dri -Degl=enabled -Dgbm=enabled -Dglvnd=enabled \
    -Dgles1=disabled -Dgles2=enabled -Dopengl=true \
    -Dllvm=enabled -Dshared-llvm=enabled \
    -Dgallium-va=disabled -Dvideo-codecs= \
    -Dbuild-tests=false
ninja -C "${WORK}/b-mesa"
DESTDIR="$STAGE" ninja -C "${WORK}/b-mesa" install
sed -i "s|^prefix=.*|prefix=${PREFIX}|" "${STAGE}${PREFIX}/lib/pkgconfig/"*.pc

mkdir -p "${REPO_ROOT}/artifacts/mesa"
tar -C "$STAGE" -cf - opt | xz -T0 -6 > "${REPO_ROOT}/artifacts/mesa/ps4-mesa-${MESA_VER}.tar.xz"
sha256sum "${REPO_ROOT}/artifacts/mesa/ps4-mesa-${MESA_VER}.tar.xz" | tee "${REPO_ROOT}/artifacts/mesa/ps4-mesa-${MESA_VER}.tar.xz.sha256"
