import unittest

from tool_router import ToolRouter, validate

CALC = {
    "type": "object",
    "required": ["op", "a", "b"],
    "additionalProperties": False,
    "properties": {
        "op": {"type": "string", "enum": ["add", "sub", "mul"]},
        "a": {"type": "number"},
        "b": {"type": "number"},
    },
}


def calc(op, a, b):
    return {"add": a + b, "sub": a - b, "mul": a * b}[op]


def router():
    r = ToolRouter()
    r.register("calc", CALC, calc, "arithmetic")
    return r


class TestValidate(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate({"op": "add", "a": 1, "b": 2}, CALC), [])

    def test_missing_required(self):
        errs = validate({"op": "add", "a": 1}, CALC)
        self.assertTrue(any("required" in e["expected"] for e in errs))

    def test_wrong_type(self):
        errs = validate({"op": "add", "a": "x", "b": 2}, CALC)
        self.assertTrue(any(e["path"] == "$.a" for e in errs))

    def test_enum_violation(self):
        errs = validate({"op": "div", "a": 1, "b": 2}, CALC)
        self.assertTrue(any("one of" in e["expected"] for e in errs))

    def test_additional_properties_rejected(self):
        errs = validate({"op": "add", "a": 1, "b": 2, "z": 9}, CALC)
        self.assertTrue(any("additional" in e["expected"] for e in errs))

    def test_bool_not_integer(self):
        self.assertTrue(validate(True, {"type": "integer"}))

    def test_nested_array_items(self):
        schema = {"type": "array", "items": {"type": "integer"}, "minItems": 2}
        self.assertEqual(validate([1, 2], schema), [])
        self.assertTrue(validate([1, "x"], schema))
        self.assertTrue(validate([1], schema))


class TestRouter(unittest.TestCase):
    def test_happy_path(self):
        out = router().execute({"tool": "calc", "args": {"op": "mul", "a": 3, "b": 4}})
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"], 12)

    def test_unknown_tool(self):
        out = router().execute({"tool": "nope", "args": {}})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_trace"]["kind"], "unknown_tool")

    def test_validation_trace_no_retry(self):
        out = router().execute({"tool": "calc", "args": {"op": "add", "a": 1}})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_trace"]["kind"], "validation")

    def test_execution_error_traced(self):
        r = ToolRouter()
        r.register("boom", {"type": "object"}, lambda **kw: 1 / 0)
        out = r.execute({"tool": "boom", "args": {}})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_trace"]["kind"], "execution")

    def test_parse_raw_json(self):
        out = router().parse_and_execute('{"tool": "calc", "args": {"op": "sub", "a": 5, "b": 2}}')
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"], 3)

    def test_parse_garbage(self):
        out = router().parse_and_execute("not json at all")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_trace"]["kind"], "parse")

    def test_retry_attempts_recorded(self):
        calls = {"n": 0}
        def flaky(**kw):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("try again")
            return "done"
        r = ToolRouter()
        r.register("flaky", {"type": "object"}, flaky)
        out = r.execute({"tool": "flaky", "args": {}}, max_retries=2)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["attempts"]), 1)  # one failed attempt before success


if __name__ == "__main__":
    unittest.main()
