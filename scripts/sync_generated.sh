#!/bin/sh
# Import finished `cactus generate-data` chunks, validate, and push - only when it is safe.
#
# Usage: scripts/sync_generated.sh <dir with raw_*.jsonl>
#
# Safety gates (any failure aborts without committing):
#   - the frozen eval must hash to eval/frozen.sha256 (generated rows are train-only);
#   - build-data must succeed against the current catalog;
#   - check-secrets must be clean and the unit tests must pass.
# Nothing is committed when nothing changed. Raw chunks stay outside the repo.
set -eu
cd "$(dirname "$0")/.."
RAW="${1:?directory with raw_*.jsonl}"
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
CAT=data/catalog/hela-stack-tools.json

git pull --rebase -q origin main

for f in "$RAW"/raw_*.jsonl; do
  [ -s "$f" ] || continue
  n="$(basename "$f" .jsonl | sed 's/^raw_//')"
  python3 -m hela_needle import-generated "$f" --catalog "$CAT" --source openrouter-free --out "data/seed/generated_$n.jsonl" >/dev/null
done

python3 -m hela_needle build-data --catalog "$CAT" >/dev/null
if [ "$(sha256sum data/build/eval.jsonl | cut -d' ' -f1)" != "$(cut -d' ' -f1 eval/frozen.sha256)" ]; then
  echo "eval changed; refusing to commit" >&2
  exit 3
fi
python3 -m hela_needle check-secrets data/build/train.jsonl data/build/eval.jsonl >/dev/null || { echo "secret check failed" >&2; exit 4; }
python3 -m unittest discover -s tests >/dev/null 2>&1 || { echo "tests failed" >&2; exit 5; }
python3 -m hela_needle coverage --catalog "$CAT" >/dev/null

find . -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
git add -A
if git diff --cached --quiet; then
  echo "nothing new"
  exit 0
fi
git -c user.name=1999AZZAR -c user.email=48999412+1999AZZAR@users.noreply.github.com commit -q -m "Import generated seeds (auto); refresh coverage"
git push -q origin main
echo "pushed $(git rev-parse --short HEAD): $(wc -l < data/build/train.jsonl) train rows"
