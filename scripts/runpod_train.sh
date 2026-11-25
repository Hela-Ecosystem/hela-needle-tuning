#!/usr/bin/env bash
# Run ON the rented GPU pod. Builds data, fine-tunes, exports a .cact, records
# what it cost to do so. Nothing here talks to RunPod's API or holds an account
# key, and it never terminates the pod: copy the results back, then terminate
# the pod yourself (stopped pods can still bill for disk).
#
# Not yet run. First real use should be a short dry run (EPOCHS=1) to record the
# true hardware needs and wall time in docs/TRAINING.md.
#
# One line on a fresh pod (runpod/base cuda12.9 on Ubuntu 24.04 is what we plan to use):
#   export GH_TOKEN=<fine-grained token: hela-needle-runs ONLY, Contents: write, 1-day expiry>; curl -fsSL https://raw.githubusercontent.com/Hela-Ecosystem/hela-needle-tuning/main/scripts/runpod_train.sh -o t.sh && bash t.sh
#
# This code repo is public (no token needed to read it). The result is uploaded as a
# release named run-<id> (model, meta, logs) to the PRIVATE repo Hela-Ecosystem/hela-needle-runs.
# A failed run uploads its logs as run-<id>-failed so they can be read without pasting.
# The script only terminates the pod if AUTO_TERMINATE=1, and only after a successful upload.
#
# Env: EPOCHS (default 3), BRANCH (default main), AUTO_TERMINATE (default 0),
#      EXTRA_FINETUNE_ARGS, EXTRA_BUILD_ARGS.
set -euo pipefail

: "${GH_TOKEN:?set GH_TOKEN (fine-grained token, hela-needle-runs only, Contents: write)}"
set +x  # never trace commands that carry the token
EPOCHS="${EPOCHS:-3}"
BRANCH="${BRANCH:-main}"
WORK="${WORK:-/workspace/needle-run}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"

command -v nvidia-smi >/dev/null || { echo "no GPU visible (nvidia-smi missing)" >&2; exit 1; }
mkdir -p "$WORK" && cd "$WORK"

# runpod/base is a minimal Ubuntu image: make sure git, pip and venv exist.
if ! command -v git >/dev/null || ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -m pip --version >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq git python3-venv python3-pip
fi

# The code repo is public: clone without credentials so the token is never used for it.
if [ ! -d repo ]; then
  git clone --depth 1 --branch "$BRANCH" https://github.com/Hela-Ecosystem/hela-needle-tuning.git repo
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
    echo "run failed (exit $rc); uploading logs for diagnosis" >&2
    bash scripts/upload_release.sh "$RUN_DIR" "run-${RUN_ID}-failed" || true
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
python -m unittest discover -s tests
python -m hela_needle build-data --catalog data/catalog/hela-stack-tools.json \
  --cells mitosis membrane nucleus genome enzyme cytosol ribosome phenotype | tee "$RUN_DIR/build-data.log"
python -m hela_needle check-secrets data/build/train.jsonl data/build/eval.jsonl

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | tee "$RUN_DIR/gpu.txt"

START=$(date +%s)
# shellcheck disable=SC2086
cactus finetune data/build/train.jsonl --epochs "$EPOCHS" \
  --checkpoint-dir checkpoints --out checkpoints/needle_lora.safetensors \
  ${EXTRA_FINETUNE_ARGS:-} 2>&1 | tee "$RUN_DIR/finetune.log"
MID=$(date +%s)

# shellcheck disable=SC2086
cactus build checkpoints/needle3.safetensors --lora checkpoints/needle_lora.safetensors \
  --out "$RUN_DIR/hela-needle3.cact" ${EXTRA_BUILD_ARGS:-} 2>&1 | tee "$RUN_DIR/build.log"
END=$(date +%s)

cat > "$RUN_DIR/meta.json" <<EOF
{
  "run_id": "$RUN_ID",
  "git_sha": "$SHA",
  "epochs": $EPOCHS,
  "gpu": "$(head -1 "$RUN_DIR/gpu.txt")",
  "finetune_seconds": $((MID - START)),
  "build_seconds": $((END - MID)),
  "train_rows": $(wc -l < data/build/train.jsonl),
  "eval_rows": $(wc -l < data/build/eval.jsonl)
}
EOF
cat "$RUN_DIR/meta.json"

trap - EXIT
if bash scripts/upload_release.sh "$RUN_DIR" "run-${RUN_ID}"; then
  if [ "${AUTO_TERMINATE:-0}" = "1" ] && command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ]; then
    echo "uploaded; terminating pod ${RUNPOD_POD_ID}"
    runpodctl remove pod "$RUNPOD_POD_ID"
  else
    echo "uploaded. TERMINATE THE POD NOW (billing continues while it exists)."
  fi
else
  cat <<MSG

Upload failed. The model is still on this pod at:
  $RUN_DIR/hela-needle3.cact
Copy it out (runpodctl send / scp) BEFORE terminating the pod.
MSG
  exit 1
fi
