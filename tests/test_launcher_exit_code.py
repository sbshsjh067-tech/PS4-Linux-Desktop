"""Guards against the CE-34878-0 regression in the Orbis launcher.

Root cause of the crash on real hardware: `main()` treated "no writable USB at
/mnt/usb0" as fatal and returned 1. On Orbis a non-zero process exit is reported
by the system as CE-34878-0 ("the application crashed"), which the user sees the
instant they open the app - before any UI, because this launcher has no UI.

These tests are cheap and run everywhere:
  * the launcher must never terminate with a non-zero status;
  * it must not hard-code a single mount point;
  * it must still compile cleanly with -Wall -Wextra (when a host compiler exists).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_C = REPO_ROOT / "orbis-launcher" / "main.c"

STUB_LIBKERNEL = """\
#ifndef STUB_LIBKERNEL_H
#define STUB_LIBKERNEL_H
#include <sys/types.h>
#include <stdint.h>
int sceKernelDebugOutText(int fd, const char *fmt, ...);
int sceKernelOpen(const char *path, int flags, int mode);
int sceKernelClose(int fd);
ssize_t sceKernelRead(int fd, void *buf, size_t n);
ssize_t sceKernelWrite(int fd, const void *buf, size_t n);
int sceKernelMkdir(const char *path, int mode);
int sceKernelUnlink(const char *path);
int sceKernelSleep(unsigned int seconds);
#endif
"""


class LauncherExitCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = MAIN_C.read_text(encoding="utf-8")

    def test_main_has_no_nonzero_return(self) -> None:
        offenders = re.findall(r"return\s+[1-9][0-9]*\s*;", self.source)
        self.assertEqual(
            offenders,
            [],
            "a non-zero return from main() shows up on the console as CE-34878-0",
        )

    def test_main_does_not_call_exit_with_failure(self) -> None:
        offenders = re.findall(r"\b(?:exit|_exit|abort)\s*\(\s*[1-9]", self.source)
        self.assertEqual(offenders, [], "never terminate the launcher abnormally")

    def test_removable_storage_roots_are_enumerated(self) -> None:
        for root in ("/mnt/usb0", "/mnt/usb1", "/mnt/ext0", "/mnt/ext1"):
            self.assertIn(root, self.source, f"{root} must be probed")
        self.assertIn("find_writable_usb_dir", self.source)

    def test_missing_storage_is_not_fatal(self) -> None:
        self.assertNotIn(
            "ensure_usb_dir() != 0",
            self.source,
            "the old fatal path must not come back",
        )
        self.assertIn("no writable removable storage", self.source)


class LauncherSyntaxTest(unittest.TestCase):
    def test_compiles_with_wall_wextra(self) -> None:
        compiler = shutil.which("gcc") or shutil.which("clang")
        if compiler is None:
            self.skipTest("no host C compiler available")

        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = Path(tmp) / "orbis"
            stub_dir.mkdir()
            (stub_dir / "libkernel.h").write_text(STUB_LIBKERNEL, encoding="utf-8")
            proc = subprocess.run(
                [
                    compiler,
                    "-fsyntax-only",
                    "-std=gnu11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wno-unused-parameter",
                    f"-I{tmp}",
                    str(MAIN_C),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
