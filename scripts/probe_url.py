#!/usr/bin/env python3
"""Diagnose what tmpfiles.org actually serves: full page text, every link, and
the raw redirect chain of the /dl/ endpoint. One-line annotations only."""

from __future__ import annotations

import http.client
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


def esc(text: str) -> str:
    return text.replace("%", "%25").replace("\r", " ").replace("\n", "%0A")[:1400]


def notice(title: str, text: str) -> None:
    print(f"::notice title={title}::{esc(text)}")


def fetch(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (probe)"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.headers.get("Content-Type", "?"), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "?") if exc.headers else "?", exc.read().decode("utf-8", "replace")


def raw_head(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    conn = http.client.HTTPSConnection(parts.netloc, timeout=60)
    path = parts.path + (("?" + parts.query) if parts.query else "")
    conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0 (probe)", "Range": "bytes=0-15"})
    resp = conn.getresponse()
    out = [f"status={resp.status}"]
    for key in ("Location", "Content-Type", "Content-Disposition", "Content-Range", "Content-Length"):
        value = resp.getheader(key)
        if value:
            out.append(f"{key}={value}")
    out.append("body16=" + resp.read(16).hex())
    conn.close()
    return " ".join(out)


def main() -> int:
    page = sys.argv[1]
    status, ctype, html = fetch(page)
    notice("page-status", f"http={status} type={ctype} bytes={len(html)}")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    notice("page-text", re.sub(r"\s+", " ", text).strip()[:900])
    links = re.findall(r'href=["\']([^"\']+)["\']', html) + re.findall(r'action=["\']([^"\']+)["\']', html)
    notice("page-links", " | ".join(dict.fromkeys(links))[:900])
    for candidate in sys.argv[2:]:
        notice("raw", f"{candidate} -> {raw_head(candidate)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
