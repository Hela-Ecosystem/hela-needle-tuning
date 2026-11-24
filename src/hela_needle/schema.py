"""Small JSON-schema subset check used for dataset validation and scoring."""
from __future__ import annotations

from typing import Any

_TYPES = {
    "string": str,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py = _TYPES.get(expected)
    return True if py is None else isinstance(value, py)


def validate_args(schema: dict[str, Any], args: Any) -> list[str]:
    """Return a list of problems; empty means the arguments fit the schema.

    Checks required fields, unknown keys, primitive types and enums. Anything
    fancier (oneOf, patterns, nested schemas) is deliberately not judged.
    """
    if not isinstance(args, dict):
        return ["arguments must be an object"]
    props = schema.get("properties") or {}
    errors: list[str] = []
    for key in schema.get("required") or []:
        if key not in args:
            errors.append(f"missing required '{key}'")
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            if props:
                errors.append(f"unknown argument '{key}'")
            continue
        expected = spec.get("type")
        if isinstance(expected, str) and not _type_ok(expected, value):
            errors.append(f"'{key}' should be {expected}")
        enum = spec.get("enum")
        if enum and value not in enum:
            errors.append(f"'{key}' not in enum")
    return errors
