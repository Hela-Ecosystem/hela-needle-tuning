"""Build Cactus-format training rows that mirror how the HeLa runtime calls Needle.

The runtime (hela-runtime ``src/agent.ts``) asks the model in two stages and the
rows here reproduce both prompts, so the model is tuned on the exact text it
will see:

1. choose: a shortlist of up to 4 tools with *empty* parameter schemas plus a
   ``done`` tool. The answer is one tool name.
2. arguments: one tool with its full schema. The answer is the arguments.

Row format (Cactus ``finetune``): ``{"query", "tools", "answers"}``; an
off-topic row has ``answers: []``.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from .catalog import DONE_NAME, Tool, done_tool
from .schema import validate_args
from .scrub import scrub_value
from .splits import split_of

SHORTLIST = 4
DEFAULT_WORKSPACE = "/workspace"


def choose_prompt(task: str, workspace: str = DEFAULT_WORKSPACE, history: str = "", step: str | None = None) -> str:
    parts = [
        f"Task: {task}",
        f"Current step: {step}." if step else "Choose the next action that makes progress.",
        f"Workspace root: {workspace}",
        f"Recent actions:\n{history}" if history else "",
        "Choose the tool for this step. Call done when every requested action is complete.",
    ]
    return "\n".join(p for p in parts if p)


def arguments_prompt(task: str, tool: str, workspace: str = DEFAULT_WORKSPACE, history: str = "", step: str | None = None) -> str:
    parts = [
        f"Task: {task}",
        f"Current step: {step}." if step else "",
        f"Chosen tool: {tool}.",
        f"Workspace root: {workspace}",
        f"Current directory: {workspace}",
        f"Recent actions:\n{history}" if history else "",
        "Generate the arguments for this tool call.",
    ]
    return "\n".join(p for p in parts if p)


def shortlist(target: Tool | None, catalog: list[Tool], rng: random.Random, size: int = SHORTLIST) -> list[Tool]:
    """The target plus distractors, same cell first (what retrieval tends to return)."""
    pool = [t for t in catalog if target is None or t.name != target.name]
    same = [t for t in pool if target is not None and t.cell == target.cell]
    other = [t for t in pool if target is None or t.cell != target.cell]
    rng.shuffle(same)
    rng.shuffle(other)
    picked = (same[: size - 2] + other)[: size - 1 if target else size]
    chosen = ([target] if target else []) + picked
    rng.shuffle(chosen)
    return chosen


def choose_row(task: str, target: str | None, catalog: list[Tool], rng: random.Random, pin: list[str] | None = None, **kw: Any) -> dict[str, Any]:
    """``target=None`` or ``'done'`` trains the done / nothing-applies answer.

    ``pin`` fixes the exact shortlist (in order), used to replay a real failure.
    """
    by_name = {t.name: t for t in catalog}
    tool = by_name.get(target) if target and target != DONE_NAME else None
    if target and target != DONE_NAME and tool is None:
        raise KeyError(f"unknown tool {target!r}")
    if pin:
        missing = [n for n in pin if n not in by_name]
        if missing:
            raise KeyError(f"unknown tool {missing[0]!r} in pinned shortlist")
        picked = [by_name[n] for n in pin]
    else:
        picked = shortlist(tool, catalog, rng)
    tools = [t.declaration(full=False) for t in picked] + [done_tool().declaration(full=False)]
    answer = [{"name": target or DONE_NAME, "arguments": {}}]
    return {"query": choose_prompt(task, **kw), "tools": tools, "answers": answer}


def arguments_row(task: str, target: str, arguments: dict[str, Any], catalog: list[Tool], **kw: Any) -> dict[str, Any]:
    by_name = {t.name: t for t in catalog}
    tool = by_name.get(target)
    if tool is None:
        raise KeyError(f"unknown tool {target!r}")
    problems = validate_args(tool.parameters, arguments)
    if problems:
        raise ValueError(f"{target}: {'; '.join(problems)}")
    return {
        "query": arguments_prompt(task, target, **kw),
        "tools": [tool.declaration(full=True)],
        "answers": [{"name": target, "arguments": arguments}],
    }


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first row for each (task, stage); earlier seed files win."""
    seen: set[tuple[str, str, bool]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        task = row["query"].split("\n", 1)[0].lower()
        # A pinned shortlist replays a specific failure, so it is never a duplicate of an unpinned row.
        key = (task, row["meta"]["stage"], bool(row["meta"].get("pinned")))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def build_rows(seed_path: str | Path, catalog: list[Tool], seed: int = 7) -> list[dict[str, Any]]:
    """Expand a seed file (one JSON object per line) into rows with split labels.

    Seed fields: ``task``, ``tool`` (qualified name, or ``done``/null for no
    action), optional ``arguments`` (adds a second-stage row), ``regression``
    (always eval), ``note``. Any unknown tool or invalid arguments raise, so a
    stale seed fails the build instead of silently teaching the wrong thing.
    """
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(Path(seed_path).read_text(encoding="utf8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = json.loads(line)
        try:
            task, tool = item["task"], item.get("tool")
            regression = bool(item.get("regression"))
            forced = item.get("split")
            if forced not in (None, "train", "eval"):
                raise ValueError(f"split must be 'train' or 'eval', got {forced!r}")
            stage = [("choose", choose_row(task, tool, catalog, rng, pin=item.get("shortlist")))]
            if item.get("arguments") is not None:
                stage.append(("arguments", arguments_row(task, tool, item["arguments"], catalog)))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{seed_path}:{line_no}: {exc}") from exc
        for kind, row in stage:
            row = scrub_value(row)
            row["meta"] = {"stage": kind, "split": forced or split_of(task, regression), "regression": regression, "pinned": bool(item.get("shortlist")) and kind == "choose", "source": Path(seed_path).name}
            rows.append(row)
    return rows
