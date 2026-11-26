"""Derive new training seeds from seeds that are already validated.

chains:     compound tasks ("do A, then B") with the executed steps in the history, so the model learns
            the next tool, the arguments after a result, and to answer `done` once everything is finished.
negatives:  tasks that need a cell some profiles do not activate, answered with "none" there.

Everything is deterministic for a given seed, and every derived line is built only from lines that
already passed the builder, so the usual validation applies again when the data is built.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from .agentcat import real_name
from .catalog import Tool

SKIP_FILES = ("chains", "negatives_inactive", "eval_hand", "claude_history", "claude_negatives")

EN_JOIN = ["{a}, then {b}", "{a} and then {b}", "First {a}. After that, {b}", "{a}. Next, {b}", "{a} and afterwards {b}"]
EN_JOIN3 = ["{a}, then {b}, and finally {c}", "First {a}, then {b}, then {c}", "{a}. {b}. After that, {c}"]
ID_JOIN = ["{a}, lalu {b}", "{a} terus {b}", "Pertama {a}. Setelah itu, {b}", "{a} kemudian {b}"]
ID_JOIN3 = ["{a}, lalu {b}, dan terakhir {c}", "Pertama {a}, kemudian {b}, setelah itu {c}"]
ID_WORDS = re.compile(r"\b(tolong|buka|cari|hapus|tampilkan|buat|baca|salin|pindahkan|jalankan|berapa|apa|ke|dari|dong|sekarang|lalu|dan)\b", re.I)

# Tools whose task wording is not specific to their cell, so "none" would be wrong elsewhere.
AMBIGUOUS = {"receptor": {"screenshot", "shell_exec", "file_list", "file_push", "file_pull", "wait", "version", "clipboard_get", "clipboard_set", "input_text"}}
CELL_CUES = {
    "receptor": re.compile(r"\b(phone|android|device|apk|adb|wi-?fi|notification|handset|emulator|ponsel|hp)\b", re.I),
    "plastid": re.compile(r"\b(blender|3d|mesh|scene|render|blend|model|object)\b", re.I),
    "phenotype": re.compile(r"\b(design|palette|colou?r|theme|token|css|tailwind|ui|ux|brand|motion|component|typography|style|logo|template|figma)\b", re.I),
    "ribosome": re.compile(r"opencode", re.I),
}
CAPS = {"receptor": 60, "plastid": 40, "phenotype": 50, "ribosome": 30}


COMPOUND = re.compile(r"\b(then|after that|afterwards|next|at once|both|also|first|finally|lalu|terus|kemudian|setelah itu|pertama)\b|[:;]", re.I)


def is_simple(task: str) -> bool:
    """A short single-action request: a safe building block for a longer compound task."""
    return 6 <= len(task) <= 110 and not COMPOUND.search(task) and not re.search(r"[.!?]\s+\S", task)


HANDWRITTEN = ("core", "claude_core", "claude_pairs", "claude_gaps", "expanded")


def language(task: str) -> str:
    return "id" if ID_WORDS.search(task) else "en"


def load_pool(seeds_dir: str | Path, catalog: list[Tool], visible: set[str] | None, handwritten_only: bool = False) -> list[dict[str, Any]]:
    """Validated single-step seeds usable as building blocks: task, tool, arguments."""
    by_name = {t.name: t for t in catalog}
    pool, seen = [], set()
    for path in sorted(Path(seeds_dir).glob("*.jsonl")):
        if path.name.startswith(SKIP_FILES):
            continue
        if handwritten_only and not path.name.startswith(HANDWRITTEN):
            continue
        for line in path.read_text(encoding="utf8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            tool = by_name.get(d.get("tool") or "")
            if tool is None or (visible is not None and tool.name not in visible):
                continue
            if d.get("split") == "eval" or d.get("regression") or d.get("history") or d.get("shortlist"):
                continue
            args = d.get("arguments") or {}
            required = (tool.parameters.get("required") or [])
            if any(k not in args for k in required):
                continue
            if not is_simple(d["task"].strip()):
                continue
            key = (d["task"].strip().lower(), tool.name)
            if key in seen:
                continue
            seen.add(key)
            pool.append({"task": d["task"].strip(), "tool": tool.name, "arguments": args, "cell": tool.cell, "real": real_name(tool)})
    return pool


def fake_result(real: str, rng: random.Random) -> str:
    """A plausible tool result in the runtime's JSON shape; the wording never decides the answer."""
    if any(k in real for k in ("list", "find", "search", "query", "read_graph", "timeline", "stats", "observe", "models")):
        msg = f"Found {rng.randint(1, 12)} items"
    elif any(k in real for k in ("read", "get", "extract", "content", "info", "size", "summary", "status")):
        msg = "Retrieved the requested data"
    elif any(k in real for k in ("write", "create", "copy", "move", "delete", "archive", "spawn", "navigate", "click", "type", "press", "tap", "set", "start", "stop", "open")):
        msg = "Operation completed successfully"
    else:
        msg = "ok"
    return json.dumps({"success": True, "message": msg})


def _clean(text: str) -> str:
    return text.strip().rstrip(".!?")


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:] if len(text) > 1 and text[0].isupper() and text[1].islower() else text


def compose_task(tasks: list[str], rng: random.Random) -> str:
    parts = [_clean(tasks[0])] + [_lower_first(_clean(t)) for t in tasks[1:]]
    indonesian = all(language(t) == "id" for t in tasks)
    if len(parts) == 2:
        pattern = rng.choice(ID_JOIN if indonesian else EN_JOIN)
        text = pattern.format(a=parts[0], b=parts[1])
    else:
        pattern = rng.choice(ID_JOIN3 if indonesian else EN_JOIN3)
        text = pattern.format(a=parts[0], b=parts[1], c=parts[2])
    text = re.sub(r"^(First|Pertama) ([A-Z])(?=[a-z])", lambda m: f"{m.group(1)} {m.group(2).lower()}", text)
    return text if text.endswith((".", "!", "?")) else text + "."


def build_chains(pool: list[dict[str, Any]], count: int, seed: int = 11) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    lines: list[dict[str, Any]] = []
    made: set[str] = set()
    attempts = 0
    while len(made) < count and attempts < count * 20:
        attempts += 1
        k = 3 if rng.random() < 0.25 else 2
        steps = rng.sample(pool, k)
        if len({s["tool"] for s in steps}) < k or len({language(s["task"]) for s in steps}) > 1:
            continue  # distinct tools, one language per chain
        task = compose_task([s["task"] for s in steps], rng)
        if task in made:
            continue
        made.add(task)
        history: list[dict[str, Any]] = []
        for step in steps:
            line = {"task": task, "tool": step["tool"], "split": "train", "note": "chain"}
            if step["arguments"]:
                line["arguments"] = step["arguments"]
            if history:
                line["history"] = list(history)
            lines.append(line)
            history.append({"tool": step["tool"], "args": step["arguments"], "result": fake_result(step["real"], rng)})
        lines.append({"task": task, "tool": "done", "history": list(history), "split": "train", "note": "chain"})
    return lines


def build_negatives(pool: list[dict[str, Any]], seed: int = 13, caps: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Tasks specific to a cell, answered "none" under profiles where that cell is inactive."""
    rng = random.Random(seed)
    caps = caps or CAPS
    lines: list[dict[str, Any]] = []
    for cell, cue in CELL_CUES.items():
        candidates = []
        seen: set[str] = set()
        for item in pool:
            if item["cell"] != cell or item["real"] in AMBIGUOUS.get(cell, set()):
                continue
            if cell == "ribosome" and not item["real"].startswith("opencode_"):
                continue
            if not cue.search(item["task"]) or item["task"].lower() in seen:
                continue
            seen.add(item["task"].lower())
            candidates.append(item)
        rng.shuffle(candidates)
        for item in candidates[: caps.get(cell, 0)]:
            lines.append({"task": item["task"], "tool": None, "inactive_cell": cell, "split": "train", "note": "inactive-cell negative"})
    return lines
