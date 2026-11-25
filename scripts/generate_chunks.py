#!/usr/bin/env python3
"""Generate synthetic tasks per tool with the Cactus CLI, in small resumable chunks.

Each chunk is one cell's tools (at most --chunk of them) so every request carries a
small tool list and the output is balanced per tool. Raw outputs stay OUTSIDE the
repo (`--out-dir`); import them with `python -m hela_needle import-generated`.

Only free OpenRouter models are allowed unless --allow-paid is given, so a typo
cannot spend money. The key is read from OPENROUTER_API_KEY by the Cactus CLI and
is never printed here.

Example:
  python scripts/generate_chunks.py --catalog data/catalog/hela-stack-tools.json \
    --cells mitosis membrane nucleus genome enzyme cytosol ribosome phenotype \
    --out-dir ~/runs/gen --cactus ~/venv/bin/cactus
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hela_needle.catalog import load_catalog  # noqa: E402


def slim(params: dict) -> dict:
    """Keep types, short descriptions and enums; drop nested schemas (they blow up the prompt)."""
    props = {}
    for key, spec in (params.get("properties") or {}).items():
        item = {"type": spec.get("type", "string")}
        if spec.get("description"):
            item["description"] = spec["description"][:160]
        if spec.get("enum"):
            item["enum"] = spec["enum"][:12]
        props[key] = item
    out = {"type": "object", "properties": props}
    if params.get("required"):
        out["required"] = params["required"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--cells", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cactus", default="cactus")
    ap.add_argument("--model", default="openrouter/free")
    ap.add_argument("--per-tool", type=int, default=6)
    ap.add_argument("--chunk", type=int, default=20, help="max tools per request set")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--allow-paid", action="store_true")
    a = ap.parse_args()

    if not a.allow_paid and "free" not in a.model:
        sys.exit(f"refusing non-free model {a.model!r} (pass --allow-paid to spend money)")

    out = Path(a.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(a.catalog, "qualified", a.cells)
    by_cell: dict[str, list] = {}
    for tool in catalog:
        by_cell.setdefault(tool.cell, []).append(tool)

    total = 0
    for cell in a.cells:
        tools = by_cell.get(cell, [])
        for n, start in enumerate(range(0, len(tools), a.chunk), 1):
            group = tools[start : start + a.chunk]
            raw = out / f"raw_{cell}_{n}.jsonl"
            if raw.exists() and raw.stat().st_size > 0:
                print(f"skip   {raw.name} (exists)")
                continue
            spec = out / f"tools_{cell}_{n}.json"
            spec.write_text(json.dumps([{"name": t.name, "description": t.description[:300], "parameters": slim(t.parameters)} for t in group]))
            want = a.per_tool * len(group)
            print(f"run    {raw.name}: {len(group)} tools, {want} samples", flush=True)
            cmd = [a.cactus, "generate-data", "--tools", str(spec), "--num-samples", str(want),
                   "--workers", str(a.workers), "--model", a.model, "--output", str(raw)]
            try:
                subprocess.run(cmd, check=False, timeout=a.timeout, env={**__import__("os").environ, "CACTUS_TELEMETRY": "0"})
            except subprocess.TimeoutExpired:
                print(f"timeout {raw.name}; continuing", flush=True)
            rows = sum(1 for _ in raw.open()) if raw.exists() else 0
            total += rows
            print(f"done   {raw.name}: {rows} rows", flush=True)
    print(f"total rows: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
