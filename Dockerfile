# SPDX-License-Identifier: GPL-2.0-only
#
# PS4 Linux Desktop — reproducible external build environment.
#
# Provides every dependency required by scripts/build-external-release.sh:
#   clang/lld/llvm      -> PS4 kernel (LLVM=1, ThinLTO) + OpenOrbis FSELF toolchain
#   gcc                 -> fail0verflow/ps4-kexec ring-0 payload
#   debootstrap         -> Debian 12 root filesystem
#   e2fsprogs           -> ext4 `linux.img` via `mke2fs -d` (no loop mounts)
#   dotnet-sdk-8.0      -> LibOrbisPkg PkgTool.Core fallback
#
# Build:
#   docker build -t ps4-linux-desktop/build:external .
#
# Run (writes ./artifacts/external on the host):
#   docker run --rm -it \
#       -v "$PWD/artifacts:/repo/artifacts" \
#       -v "$PWD/.external-work:/repo/.external-work" \
#       ps4-linux-desktop/build:external --no-upload
#
# Full pipeline incl. tmpfiles.org upload:
#   docker run --rm -it -v "$PWD/artifacts:/repo/artifacts" \
#       ps4-linux-desktop/build:external

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git curl ca-certificates wget \
        clang lld llvm \
        bc flex bison libssl-dev libelf-dev libncurses-dev \
        dwarves zstd xz-utils cpio kmod rsync \
        python3 python3-pip \
        e2fsprogs debootstrap \
        util-linux file binutils \
        openssl sudo less vim-tiny \
    && rm -rf /var/lib/apt/lists/*

# .NET SDK is only needed for the from-source LibOrbisPkg fallback; never fatal.
RUN apt-get update \
    && (apt-get install -y --no-install-recommends dotnet-sdk-8.0 || echo "dotnet-sdk-8.0 unavailable") \
    && rm -rf /var/lib/apt/lists/*

# Sanity: the toolchain versions this image is validated against.
RUN clang --version | head -1 \
    && ld.lld --version \
    && gcc --version | head -1 \
    && debootstrap --version \
    && mke2fs -V 2>&1 | head -1 \
    && python3 --version

WORKDIR /repo
COPY . /repo

RUN chmod +x /repo/scripts/*.sh /repo/bin/* && bash -n /repo/scripts/build-external-release.sh

# Everything lands in /repo/artifacts/external + /repo/.external-work (mount them).
ENTRYPOINT ["/repo/scripts/build-external-release.sh"]
CMD []
