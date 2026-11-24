"""Deterministic, frozen train/eval split.

Membership depends only on the task text, so adding or removing other rows can
never move an existing example between train and eval.
"""
from __future__ import annotations

import hashlib

EVAL_PERCENT = 20


def bucket(task: str) -> int:
    digest = hashlib.sha256(task.strip().lower().encode("utf8")).hexdigest()
    return int(digest[:8], 16) % 100


def split_of(task: str, regression: bool = False) -> str:
    """Regression cases are always eval; they are mistakes we must never repeat."""
    if regression:
        return "eval"
    return "eval" if bucket(task) < EVAL_PERCENT else "train"
