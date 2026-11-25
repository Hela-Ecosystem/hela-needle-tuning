"""Convert rows written by `cactus generate-data` into validated seed lines.

The generator emits Cactus rows (`query`, `tools`, `answers`) with the whole tool
list attached. Training rows must instead use the runtime's two-stage prompts and
shortlist format, so only the (task, tool, arguments) triple is kept and the
normal builder re-wraps it. Anything that does not validate is dropped and counted.
"""
from __future__ import annotations

import collections
from typing import Any

from .catalog import Tool
from .schema import validate_args
from .scrub import credential_findings

MIN_TASK = 8
MAX_TASK = 300


def convert(rows: list[dict[str, Any]], catalog: list[Tool]) -> tuple[list[dict[str, Any]], collections.Counter]:
    """Return (seed lines, rejection reason counts)."""
    by_name = {t.name: t for t in catalog}
    seen: set[str] = set()
    seeds: list[dict[str, Any]] = []
    rejected: collections.Counter = collections.Counter()
    for row in rows:
        task = str(row.get("query", "")).strip()
        answers = row.get("answers") or []
        if not (MIN_TASK <= len(task) <= MAX_TASK):
            rejected["task length"] += 1
            continue
        if credential_findings(task):
            rejected["secret-like text in task"] += 1
            continue
        if len(answers) > 1:
            rejected["multiple calls"] += 1
            continue
        key = task.lower()
        if key in seen:
            rejected["duplicate task"] += 1
            continue
        if not answers:
            seen.add(key)
            seeds.append({"task": task, "tool": None})
            continue
        call = answers[0]
        tool = by_name.get(call.get("name"))
        if tool is None:
            rejected["unknown tool"] += 1
            continue
        args = call.get("arguments")
        problems = validate_args(tool.parameters, args if args is not None else {})
        if problems:
            rejected["invalid arguments"] += 1
            continue
        if credential_findings(str(args)):
            rejected["secret-like text in arguments"] += 1
            continue
        seen.add(key)
        seed: dict[str, Any] = {"task": task, "tool": tool.name}
        if args:
            seed["arguments"] = args
        seeds.append(seed)
    return seeds, rejected
