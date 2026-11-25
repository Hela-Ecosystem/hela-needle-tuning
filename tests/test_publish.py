import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from hela_needle import publish

GOOD = {"n": 120, "choose_tool_acc": 0.80, "args_valid": 0.95, "args_match": 0.70, "regression_n": 4, "regression_tool_acc": 1.0}
BASE = {"n": 120, "choose_tool_acc": 0.60, "args_valid": 0.90, "args_match": 0.50, "regression_n": 4, "regression_tool_acc": 0.5}


def setup(root: Path, models: Path, profile="minimal", cand=GOOD, base=BASE, evaluated_bytes=b"model-bytes", shipped_bytes=b"model-bytes"):
    (root / "eval" / "candidates").mkdir(parents=True)
    (root / "eval" / "baselines").mkdir(parents=True)
    (models / f"hela-needle3-{profile}.cact").write_bytes(shipped_bytes)
    (root / "eval" / "candidates" / f"{profile}.json").write_text(json.dumps(cand))
    (root / "eval" / "candidates" / f"{profile}.sha256").write_text(hashlib.sha256(evaluated_bytes).hexdigest() + "  x.cact\n")
    (root / "eval" / "baselines" / f"{profile}.json").write_text(json.dumps(base))
    (models / f"meta-{profile}.json").write_text(json.dumps({"train_rows": 751, "eval_rows": 85, "epochs": 3}))


class Publish(unittest.TestCase):
    def run_plan(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            root, models = Path(d) / "repo", Path(d) / "models"
            root.mkdir()
            models.mkdir()
            setup(root, models, **kw)
            return publish.plan(models, ["minimal"], root, "models-1", "o/r", git_sha="abc", catalog_sha="def")

    def test_passing_model_is_planned_with_checksum_and_url(self):
        the_plan, problems = self.run_plan()
        self.assertEqual(problems, [])
        e = the_plan["entries"][0]
        self.assertEqual(e["sha256"], hashlib.sha256(b"model-bytes").hexdigest())
        self.assertEqual(e["url"], "https://github.com/o/r/releases/download/models-1/hela-needle3-minimal.cact")
        self.assertEqual(e["trained_on"]["train_rows"], 751)
        self.assertEqual(e["base"]["license"], "Apache-2.0")

    def test_swapped_file_is_refused(self):
        the_plan, problems = self.run_plan(shipped_bytes=b"different")
        self.assertIsNone(the_plan)
        self.assertIn("not the file that was evaluated", problems[0])

    def test_failing_gate_is_refused(self):
        the_plan, problems = self.run_plan(cand={**GOOD, "choose_tool_acc": 0.61})
        self.assertIsNone(the_plan)
        self.assertIn("gate fails", problems[0])

    def test_missing_evaluation_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root, models = Path(d) / "repo", Path(d) / "models"
            root.mkdir()
            models.mkdir()
            (models / "hela-needle3-minimal.cact").write_bytes(b"x")
            the_plan, problems = publish.plan(models, ["minimal"], root, "t", "o/r")
            self.assertIsNone(the_plan)
            self.assertIn("missing", problems[0])

    def test_manifest_keeps_other_profiles(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "manifest.json"
            publish.apply_manifest(m, {"entries": [{"profile": "research", "file": "a"}]})
            out = publish.apply_manifest(m, {"entries": [{"profile": "minimal", "file": "b"}]})
            self.assertEqual(list(out["models"]), ["minimal", "research"])


if __name__ == "__main__":
    unittest.main()
