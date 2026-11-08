"""Deterministic tool-call validation and retry-trace routing.

Agents emit tool calls as JSON. Hallucinated parameters are a production
outage, so every call is validated against its tool's JSON schema *before*
execution. Failures return a structured error trace that a model (or a
rule-based repair loop) can use to retry. Validation is fully deterministic:
same call, same verdict, no model involved.
"""

import json


class ValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors  # list of dicts: path, expected, got
        super().__init__("; ".join("%s: expected %s, got %r" % (e["path"], e["expected"], e["got"]) for e in errors))


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _type_name(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null" if value is None else type(value).__name__


def validate(value, schema, path="$"):
    """Validate value against a JSON-schema subset. Returns a list of errors."""
    errors = []

    def err(expected, got_value):
        errors.append({"path": path, "expected": expected, "got": got_value})

    if "enum" in schema and value not in schema["enum"]:
        err("one of %r" % (schema["enum"],), value)
        return errors

    expected_type = schema.get("type")
    if expected_type:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(t in _TYPE_MAP and isinstance(value, _TYPE_MAP[t]) and
                   (t != "integer" or not isinstance(value, bool)) and
                   (t != "number" or not isinstance(value, bool)) for t in types):
            err("type %s" % expected_type, _type_name(value))
            return errors  # deeper checks meaningless on wrong type

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                err("required key %r" % key, "missing")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in value:
                errors.extend(validate(value[key], subschema, "%s.%s" % (path, key)))
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            for key in sorted(extra):
                err("no additional properties", "unexpected key %r" % key)

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            err("at least %d items" % schema["minItems"], len(value))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            err("at most %d items" % schema["maxItems"], len(value))
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                errors.extend(validate(item, item_schema, "%s[%d]" % (path, i)))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            err("minLength %d" % schema["minLength"], len(value))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            err("maxLength %d" % schema["maxLength"], len(value))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            err(">= %r" % schema["minimum"], value)
        if "maximum" in schema and value > schema["maximum"]:
            err("<= %r" % schema["maximum"], value)

    return errors


class ToolRouter:
    """Registry of tools; validates calls, executes, formats retry traces."""

    def __init__(self):
        self._tools = {}

    def register(self, name, schema, fn, description=""):
        self._tools[name] = {"schema": schema, "fn": fn, "description": description}

    def manifest(self):
        """Schemas for injection into a system prompt."""
        return {name: {"description": t["description"], "schema": t["schema"]}
                for name, t in self._tools.items()}

    def execute(self, call, max_retries=0):
        """Validate and run one call. Returns a result dict; never raises.

        On validation failure returns {"ok": False, "error_trace": ...} shaped
        for retry. Callables raising exceptions are reported the same way.
        """
        attempts = []
        for attempt in range(max_retries + 1):
            name = call.get("tool") if isinstance(call, dict) else None
            if name not in self._tools:
                trace = {"kind": "unknown_tool", "expected": sorted(self._tools), "got": name}
                attempts.append(trace)
                return {"ok": False, "error_trace": trace, "attempts": attempts}
            args = call.get("args", {})
            errors = validate(args, self._tools[name]["schema"])
            if errors:
                trace = {"kind": "validation", "errors": errors,
                         "hint": "fix the args to match the schema and retry"}
                attempts.append(trace)
                if attempt == max_retries:
                    return {"ok": False, "error_trace": trace, "attempts": attempts}
                continue
            try:
                result = self._tools[name]["fn"](**args)
            except Exception as exc:  # tool blew up: report, maybe retry
                trace = {"kind": "execution", "error": str(exc), "exception": type(exc).__name__}
                attempts.append(trace)
                if attempt == max_retries:
                    return {"ok": False, "error_trace": trace, "attempts": attempts}
                continue
            return {"ok": True, "result": result, "attempts": attempts}

    def parse_and_execute(self, raw, max_retries=0):
        """Parse a raw model output string as a JSON tool call, then execute."""
        try:
            call = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            return {"ok": False, "error_trace": {"kind": "parse", "error": str(exc)}}
        return self.execute(call, max_retries=max_retries)
