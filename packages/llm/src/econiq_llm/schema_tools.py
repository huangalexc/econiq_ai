"""Turning Pydantic schemas into something a provider's structured-output mode
will accept.

Provider JSON-schema support is a strict subset of what Pydantic emits: numeric
bounds, string lengths, patterns and array cardinality are rejected, and
recursive schemas are not supported at all. Rather than weaken the ontology
models to fit, we strip the unsupported keywords here and keep enforcing them
locally — the Pydantic model remains the authority, and the repair loop in
``econiq_llm.agent`` handles anything the provider gets wrong.
"""

from __future__ import annotations

from typing import Any, cast

#: Keywords providers reject in structured-output schemas. They are constraints
#: we still enforce — just on our side of the boundary.
UNSUPPORTED_KEYWORDS: frozenset[str] = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "default",
    }
)


def sanitize_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``schema`` with provider-unsupported keywords removed.

    ``additionalProperties: false`` is added to every object, which providers
    require and which matches the ``extra="forbid"`` posture of the ontology
    models: a field the contract does not define must not appear.
    """
    return cast(dict[str, Any], _walk(schema))


def _walk(node: Any) -> Any:
    if isinstance(node, list):
        return [_walk(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in UNSUPPORTED_KEYWORDS:
            continue
        out[key] = _walk(value)

    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
        props = out.get("properties")
        if isinstance(props, dict) and "required" not in out:
            # Providers require every declared property to be listed; optional
            # fields stay expressible through `anyOf: [..., {"type": "null"}]`,
            # which Pydantic already emits for `X | None`.
            out["required"] = list(props)
    return out


def schema_is_recursive(schema: dict[str, Any]) -> bool:
    """Whether ``schema`` contains a ``$ref`` cycle.

    Recursive schemas — the Capability requirement tree, for instance — cannot
    use provider-enforced structured output. The caller falls back to asking for
    JSON in the prompt and leans on local validation instead, which is why the
    validation-and-repair loop is not optional.
    """
    defs: dict[str, Any] = schema.get("$defs", {})
    if not defs:
        return False

    edges: dict[str, set[str]] = {name: _refs(body) for name, body in defs.items()}
    seen: set[str] = set()
    stack: set[str] = set()

    def visits(name: str) -> bool:
        if name in stack:
            return True
        if name in seen or name not in edges:
            return False
        seen.add(name)
        stack.add(name)
        cyclic = any(visits(child) for child in edges[name])
        stack.discard(name)
        return cyclic

    return any(visits(name) for name in edges)


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            found.add(ref.removeprefix("#/$defs/"))
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= _refs(item)
    return found
