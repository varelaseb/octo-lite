"""ANN-72 lane-record contract checks."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec/domains/octo-lite.spec.html"
LANES = "octo-lite/lanes/<owner agent name>.toml"
PHASES = ("shaping", "shaping review", "implementing", "merging", "code review",
          "QA", "waiting on human", "closing")


class LaneRecordTests(unittest.TestCase):
    def test_spec_example_is_valid_toml_with_declared_types(self) -> None:
        html = SPEC.read_text(encoding="utf-8")
        match = re.search(
            r'<pre data-anchor="octo-lane-record-example"><code>(.*?)</code></pre>',
            html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, "lane record example is missing")
        record = tomllib.loads(unescape(match.group(1)))

        self.assertIsInstance(record["owner"], str)
        self.assertIsInstance(record["repository"], str)
        self.assertIsInstance(record["issue"], str)
        self.assertIsInstance(record["pr"], int)
        self.assertIsInstance(record["goal"], str)
        self.assertIn(record["goal_state"], {"active", "blocked", "complete"})
        self.assertIsInstance(record["last_handoff_at"], str)
        self.assertIn(record["waiting_on"], {"", "spec review", "QA review"})
        self.assertIn(record["phase"], PHASES)
        self.assertIsInstance(record["workers"], list)
        self.assertEqual(record["workers"][0]["pane"], "w5:pC1")
        self.assertEqual(record["workers"][0]["ticket"], "ANN-64")
        self.assertEqual(record["workers"][0]["role"], "implementer")

    def test_meta_operator_hook_names_create_and_delete_fields(self) -> None:
        text = (ROOT / "agents/meta-operator.md").read_text(encoding="utf-8")
        for term in (LANES, "`owner`", "`repository`", "`issue`", "`goal`",
                     '`goal_state = "active"`', '`phase = "shaping"`', "delete it"):
            with self.subTest(term=term):
                self.assertIn(term, text)

    def test_orchestrator_hook_names_every_field(self) -> None:
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        for term in (LANES, "`issue`", "`pr`", "`[[workers]]`", "`last_handoff_at`",
                     "`goal_state`", "`waiting_on`", '`"spec review"`',
                     '`"QA review"`', '`""`', "`phase`", "`pane`", "`ticket`",
                     "`role`", *(f'`"{p}"`' for p in PHASES)):
            with self.subTest(term=term):
                self.assertIn(term, text)

    def test_no_unrelated_file_instructs_lane_record_writes(self) -> None:
        allowed = {
            SPEC,
            ROOT / "agents/meta-operator.md",
            ROOT / "agents/orchestrator.md",
            Path(__file__),
        }
        for path in ROOT.rglob("*"):
            if not path.is_file() or path in allowed or ".git" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("octo-lite/lanes/", text)


if __name__ == "__main__":
    unittest.main()
