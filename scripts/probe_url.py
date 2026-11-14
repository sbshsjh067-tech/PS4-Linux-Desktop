#!/usr/bin/env python3
"""Probe tmpfiles.org URL forms and report, as one-line annotations, exactly what
each form serves (status, content-type, length, sha256, first bytes)."""

from __future__ import annotations

import hashlib
import sys
import urllib.error
import urllib.request


def probe(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (probe)"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read()
            status = resp.status
            ctype = resp.headers.get("Content-Type", "?")
            clen = resp.headers.get("Content-Length", "?")
            cdisp = resp.headers.get("Content-Disposition", "?")
            final = resp.geturl()
    except urllib.error.HTTPError as exc:  # pragma: no cover - diagnostic path
        body = exc.read()
        status = exc.code
        ctype = exc.headers.get("Content-Type", "?") if exc.headers else "?"
        clen = "?"
        cdisp = "?"
        final = url
    except Exception as exc:  # pragma: no cover - diagnostic path
        return f"{url} -> EXCEPTION {exc.__class__.__name__}: {exc}"

    digest = hashlib.sha256(body).hexdigest()
    head = body[:160].decode("utf-8", "replace").replace("\n", " ").replace("\r", " ")
    return (
        f"{url} -> http={status} type={ctype} len={clen} cd={cdisp} "
        f"final={final} sha256={digest} first160={head!r}"
    )


def main() -> int:
    for arg in sys.argv[1:]:
        line = probe(arg)
        print("::notice title=probe::" + line.replace("%", "%25").replace("\n", "%0A"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
