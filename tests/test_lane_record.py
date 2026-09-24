"""ANN-72 lane-record contract checks."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec/domains/octo-lite.spec.html"


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
        self.assertIsInstance(record["pr"], int)
        self.assertIsInstance(record["goal"], str)
        self.assertIn(record["goal_state"], {"active", "blocked", "complete"})
        self.assertIsInstance(record["last_handoff_at"], str)
        self.assertIsInstance(record["workers"], list)
        self.assertEqual(record["workers"][0]["pane"], "w5:pC1")
        self.assertEqual(record["workers"][0]["ticket"], "ANN-64")
        self.assertEqual(record["workers"][0]["role"], "implementer")

    def test_meta_operator_owns_create_and_teardown(self) -> None:
        text = (ROOT / "agents/meta-operator.md").read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"Meta-operator: after spawning a lane orchestrator, create the TOML file directly at `\$\{XDG_STATE_HOME:-~/.local/state\}/octo-lite/lanes/<owner agent name>\.toml`",
        )
        for field in ("`owner` pane", "`repository`", "`goal`", '`goal_state = "active"`'):
            with self.subTest(field=field):
                self.assertIn(field, text)
        self.assertRegex(
            text,
            r"at teardown of the finished lane and its children, delete it",
        )

    def test_orchestrator_owns_record_updates(self) -> None:
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"Orchestrator: as lane owner, set `pr` when a draft PR opens")
        self.assertRegex(
            text,
            r"worker spawn or close or handoff consumption.*`\[\[workers\]\]`.*`last_handoff_at`",
        )
        self.assertRegex(text, r"goal blocked or complete.*`goal_state`")
        self.assertIn("Only the owner updates the lane record", text)

    def test_implement_spec_points_at_each_owner_update(self) -> None:
        text = (ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "Implement-spec lane record pointers",
            text,
        )
        self.assertIn(
            "spec/domains/octo-lite.spec.html#lane-record",
            text,
        )
        self.assertIn("no helper or service writes it", text)
        for event in (
            "draft PR open",
            "worker spawn",
            "worker close",
            "handoff consumed",
            "goal blocked/complete",
        ):
            with self.subTest(event=event):
                self.assertIn(event, text)

    def test_no_unrelated_file_instructs_lane_record_writes(self) -> None:
        allowed = {
            SPEC,
            ROOT / "agents/meta-operator.md",
            ROOT / "agents/orchestrator.md",
            ROOT / "skills/implement-spec/SKILL.md",
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
