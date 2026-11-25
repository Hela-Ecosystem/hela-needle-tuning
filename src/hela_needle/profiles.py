"""Runtime profiles: which organelles (cells) are active.

The runtime shortlists tools only from the active profile, so a task whose tool
lives in an inactive cell has no right answer there. Training rows therefore draw
their candidate tools from one profile's cells, and tasks that need an inactive
cell are answered with "none".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .catalog import Tool

ORGANELLES = ["cytosol", "nucleus", "membrane", "genome", "enzyme", "phenotype", "plastid", "receptor", "ribosome", "mitosis"]
_LINE = re.compile(r"^- ([A-Za-z]+) \(")


def parse_profile_text(text: str) -> list[str]:
    """Cells listed as active in a profile text (lines like ``- Cytosol (browser-mcp): ...``)."""
    cells = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m and m.group(1).lower() in ORGANELLES:
            cells.append(m.group(1).lower())
    return cells


def load_profiles(path: str | Path) -> dict[str, list[str]]:
    data = json.loads(Path(path).read_text(encoding="utf8"))
    for name, cells in data.items():
        unknown = [c for c in cells if c not in ORGANELLES]
        if unknown:
            raise ValueError(f"profile {name!r} lists unknown cells {unknown}")
    return data


# The runtime's own tools (hela.update.check / hela.update.apply) are offered under every profile.
ALWAYS_ACTIVE = {"runtime"}


def cell_active(cell: str, cells: "list[str] | set[str]") -> bool:
    return cell in ALWAYS_ACTIVE or cell in cells


def profile_catalog(catalog: list[Tool], cells: list[str]) -> list[Tool]:
    active = set(cells)
    return [t for t in catalog if cell_active(t.cell, active)]
