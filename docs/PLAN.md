# Plan

Goal: the runtime's native agent (`hela.agent.run`) picks the right tool and fills valid arguments for HeLa's catalog, measurably better than the shipped `needle3`, without any change to the public runtime code.

Success is a number, not a feeling: a tuned `.cact` that passes `hela_needle gate` against `eval/baseline.json`.

## Decisions so far

| Decision | Reason |
|----------|--------|
| Separate repo, public code and private artifacts | Code, seeds and the catalog snapshot are public here. Weights and run logs go to the private `hela-needle-runs`; the uploader refuses public destinations. |
| Runtime stays agnostic | It loads `NEEDLE_*` paths, so shipping weights is configuration. |
| Rows copy the runtime's two prompts | The model is tuned on exactly the text it sees. Update `examples.py` whenever `agent.ts` prompts change. |
| Frozen hash split | Adding rows never moves an existing row between train and eval. |
| Cactus CLI does the training | No custom trainer to maintain. |
| Rent a GPU, small card first | The model is tiny; see Budget. |
| No Claude attribution in commits | Standing instruction for everything pushed to the Hela-Ecosystem org. |

## Milestones

### M0: scaffold (done)
Builder, scrubber, split, eval runner, gate, tests, untuned baseline, runbook script.
Acceptance: `python -m unittest discover -s tests` passes; `build-data` builds from `data/catalog/`; baseline committed.

### M1: dataset worth training on

**Progress (2026-11-25):** builder supports multi-step history; Claude-written core, history and negative seeds added (train rows 331 -> 627); hand-written eval frozen at 211 rows including history cases; free-model generation (6 samples per tool, 231 tools) running; first run's per-row analysis showed membrane look-alike confusion and an over-strict argument metric (fixed with `args_match`). Still open: catalog refresh from the live runtime, profile-aware rows and the `--system` effect test.
- Grow beyond the generated seed (`scripts/expand_seeds.py`, about 200 lines) to cover **every tool in the active profile**, not just the 22 the generator knows. Target at least 8 phrasings per tool.
- Add read-only phrasings ("do not modify anything") for every read tool, and the matching negatives.
- Add multi-step history rows: a prior call succeeded, so the right answer is the next tool or `done`.
- Add failure rows: a prior call returned an error, so the right answer is a different action, not the same call again (mirrors the repeated-failure guard in hela-runtime#5).
- Add a pinned-shortlist regression row for every production selection mistake.
Acceptance: at least 3 train rows per tool, eval at least 150 rows, `check-secrets` clean, `build-data` passes with no unknown tools.

### M2: dry run on a small rented GPU
- Run `scripts/runpod_train.sh` with `EPOCHS=1` on one 24 GB-class card.
- Record GPU, wall time, cost, peak memory and any CLI surprises in `docs/TRAINING.md`, correcting any command that behaved differently from upstream docs.
Acceptance: a `.cact` that the Needle engine loads and answers with; `meta.json` filled in.

### M3: first real run and gate
- Train with the M1 data for 3 epochs, build, evaluate with the real engine, run the gate.
- Report scores with hardware and quantisation noted (local build is 4-bit; the shipped baseline is 2-bit).
Acceptance: gate passes, or the failure reasons are written down and drive M1 data fixes. A failed gate is a valid outcome.

### M4: compare with the hosted platform
- Train once with `cactus platform finetune` (2-bit, same as shipped) and compare on the same eval.
- Spends allowance, so ask the owner first.
Acceptance: a table of local-4-bit vs platform-2-bit vs baseline; pick the shipping route.

### M5: ship to one runtime, then widen
- Weights licence: **resolved** (2026-11-25). Needle 3's repository ships the Apache License 2.0 and its model card says `license: apache-2.0`; modified redistribution is allowed with the licence and notice (see `NOTICE`, `models/LICENSE`).
- Point `NEEDLE_MODEL_PATH` at the tuned file on one runtime, run the end-to-end `hela.agent.run` tasks, then roll out.
- Stage the trained models in the private runs repo, evaluate them with `scripts/eval_profiles.sh`, then publish the ones that pass with `scripts/publish_models.sh` (public release of this repo plus `models/manifest.json`). Weights never go into git.
Acceptance: end-to-end agent results show the tuned model choosing correctly on the pinned regression tasks, with `ok`, `status` and `failedCalls` as reported by hela-runtime#5.

### Ongoing
- Retrain when the catalog changes; `build-data` failing on a missing tool is the trigger.
- Re-run the gate on every new candidate; never replace shipped weights without it.

## Budget and hardware

Hardware needs are not documented upstream, so the numbers below are measured from our own runs.
Expectation (unverified): a small LoRA run on a 16-24 GB card, minutes to a couple of hours. Rent on-demand, one small card, terminate the pod when the run ends, do not leave pods stopped. Use Secure Cloud for anything built from real session data. Set a spend limit in the account before starting, and stop if the first run needs a bigger card than expected.

## Risks

| Risk | Mitigation |
|------|-----------|
| Overfit to a small, templated dataset (the generated phrasings are repetitive) | Hold out by hash, add varied hand-written phrasings, check the regression set and a fresh hand-written eval. |
| Data leaks into a rented machine | Seeds and catalog only; `check-secrets` before every build; no raw session transcripts. |
| Prompts drift from the runtime | `examples.py` mirrors `agent.ts`; an end-to-end check in M5 catches drift. |
| 4-bit local vs 2-bit shipped mismatch | Compare on the same eval; run M4. |
| Weights licence | Resolved: Apache-2.0 (see NOTICE). Keep the licence and notice with every release; publish only through `publish_models.sh`. |
| Single-shot limit | Fine-tuning improves selection and arguments, not planning; multi-step ability stays with the agent loop. |

## Open questions for the owner

1. RunPod account and spend limit: who owns it, and what is the cap?
2. Is the hosted Cactus Platform acceptable to spend on (M4)?
3. Should training data ever include scrubbed real session tasks, or stay catalog-and-seed only?
