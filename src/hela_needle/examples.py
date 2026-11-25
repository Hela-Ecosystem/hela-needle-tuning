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

import collections
import json
import random
from pathlib import Path
from typing import Any

from .catalog import DONE_NAME, Tool, done_tool
from .profiles import cell_active, profile_catalog
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


def format_history(history: list[dict[str, Any]] | None, by_name: dict[str, Tool], result_limit: int) -> str:
    """Render prior steps exactly as the runtime does: last 4, ``tool(args) -> result | ERROR msg``."""
    lines = []
    for step in (history or [])[-4:]:
        name = step["tool"]
        if name not in by_name:
            raise KeyError(f"unknown tool {name!r} in history")
        outcome = f"ERROR {step['error']}" if step.get("error") else str(step.get("result", ""))[:result_limit]
        lines.append(f"{name}({json.dumps(step.get('args', {}), separators=(',', ':'))}) -> {outcome}")
    return "\n".join(lines)


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
    seen: set[tuple[str, str, bool, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        task = row["query"].split("\n", 1)[0].lower()
        # A pinned shortlist replays a specific failure, so it is never a duplicate of an unpinned row.
        # The same task after a different history is a different example.
        recent = row["query"].split("Recent actions:\n", 1)[1].split("\n", 1)[0] if "Recent actions:\n" in row["query"] else ""
        key = (task, row["meta"]["stage"], bool(row["meta"].get("pinned")), recent)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def pick_profile(item: dict[str, Any], tool: Tool | None, profiles: dict[str, list[str]], rng: random.Random) -> str:
    """Choose the profile whose active cells the example is drawn from.

    An explicit ``profile`` wins. A tool row picks among profiles where the tool's cell is
    active. A row marked ``inactive_cell`` (the task needs a cell some profiles lack) picks a
    profile where that cell is inactive, so the right answer really is "none".
    """
    explicit = item.get("profile")
    if explicit:
        if explicit not in profiles:
            raise ValueError(f"unknown profile {explicit!r}")
        if tool is not None and not cell_active(tool.cell, profiles[explicit]):
            raise ValueError(f"{tool.name} is not active in profile {explicit!r}")
        return explicit
    names = sorted(profiles)
    inactive = item.get("inactive_cell")
    if inactive:
        names = [n for n in names if inactive not in profiles[n]]
    elif tool is not None:
        names = [n for n in names if cell_active(tool.cell, profiles[n])]
    if not names:
        raise ValueError("no profile fits this example")
    return names[rng.randrange(len(names))]


def applies_to_profile(item: dict[str, Any], by_name: dict[str, Tool], cells: set[str], name: str) -> bool:
    """Whether a seed line makes sense for a model trained only for one profile.

    A line is dropped when its target tool, a tool in its history or a pinned shortlist lives in
    a cell the profile does not activate, when it is pinned to another profile, or when it is a
    "needs an inactive cell" negative but that cell is active here.
    """
    tool = item.get("tool")
    names = [tool] if tool and tool != "done" else []
    names += [h.get("tool") for h in item.get("history") or []] + list(item.get("shortlist") or [])
    for n in names:
        t = by_name.get(n)
        if t is not None and not cell_active(t.cell, cells):
            return False
    if item.get("profile") and item["profile"] != name:
        return False
    if item.get("inactive_cell") and item["inactive_cell"] in cells:
        return False
    return True


def build_rows(
    seed_path: str | Path,
    catalog: list[Tool],
    seed: int = 7,
    profiles: dict[str, list[str]] | None = None,
    only_profile: str | None = None,
    visible: set[str] | None = None,
    stats: "collections.Counter | None" = None,
) -> list[dict[str, Any]]:
    """Expand a seed file (one JSON object per line) into rows with split labels.

    Seed fields: ``task``, ``tool`` (qualified name, or ``done``/null for no
    action), optional ``arguments`` (adds a second-stage row), ``regression``
    (always eval), ``note``. Any unknown tool or invalid arguments raise, so a
    stale seed fails the build instead of silently teaching the wrong thing.
    """
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(Path(seed_path).read_text(encoding="utf8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = json.loads(line)
        try:
            task, tool = item["task"], item.get("tool")
            if visible is not None:
                known = {t.name for t in catalog}
                used = ([tool] if tool and tool != "done" else []) + [h.get("tool") for h in item.get("history") or []] + list(item.get("shortlist") or [])
                if any(n in known and n not in visible for n in used):
                    if stats is not None:
                        stats["not offered to Needle"] += 1
                    continue
            if only_profile and not applies_to_profile(item, {t.name: t for t in catalog}, set(profiles[only_profile]), only_profile):
                continue
            # Each row has its own randomness, so adding or reordering other seeds never
            # changes this row's shortlist (the eval stays frozen).
            rng = random.Random(f"{seed}:{task}:{json.dumps(item.get('history'), sort_keys=True)}")
            regression = bool(item.get("regression"))
            forced = item.get("split")
            if forced not in (None, "train", "eval"):
                raise ValueError(f"split must be 'train' or 'eval', got {forced!r}")
            by_name = {t.name: t for t in catalog}
            profile = None
            pool = catalog
            if profiles:
                target = by_name.get(tool) if tool and tool != "done" else None
                profile = only_profile or pick_profile(item, target, profiles, rng)
                pool = profile_catalog(catalog, profiles[profile])
                if visible is not None:
                    pool = [t for t in pool if t.name in visible]
            hist_choose = format_history(item.get("history"), by_name, 300)
            hist_args = format_history(item.get("history"), by_name, 400)
            stage = [("choose", choose_row(task, tool, pool, rng, pin=item.get("shortlist"), **({"history": hist_choose} if hist_choose else {})))]
            if item.get("arguments") is not None:
                stage.append(("arguments", arguments_row(task, tool, item["arguments"], catalog, **({"history": hist_args} if hist_args else {}))))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{seed_path}:{line_no}: {exc}") from exc
        for kind, row in stage:
            row = scrub_value(row)
            row["meta"] = {"stage": kind, "split": forced or split_of(task, regression), "regression": regression, "pinned": bool(item.get("shortlist")) and kind == "choose", "history": bool(item.get("history")), "profile": profile, "kind": ("none" if tool is None else "done" if tool == "done" else "tool"), "source": Path(seed_path).name}
            rows.append(row)
    return rows


def build_all(
    seeds_dir: str | Path,
    catalog: list[Tool],
    seed: int = 7,
    profiles: dict[str, list[str]] | None = None,
    only_profile: str | None = None,
    visible: set[str] | None = None,
    stats: "collections.Counter | None" = None,
) -> list[dict[str, Any]]:
    """Every seed file in a directory (sorted), expanded and de-duplicated.

    ``only_profile`` builds the dataset for a model dedicated to that profile: only lines that
    apply to it, with every candidate shortlist drawn from its cells.
    """
    if only_profile and (not profiles or only_profile not in profiles):
        raise ValueError(f"unknown profile {only_profile!r}")
    rows: list[dict[str, Any]] = []
    for path in sorted(Path(seeds_dir).glob("*.jsonl")):
        rows += build_rows(path, catalog, seed, profiles, only_profile, visible, stats)
    return dedupe(rows)
