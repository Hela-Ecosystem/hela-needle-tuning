#!/usr/bin/env bash
# Run ON the rented GPU pod. Builds data, fine-tunes, exports a .cact, records
# what it cost to do so. Nothing here talks to RunPod's API or holds an account
# key, and it never terminates the pod: copy the results back, then terminate
# the pod yourself (stopped pods can still bill for disk).
#
# Not yet run. First real use should be a short dry run (EPOCHS=1) to record the
# true hardware needs and wall time in docs/TRAINING.md.
#
# Usage on the pod (CUDA template with python3.10+, git, nvidia-smi):
#   export GH_TOKEN=<read-only token for Hela-Ecosystem/hela-needle-tuning>
#   curl -fsSL -H "Authorization: Bearer $GH_TOKEN" \
#     https://raw.githubusercontent.com/Hela-Ecosystem/hela-needle-tuning/main/scripts/runpod_train.sh -o runpod_train.sh
#   bash runpod_train.sh
#
# Env: EPOCHS (default 3), BRANCH (default main), EXTRA_FINETUNE_ARGS, EXTRA_BUILD_ARGS.
set -euo pipefail

: "${GH_TOKEN:?set GH_TOKEN to a read-only token for the repo}"
EPOCHS="${EPOCHS:-3}"
BRANCH="${BRANCH:-main}"
WORK="${WORK:-/workspace/needle-run}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"

command -v nvidia-smi >/dev/null || { echo "no GPU visible (nvidia-smi missing)" >&2; exit 1; }
mkdir -p "$WORK" && cd "$WORK"

# The token is only used for this clone and is not written to the remote URL.
if [ ! -d repo ]; then
  git -c "http.extraHeader=Authorization: Bearer ${GH_TOKEN}" clone --depth 1 --branch "$BRANCH" \
    https://github.com/Hela-Ecosystem/hela-needle-tuning.git repo
fi
cd repo
SHA="$(git rev-parse --short HEAD)"
RUN_DIR="$PWD/runs/$RUN_ID"
mkdir -p "$RUN_DIR"

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
  --cells mitosis membrane nucleus genome enzyme cytosol ribosome | tee "$RUN_DIR/build-data.log"
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

cat <<MSG

Done. Copy these back, then TERMINATE the pod:
  $RUN_DIR/hela-needle3.cact
  $RUN_DIR/meta.json  $RUN_DIR/finetune.log  $RUN_DIR/build.log
Then on the machine with the Needle engine:
  python -m hela_needle eval --engine <needle3> --model hela-needle3.cact --system data/catalog/hela-system.txt --out eval/candidate.json
  python -m hela_needle gate --candidate eval/candidate.json
MSG
