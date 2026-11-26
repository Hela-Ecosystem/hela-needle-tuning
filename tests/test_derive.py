import json
import random
import tempfile
import unittest
from pathlib import Path

from hela_needle import derive
from hela_needle.catalog import Tool
from hela_needle.examples import build_all

P = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
LS = Tool("hela_membrane_list_directory", "ls", P, "membrane")
READ = Tool("hela_membrane_read_file", "read", P, "membrane")
RUN = Tool("hela_nucleus_execute_command", "run", {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}, "nucleus")
TAP = Tool("hela_receptor_tap", "tap", {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]}, "receptor")
CAT = [LS, READ, RUN, TAP]


def write(d: Path, name: str, lines: list[dict]) -> None:
    (d / name).write_text("\n".join(json.dumps(x) for x in lines) + "\n")


class Derive(unittest.TestCase):
    def pool(self, d):
        write(Path(d), "core.jsonl", [
            {"task": "List the files in /workspace", "tool": LS.name, "arguments": {"path": "/workspace"}},
            {"task": "Read /workspace/a.txt", "tool": READ.name, "arguments": {"path": "/workspace/a.txt"}},
            {"task": "Run the tests", "tool": RUN.name, "arguments": {"command": "npm test"}},
            {"task": "Tap the back button on the phone", "tool": TAP.name, "arguments": {"x": 10}},
            {"task": "hidden eval row", "tool": LS.name, "arguments": {"path": "/x"}, "split": "eval"},
            {"task": "missing required", "tool": READ.name, "arguments": {}},
        ])
        write(Path(d), "chains.jsonl", [{"task": "must be skipped", "tool": LS.name, "arguments": {"path": "/y"}}])
        return derive.load_pool(d, CAT, None)

    def test_pool_skips_eval_invalid_and_derived_files(self):
        with tempfile.TemporaryDirectory() as d:
            tasks = {p["task"] for p in self.pool(d)}
        self.assertEqual(tasks, {"List the files in /workspace", "Read /workspace/a.txt", "Run the tests", "Tap the back button on the phone"})

    def test_chain_rows_walk_the_steps_then_done(self):
        with tempfile.TemporaryDirectory() as d:
            lines = derive.build_chains(self.pool(d), 3, seed=3)
        tasks = {x["task"] for x in lines}
        self.assertEqual(len(tasks), 3)
        one = [x for x in lines if x["task"] == sorted(tasks)[0]]
        steps = [x for x in one if x["tool"] != "done"]
        done = [x for x in one if x["tool"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertNotIn("history", steps[0])
        for i, s in enumerate(steps):
            self.assertEqual(len(s.get("history", [])), i)  # step i has i executed steps behind it
        self.assertEqual(len(done[0]["history"]), len(steps))
        self.assertTrue(all(x["split"] == "train" for x in lines))

    def test_composed_chains_build_without_errors(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            lines = derive.build_chains(self.pool(d), 6, seed=5)
            for x in lines:
                x.pop("note", None)
            write(Path(out), "chains.jsonl", lines)
            profiles = {"dev": ["membrane", "nucleus", "receptor"]}
            rows = build_all(out, CAT, 7, profiles)
        self.assertTrue(any("Recent actions:" in r["query"] for r in rows))

    def test_only_short_single_action_tasks_are_building_blocks(self):
        self.assertTrue(derive.is_simple("List the files in /workspace"))
        self.assertFalse(derive.is_simple("Open the page, then take a screenshot"))
        self.assertFalse(derive.is_simple("First read the file. After that delete it."))
        self.assertFalse(derive.is_simple("x" * 200))
        self.assertFalse(derive.is_simple("Run both tasks at once"))

    def test_indonesian_tasks_get_indonesian_connectors(self):
        rng = random.Random(1)
        text = derive.compose_task(["Tolong buka halaman login", "Cari file log dong"], rng)
        self.assertTrue(any(w in text for w in ("lalu", "terus", "Setelah itu", "kemudian")))

    def test_negatives_only_use_cell_specific_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            lines = derive.build_negatives(self.pool(d), seed=1)
        self.assertEqual([x["task"] for x in lines], ["Tap the back button on the phone"])
        self.assertIsNone(lines[0]["tool"])
        self.assertEqual(lines[0]["inactive_cell"], "receptor")


if __name__ == "__main__":
    unittest.main()
