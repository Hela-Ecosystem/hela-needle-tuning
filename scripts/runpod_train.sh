#!/usr/bin/env bash
# Train Needle models on a rented (or any NVIDIA) GPU machine: one dedicated model per HeLa profile.
# Builds the data, fine-tunes, exports a .cact per profile, records timings and coverage,
# and (optionally) uploads everything to a PRIVATE GitHub repo. It never terminates the pod:
# copy results out, then terminate the pod yourself (stopped pods can still bill for disk).
#
# One line on a fresh pod (runpod/base cuda12.9 on Ubuntu 24.04 works; any CUDA 12 image does):
#
#   export GH_TOKEN=<fine-grained token: your PRIVATE results repo only, Contents: write, 1-day expiry>; curl -fsSL https://raw.githubusercontent.com/Hela-Ecosystem/hela-needle-tuning/main/scripts/runpod_train.sh -o t.sh && RUNS_REPO=<you>/<private-repo> PROFILES=dev-workspace bash t.sh
#
# No GitHub at all? Skip the upload and copy the files yourself:
#   curl -fsSL https://raw.githubusercontent.com/Hela-Ecosystem/hela-needle-tuning/main/scripts/runpod_train.sh -o t.sh && NO_UPLOAD=1 bash t.sh
#
# Env:
#   PROFILES        space-separated profile ids, or ALL (default: dev-workspace). See data/catalog/profiles.json.
#   RUNS_REPO       owner/name of the PRIVATE repo to upload to (default Hela-Ecosystem/hela-needle-runs).
#   NO_UPLOAD=1     do not upload; models stay in the printed run directory.
#   GH_TOKEN        needed only for upload; fine-grained, results repo only. Never a broad token.
#   CODE_REPO       code repo to clone (default Hela-Ecosystem/hela-needle-tuning); BRANCH (default main).
#   EPOCHS          default 3.   AUTO_TERMINATE=1 terminates the pod after a successful upload (unverified).
#   LORA_RANK       default 32 (alpha = 2 x rank). VAL_SPLIT default 0.03: the frozen eval is the real test,
#                   so only a sliver of the rows is held out for the loss curve.
#   EXTRA_FINETUNE_ARGS, EXTRA_BUILD_ARGS   passed through to `cactus finetune` / `cactus build`.
set -euo pipefail
set +x  # never trace commands that may carry the token

NO_UPLOAD="${NO_UPLOAD:-0}"
if [ "$NO_UPLOAD" != "1" ]; then
  : "${GH_TOKEN:?set GH_TOKEN (fine-grained token for your private results repo, Contents: write) or run with NO_UPLOAD=1}"
fi
EPOCHS="${EPOCHS:-3}"
LORA_RANK="${LORA_RANK:-32}"
LORA_ALPHA="${LORA_ALPHA:-$((LORA_RANK * 2))}"
VAL_SPLIT="${VAL_SPLIT:-0.03}"
BRANCH="${BRANCH:-main}"
CODE_REPO="${CODE_REPO:-Hela-Ecosystem/hela-needle-tuning}"
RUNS_REPO="${RUNS_REPO:-Hela-Ecosystem/hela-needle-runs}"
WORK="${WORK:-/workspace/needle-run}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"

command -v nvidia-smi >/dev/null || { echo "no GPU visible (nvidia-smi missing)" >&2; exit 1; }
mkdir -p "$WORK" && cd "$WORK"

# Minimal images may lack git, pip or venv.
if ! command -v git >/dev/null || ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -m pip --version >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq git python3-venv python3-pip
fi

# The code repo is public: clone without credentials so the token is never used for it.
if [ ! -d repo ]; then
  git clone --depth 1 --branch "$BRANCH" "https://github.com/${CODE_REPO}.git" repo
fi
cd repo
SHA="$(git rev-parse --short HEAD)"
RUN_DIR="$PWD/runs/$RUN_ID"
mkdir -p "$RUN_DIR"

# On any failure, upload whatever logs exist so the run can be diagnosed remotely.
finish() {
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then
    echo "run failed (exit $rc)" >&2
    if [ "$NO_UPLOAD" != "1" ]; then
      echo "uploading logs for diagnosis" >&2
      REPO="$RUNS_REPO" bash scripts/upload_release.sh "$RUN_DIR" "run-${RUN_ID}-failed" || true
    fi
  fi
  exit "$rc"
}
trap finish EXIT

python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet "cactus-compute[train,gpu]"

# Fail in seconds, not after a billed training run, if JAX cannot see the GPU
# (usually a driver/CUDA mismatch with the JAX wheels). Cactus trains on JAX,
# so the pod image's own PyTorch version is irrelevant.
python - <<'PY'
import sys, jax
devices = jax.devices()
print("python", sys.version.split()[0], "| jax", jax.__version__, "| devices", devices)
if not any(d.platform in ("gpu", "cuda") for d in devices):
    sys.exit("JAX sees no GPU: check the driver in nvidia-smi against the JAX CUDA wheel requirements")
PY

export PYTHONPATH=src
CATALOG=data/catalog/hela-stack-tools.json
python -m unittest discover -s tests

if [ "${PROFILES:-dev-workspace}" = "ALL" ]; then
  PROFILES="$(python -c "import json; print(' '.join(json.load(open('data/catalog/profiles.json'))))")"
fi
PROFILES="${PROFILES:-dev-workspace}"
echo "profiles: $PROFILES" | tee "$RUN_DIR/profiles.txt"

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | tee "$RUN_DIR/gpu.txt"

for P in $PROFILES; do
  echo "=== profile $P"
  OUT="data/build/$P"
  python -m hela_needle build-data --catalog "$CATALOG" --profile "$P" --out "$OUT" | tee "$RUN_DIR/build-data-$P.log"
  python -m hela_needle check-secrets "$OUT/train.jsonl" "$OUT/eval.jsonl"
  python -m hela_needle coverage --catalog "$CATALOG" --out "$RUN_DIR/coverage.md"

  CK="checkpoints/$P"
  mkdir -p "$CK"
  START=$(date +%s)
  # shellcheck disable=SC2086
  cactus finetune "$OUT/train.jsonl" --epochs "$EPOCHS" \
    --lora-rank "$LORA_RANK" --lora-alpha "$LORA_ALPHA" --val-split "$VAL_SPLIT" \
    --checkpoint-dir "$CK" --out "$CK/lora.safetensors" \
    ${EXTRA_FINETUNE_ARGS:-} 2>&1 | tee "$RUN_DIR/finetune-$P.log"
  MID=$(date +%s)

  # Locate the base checkpoint that finetune downloaded (not the adapter).
  BASE=""
  for c in "$CK/needle3.safetensors" "checkpoints/needle3.safetensors"; do
    [ -f "$c" ] && { BASE="$c"; break; }
  done
  [ -n "$BASE" ] || BASE="$(find checkpoints -name '*.safetensors' ! -name '*lora*' | head -1)"
  [ -n "$BASE" ] || { echo "could not find the base checkpoint under checkpoints/" >&2; exit 1; }

  # shellcheck disable=SC2086
  cactus build "$BASE" --lora "$CK/lora.safetensors" \
    --out "$RUN_DIR/hela-needle3-$P.cact" ${EXTRA_BUILD_ARGS:-} 2>&1 | tee "$RUN_DIR/build-$P.log"
  END=$(date +%s)

  cat > "$RUN_DIR/meta-$P.json" <<EOF
{
  "run_id": "$RUN_ID",
  "profile": "$P",
  "git_sha": "$SHA",
  "epochs": $EPOCHS,
  "gpu": "$(head -1 "$RUN_DIR/gpu.txt")",
  "finetune_seconds": $((MID - START)),
  "build_seconds": $((END - MID)),
  "train_rows": $(wc -l < "$OUT/train.jsonl"),
  "eval_rows": $(wc -l < "$OUT/eval.jsonl")
}
EOF
  cat "$RUN_DIR/meta-$P.json"
  rm -rf "$CK"  # free disk before the next profile
done

trap - EXIT
if [ "$NO_UPLOAD" = "1" ]; then
  cat <<MSG

Done. Models are in:
  $RUN_DIR
Copy that folder out (scp / runpodctl send) BEFORE terminating the pod.
Then evaluate each model on a machine with the Needle engine:  scripts/eval_profiles.sh
MSG
  exit 0
fi

if REPO="$RUNS_REPO" bash scripts/upload_release.sh "$RUN_DIR" "run-${RUN_ID}"; then
  if [ "${AUTO_TERMINATE:-0}" = "1" ] && command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ]; then
    echo "uploaded; terminating pod ${RUNPOD_POD_ID}"
    runpodctl remove pod "$RUNPOD_POD_ID"
  else
    echo "uploaded. TERMINATE THE POD NOW (billing continues while it exists)."
  fi
else
  cat <<MSG

Upload failed. The models are still on this pod at:
  $RUN_DIR
Copy them out (runpodctl send / scp) BEFORE terminating the pod.
MSG
  exit 1
fi
