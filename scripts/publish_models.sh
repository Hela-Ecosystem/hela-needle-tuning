#!/usr/bin/env bash
# Publish gated per-profile Needle models as a PUBLIC release of this repo. Maintainers only.
#
# Usage:
#   scripts/publish_models.sh --run <tag in the private staging repo> [--profiles "a b"] [--system-mode profile|none] [--yes]
#   scripts/publish_models.sh --from-dir <folder with hela-needle3-<profile>.cact> ...
#
# Without --yes it only checks and prints what would be published (a dry run).
#
# A profile is published only if:
#   - the file being uploaded has the sha256 recorded when it was evaluated (scripts/eval_profiles.sh),
#   - it passes the release gate against that profile's own baseline,
#   - the working tree is clean and pushed, so the manifest's commit is public.
# The release carries the Apache-2.0 LICENSE and the NOTICE required for redistributing a derivative
# of Needle 3. Needs the GitHub CLI (`gh`) logged in with write access to this repo.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1

PUBLIC_REPO="${PUBLIC_REPO:-Hela-Ecosystem/hela-needle-tuning}"
STAGING_REPO="${RUNS_REPO:-Hela-Ecosystem/hela-needle-runs}"
RUN=""; DIR=""; PROFILES=""; MODE="profile"; YES=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --run) RUN="$2"; shift 2 ;;
    --from-dir) DIR="$2"; shift 2 ;;
    --profiles) PROFILES="$2"; shift 2 ;;
    --system-mode) MODE="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$RUN" ] || [ -n "$DIR" ] || { echo "give --run <staging tag> or --from-dir <folder>" >&2; exit 2; }

if [ -n "$RUN" ]; then
  DIR="$(mktemp -d)"
  gh release download "$RUN" -R "$STAGING_REPO" -D "$DIR" -p 'hela-needle3-*.cact' -p 'meta-*.json'
fi
if [ -z "$PROFILES" ]; then
  PROFILES="$(for f in "$DIR"/hela-needle3-*.cact; do b="$(basename "$f" .cact)"; echo "${b#hela-needle3-}"; done | tr '\n' ' ')"
fi

SHA="$(git rev-parse --short HEAD)"
CATALOG_SHA="$(sha256sum data/catalog/hela-stack-tools.json | cut -d' ' -f1)"
TAG="models-$(date -u +%Y%m%d)-$SHA"
PLAN="$(mktemp)"

# shellcheck disable=SC2086
python3 -m hela_needle publish-plan --models-dir "$DIR" --profiles $PROFILES --tag "$TAG" \
  --public-repo "$PUBLIC_REPO" --system-mode "$MODE" --git-sha "$SHA" --catalog-sha "$CATALOG_SHA" --out "$PLAN"

if [ "$YES" != "1" ]; then
  echo "dry run: nothing published. Re-run with --yes to publish release $TAG to $PUBLIC_REPO."
  exit 0
fi

git fetch -q origin main
if [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "refusing: the working tree must be clean and equal to origin/main so the published commit exists" >&2
  exit 3
fi

NOTES="$(mktemp)"
python3 - "$PLAN" > "$NOTES" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
print("Per-profile fine-tuned Needle 3 models for HeLa. Fine-tuned derivatives of Needle 3 by Cactus Compute (Apache License 2.0); see NOTICE and the model card.\n")
print("| Profile | File | Size | sha256 |\n|---|---|---:|---|")
for e in plan["entries"]:
    print(f"| {e['profile']} | `{e['file']}` | {e['size'] / 1e6:.1f} MB | `{e['sha256']}` |")
print("\nEach model passed the release gate against the untuned model on that profile's frozen eval. Verify the checksum before use; `models/manifest.json` lists scores and provenance.")
PY

FILES=()
for P in $PROFILES; do FILES+=("$DIR/hela-needle3-$P.cact"); done
gh release create "$TAG" -R "$PUBLIC_REPO" --title "Needle models $TAG" --notes-file "$NOTES" \
  "${FILES[@]}" "models/LICENSE#LICENSE" "NOTICE#NOTICE"

python3 -m hela_needle manifest-apply --plan "$PLAN" --manifest models/manifest.json
git add models/manifest.json
git -c user.name="${GIT_AUTHOR_NAME:-$(git config user.name)}" -c user.email="${GIT_AUTHOR_EMAIL:-$(git config user.email)}" \
  commit -q -m "Publish per-profile models $TAG: ${PROFILES}"
git push -q origin main
echo "published https://github.com/$PUBLIC_REPO/releases/tag/$TAG"
