"""Redact anything that must not reach a training file."""
from __future__ import annotations

import re
from typing import Any

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"), "<redacted:token>"),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "<redacted:key>"),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<redacted:key>"),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer <redacted>"),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "<redacted:private-key>"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "<redacted:email>"),
    ("home-path", re.compile(r"/(?:home|Users)/[^/\s\"']+"), "/workspace"),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<redacted:ip>"),
]


def scrub_text(text: str) -> str:
    for _, pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def findings(text: str) -> list[str]:
    """Names of the rules that match, without modifying anything."""
    return [name for name, pattern, _ in _RULES if pattern.search(text)]


def scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [scrub_value(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub_value(v) for k, v in value.items()}
    return value
