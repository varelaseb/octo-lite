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
        self.assertIsInstance(record["issue"], str)
        self.assertIsInstance(record["pr"], int)
        self.assertIsInstance(record["goal"], str)
        self.assertIn(record["goal_state"], {"active", "blocked", "complete"})
        self.assertIsInstance(record["last_handoff_at"], str)
        self.assertIn(record["waiting_on"], {"", "spec review", "QA review"})
        self.assertIsInstance(record["workers"], list)
        self.assertEqual(record["workers"][0]["pane"], "w5:pC1")
        self.assertEqual(record["workers"][0]["ticket"], "ANN-64")
        self.assertEqual(record["workers"][0]["role"], "implementer")

    def test_meta_operator_owns_create_and_teardown(self) -> None:
        text = (ROOT / "agents/meta-operator.md").read_text(encoding="utf-8")
        match = re.search(
            r"This role writes no repository files\.(.*?)\n\n- Mutate no repository\.",
            text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, "meta-operator lane-record hook is missing")
        hook = match.group(1)
        self.assertRegex(
            hook,
            r"[Aa]fter\s+spawning\s+a\s+lane\s+orchestrator,\s+create\s+the\s+TOML\s+file\s+directly\s+at\s+`\$\{XDG_STATE_HOME:-~/.local/state\}/octo-lite/lanes/<owner agent name>\.toml`",
        )
        for field in (
            "`owner` pane",
            "`repository`",
            "`issue`",
            "`goal`",
            '`goal_state = "active"`',
        ):
            with self.subTest(field=field):
                self.assertIn(field, hook)
        self.assertRegex(
            hook,
            r"at\s+teardown\s+of\s+the\s+finished\s+lane\s+and\s+its\s+children,\s+delete\s+it",
        )

    def test_orchestrator_owns_record_updates(self) -> None:
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"Orchestrator:\s+as lane owner,\s+use\s+`\$\{XDG_STATE_HOME:-~/.local/state\}/octo-lite/lanes/<owner agent name>\.toml`",
        )
        self.assertRegex(text, r"Set\s+`pr`\s+when a draft PR opens")
        self.assertRegex(
            text,
            re.compile(
                r"worker\s+spawn\s+or\s+close\s+or\s+handoff\s+consumption.*`\[\[workers\]\]`.*`last_handoff_at`",
                flags=re.DOTALL,
            ),
        )
        self.assertRegex(
            text,
            re.compile(r"goal\s+blocked\s+or\s+complete.*`goal_state`", flags=re.DOTALL),
        )
        self.assertRegex(
            text,
            r"when\s+the\s+lane\s+owner\s+hands\s+a\s+human\s+gate\s+\(spec\s+review\s+or\s+QA\s+review\)\s+to\s+the\s+human,\s+the\s+lane\s+owner\s+sets\s+`waiting_on`\s+to\s+`\"spec review\"`\s+or\s+`\"QA review\"`;\s+when\s+the\s+gate\s+resolves,\s+the\s+lane\s+owner\s+sets\s+`waiting_on`\s+to\s+`\"\"`",
        )
        self.assertIn("Only the owner updates the lane record", text)

    def test_implement_spec_points_at_each_owner_update(self) -> None:
        text = (ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "Implement-spec lane record pointers",
            text,
        )
        match = re.search(
            r"Implement-spec lane record pointers:.*?no helper or service writes it\.",
            text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, "implement-spec lane-record paragraph is missing")
        paragraph = match.group(0)
        self.assertIn(
            "the lane owner updates",
            paragraph,
        )
        self.assertIn(
            "`${XDG_STATE_HOME:-~/.local/state}/octo-lite/lanes/<owner agent name>.toml`",
            paragraph,
        )
        self.assertIn(
            "spec/domains/octo-lite.spec.html#lane-record",
            paragraph,
        )
        for event, field in (
            ("draft PR open", "`pr`"),
            ("worker spawn", "`[[workers]]`"),
            ("worker close", "`[[workers]]`"),
            ("handoff consumed", "`last_handoff_at`"),
            ("goal blocked/complete", "`goal_state`"),
        ):
            with self.subTest(event=event):
                event_pattern = re.escape(event).replace("\\ ", r"\s+")
                self.assertRegex(
                    paragraph,
                    rf"{event_pattern},\s+the\s+lane\s+owner\s+updates\s+{re.escape(field)}",
                )
        self.assertRegex(
            paragraph,
            r"when\s+the\s+lane\s+owner\s+hands\s+a\s+human\s+gate\s+\(spec\s+review\s+or\s+QA\s+review\)\s+to\s+the\s+human,\s+the\s+lane\s+owner\s+sets\s+`waiting_on`\s+to\s+`\"spec review\"`\s+or\s+`\"QA review\"`;\s+when\s+the\s+gate\s+resolves,\s+the\s+lane\s+owner\s+sets\s+`waiting_on`\s+to\s+`\"\"`",
        )

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
