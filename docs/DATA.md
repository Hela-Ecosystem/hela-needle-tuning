# Data sources and rules

Every training row is built by `python -m hela_needle build-data` from seed files in `data/seed/`. The builder wraps each (task, tool, arguments) in the runtime's two-stage prompts, samples a realistic shortlist, scrubs paths and secrets, and fails on any unknown tool or invalid arguments.

| Seed file | Source | Split | Notes |
|-----------|--------|-------|-------|
| `core.jsonl` | hand-written | hash | First seeds and audit regressions, including the pinned shortlist that reproduces the original failure. |
| `expanded.jsonl` | `scripts/expand_seeds.py` (templates) | hash | 22 tools, repetitive phrasing. Deterministic. |
| `eval_hand.jsonl` | hand-written, varied wording | **eval** | The independent test set: negatives, inactive-cell tasks, membrane look-alikes, history cases. Never train on it. |
| `claude_core.jsonl` | written by Claude | train | Casual, Indonesian and typo'd wording across all active cells. |
| `claude_history.jsonl` | written by Claude | train | Multi-step rows: next step after success, `done` after success, a different action after an error. |
| `claude_negatives.jsonl` | written by Claude | train | Finished, off-topic, and tasks that need the inactive phone or Blender cells. |
| `generated_*.jsonl` | `cactus generate-data` via OpenRouter free models, imported with `import-generated` | train | Model is whichever free model OpenRouter routed to; provenance is the file label only. |

## Rules

- **The eval is frozen.** It is `eval_hand.jsonl` plus the hash portion of `core` and `expanded`. All other sources are forced to `train`, so adding data never changes the eval or invalidates `eval/baseline.json`. If the eval must change, re-run the baseline in the same commit.
- **No real session data.** Tasks come from the catalog, hand-written seeds and model-generated text. Real usage can be added later only after scrubbing and review.
- **Free models only for generation.** `scripts/generate_chunks.py` refuses non-free models without `--allow-paid`.
- **Claude-written rows:** the owner approved Claude writing training samples. Anthropic's terms restrict using outputs to build competing models; the intended use here (a router for the owner's own agent) is believed fine, but the owner decides this before any model is published, because publishing is what makes the data's provenance matter to others. The provenance is stated in `NOTICE` and the model card.
- **"Done" and "no tool applies"** currently share the `done` answer. Revisit if the runtime needs them to differ.

## Coverage tracking and profiles

- `docs/COVERAGE.md` (generated, committed) lists, per cell, profile and source file, how many tools have training rows, and names every tool with none or fewer than 3. Regenerate it with `python -m hela_needle coverage` whenever seeds or the catalog change, and read it before each training run. Each pod run also stores its own `coverage.md` next to the model.
- **Profile awareness.** `data/catalog/profiles.json` is parsed from the runtime's profile texts. Each row picks one profile whose cells include the target tool, and its candidate shortlist is drawn only from that profile's cells. Tasks that need a cell some profiles lack (`"inactive_cell": "receptor"`) pick a profile where it is inactive and are answered with "none". Seed lines may pin a `profile`.
- **Frozen shortlists.** Each row's randomness is seeded from its own task and history, so adding or reordering other seeds never changes an existing row.
- The profile text itself reaches the engine through `--system` at run time but is not part of Cactus training rows; whether that matters is an open experiment (see `docs/PLAN.md`).

## Refreshing

1. Export the live runtime's tool list (the bundled snapshot predates tools such as `hela_genome_list_missions`) and replace `data/catalog/hela-stack-tools.json`.
2. `build-data` will fail on any seed naming a missing tool; fix or drop those lines.
3. Re-run the baseline on the frozen eval.

## Automatic import

`scripts/sync_generated.sh <raw dir>` imports finished generation chunks, rebuilds, and pushes, but only if the frozen eval still hashes to `eval/frozen.sha256`, the secret check is clean and the tests pass. When the eval is changed on purpose, regenerate the baseline and update `eval/frozen.sha256` in the same commit.
