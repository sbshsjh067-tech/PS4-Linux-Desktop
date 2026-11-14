#!/usr/bin/env python3
"""Turn the external build log into GitHub Actions annotations.

The build pipeline writes a complete transcript to
``artifacts/external/build.log``. On GitHub the job log itself lives on blob
storage, so this script republishes the interesting lines as *workflow
commands* (``::error`` / ``::notice``), which appear as check-run annotations
and can be read over the REST API:

    gh api repos/<owner>/<repo>/check-runs/<id>/annotations

Usage:
    python3 scripts/ci_failure_annotations.py [build.log]

Exit status is always 0 - diagnostics must never mask the real failure.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")
INTERESTING = (
    "[FATAL]",
    "[WARN]",
    "[stderr]",
    "ERROR",
    "Error",
    "error:",
    "failed",
    "Failed",
    "make: ***",
    "No such file",
    "not found",
    "Traceback",
    "Exception",
    "Unhandled",
    "command not found",
    "cannot",
    "undefined reference",
    "errno",
    "  * ",
)


def escape(message: str) -> str:
    """Escape a message for use in a GitHub workflow command."""
    return (
        message.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .strip()[:900]
    )


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "artifacts/external/build.log")

    if not path.is_file():
        print(
            "::error title=External build::build.log missing - "
            "the pipeline stopped before it could log anything"
        )
        return 0

    text = ANSI.sub("", path.read_text(errors="replace"))
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]

    emitted = 0
    for line in lines:
        if not any(token in line for token in INTERESTING):
            continue
        print(f"::error title=build.log::{escape(line)}")
        emitted += 1
        if emitted >= 12:
            break

    if emitted == 0:
        print("::warning title=build.log::no recognised error line found in the transcript")

    print("::notice title=Last pipeline lines::" + escape("\n".join(lines[-12:])))

    stages = [line for line in lines if line.startswith("==========")]
    if stages:
        print("::notice title=Stages reached::" + escape("\n".join(stages[-8:])))

    # The packager's own report is the most reliable source of blocking reasons.
    report = Path("artifacts/external/pkg-report.json")
    if report.is_file():
        try:
            data = json.loads(report.read_text(errors="replace"))
        except json.JSONDecodeError:
            data = {}
        reasons = data.get("blocking_reasons") or []
        if reasons:
            print("::error title=pkg-report blocking reasons::" + escape("\n".join(reasons)))
        prereqs = data.get("prerequisites") or []
        failed = [
            f"{p.get('name')}: {p.get('detail')}"
            for p in prereqs
            if not (p.get("present") and p.get("valid"))
        ]
        if failed:
            print("::error title=pkg-report missing prerequisites::" + escape("\n".join(failed)))

    # Raw tool stderr (dotnet / PkgTool.Core) is the only place runtime errors appear.
    for extra in ("artifacts/external/pkg-build.stderr",):
        path = Path(extra)
        if path.is_file() and path.read_text(errors="replace").strip():
            tail = path.read_text(errors="replace").strip().splitlines()[-25:]
            print(f"::error title={path.name}::" + escape("\n".join(tail)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
