# PS4 Linux Desktop — Master Engineering Makefile
# Targets PS4 Fat (CUH-10xx/11xx Aeolia & CUH-12xx Belize) with AMD Jaguar (-march=btver2)

CC       ?= gcc
CFLAGS   := -O2 -march=btver2 -mtune=btver2 -mno-avx2 -mno-fma -mno-bmi2 -fno-builtin -fno-stack-protector -fno-asynchronous-unwind-tables -Wall -Wextra -Werror
PYTHON   ?= python3

.PHONY: all build-initramfs-guard pack-initramfs stage-pkg verify-patches test lint clean

all: build-initramfs-guard verify-patches

build-initramfs-guard: initramfs/src/ps4_hdmi_guard.c
	@mkdir -p initramfs/bin
	$(CC) $(CFLAGS) -static -nostdlib -o initramfs/bin/ps4_hdmi_guard initramfs/src/ps4_hdmi_guard.c
	strip --strip-unneeded initramfs/bin/ps4_hdmi_guard
	@echo "[OK] Built Jaguar-safe freestanding static binary: initramfs/bin/ps4_hdmi_guard"

pack-initramfs: build-initramfs-guard
	@mkdir -p artifacts/boot
	./bin/ps4-initramfs-tool pack initramfs artifacts/boot/initramfs.cpio.gz

stage-pkg: build-initramfs-guard
	./bin/ps4-pkg-packager build-or-stage

verify-patches:
	./scripts/build-ps4-mesa.sh --verify-patches

lint:
	@for s in scripts/*.sh initramfs/init scripts/ps4-mesa-select scripts/ps4-rescue-desktop; do \
		bash -n "$$s" || exit 1; \
	done
	$(PYTHON) -m py_compile src/ps4_linux/*.py bin/ps4-* scripts/ps4-thermal-guard
	@echo "[OK] All shell and Python syntax checks passed."

test: all lint
	$(PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf artifacts .kernel-work .mesa-work
