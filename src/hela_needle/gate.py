"""Release gate: new weights must beat the baseline and must not regress."""
from __future__ import annotations

from typing import Any

MIN_GAIN = 0.02
MIN_EVAL_ROWS = 20


def check(candidate: dict[str, Any], baseline: dict[str, Any], min_gain: float = MIN_GAIN) -> list[str]:
    """Return the reasons to block the release; empty means it may ship."""
    reasons: list[str] = []
    if candidate.get("n", 0) < MIN_EVAL_ROWS:
        reasons.append(f"eval set too small ({candidate.get('n', 0)} < {MIN_EVAL_ROWS})")
    cand, base = candidate.get("choose_tool_acc"), baseline.get("choose_tool_acc")
    if cand is None or base is None:
        reasons.append("choose_tool_acc missing")
    elif cand < base + min_gain:
        reasons.append(f"choose_tool_acc {cand} does not beat baseline {base} by {min_gain}")
    for key in ("args_valid", "regression_tool_acc"):
        c, b = candidate.get(key), baseline.get(key)
        if c is not None and b is not None and c < b:
            reasons.append(f"{key} regressed: {c} < {b}")
    if candidate.get("regression_n", 0) and (candidate.get("regression_tool_acc") or 0) < 1.0:
        reasons.append(f"regression cases not all passing ({candidate.get('regression_tool_acc')})")
    return reasons
