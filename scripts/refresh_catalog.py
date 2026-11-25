#!/usr/bin/env python3
"""Merge a live runtime tool export into the bundled catalog snapshot.

Live tools (`hela_<cell>_<tool>`, from an MCP tools/list) replace the snapshot for every
cell they cover. Cells the live runtime could not start (listed in --keep-cells) keep their
snapshot entries, so the catalog still spans all 10 organelles. Runtime-level tools
(hela.pipe, hela.agent.run, ...) are ignored.

Export the live list with an MCP client (tools/list) and save it as a JSON array of
{name, description, parameters}. See docs/DATA.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hela_needle.profiles import ORGANELLES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", required=True)
    ap.add_argument("--bundled", default="data/catalog/hela-stack-tools.json")
    ap.add_argument("--out", default="data/catalog/hela-stack-tools.json")
    ap.add_argument("--keep-cells", nargs="*", default=["receptor", "plastid"], help="cells to keep from the snapshot")
    a = ap.parse_args()

    live = json.loads(Path(a.live).read_text(encoding="utf8"))
    bundled = json.loads(Path(a.bundled).read_text(encoding="utf8"))
    merged: list[dict] = []
    live_cells: set[str] = set()
    for tool in live:
        if tool["name"] in ("hela.update.check", "hela.update.apply"):
            # The runtime's own tools: offered to Needle under every profile.
            live_cells.add("runtime")
            merged.append({"name": tool["name"], "server": "hela-runtime", "description": tool.get("description", ""),
                           "parameters": tool.get("parameters") or {"type": "object", "properties": {}}})
            continue
        parts = tool["name"].split("_", 2)
        if len(parts) != 3 or parts[0] != "hela" or parts[1] not in ORGANELLES:
            continue
        live_cells.add(parts[1])
        merged.append({
            "name": parts[2],
            "server": f"hela-{parts[1]}",
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
        })
    kept = 0
    for tool in bundled:
        cell = tool["server"].removeprefix("hela-")
        if cell in a.keep_cells and cell not in live_cells:
            merged.append(tool)
            kept += 1
    order = {c: i for i, c in enumerate(ORGANELLES + ["runtime"])}
    merged.sort(key=lambda t: (order.get(t["server"].removeprefix("hela-"), 99), t["name"]))
    Path(a.out).write_text(json.dumps(merged, indent=1) + "\n", encoding="utf8")
    old = {(t["server"], t["name"]) for t in bundled}
    new = {(t["server"], t["name"]) for t in merged}
    print(f"wrote {len(merged)} tools ({len(live_cells)} live cells, {kept} kept from snapshot)")
    print(f"added {len(new - old)}, removed {len(old - new)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
