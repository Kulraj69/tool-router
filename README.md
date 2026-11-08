# tool-router

Deterministic tool-call validation and retry-trace routing for LLM agents.
Offline, standard library only, no model calls.

Covers two list items at once: "Strict Pydantic Tool Router" (validate tool
calls against schemas, retry with the error trace) and "Grammar-Constrained
Output Enforcer" (force structured outputs to be valid before acting on
them). Agents hallucinate API parameters; this turns stochastic output into
checked actions.

```python
from tool_router import ToolRouter

router = ToolRouter()
router.register("calc", {
    "type": "object",
    "required": ["op", "a", "b"],
    "additionalProperties": False,
    "properties": {
        "op": {"type": "string", "enum": ["add", "sub", "mul"]},
        "a": {"type": "number"},
        "b": {"type": "number"},
    },
}, lambda op, a, b: {"add": a + b, "sub": a - b, "mul": a * b}[op])

out = router.parse_and_execute('{"tool": "calc", "args": {"op": "mul", "a": 3, "b": 4}}')
# {"ok": True, "result": 12, "attempts": []}
```

Failed calls never raise: they return a structured `error_trace` (unknown
tool, schema violation with paths, execution exception, unparseable output)
that a model or a rule-based repair loop can consume on the next attempt.
Schema support: types, required, properties, additionalProperties, enum,
items, min/max, minLength/maxLength.

Honest scope: validation enforces shape, not semantic correctness. A valid
call can still be the wrong action - pair with trajectory grading and a
sandboxed executor for that.

## Tests

```
python3 -m unittest discover -s tests
```
