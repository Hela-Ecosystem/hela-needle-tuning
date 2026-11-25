"""Load the HeLa tool catalog in the shapes the runtime and Needle expect."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

DONE_NAME = "done"
DONE_DESCRIPTION = "Call this when the task is complete and no further tool action is needed."


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    cell: str

    def declaration(self, full: bool) -> dict[str, Any]:
        """The object handed to the Needle engine.

        The runtime asks Needle twice: first to choose a tool (declarations carry
        an empty parameter schema), then to fill arguments (one tool, full schema).
        """
        params = self.parameters if full else {"type": "object", "properties": {}}
        return {"name": self.name, "description": self.description, "parameters": params}


def done_tool() -> Tool:
    return Tool(DONE_NAME, DONE_DESCRIPTION, {"type": "object", "properties": {}}, "runtime")


def cell_of(server: str | None) -> str:
    server = server or ""
    return server[5:] if server.startswith("hela-") else server


def load_catalog(
    path: str | Path,
    name_style: str = "qualified",
    cells: Iterable[str] | None = None,
) -> list[Tool]:
    """Read a catalog JSON file.

    Accepts the bundled asset format (``name``, ``server``, ``description``,
    ``parameters``) or a live export (``inputSchema`` instead of ``parameters``,
    names already qualified). ``name_style`` is ``qualified`` (``hela_<cell>_<tool>``)
    or ``bare``. ``cells`` restricts the result to those cells.
    """
    if name_style not in ("qualified", "bare"):
        raise ValueError("name_style must be 'qualified' or 'bare'")
    wanted = set(cells) if cells else None
    raw = json.loads(Path(path).read_text(encoding="utf8"))
    if isinstance(raw, dict):
        raw = raw.get("tools", [])
    tools: list[Tool] = []
    seen: set[str] = set()
    for item in raw:
        cell = cell_of(item.get("server")) or item.get("cell", "")
        if wanted is not None and cell not in wanted:
            continue
        name = item["name"]
        if name_style == "qualified" and cell and not name.startswith(("hela_", "hela.")):
            name = f"hela_{cell}_{name}"
        if name in seen:
            continue
        seen.add(name)
        params = item.get("parameters") or item.get("inputSchema") or {"type": "object", "properties": {}}
        tools.append(Tool(name, item.get("description") or name, params, cell))
    return tools
