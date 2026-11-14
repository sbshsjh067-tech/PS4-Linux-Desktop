#!/usr/bin/env bash
# Mirror the already-published fPKG release asset to https://tmpfiles.org and
# publish the resulting URL back into the release (body + TMPFILES-URL.txt).
#
# Hard rules honoured here:
#   * nothing is rebuilt - the bytes come from the release asset;
#   * the file is uploaded verbatim (`curl -F file=@...`), never re-compressed
#     or repacked;
#   * the upload is only reported as successful after the API answered, the
#     file page loads and the direct download returns HTTP 200 with a
#     Content-Length equal to the local size.
set -euo pipefail

TAG="${TAG:?TAG is required}"
ASSET="${ASSET:?ASSET is required}"
SHA_EXPECTED="${SHA_EXPECTED:?SHA_EXPECTED is required}"
SIZE_EXPECTED="${SIZE_EXPECTED:?SIZE_EXPECTED is required}"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/download"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }

log "downloading $ASSET from release $TAG"
gh release download "$TAG" -R "$REPO" --pattern "$ASSET" --dir "$WORK/download" --clobber
PKG="$WORK/download/$ASSET"
[[ -f "$PKG" ]] || { log "FATAL: $ASSET missing after download"; exit 1; }

SIZE="$(stat -c %s "$PKG")"
SHA="$(sha256sum "$PKG" | cut -d' ' -f1)"
log "size=$SIZE sha256=$SHA"
if [[ "$SIZE" != "$SIZE_EXPECTED" ]]; then
    log "FATAL: size $SIZE != expected $SIZE_EXPECTED"; exit 1
fi
if [[ "$SHA" != "$SHA_EXPECTED" ]]; then
    log "FATAL: sha256 $SHA != expected $SHA_EXPECTED"; exit 1
fi
log "integrity OK (byte-identical to the verified build output)"

log "uploading to https://tmpfiles.org/api/v1/upload"
RESP="$WORK/upload.json"
CODE="$(curl -sS -o "$RESP" -w '%{http_code}' --max-time 600 \
    -F "file=@$PKG;filename=$ASSET" https://tmpfiles.org/api/v1/upload || true)"
log "http_code=$CODE"
cat "$RESP" >&2 || true
if [[ "$CODE" != "200" ]]; then
    log "FATAL: tmpfiles.org returned HTTP $CODE"
    echo "::error title=tmpfiles upload::HTTP $CODE from tmpfiles.org"
    exit 1
fi

PAGE_URL="$(python3 - "$RESP" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
url = (data.get("data") or {}).get("url") or ""
if not url.startswith("http"):
    raise SystemExit("no url in the API answer")
print(url)
PY
)" || { log "FATAL: could not parse a URL from the API answer"; exit 1; }

# tmpfiles.org does not serve /dl/<id>/<name> directly (it 302s back to the
# page); the real signed download link -- /dl/<token>/<id>/<name> -- is inside
# the landing page. Extract it instead of guessing.
log "fetching the landing page to read the signed download link"
PAGE_CODE="$(curl -sS -o "$WORK/page.html" -w '%{http_code}' -L --max-time 90 \
    -A 'Mozilla/5.0 (delivery-check)' "$PAGE_URL" || true)"
log "page http=$PAGE_CODE"
grep -q "$ASSET" "$WORK/page.html" || log "WARN: the asset name was not found in the page HTML"

EXPIRES="$(python3 - "$WORK/page.html" <<'PY'
import re, sys
html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
text = re.sub(r"<[^>]+>", " ", html)
m = re.search(r"File expires in ([0-9]+) minutes", text)
print(m.group(1) if m else "unknown")
PY
)"

DIRECT_URL="$(python3 - "$WORK/page.html" <<'PY'
import re, sys
html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
links = [l for l in re.findall(r'href=["\']([^"\']+)["\']', html) if "/dl/" in l]
if links:
    link = links[0]
    print(link if link.startswith("http") else "https://tmpfiles.org" + link)
else:
    print("")
PY
)"
log "page=$PAGE_URL"
log "direct=$DIRECT_URL"
log "expires_in_minutes=$EXPIRES"

# Strongest check available: pull the file back through the public link and
# compare it byte-for-byte with what we uploaded.
DL_SHA="unknown"
DL_SIZE="0"
DL_CODE="none"
STATUS="page-only (no /dl/ link found in the page)"
if [[ -n "$DIRECT_URL" ]]; then
    log "downloading the delivered file back from tmpfiles.org"
    DL_CODE="$(curl -sSL --max-time 900 -A 'Mozilla/5.0 (delivery-check)' \
        -e "$PAGE_URL" -o "$WORK/redownload.pkg" -w '%{http_code}' "$DIRECT_URL" || echo 000)"
    if [[ -s "$WORK/redownload.pkg" ]]; then
        DL_SIZE="$(stat -c %s "$WORK/redownload.pkg")"
        DL_SHA="$(sha256sum "$WORK/redownload.pkg" | cut -d' ' -f1)"
        log "redownloaded http=$DL_CODE size=$DL_SIZE sha256=$DL_SHA"
        if [[ "$DL_SHA" == "$SHA" && "$DL_SIZE" == "$SIZE" ]]; then
            STATUS="verified (downloaded from the public link and byte-identical)"
        else
            STATUS="ROUND-TRIP MISMATCH (served sha256=$DL_SHA size=$DL_SIZE)"
        fi
    else
        STATUS="direct link returned $DL_CODE with an empty body"
    fi
fi

DL_LEN="$DL_SIZE"
printf '%s\n' \
    "url=$PAGE_URL" \
    "direct_url=$DIRECT_URL" \
    "size=$SIZE" \
    "sha256=$SHA" \
    "page_http=$PAGE_CODE" \
    "direct_http=${DL_CODE:-none}" \
    "direct_content_length=${DL_LEN:-unknown}" \
    "download_sha256=$DL_SHA" \
    "download_size=$DL_SIZE" \
    "expires_in_minutes=$EXPIRES" \
    "status=$STATUS" \
    > "$WORK/TMPFILES-URL.txt"
cat "$WORK/TMPFILES-URL.txt" >&2

gh release upload "$TAG" "$WORK/TMPFILES-URL.txt" -R "$REPO" --clobber

gh release view "$TAG" -R "$REPO" --json body -q .body > "$WORK/body.md" || : > "$WORK/body.md"
python3 - "$WORK/body.md" "$PAGE_URL" "$DIRECT_URL" "$SIZE" "$SHA" "$STATUS" \
        "${DL_CODE:-none}" "${DL_LEN:-unknown}" "$DL_SHA" "$DL_SIZE" "$EXPIRES" <<'PY'
import re, sys

body_path, page, direct, size, sha, status, code, clen, dl_sha, dl_size, expires = sys.argv[1:12]
body = open(body_path, encoding="utf-8").read() if body_path else ""
body = re.split(r"\n## tmpfiles\.org mirror\n", body)[0].rstrip()
body += "\n\n## tmpfiles.org mirror\n\n"
body += "| field | value |\n|---|---|\n"
body += f"| page | {page} |\n"
body += f"| direct download | {direct} |\n"
body += f"| size | {size} bytes |\n"
body += f"| sha256 | `{sha}` |\n"
body += f"| direct HTTP | {code} |\n"
body += f"| direct content-length | {clen} |\n"
body += f"| expires in (minutes) | {expires} |\n"
body += f"| re-download size | {dl_size} bytes |\n"
body += f"| re-download sha256 | `{dl_sha}` |\n"
body += f"| status | {status} |\n"
open(body_path, "w", encoding="utf-8").write(body)
print(body[-600:])
PY

gh release edit "$TAG" -R "$REPO" --notes-file "$WORK/body.md"

echo "::notice title=tmpfiles-url::${PAGE_URL}"
echo "::notice title=tmpfiles-direct::${DIRECT_URL} (http=${DL_CODE:-none} content-length=${DL_LEN:-unknown})"
echo "::notice title=tmpfiles-file::size=${SIZE} sha256=${SHA} status=${STATUS}"
echo "::notice title=tmpfiles-roundtrip::downloaded size=${DL_SIZE} sha256=${DL_SHA}"
if [[ "$STATUS" == ROUND-TRIP* || "$STATUS" == "direct link"* || "$STATUS" == "page-only"* ]]; then
    echo "::error title=tmpfiles delivery::${STATUS}"
    exit 1
fi
