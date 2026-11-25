# HeLa Needle models

Small tool-selection models for the HeLa runtime, one per runtime profile, fine-tuned from [Needle 3](https://huggingface.co/Cactus-Compute/needle3) by Cactus Compute.

> **Status:** no model is published yet. `manifest.json` lists a model only after it has passed the release gate, so an empty list means exactly that. Nothing here is a promise of quality: the first tuned model did not beat the untuned one, and every published model carries its own measured scores.

## What a model is

Needle picks a tool and fills its arguments for the HeLa agent (`hela.agent.run`) and the Mitosis planners. The shipped `needle3.cact` knows nothing about HeLa's tools. Each file here is the same model tuned on one profile's tools: only that profile's cells are ever offered as candidates, and tasks that need a tool from an inactive cell are answered with "none".

Every canonical profile includes Mitosis, and the installer enables Needle for any profile with Mitosis, so all 8 profiles (`3d-modeling`, `all`, `android-testing`, `dev-workspace`, `headless-server`, `minimal`, `research`, `web-devops`) use Needle.

## Using one

1. Find your profile in [`manifest.json`](manifest.json): it gives the download URL, `sha256` and size.
2. Download, then **verify the sha256** before using the file.
3. Point the runtime at it: `NEEDLE_MODEL_PATH=/path/to/hela-needle3-<profile>.cact` (the engine and the profile's system text stay as installed). Check `system_mode` in the manifest: it records whether the model was scored with the profile's system text (`profile`) or without it (`none`), and `NEEDLE_SYSTEM_PATH` should follow that.
4. If anything fails (no entry, checksum mismatch, engine error) keep using the shipped `needle3.cact`. These models are an optimisation, never a requirement.

An installer integration is described in [`docs/INSTALLER.md`](../docs/INSTALLER.md).

## What to know

- **Format:** 4-bit (W4A8) `.cact`, about 63 MB each. The shipped model is 2-bit and 35 MB.
- **No confidence head.** `cactus build` drops it for locally tuned models, so the engine reports confidence as `None`. The runtime treats it as optional.
- **Synthetic training data.** Written by Claude, by free OpenRouter models and by hand from HeLa's tool catalog; no real user sessions. Sources and rules: [`docs/DATA.md`](../docs/DATA.md).
- **Scores** are on a frozen, hand-written eval for that profile and are in the manifest next to each model. They measure tool choice and argument accuracy on single steps and short histories, not whole agent tasks.
- **Catalog drift.** A model is tied to the catalog it was trained on (`catalog_sha256` in the manifest). When tools are added, renamed or change arguments, retrain.

## Licence and provenance

Apache License 2.0, inherited from Needle 3 and used for this repository too ([`LICENSE`](LICENSE), [`../NOTICE`](../NOTICE)). These are modified versions: a LoRA adapter merged into the original weights. Please keep the licence and notice when redistributing.

## Train your own

See the top of the [main README](../README.md): one command on a GPU machine.
