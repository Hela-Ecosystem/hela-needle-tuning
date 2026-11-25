"""Which tools the HeLa agent actually offers Needle.

The runtime's agent catalog is every cell tool except an exclusion list (planner and orchestration
tools such as ``llm_*`` and ``workflow_*``, and the agent-management tools), plus the runtime's own
``hela.update.check`` / ``hela.update.apply``. Needle never sees an excluded tool, so training on one
is wasted effort and "covering all tools" means covering this catalog.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .catalog import Tool


def load_exclusions(path: str | Path) -> tuple[set[str], list[re.Pattern[str]]]:
    data = json.loads(Path(path).read_text(encoding="utf8"))
    return set(data["names"]), [re.compile(p) for p in data["patterns"]]


def real_name(tool: Tool) -> str:
    """The cell's own tool name (``read_file``), without the ``hela_<cell>_`` namespace."""
    prefix = f"hela_{tool.cell}_"
    return tool.name[len(prefix):] if tool.name.startswith(prefix) else tool.name


def is_visible(tool: Tool, names: set[str], patterns: list[re.Pattern[str]]) -> bool:
    real = real_name(tool)
    if tool.name in names or real in names:
        return False
    return not any(p.search(tool.name) or p.search(real) for p in patterns)


def visible_names(catalog: list[Tool], exclusions_path: str | Path | None) -> set[str] | None:
    """Names of the tools the agent offers, or None when no exclusion file is available."""
    if not exclusions_path or not Path(exclusions_path).exists():
        return None
    names, patterns = load_exclusions(exclusions_path)
    return {t.name for t in catalog if is_visible(t, names, patterns)}
