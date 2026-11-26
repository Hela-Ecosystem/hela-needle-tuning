import json
import random
import tempfile
import unittest
from pathlib import Path

from hela_needle.catalog import Tool
from hela_needle.examples import DONE_COPIES, build_rows, dedupe, hard_shortlist, similar_tools

PATH = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}


def tool(name: str, desc: str, cell: str) -> Tool:
    return Tool(name, desc, PATH, cell)


READ = tool("hela_membrane_read_file", "Read the text content of a file", "membrane")
INFO = tool("hela_membrane_get_file_info", "Get the size, permissions and modification time of a file", "membrane")
LS = tool("hela_membrane_list_directory", "List the files in a directory", "membrane")
WRITE = tool("hela_membrane_write_file", "Write text content to a file", "membrane")
TIME = tool("hela_mitosis_get_current_time", "Current time in a timezone", "mitosis")
SQL = tool("hela_genome_execute_sql", "Run a SQL statement on the memory database", "genome")
CAT = [READ, INFO, LS, WRITE, TIME, SQL]


def seeds(lines):
    d = tempfile.mkdtemp()
    p = Path(d) / "s.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf8")
    return p


class HardNegatives(unittest.TestCase):
    def test_look_alikes_rank_by_shared_words_and_cell(self):
        near = [t.name for t in similar_tools(READ, CAT, 3)]
        self.assertIn(INFO.name, near)
        self.assertNotIn(SQL.name, near)

    def test_hard_shortlist_holds_the_anchor_and_is_deterministic(self):
        a = hard_shortlist(READ, CAT, random.Random("x"))
        b = hard_shortlist(READ, CAT, random.Random("x"))
        self.assertEqual(a, b)
        self.assertIn(READ.name, a)
        self.assertEqual(len(a), 4)
        self.assertEqual(len(set(a)), 4)

    def test_train_rows_get_a_hard_copy_and_eval_rows_do_not(self):
        p = seeds([
            {"task": "Show me the contents of /workspace/a.txt", "tool": READ.name, "arguments": {"path": "/workspace/a.txt"}, "split": "train"},
            {"task": "Show me the contents of /workspace/b.txt", "tool": READ.name, "arguments": {"path": "/workspace/b.txt"}, "split": "eval"},
        ])
        plain = build_rows(p, CAT)
        hard = build_rows(p, CAT, hard=True)
        # the plain rows are untouched, so the frozen eval stays frozen
        self.assertEqual([json.dumps(r, sort_keys=True) for r in plain], [json.dumps(r, sort_keys=True) for r in hard if "variant" not in r["meta"]])
        extra = [r for r in hard if r["meta"].get("variant")]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0]["meta"]["split"], "train")
        self.assertEqual(extra[0]["meta"]["stage"], "choose")
        self.assertEqual(extra[0]["answers"][0]["name"], READ.name)
        self.assertIn(READ.name, [t["name"] for t in extra[0]["tools"]])
        self.assertEqual(sum(1 for r in hard if r["meta"]["split"] == "eval"), sum(1 for r in plain if r["meta"]["split"] == "eval"))

    def test_done_after_history_gets_several_copies_with_the_last_tool_in_view(self):
        p = seeds([{"task": "Read /workspace/a.txt and stop", "tool": "done", "split": "train",
                    "history": [{"tool": READ.name, "args": {"path": "/workspace/a.txt"}, "result": "ok"}]}])
        extra = [r for r in build_rows(p, CAT, hard=True) if r["meta"].get("variant")]
        self.assertEqual(len(extra), DONE_COPIES)
        for r in extra:
            self.assertEqual(r["answers"][0]["name"], "done")
            self.assertIn(READ.name, [t["name"] for t in r["tools"]])
        self.assertEqual(len({json.dumps(r["tools"], sort_keys=True) for r in extra}) > 1, True)

    def test_dedupe_keeps_the_hard_copy(self):
        p = seeds([{"task": "Show me the contents of /workspace/a.txt", "tool": READ.name, "split": "train"}])
        self.assertEqual(len(dedupe(build_rows(p, CAT, hard=True))), 2)


if __name__ == "__main__":
    unittest.main()
