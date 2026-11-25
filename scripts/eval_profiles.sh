#!/usr/bin/env bash
# Evaluate per-profile models against the untuned baseline and the gate, on a machine that has the
# Needle engine (the engine binary is platform specific, so this does not run on the training pod).
#
# Usage: scripts/eval_profiles.sh <dir with hela-needle3-<profile>.cact> [profile ...]
# Env:   ENGINE      path to the needle3 engine binary           (required)
#        BASE_MODEL  path to the shipped needle3.cact             (required, the baseline)
#        TIMEOUT     seconds per engine call (default 60)
#        SYSTEM_MODE profile (default) passes the profile's system text like the installer does;
#                    none passes no system text. Needle's answers change with the system text and the
#                    training rows have none, so run both and ship whichever scores better.
#
# For each profile: build its dataset, score the shipped model once (eval/baselines/<profile>.json,
# reused later), score the tuned model, and run the gate. The profile's own system text
# (data/catalog/profiles/<profile>.txt) is passed to the engine, as the installer does at run time.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
: "${ENGINE:?set ENGINE to the needle3 engine binary}"
: "${BASE_MODEL:?set BASE_MODEL to the shipped needle3.cact}"
DIR="${1:?directory with hela-needle3-<profile>.cact}"
shift || true
TIMEOUT="${TIMEOUT:-60}"
CATALOG=data/catalog/hela-stack-tools.json
if [ "$#" -gt 0 ]; then PROFILES="$*"; else
  PROFILES="$(for f in "$DIR"/hela-needle3-*.cact; do b="$(basename "$f" .cact)"; echo "${b#hela-needle3-}"; done)"
fi
mkdir -p eval/baselines eval/candidates
printf '%-16s %8s %8s %8s %8s  %s\n' profile "choose" "base" "match" "regress" verdict
status=0
for P in $PROFILES; do
  OUT="data/build/$P"
  python -m hela_needle build-data --catalog "$CATALOG" --profile "$P" --out "$OUT" >/dev/null
  SYS="data/catalog/profiles/$P.txt"
  [ -f "$SYS" ] || SYS=data/catalog/hela-system.txt
  SYSARGS=(--system "$SYS")
  TAG=""
  if [ "${SYSTEM_MODE:-profile}" = "none" ]; then SYSARGS=(); TAG=".nosystem"; fi
  if [ ! -f "eval/baselines/$P$TAG.json" ]; then
    python -m hela_needle eval --eval "$OUT/eval.jsonl" --engine "$ENGINE" --model "$BASE_MODEL" "${SYSARGS[@]}" --timeout "$TIMEOUT" --out "eval/baselines/$P$TAG.json" >/dev/null
  fi
  python -m hela_needle eval --eval "$OUT/eval.jsonl" --engine "$ENGINE" --model "$DIR/hela-needle3-$P.cact" "${SYSARGS[@]}" --timeout "$TIMEOUT" --out "eval/candidates/$P$TAG.json" >/dev/null
  if python -m hela_needle gate --candidate "eval/candidates/$P$TAG.json" --baseline "eval/baselines/$P$TAG.json" >"eval/candidates/$P$TAG.gate.txt" 2>&1; then v=PASS; else v=FAIL; status=1; fi
  python3 - "$P$TAG" "$v" <<'PY'
import json, sys
p, v = sys.argv[1], sys.argv[2]
c = json.load(open(f"eval/candidates/{p}.json")); b = json.load(open(f"eval/baselines/{p}.json"))
f = lambda x: "-" if x is None else f"{x:.3f}"
print(f"{p:<16} {f(c.get('choose_tool_acc')):>8} {f(b.get('choose_tool_acc')):>8} {f(c.get('args_match')):>8} {f(c.get('regression_tool_acc')):>8}  {v}")
PY
done
exit $status
