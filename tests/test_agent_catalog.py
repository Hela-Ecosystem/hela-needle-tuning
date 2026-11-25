import collections
import json
import tempfile
import unittest
from pathlib import Path

from hela_needle import coverage, publish
from hela_needle.agentcat import is_visible, load_exclusions, real_name, visible_names
from hela_needle.catalog import Tool
from hela_needle.examples import build_all
from hela_needle.profiles import cell_active, profile_catalog

PARAMS = {"type": "object", "properties": {"p": {"type": "string"}}, "required": ["p"]}
NONE = {"type": "object", "properties": {}}


def tool(name, cell, params=PARAMS):
    return Tool(name, name, params, cell)


READ = tool("hela_membrane_read_file", "membrane")
LLM = tool("hela_mitosis_llm_summarize", "mitosis")
WORKFLOW = tool("hela_mitosis_workflow_status", "mitosis")
SPAWN = tool("hela_ribosome_agent_spawn", "ribosome")
SESSION = tool("hela_ribosome_session_spawn", "ribosome")
UPDATE = tool("hela.update.check", "runtime", NONE)
CATALOG = [READ, LLM, WORKFLOW, SPAWN, SESSION, UPDATE]


def exclusions():
    d = tempfile.mkdtemp()
    p = Path(d) / "x.json"
    p.write_text(json.dumps({"names": ["workflow_status"], "patterns": ["^llm_.*$", "^agent_(spawn|list)$"]}))
    return p


class AgentCatalog(unittest.TestCase):
    def test_visibility_follows_the_runtime_rules(self):
        names, patterns = load_exclusions(exclusions())
        self.assertTrue(is_visible(READ, names, patterns))
        self.assertTrue(is_visible(SESSION, names, patterns))
        self.assertTrue(is_visible(UPDATE, names, patterns))
        self.assertFalse(is_visible(LLM, names, patterns))  # llm_* pattern
        self.assertFalse(is_visible(WORKFLOW, names, patterns))  # listed by real name
        self.assertFalse(is_visible(SPAWN, names, patterns))  # agent_spawn pattern
        self.assertEqual(real_name(SPAWN), "agent_spawn")
        self.assertEqual(real_name(UPDATE), "hela.update.check")

    def test_visible_names_is_none_without_a_file(self):
        self.assertIsNone(visible_names(CATALOG, "/nonexistent/x.json"))

    def test_runtime_tools_are_active_in_every_profile(self):
        self.assertTrue(cell_active("runtime", ["membrane"]))
        self.assertFalse(cell_active("receptor", ["membrane"]))
        self.assertIn(UPDATE, profile_catalog(CATALOG, ["membrane"]))

    def test_builder_skips_rows_for_tools_the_agent_never_offers(self):
        visible = visible_names(CATALOG, exclusions())
        profiles = {"dev": ["membrane", "mitosis", "ribosome"]}
        lines = [
            {"task": "read a", "tool": READ.name, "arguments": {"p": "x"}},
            {"task": "summarise it", "tool": LLM.name, "arguments": {"p": "x"}},
            {"task": "next after spawn", "tool": READ.name, "history": [{"tool": SPAWN.name, "args": {}, "result": "ok"}]},
            {"task": "check updates", "tool": UPDATE.name},
        ]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
            stats = collections.Counter()
            rows = build_all(d, CATALOG, 7, profiles, None, visible, stats)
        tasks = {r["query"].split("\n")[0] for r in rows}
        self.assertIn("Task: read a", tasks)
        self.assertIn("Task: check updates", tasks)
        self.assertNotIn("Task: summarise it", tasks)
        self.assertNotIn("Task: next after spawn", tasks)  # its history used an excluded tool
        self.assertEqual(stats["not offered to Needle"], 2)
        offered = {t["name"] for r in rows for t in r["tools"]}
        self.assertTrue(offered.isdisjoint({LLM.name, WORKFLOW.name, SPAWN.name}))

    def test_gaps_report_uncovered_tools_and_missing_argument_rows(self):
        visible = visible_names(CATALOG, exclusions())
        profiles = {"dev": ["membrane", "mitosis", "ribosome"]}
        catalog = [t for t in CATALOG if t.name in visible]
        lines = [{"task": "read a", "tool": READ.name}, {"task": "new session", "tool": SESSION.name, "arguments": {"p": "bash"}}]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "s.jsonl").write_text("\n".join(json.dumps({**x, "split": "train"}) for x in lines) + "\n")
            rows = build_all(d, CATALOG, 7, profiles, "dev", visible)
        no_choose, no_args = coverage.gaps(rows, catalog, profiles["dev"])
        self.assertEqual(no_choose, [UPDATE.name])  # nothing trains the runtime tool
        self.assertEqual(no_args, [READ.name])  # read has parameters but no arguments row

    def test_publish_refuses_a_profile_with_untrained_tools(self):
        gaps = {"minimal": (["hela_membrane_read_file"], [])}
        with tempfile.TemporaryDirectory() as d:
            root, models = Path(d) / "r", Path(d) / "m"
            root.mkdir()
            models.mkdir()
            the_plan, problems = publish.plan(models, ["minimal"], root, "t", "o/r", gaps=gaps)
            self.assertIsNone(the_plan)
            self.assertIn("no training row", problems[0])
            # with the override it proceeds to the next check (missing files), not the coverage one
            _, problems = publish.plan(models, ["minimal"], root, "t", "o/r", gaps=gaps, allow_uncovered=True)
            self.assertIn("missing", problems[0])


if __name__ == "__main__":
    unittest.main()
