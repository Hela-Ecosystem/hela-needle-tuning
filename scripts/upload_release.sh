#!/usr/bin/env bash
# Upload every file in a run directory to a PRIVATE GitHub release of this repo.
#
# Usage: GH_TOKEN=... scripts/upload_release.sh <run_dir> <tag>
# The token needs Contents: write on the repo only (fine-grained, short expiry).
# Weights are never committed to git; releases of a private repo are private.
set -euo pipefail

: "${GH_TOKEN:?set GH_TOKEN (fine-grained, Contents: write, this repo only)}"
REPO="${REPO:-Hela-Ecosystem/hela-needle-tuning}"
DIR="${1:?run directory}"
TAG="${2:?release tag}"

api() { curl -fsS -H "Authorization: Bearer ${GH_TOKEN}" -H "Accept: application/vnd.github+json" "$@"; }

BODY="$(python3 - "$TAG" <<'PY'
import json, sys
print(json.dumps({
    "tag_name": sys.argv[1],
    "name": sys.argv[1],
    "body": "Automated upload from scripts/runpod_train.sh. Weights license is unresolved: do not redistribute.",
    "prerelease": True,
}))
PY
)"

RESP="$(api -X POST "https://api.github.com/repos/${REPO}/releases" -d "$BODY")"
ID="$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

count=0
for f in "$DIR"/*; do
  [ -f "$f" ] || continue
  name="$(basename "$f")"
  api -X POST -H "Content-Type: application/octet-stream" --data-binary @"$f" \
    "https://uploads.github.com/repos/${REPO}/releases/${ID}/assets?name=${name}" >/dev/null
  echo "uploaded ${name} ($(wc -c < "$f") bytes)"
  count=$((count + 1))
done
[ "$count" -gt 0 ] || { echo "nothing to upload in $DIR" >&2; exit 1; }
echo "release: https://github.com/${REPO}/releases/tag/${TAG}"
