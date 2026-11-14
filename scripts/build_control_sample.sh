#!/usr/bin/env bash
# Diagnostic only: build the upstream OpenOrbis hello_world sample with the same
# pinned toolchain, as a known-good control for the launcher's SELF/ELF shape.
# Never fails the job; every step is reported as an annotation.
set -uo pipefail

note() { local t="$1"; shift; printf '::notice title=%s::%s\n' "$t" "$(printf '%s' "$*" | tr '\n' ' ' | head -c 900)"; }

TC="${TC:-}"
note control-paths "TC=$TC oo=$(ls /tmp/oo 2>/dev/null | tr '\n' ' ')"

SAMPLE=/tmp/oo/samples/hello_world
if [ ! -d "$SAMPLE" ]; then
    note control-missing "$SAMPLE not present"
    exit 0
fi

note control-sample-files "$(ls -a "$SAMPLE" | tr '\n' ' ')"

cd "$SAMPLE" || { note control-cd "cannot enter $SAMPLE"; exit 0; }
OO_PS4_TOOLCHAIN="$TC" make eboot.bin > /tmp/control-build.log 2>&1
rc=$?
note control-build "rc=$rc eboot=$(stat -c %s eboot.bin 2>/dev/null || echo none)"
note control-build-log "$(tail -14 /tmp/control-build.log)"
if [ -f eboot.bin ]; then
    cp eboot.bin "${GITHUB_WORKSPACE:-.}/in/control-hello-world-eboot.bin" && note control-copied ok
fi
exit 0
