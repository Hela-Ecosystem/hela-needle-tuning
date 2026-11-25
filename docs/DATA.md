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
- **Claude-written rows:** the owner approved Claude writing training samples. Anthropic's terms restrict using outputs to build competing models; the intended use here (a router for the owner's own agent) is believed fine, but the owner should confirm before any weights are distributed.
- **"Done" and "no tool applies"** currently share the `done` answer. Revisit if the runtime needs them to differ.

## Refreshing

1. Export the live runtime's tool list (the bundled snapshot predates tools such as `hela_genome_list_missions`) and replace `data/catalog/hela-stack-tools.json`.
2. `build-data` will fail on any seed naming a missing tool; fix or drop those lines.
3. Re-run the baseline on the frozen eval.
