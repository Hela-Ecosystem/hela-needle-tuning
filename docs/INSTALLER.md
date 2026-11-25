# Installer integration (proposal)

Goal: a user installs HeLa with a profile and automatically gets the Needle model tuned for it, with a safe fallback to the shipped model. Nothing here changes the public runtime until a model has been published and the maintainers accept the change.

## What exists today (hela-mcp-ecosystem)

- `scripts/provision-needle.mjs` downloads the pinned **shipped** Needle 3 assets (engine per platform, `needle3.cact`, `LICENSE`) from Hugging Face, each checked against a hard-coded sha256 and a size limit.
- `scripts/installation.mjs` sets `capabilities.needle = servers.has('hela-mitosis')`. Every canonical profile includes Mitosis, so all 8 profiles get Needle.
- `scripts/generate-config.mjs` sets `NEEDLE_ENGINE_PATH`, `NEEDLE_MODEL_PATH` and `NEEDLE_SYSTEM_PATH` (to `profiles/<profile>.txt`).

## Proposed change

After the shipped model is provisioned, try the profile model:

1. Fetch `https://raw.githubusercontent.com/Hela-Ecosystem/hela-needle-tuning/main/models/manifest.json` (or a copy pinned at release time).
2. If `models[<profile>]` exists and its `base.revision` equals the shipped model's pinned revision, download `url` with the same verified downloader (`downloadVerified`, expected `sha256`, size limit taken from `size`).
3. On success set `NEEDLE_MODEL_PATH` to the tuned file. If the manifest's `system_mode` is `none`, do not set `NEEDLE_SYSTEM_PATH` (or point it at an empty file); if it is `profile`, keep the profile text.
4. On **any** failure (no entry, network error, checksum mismatch, wrong base revision), keep the shipped model and continue. The tuned model is an optimisation, never a requirement. `--without-model` keeps skipping both.

Install cost: about 63 MB per profile model on top of the shipped 35 MB. Only the installed profile's model is downloaded.

## Safety properties

- A model is listed in the manifest only after it passed the gate against that profile's baseline on a frozen eval, and its sha256 equals the sha256 of the file that was evaluated (`scripts/publish_models.sh` enforces both).
- The installer verifies the checksum before use and never executes the model file: it is data for the Needle engine.
- A wrong or tampered file fails verification and falls back.

## Open points for the maintainers

- Whether to read the manifest live from GitHub or pin it per ecosystem release (pinning is more reproducible; live gets new models without a release).
- Whether the runtime should expose which model is active (for support and for comparing agent outcomes).
- Where `runtime` tests would cover the fallback path.
