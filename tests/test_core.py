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

    def test_history_is_rendered_like_the_runtime(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text(json.dumps({
                "task": "list then read", "tool": READ.name, "arguments": {"path": "/workspace/a.txt"},
                "history": [{"tool": LS.name, "args": {"path": "/workspace"}, "result": "ok: a.txt"},
                            {"tool": READ.name, "args": {"path": "/x"}, "error": "ENOENT"}],
            }) + "\n")
            rows = build_rows(p, CAT)
            q = rows[0]["query"]
            self.assertIn("Recent actions:\n" + LS.name + '({"path":"/workspace"}) -> ok: a.txt\n' + READ.name + '({"path":"/x"}) -> ERROR ENOENT', q)
            self.assertTrue(q.endswith("Call done when every requested action is complete."))
            self.assertTrue(rows[1]["query"].rstrip().endswith("Generate the arguments for this tool call."))
            self.assertTrue(rows[0]["meta"]["history"])
            p.write_text(json.dumps({"task": "t", "tool": None, "history": [{"tool": "hela_nope", "args": {}}]}) + "\n")
            with self.assertRaises(ValueError):
                build_rows(p, CAT)

    def test_dedupe_separates_same_task_with_different_history(self):
        a = choose_row("Same task", TIME.name, CAT, random.Random(1), history="x -> y")
        b = choose_row("Same task", TIME.name, CAT, random.Random(2), history="x -> z")
        for r in (a, b):
            r["meta"] = {"stage": "choose"}
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_profiles_restrict_the_shortlist_and_inactive_cells_get_none(self):
        import tempfile
        from hela_needle.profiles import profile_catalog
        phone = Tool("hela_receptor_tap", "Tap the screen", {"type": "object", "properties": {}}, "receptor")
        cat = CAT + [phone]
        profiles = {"dev": ["membrane", "mitosis", "nucleus"], "android": ["receptor", "nucleus"]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            lines = [
                {"task": "tap the screen", "tool": phone.name},
                {"task": "tap the home icon on the phone", "tool": None, "inactive_cell": "receptor"},
                {"task": "list /x", "tool": LS.name, "profile": "dev"},
            ]
            p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
            rows = build_rows(p, cat, profiles=profiles)
            by_task = {r["query"].split("\n")[0]: r for r in rows}
            tap = by_task["Task: tap the screen"]
            self.assertEqual(tap["meta"]["profile"], "android")  # only profile with receptor
            self.assertTrue(all(t["name"] != LS.name for t in tap["tools"]))  # membrane is inactive there
            neg = by_task["Task: tap the home icon on the phone"]
            self.assertEqual(neg["meta"]["profile"], "dev")  # receptor inactive
            self.assertEqual(neg["meta"]["kind"], "none")
            self.assertTrue(all(t["name"] != phone.name for t in neg["tools"]))
            p.write_text(json.dumps({"task": "x", "tool": phone.name, "profile": "dev"}) + "\n")
            with self.assertRaises(ValueError):
                build_rows(p, cat, profiles=profiles)

    def test_only_profile_builds_a_dedicated_dataset(self):
        import tempfile
        from hela_needle.examples import build_all
        phone = Tool("hela_receptor_tap", "Tap the screen", {"type": "object", "properties": {}}, "receptor")
        cat = CAT + [phone]
        profiles = {"dev": ["membrane", "mitosis", "nucleus"], "android": ["receptor", "nucleus"]}
        lines = [
            {"task": "tap the screen", "tool": phone.name},
            {"task": "list /x", "tool": LS.name},
            {"task": "tap the phone icon", "tool": None, "inactive_cell": "receptor"},
            {"task": "what time is it in Rome", "tool": TIME.name},
            {"task": "list then read", "tool": READ.name, "history": [{"tool": phone.name, "args": {}, "result": "ok"}]},
            {"task": "all done", "tool": "done"},
        ]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
            dev = build_all(d, cat, 7, profiles, "dev")
            tasks = {r["query"].split("\n")[0] for r in dev}
            self.assertIn("Task: list /x", tasks)
            self.assertIn("Task: tap the phone icon", tasks)  # receptor is inactive in dev: right answer is none
            self.assertIn("Task: all done", tasks)
            self.assertNotIn("Task: tap the screen", tasks)  # needs receptor
            self.assertNotIn("Task: list then read", tasks)  # history uses a receptor tool
            self.assertTrue(all(r["meta"]["profile"] == "dev" for r in dev))
            self.assertTrue(all(t["name"] != phone.name for r in dev for t in r["tools"]))
            android = build_all(d, cat, 7, profiles, "android")
            self.assertNotIn("Task: tap the phone icon", {r["query"].split("\n")[0] for r in android})
            with self.assertRaises(ValueError):
                build_all(d, cat, 7, profiles, "nope")

    def test_row_randomness_is_independent_of_other_rows(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a.jsonl"
            b = Path(d) / "b.jsonl"
            a.write_text(json.dumps({"task": "show the folder", "tool": LS.name}) + "\n")
            b.write_text(json.dumps({"task": "something else", "tool": RUN.name}) + "\n" + json.dumps({"task": "show the folder", "tool": LS.name}) + "\n")
            only = build_rows(a, CAT)[0]
            after = [r for r in build_rows(b, CAT) if r["query"].startswith("Task: show the folder")][0]
            self.assertEqual(only["tools"], after["tools"])

    def test_seed_can_force_split(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text(json.dumps({"task": "zzz force me", "tool": None, "split": "eval"}) + "\n")
            self.assertEqual(build_rows(p, CAT)[0]["meta"]["split"], "eval")
            p.write_text(json.dumps({"task": "x", "tool": None, "split": "dev"}) + "\n")
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


class Generated(unittest.TestCase):
    def test_convert_keeps_valid_and_counts_rejections(self):
        from hela_needle.generated import convert
        ok = {"query": "Show what is in the reports folder", "answers": [{"name": LS.name, "arguments": {"path": "/workspace/reports"}}]}
        rows = [
            ok,
            dict(ok),  # duplicate
            {"query": "Show what is in the reports folder please", "answers": [{"name": "hela_nope", "arguments": {}}]},
            {"query": "List the folder with a missing path", "answers": [{"name": LS.name, "arguments": {}}]},
            {"query": "Do two things at once now", "answers": [{"name": LS.name, "arguments": {"path": "/a"}}, {"name": READ.name, "arguments": {"path": "/b"}}]},
            {"query": "Tell me a joke about cats", "answers": []},
            {"query": "hi", "answers": []},
            {"query": "use token ghp_" + "b" * 30 + " to log in", "answers": []},
        ]
        seeds, rejected = convert(rows, CAT)
        self.assertEqual([s["tool"] for s in seeds], [LS.name, None])
        self.assertEqual(seeds[0]["arguments"], {"path": "/workspace/reports"})
        self.assertEqual(rejected["duplicate task"], 1)
        self.assertEqual(rejected["unknown tool"], 1)
        self.assertEqual(rejected["invalid arguments"], 1)
        self.assertEqual(rejected["multiple calls"], 1)
        self.assertEqual(rejected["task length"], 1)
        self.assertEqual(rejected["secret-like text in task"], 1)
        # generic home paths are not secrets; the builder rewrites them later
        kept, _ = convert([{"query": "Read the file at /home/user/notes.txt", "answers": [{"name": READ.name, "arguments": {"path": "/home/user/notes.txt"}}]}], CAT)
        self.assertEqual(len(kept), 1)


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
        self.assertEqual(scores["args_match"], 1.0)
        self.assertEqual(scores["regression_tool_acc"], 0.0)

    def test_details_record_each_row(self):
        details = []
        evalrun.evaluate(self._rows(), lambda r: {"function_calls": [{"name": LS.name, "arguments": {}}]}, details)
        self.assertEqual(len(details), 3)
        self.assertEqual(details[0]["expected"], TIME.name)
        self.assertEqual(details[0]["got"], LS.name)
        self.assertFalse(details[0]["tool_ok"])


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
