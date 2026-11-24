# Training procedure

Training uses the upstream Cactus CLI (`cactus-compute[train]`). The commands below come from the upstream `llms.txt` in `cactus-compute/cactus`; **none have been run in this repo yet**. Treat them as the plan, and correct this file the first time one behaves differently.

```bash
pip install "cactus-compute[train]"      # add [gpu] for CUDA or [metal] for Apple Silicon

python -m hela_needle build-data --catalog <catalog.json> --cells <active cells>
python -m hela_needle check-secrets data/build/train.jsonl data/build/eval.jsonl

cactus finetune data/build/train.jsonl --epochs 3
cactus build checkpoints/needle3.safetensors \
  --lora checkpoints/needle_lora.safetensors --out build/hela-needle3.cact

python -m hela_needle eval --engine <needle3> --model build/hela-needle3.cact \
  --system <hela-system.txt> --out eval/candidate.json
python -m hela_needle gate --candidate eval/candidate.json
```

`train.jsonl` rows use the Cactus format `{"query", "tools", "answers"}`. `eval.jsonl` keeps a `meta` field for scoring.

## Known facts (upstream docs)

- Fine-tuning is LoRA on the frozen base at the full 20 layers, merged at export. `cactus build --layers N` exports a smaller rung (2 to 20).
- Local training is 4-bit. The shipped `needle3.cact` is 2-bit, quantised on the Cactus Platform. **Our baseline was measured on the shipped 2-bit weights, a locally built candidate is 4-bit**, so the comparison is not apples to apples. It favours the candidate on size-for-quality, but record the difference with every score.
- `cactus build --lora` does not include the confidence head, so `confidence` is absent from engine output. The runtime treats it as optional, but re-check after the first real build.
- Checkpoints and adapters must be `.safetensors`; pickle is refused.

## Not documented upstream (find out before relying on it)

- Hardware needs for local training (RAM, VRAM, disk).
- License of the Needle weights. The code repo is Apache 2.0, the weights come from separate Hugging Face repos with no stated license in what we read. **Resolve this before publishing any tuned weights.**
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
