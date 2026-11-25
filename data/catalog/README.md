# Catalog snapshot

`hela-stack-tools.json` is the tool list the data builder validates against, in the runtime's bundled asset format (`name`, `server`, `description`, `parameters`). `profiles.json` and `profiles/*.txt` say which cells each runtime profile activates; `hela-system.txt` is the runtime's system prompt for the full profile.

**Current snapshot (2026-11-25):** live tool list of a servy runtime (233 tools in the 8 cells that start there) merged with the older bundled entries for the **receptor** (46) and **plastid** (15) cells, which are not installed on servy and could not be listed live. Those 61 entries may be stale.

Differences against the previous bundled snapshot: 9 tools added (`cytosol_browser_image_analyze`, `cytosol_browser_list_dialogs`, `cytosol_browser_visual_analyze`, `genome_create_mission`, `genome_list_missions`, `genome_obsidian_vault`, `genome_search_feedback`, `genome_search_priors`, `genome_update_mission`), 7 removed (`genome_ui_server`, `mitosis_agent_run`, the five `phenotype_stitch_*` tools), and 18 tools with changed parameters, notably `enzyme_google_search` now takes `query`, not `q`.

Refresh: export `tools/list` from the runtime over MCP to a JSON array of `{name, description, parameters}`, then `python scripts/refresh_catalog.py --live <export.json>`; `build-data` then fails on any seed that no longer matches, which is the list of lines to fix.
