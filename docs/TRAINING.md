# Training procedure

## One-line run on a rented pod

Deploy a pod with image `runpod/base:2.1.1-cuda1290-ubuntu2404` on one RTX A5000, open the web terminal and paste:

```bash
export GH_TOKEN=<fine-grained token: hela-needle-runs ONLY, Contents: write, 1-day expiry>; curl -fsSL https://raw.githubusercontent.com/Hela-Ecosystem/hela-needle-tuning/main/scripts/runpod_train.sh -o t.sh && bash t.sh
```

The script installs the tools, builds and scrubs the data, checks that JAX sees the GPU, fine-tunes, exports the `.cact`, and uploads model, `meta.json` and logs to a release `run-<id>` in the **private** repo `Hela-Ecosystem/hela-needle-runs` (a failed run uploads its logs as `run-<id>-failed`). This code repo is public and the uploader refuses to publish to any public repo. It does not terminate the pod unless `AUTO_TERMINATE=1` (unverified: needs `runpodctl` and `RUNPOD_POD_ID` on the pod). Terminate the pod yourself once it prints "uploaded".

The eval and gate run afterwards on the machine with the Needle engine: the engine binary is not in git and our copy is ARM, so it cannot run on an x86 pod. Weights are never committed to git. Training output is staged in the private runs repo; models that pass the gate are published as release assets of this repo with `scripts/publish_models.sh`.


Training uses the upstream Cactus CLI (`cactus-compute[train]`). The commands below come from the upstream `llms.txt` in `cactus-compute/cactus`; **none have been run in this repo yet**. Treat them as the plan, and correct this file the first time one behaves differently.

```bash
pip install "cactus-compute[train]"      # add [gpu] for CUDA or [metal] for Apple Silicon

python -m hela_needle build-data --catalog <catalog.json>
python -m hela_needle check-secrets data/build/train.jsonl data/build/eval.jsonl

cactus finetune data/build/train.jsonl --epochs 3
cactus build checkpoints/needle3.safetensors \
  --lora checkpoints/needle_lora.safetensors --out build/hela-needle3.cact

python -m hela_needle eval --engine <needle3> --model build/hela-needle3.cact \
  --system <hela-system.txt> --out eval/candidate.json
python -m hela_needle gate --candidate eval/candidate.json
```

`train.jsonl` rows use the Cactus format `{"query", "tools", "answers"}`. `eval.jsonl` keeps a `meta` field for scoring.

## Pod image

Cactus trains on JAX, Flax and Optax (`requirements-train.txt`), not PyTorch, so the image's PyTorch version does not matter; any CUDA 12 image with Python 3.10+ works (3.12 is safest).

Official RunPod images (Docker Hub `runpod/base` and `runpod/pytorch`; build files in `github.com/runpod/containers`, read 2026-11-25):

- Tag format: `runpod/pytorch:<release>-cu<CUDA digits>-torch<torch digits>-ubuntu2404`, for example `...-cu1290-torch2130-ubuntu2404` (CUDA 12.9.0, torch 2.13.0). `runpod/base` tags look like `2.1.1-cuda1290-ubuntu2404`.
- CUDA builds: 12.8.1, 12.9.0, 13.0.0, 13.2.0. Torch builds: 2.6.0 up to 2.15.0, but **torch 2.15.0 exists only on the CUDA 13.0 and 13.2 images**, and the cu132 wheels need a CUDA 13 driver (>= 580).
- Not stated in the sources: the Python version, devel vs runtime flavour, minimum driver for CUDA 12 images.
- **First choice: `runpod/base:<release>-cuda1290-ubuntu2404`** (no torch, which we do not use), or the pytorch image with `cu1290` if the template UI only offers those. Avoid the CUDA 13 images until JAX's CUDA 13 support is confirmed; the preflight in `scripts/runpod_train.sh` prints the Python and JAX versions and fails if no GPU is found. `scripts/runpod_train.sh` installs into a fresh virtualenv and fails fast if JAX cannot see the GPU. An RTX A5000 (24 GB, Ampere) is the planned first card; confirm its fit in the M2 dry run and record the result here.

## Known facts (upstream docs)

- Fine-tuning is LoRA on the frozen base at the full 20 layers, merged at export. `cactus build --layers N` exports a smaller rung (2 to 20).
- Local training is 4-bit. The shipped `needle3.cact` is 2-bit, quantised on the Cactus Platform. **Our baseline was measured on the shipped 2-bit weights, a locally built candidate is 4-bit**, so the comparison is not apples to apples. It favours the candidate on size-for-quality, but record the difference with every score.
- `cactus build --lora` does not include the confidence head, so `confidence` is absent from engine output. The runtime treats it as optional, but re-check after the first real build.
- Checkpoints and adapters must be `.safetensors`; pickle is refused.

## Not documented upstream (check before relying on it)

- Hardware needs for local training (RAM, VRAM, disk).
- ~~License of the Needle weights~~ Resolved 2026-11-25: the Needle 3 model repository ships the Apache License 2.0 (`LICENSE`, sha256 `cfc7749b...`, the same file the installer pins) and its model card says `license: apache-2.0`. Redistributing modified weights is permitted with the licence and notice kept; see `NOTICE`.
- Defaults for `--lora-rank`, `--lora-alpha`, `--lr`, `--batch-size`, `--epochs`; recommended dataset size; LoRA target modules.

## Data rules

- `cactus finetune --generate N` and `cactus generate-data` send your tool schemas to an OpenRouter model and spend money. Do not run them without the owner's approval, and never against data that has not passed `check-secrets`.
- Training rows must come from the catalog and seeds, never from raw session transcripts, unless scrubbed and reviewed.

## Scale-up plan

1. Grow the seed set to a few hundred tasks across all active cells, several phrasings per tool, with negatives (`done`, `null`) and "do not modify" read-only phrasings.
2. Add pinned-shortlist regression rows for every production selection mistake.
3. Keep at least 20% of rows (by hash) as eval; do not tune on them.
4. First real run: train, build, eval, gate. Record hardware, wall time and scores here.
5. Publish passing weights as a private release asset and point `NEEDLE_MODEL_PATH` at them on one runtime first.

## Catalog drift

The catalog changes when cells add or rename tools (the bundled asset already lists cells the live runtime does not load). `build-data` fails on any seed that names a missing tool, which is the signal to update the seeds and retrain.
