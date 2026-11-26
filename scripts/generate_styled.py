#!/usr/bin/env python3
"""Generate varied training tasks per tool with explicit style control (free OpenRouter models only).

The Cactus CLI generator has no style option and its --augment mode ignores the example phrasing, so
this script sends a similar request itself: for each small group of tools and each style, ask a model
for tasks plus the correct call, then keep the raw rows. They go through the same validating importer
(`python -m hela_needle import-generated`), which drops anything invalid.

Styles target what the first generation lacks: casual chat with typos, terse commands, indirect
requests, Indonesian, non-default optional arguments, and look-alike cases.

Only free models are allowed unless --allow-paid is given. The key is read from OPENROUTER_API_KEY and
never printed. Raw output stays outside the repo (--out-dir).

  python scripts/generate_styled.py --catalog data/catalog/hela-stack-tools.json --out-dir ~/runs/gen2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hela_needle.agentcat import visible_names  # noqa: E402
from hela_needle.catalog import load_catalog  # noqa: E402

URL = "https://openrouter.ai/api/v1/chat/completions"

STYLES = {
    "casual": (
        "casual chat messages as a real person would type them: lowercase, slang, occasional typos, no punctuation",
        ['{"query": "pls show me whats in the downloads folder", "answers": [{"name": "TOOL", "arguments": {}}]}'],
    ),
    "terse": (
        "terse commands of 2 to 6 words, like a CLI or a search box (no polite phrasing)",
        ['{"query": "disk usage /var", "answers": [{"name": "TOOL", "arguments": {}}]}'],
    ),
    "indirect": (
        "indirect requests that describe the goal or the problem instead of naming the action (for example 'I need to know why the page looks empty')",
        ['{"query": "I want to be sure nobody changed that config since yesterday", "answers": [{"name": "TOOL", "arguments": {}}]}'],
    ),
    "indonesian": (
        "requests in Bahasa Indonesia, mixing casual and formal, sometimes with English technical words",
        ['{"query": "tolong buka halaman login lalu ambil tangkapan layarnya", "answers": [{"name": "TOOL", "arguments": {}}]}'],
    ),
    "options": (
        "requests that need optional arguments set to NON-default values (limits, flags, formats, modes, timeouts), stated naturally",
        ['{"query": "list only the first 5 results sorted newest first", "answers": [{"name": "TOOL", "arguments": {}}]}'],
    ),
    "lookalike": (
        "requests where a neighbouring tool in the list is tempting but wrong; the correct tool is the one whose description fits best. Make the cue subtle but decidable",
        ['{"query": "show what changed between the two exports", "answers": [{"name": "TOOL", "arguments": {}}]}'],
    ),
}

SYSTEM = (
    "You write training data for a small model that chooses a tool and fills its arguments. "
    "Reply with a JSON array only, no prose and no code fences."
)

TEMPLATE = """Tools (JSON):
{tools}

Write {n} different user requests in this style: {style}.

Rules:
- Each row: {{"query": <the user's request>, "answers": [<exactly one call>]}} where a call is {{"name": <exact tool name from the list>, "arguments": {{...}}}}.
- Spread the rows evenly across the tools. Use only argument names from that tool's schema; include every required argument with a realistic value.
- Values: file paths under /workspace, URLs on example.com/example.org, ids like sess-3; never real names, emails, IP addresses, keys or tokens.
- About {nones} of the {n} rows should be requests none of these tools can do (chit-chat, general knowledge): use "answers": [].
- No duplicate requests, and do not copy the example wording.
Example row (shape and style only): {example}
JSON array:"""


def slim(params: dict) -> dict:
    props = {}
    for key, spec in (params.get("properties") or {}).items():
        item = {"type": spec.get("type", "string")}
        if spec.get("description"):
            item["description"] = spec["description"][:140]
        if spec.get("enum"):
            item["enum"] = spec["enum"][:12]
        props[key] = item
    out = {"type": "object", "properties": props}
    if params.get("required"):
        out["required"] = params["required"]
    return out


def parse_rows(text: str) -> list[dict]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        rows = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("query"), str) and isinstance(r.get("answers"), list)]


def call(model: str, key: str, prompt: str, retries: int = 4) -> str:
    payload = json.dumps({"model": model, "temperature": 0.9, "messages": [
        {"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(URL, data=payload, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except Exception:
            time.sleep(3 * (attempt + 1))
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", default="openrouter/free")
    ap.add_argument("--cells", nargs="*")
    ap.add_argument("--styles", nargs="*", default=list(STYLES))
    ap.add_argument("--tools-per-call", type=int, default=12)
    ap.add_argument("--rows-per-call", type=int, default=14)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--exclusions", default=str(Path(__file__).resolve().parent.parent / "data/catalog/agent-exclusions.json"))
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many calls (for tests)")
    a = ap.parse_args()

    if not a.allow_paid and "free" not in a.model:
        sys.exit(f"refusing non-free model {a.model!r} (pass --allow-paid to spend money)")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("set OPENROUTER_API_KEY")

    catalog = load_catalog(a.catalog, "qualified", a.cells)
    visible = visible_names(catalog, a.exclusions)
    if visible is not None:
        catalog = [t for t in catalog if t.name in visible]
    out = Path(a.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    jobs = []
    by_cell: dict[str, list] = {}
    for t in catalog:
        by_cell.setdefault(t.cell, []).append(t)
    for cell, tools in by_cell.items():
        for n, start in enumerate(range(0, len(tools), a.tools_per_call), 1):
            group = tools[start : start + a.tools_per_call]
            for style in a.styles:
                raw = out / f"raw_{cell}_{n}_{style}.jsonl"
                if raw.exists() and raw.stat().st_size > 0:
                    continue
                jobs.append((raw, group, style))
    if a.limit:
        jobs = jobs[: a.limit]
    print(f"{len(jobs)} call(s) planned", flush=True)

    def ask(group, style, n):
        """One request; a 400 (usually a free model with a small context window) retries with half the tools."""
        desc, examples = STYLES[style]
        tools_json = json.dumps([{"name": t.name, "description": t.description[:200], "parameters": slim(t.parameters)} for t in group])
        prompt = TEMPLATE.format(tools=tools_json, n=n, nones=max(1, n // 7), style=desc, example=examples[0])
        try:
            return parse_rows(call(a.model, key, prompt))
        except urllib.error.HTTPError as e:
            if e.code == 400 and len(group) > 1:
                half = len(group) // 2
                return ask(group[:half], style, max(4, n // 2)) + ask(group[half:], style, max(4, n // 2))
            return []
        except Exception:
            return []

    def run(job):
        raw, group, style = job
        rows = ask(group, style, a.rows_per_call)
        if rows:
            raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf8")
        return raw.name, len(rows)

    total = 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for fut in as_completed([pool.submit(run, j) for j in jobs]):
            try:
                name, n = fut.result()
            except Exception as exc:  # never let one call end the run
                name, n = f"<failed: {type(exc).__name__}>", 0
            total += n
            print(f"{'done' if n else 'empty'}  {name}: {n} rows", flush=True)
    print(f"total raw rows: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
