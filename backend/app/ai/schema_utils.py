"""Convert Pydantic models into JSON Schemas accepted by Claude structured outputs.

Structured outputs require closed objects (`additionalProperties: false`) and do not support
numeric/string-length constraints, `oneOf`, or `discriminator`. Pydantic re-validates the
response afterwards, so dropping constraints here loses no safety.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DROP = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "minItems", "maxItems", "pattern", "default",
    "discriminator", "title", "uniqueItems",
}


def _walk(node: Any) -> Any:
    if isinstance(node, list):
        return [_walk(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in _DROP:
            continue
        if k == "oneOf":
            out["anyOf"] = _walk(v)
            continue
        if k in ("properties", "$defs"):
            out[k] = {name: _walk(sub) for name, sub in v.items()}
            continue
        out[k] = _walk(v)
    if out.get("type") == "object" or "properties" in out:
        out["type"] = "object"
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}).keys())
        out.setdefault("properties", {})
    return out


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _walk(model.model_json_schema())
