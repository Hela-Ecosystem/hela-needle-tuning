import json
import random
import unittest
from pathlib import Path

from hela_needle import evalrun, gate
from hela_needle.catalog import Tool, load_catalog
from hela_needle.examples import arguments_row, build_rows, choose_row, dedupe
from hela_needle.schema import validate_args
from hela_needle.scrub import findings, scrub_text
from hela_needle.splits import split_of

TIME = Tool("hela_mitosis_get_current_time", "Current time", {"type": "object", "properties": {"timezone": {"type": "string"}}, "required": ["timezone"]}, "mitosis")
LS = Tool("hela_membrane_list_directory", "List a directory", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, "membrane")
READ = Tool("hela_membrane_read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, "membrane")
RUN = Tool("hela_nucleus_execute_command", "Run a command", {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}, "nucleus")
CAT = [TIME, LS, READ, RUN]


class Schema(unittest.TestCase):
    def test_required_unknown_type_enum(self):
        s = {"properties": {"a": {"type": "integer"}, "m": {"enum": ["x"]}}, "required": ["a"]}
        self.assertEqual(validate_args(s, {"a": 1}), [])
        self.assertIn("missing required 'a'", validate_args(s, {}))
        self.assertIn("'a' should be integer", validate_args(s, {"a": True}))
        self.assertIn("unknown argument 'z'", validate_args(s, {"a": 1, "z": 1}))
        self.assertIn("'m' not in enum", validate_args(s, {"a": 1, "m": "y"}))


class Scrub(unittest.TestCase):
    def test_redacts_secrets_paths_and_addresses(self):
        text = "token ghp_" + "a" * 30 + " at /home/alice/x from 10.0.0.5 mail me@example.com"
        out = scrub_text(text)
        self.assertEqual(findings(out), [])
        self.assertIn("/workspace/x", out)


class Splits(unittest.TestCase):
    def test_stable_and_regression_always_eval(self):
        self.assertEqual(split_of("same task"), split_of("Same Task "))
        self.assertEqual(split_of("anything", regression=True), "eval")


class Rows(unittest.TestCase):
    def test_choose_row_has_empty_params_and_done(self):
        row = choose_row("what time is it in Paris", TIME.name, CAT, random.Random(1))
        names = [t["name"] for t in row["tools"]]
        self.assertIn(TIME.name, names)
        self.assertEqual(names[-1], "done")
        self.assertTrue(all(t["parameters"] == {"type": "object", "properties": {}} for t in row["tools"]))
        self.assertEqual(row["answers"], [{"name": TIME.name, "arguments": {}}])
        self.assertTrue(row["query"].startswith("Task: what time is it in Paris"))

    def test_arguments_row_validates(self):
        ok = arguments_row("t", TIME.name, {"timezone": "Asia/Tokyo"}, CAT)
        self.assertEqual(ok["tools"][0]["parameters"]["required"], ["timezone"])
        with self.assertRaises(ValueError):
            arguments_row("t", TIME.name, {}, CAT)

    def test_unknown_tool_fails_the_build(self):
        with self.assertRaises(KeyError):
            choose_row("t", "hela_nope", CAT, random.Random(1))

    def test_build_rows_from_seed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text(json.dumps({"task": "list /workspace", "tool": LS.name, "arguments": {"path": "/workspace"}, "regression": True}) + "\n")
            rows = build_rows(p, CAT)
            self.assertEqual([r["meta"]["stage"] for r in rows], ["choose", "arguments"])
            self.assertTrue(all(r["meta"]["split"] == "eval" for r in rows))
            p.write_text(json.dumps({"task": "x", "tool": LS.name, "arguments": {}}) + "\n")
            with self.assertRaises(ValueError):
                build_rows(p, CAT)

    def test_dedupe_keeps_first_per_task_and_stage(self):
        a = choose_row("Same task", TIME.name, CAT, random.Random(1))
        b = choose_row("same task", LS.name, CAT, random.Random(2))
        c = arguments_row("Same task", TIME.name, {"timezone": "UTC"}, CAT)
        for r, st in ((a, "choose"), (b, "choose"), (c, "arguments")):
            r["meta"] = {"stage": st}
        kept = dedupe([a, b, c])
        self.assertEqual(len(kept), 2)
        self.assertIs(kept[0], a)
        pinned = choose_row("Same task", TIME.name, CAT, random.Random(3), pin=[TIME.name, LS.name])
        pinned["meta"] = {"stage": "choose", "pinned": True}
        self.assertEqual(len(dedupe([a, pinned])), 2)

    def test_catalog_qualifies_names(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps([{"name": "read_file", "server": "hela-membrane", "description": "d", "parameters": {"type": "object", "properties": {}}}]))
            self.assertEqual(load_catalog(p)[0].name, "hela_membrane_read_file")
            self.assertEqual(load_catalog(p, "bare")[0].name, "read_file")


class Scoring(unittest.TestCase):
    def _rows(self):
        meta = lambda stage, reg=False: {"stage": stage, "split": "eval", "regression": reg}
        return [
            {"query": "q", "tools": [TIME.declaration(False)], "answers": [{"name": TIME.name, "arguments": {}}], "meta": meta("choose", True)},
            {"query": "q", "tools": [TIME.declaration(True)], "answers": [{"name": TIME.name, "arguments": {"timezone": "Asia/Tokyo"}}], "meta": meta("arguments")},
            {"query": "q", "tools": [TIME.declaration(False)], "answers": [{"name": "done", "arguments": {}}], "meta": meta("choose")},
        ]

    def test_scores(self):
        answers = [
            {"function_calls": [{"name": LS.name, "arguments": {}}]},
            {"function_calls": [{"name": TIME.name, "arguments": {"timezone": "Asia/Tokyo"}}]},
            {"function_calls": [{"name": "done", "arguments": {}}]},
        ]
        it = iter(answers)
        scores = evalrun.evaluate(self._rows(), lambda r: next(it))
        self.assertEqual(scores["choose_tool_acc"], 0.5)
        self.assertEqual(scores["args_valid"], 1.0)
        self.assertEqual(scores["args_exact"], 1.0)
        self.assertEqual(scores["regression_tool_acc"], 0.0)


class Gate(unittest.TestCase):
    BASE = {"n": 40, "choose_tool_acc": 0.5, "args_valid": 0.8, "regression_n": 5, "regression_tool_acc": 0.2}

    def test_pass_and_blocks(self):
        good = {"n": 40, "choose_tool_acc": 0.7, "args_valid": 0.9, "regression_n": 5, "regression_tool_acc": 1.0}
        self.assertEqual(gate.check(good, self.BASE), [])
        self.assertTrue(gate.check({**good, "choose_tool_acc": 0.51}, self.BASE))
        self.assertTrue(gate.check({**good, "args_valid": 0.7}, self.BASE))
        self.assertTrue(gate.check({**good, "regression_tool_acc": 0.8}, self.BASE))
        self.assertTrue(gate.check({**good, "n": 5}, self.BASE))


if __name__ == "__main__":
    unittest.main()
