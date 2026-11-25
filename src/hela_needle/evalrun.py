"""Run the Needle engine over eval rows and score the answers.

The engine is invoked exactly like the runtime does (``--model``, ``--system``,
``--tools``, ``--prompt``, ``--max 256``, ``--forced``) and the last stdout line
is parsed as the JSON envelope.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .schema import validate_args


def run_engine(engine: str, model: str | None, system: str | None, row: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hela-needle-eval-") as tmp:
        tools_file = Path(tmp) / "tools.json"
        tools_file.write_text(json.dumps(row["tools"]), encoding="utf8")
        cmd = [engine]
        if model:
            cmd += ["--model", model]
        if system:
            cmd += ["--system", system]
        cmd += ["--tools", str(tools_file), "--prompt", row["query"], "--max", "256", "--forced"]
        env = {**os.environ, "NEEDLE_TELEMETRY": "0", "DO_NOT_TRACK": "1"}
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    lines = [ln for ln in out.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        return {"function_calls": [], "error": (out.stderr or "no output")[:200]}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"function_calls": [], "error": "unparseable output"}


def first_call(envelope: dict[str, Any]) -> dict[str, Any] | None:
    calls = envelope.get("function_calls") or envelope.get("suppressed_calls") or []
    return calls[0] if calls else None


def score_row(row: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    expected = row["answers"][0] if row["answers"] else None
    got = first_call(envelope)
    tool_ok = (got is None and expected is None) or (got is not None and expected is not None and got.get("name") == expected["name"])
    result: dict[str, Any] = {"stage": row["meta"]["stage"], "regression": row["meta"].get("regression", False), "tool_ok": tool_ok}
    if row["meta"]["stage"] == "arguments" and expected is not None:
        args = (got or {}).get("arguments") or {}
        schema = row["tools"][0].get("parameters", {})
        result["args_valid"] = bool(got) and not validate_args(schema, args)
        result["args_exact"] = bool(got) and args == expected["arguments"]
        # Every expected key has the expected value; extra optional keys (defaults the model adds) are fine.
        result["args_match"] = bool(got) and not validate_args(schema, args) and all(args.get(k) == v for k, v in expected["arguments"].items())
    return result


def aggregate(scored: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(items: list[dict[str, Any]], key: str) -> float | None:
        vals = [i[key] for i in items if key in i]
        return round(sum(vals) / len(vals), 4) if vals else None

    choose = [s for s in scored if s["stage"] == "choose"]
    args = [s for s in scored if s["stage"] == "arguments"]
    # Arguments-stage rows show a single tool, so they cannot show a selection error.
    reg = [s for s in choose if s["regression"]]
    return {
        "n": len(scored),
        "choose_tool_acc": rate(choose, "tool_ok"),
        "args_valid": rate(args, "args_valid"),
        "args_exact": rate(args, "args_exact"),
        "args_match": rate(args, "args_match"),
        "regression_n": len(reg),
        "regression_tool_acc": rate(reg, "tool_ok"),
    }


def evaluate(
    rows: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], dict[str, Any]],
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score eval rows. If ``details`` is given, append one record per row (task, expected, got)."""
    scored = []
    for r in rows:
        if r["meta"]["split"] != "eval":
            continue
        envelope = predict(r)
        s = score_row(r, envelope)
        scored.append(s)
        if details is not None:
            got = first_call(envelope)
            exp = r["answers"][0] if r["answers"] else None
            details.append({
                "task": r["query"].split("\n", 1)[0].removeprefix("Task: "),
                "stage": s["stage"],
                "regression": s["regression"],
                "expected": exp["name"] if exp else None,
                "got": got.get("name") if got else None,
                "tool_ok": s["tool_ok"],
                "args_exact": s.get("args_exact"),
                "args_match": s.get("args_match"),
                "expected_args": exp["arguments"] if exp and s["stage"] == "arguments" else None,
                "got_args": (got or {}).get("arguments") if s["stage"] == "arguments" else None,
                "error": envelope.get("error"),
            })
    return aggregate(scored)
