#!/usr/bin/env bash
# Upload every file in a run directory to a release of the PRIVATE artifacts repo.
#
# Usage: GH_TOKEN=... scripts/upload_release.sh <run_dir> <tag>
# The token needs Contents: write on hela-needle-runs only (fine-grained, short expiry).
# This is STAGING: raw run output goes to the private repo, and this script refuses any public
# repository. Models that pass the gate are published separately with scripts/publish_models.sh.
set -euo pipefail

: "${GH_TOKEN:?set GH_TOKEN (fine-grained, Contents: write, this repo only)}"
REPO="${REPO:-Hela-Ecosystem/hela-needle-runs}"
DIR="${1:?run directory}"
TAG="${2:?release tag}"

api() { curl -fsS -H "Authorization: Bearer ${GH_TOKEN}" -H "Accept: application/vnd.github+json" "$@"; }

# Releases of a public repo are public, and the weights license is unresolved.
PRIVATE="$(api "https://api.github.com/repos/${REPO}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("private"))')"
if [ "$PRIVATE" != "True" ] && [ "${ALLOW_PUBLIC_RELEASE:-0}" != "1" ]; then
  echo "refusing to upload: ${REPO} is not private (set ALLOW_PUBLIC_RELEASE=1 to override)" >&2
  exit 2
fi

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
