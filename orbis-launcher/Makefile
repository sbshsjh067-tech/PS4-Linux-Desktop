# SPDX-License-Identifier: GPL-2.0-only
#
# PS4 Linux Desktop — OpenOrbis Launcher Build (`eboot.bin`, Orbis FSELF)
#
# Requires the OpenOrbis-PS4-Toolchain v0.5.4 (pinned, GPL-3.0) with:
#   $OO_PS4_TOOLCHAIN/{link.x,include/,lib/,bin/linux/{create-fself,PkgTool.Core}}
#
# Produces a *fake-signed* FSELF (create-fself --paid 0x3800000000000011).
# It is loadable only on GoldHEN/HEN consoles — never on retail firmware.
#
# Usage:
#   OO_PS4_TOOLCHAIN=/path/to/OpenOrbis/PS4Toolchain make -C orbis-launcher
#   make -C orbis-launcher OUTDIR=artifacts/external/launcher

TITLE      := PS4 Linux Desktop Launcher
VERSION    := 01.00
TITLE_ID   := BREW00001
CONTENT_ID := IV0000-BREW00001_00-PS4LDESKTOP00000

TOOLCHAIN  ?= $(OO_PS4_TOOLCHAIN)
OUTDIR     ?= out

CC         := clang
LD         := ld.lld

# Jaguar-safe: no AVX2/FMA/BMI2 anywhere in userland either (-march=btver2).
JAGUAR     := -march=btver2 -mtune=btver2 -mno-avx2 -mno-fma -mno-bmi2

CFLAGS     := --target=x86_64-pc-freebsd12-elf -fPIC -funwind-tables -O2 \
              -Wall -Wextra -Wno-unused-parameter $(JAGUAR) \
              -isysroot $(TOOLCHAIN) -isystem $(TOOLCHAIN)/include
LDFLAGS    := -m elf_x86_64 -pie --script $(TOOLCHAIN)/link.x --eh-frame-hdr \
              -L$(TOOLCHAIN)/lib -lc -lkernel $(TOOLCHAIN)/lib/crt1.o

CREATE_FSELF := $(TOOLCHAIN)/bin/linux/create-fself
PKGTOOL      := $(TOOLCHAIN)/bin/linux/PkgTool.Core

.PHONY: all clean check-toolchain metadata
.DEFAULT_GOAL := all

all: $(OUTDIR)/eboot.bin

check-toolchain:
	@test -n "$(TOOLCHAIN)" || { echo "ERROR: OO_PS4_TOOLCHAIN is not set"; exit 1; }
	@test -f "$(TOOLCHAIN)/link.x" || { echo "ERROR: $(TOOLCHAIN)/link.x missing"; exit 1; }
	@test -x "$(CREATE_FSELF)" || { echo "ERROR: $(CREATE_FSELF) missing"; exit 1; }

$(OUTDIR):
	@mkdir -p $(OUTDIR)

$(OUTDIR)/launcher.o: main.c | $(OUTDIR) check-toolchain
	$(CC) $(CFLAGS) -c -o $@ $<

$(OUTDIR)/ps4ld-launcher.elf: $(OUTDIR)/launcher.o
	$(LD) $< -o $@ $(LDFLAGS)

# create-fself embeds the fake SELF header; the resulting eboot.bin starts with
# the Orbis FSELF magic 4f 15 3d 1d, which the PKG packager verifies.
$(OUTDIR)/eboot.bin: $(OUTDIR)/ps4ld-launcher.elf check-toolchain
	$(CREATE_FSELF) -in=$< -out=$(OUTDIR)/ps4ld-launcher.oelf --eboot $@ --paid 0x3800000000000011

# Optional: build sce_sys/param.sfo with the toolchain (the Python packager also
# generates its own byte-accurate SFO; this target exists for cross-checking).
metadata: check-toolchain | $(OUTDIR)
	$(PKGTOOL) sfo_new $(OUTDIR)/param.sfo
	$(PKGTOOL) sfo_setentry $(OUTDIR)/param.sfo CONTENT_ID --type Utf8 --maxsize 48 --value '$(CONTENT_ID)'
	$(PKGTOOL) sfo_setentry $(OUTDIR)/param.sfo TITLE_ID --type Utf8 --maxsize 12 --value '$(TITLE_ID)'
	$(PKGTOOL) sfo_setentry $(OUTDIR)/param.sfo TITLE --type Utf8 --maxsize 128 --value '$(TITLE)'
	$(PKGTOOL) sfo_setentry $(OUTDIR)/param.sfo VERSION --type Utf8 --maxsize 8 --value '$(VERSION)'
	$(PKGTOOL) sfo_setentry $(OUTDIR)/param.sfo CATEGORY --type Utf8 --maxsize 4 --value 'gd'
	$(PKGTOOL) sfo_setentry $(OUTDIR)/param.sfo APP_TYPE --type Integer --maxsize 4 --value 1
	$(PKGTOOL) sfo_setentry $(OUTDIR)/param.sfo ATTRIBUTE --type Integer --maxsize 4 --value 0

clean:
	rm -rf $(OUTDIR)/launcher.o $(OUTDIR)/ps4ld-launcher.elf \
	       $(OUTDIR)/ps4ld-launcher.oelf $(OUTDIR)/eboot.bin $(OUTDIR)/param.sfo
