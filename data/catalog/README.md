# Catalog snapshot

`hela-stack-tools.json` is the tool list the data builder validates against, in the runtime's bundled asset format (`name`, `server`, `description`, `parameters`). `profiles.json` and `profiles/*.txt` say which cells each runtime profile activates; `hela-system.txt` is the runtime's system prompt for the full profile.

**Current snapshot (2026-11-25), every entry verified against a live server:** the runtime's tool list for the 8 cells installed on servy (233 tools), plus `tools/list` taken directly from the **receptor** cell (scrcpy-mcp, 46 tools) and the **plastid** cell (ll3m-mcp, 15 tools), plus the runtime's own `hela.update.check` and `hela.update.apply` (cell `runtime`, active in every profile). 296 tools in total. The receptor and plastid entries were identical to the older bundled snapshot, so nothing changed for them.

`agent-exclusions.json` lists the tools the agent never offers to Needle (copied from `hela-runtime`'s `agentCatalog()`); 29 of the 296 are excluded, leaving the **267-tool agent catalog** that training and coverage use.

Differences against the previous bundled snapshot: 9 tools added (`cytosol_browser_image_analyze`, `cytosol_browser_list_dialogs`, `cytosol_browser_visual_analyze`, `genome_create_mission`, `genome_list_missions`, `genome_obsidian_vault`, `genome_search_feedback`, `genome_search_priors`, `genome_update_mission`), 7 removed (`genome_ui_server`, `mitosis_agent_run`, the five `phenotype_stitch_*` tools), 18 tools with changed parameters, notably `enzyme_google_search` now takes `query`, not `q`, and the 2 runtime tools added.

Refresh (all exports use `scripts/export_tools.mjs`):

```bash
node scripts/export_tools.mjs live.json -- node <runtime>/dist/index.js          # the installed cells + runtime tools
node scripts/export_tools.mjs receptor.json --cwd <scrcpy-mcp> -- node dist/server.js
node scripts/export_tools.mjs plastid.json --cwd <ll3m-mcp>/brain -- node dist/index.js
python scripts/refresh_catalog.py --live live.json --cell receptor=receptor.json --cell plastid=plastid.json
```

`build-data` then fails on any seed that no longer matches, which is the list of lines to fix. Re-copy `agent-exclusions.json` from the runtime if its exclusion list changed.
