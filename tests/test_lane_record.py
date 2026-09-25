"""ANN-99 lane-record format checks."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec/domains/octo-lite.spec.html"
LANES = "octo-lite/lanes/<owner agent name>.toml"


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
        self.assertIsInstance(record["goal"], str)
        self.assertIsInstance(record["pr"], int)
        self.assertIsInstance(record["last_handoff_at"], str)
        self.assertIn(record["waiting_on"], {"", "spec review", "QA review", "blocked"})
        self.assertIsInstance(record["workers"], list)
        self.assertEqual(record["workers"][0]["pane"], "w5:pC1")
        self.assertEqual(record["workers"][0]["ticket"], "ANN-64")
        self.assertEqual(record["workers"][0]["role"], "implementer")
        self.assertEqual(
            set(record),
            {
                "owner",
                "repository",
                "issue",
                "goal",
                "pr",
                "last_handoff_at",
                "waiting_on",
                "workers",
            },
        )
        self.assertEqual(set(record["workers"][0]), {"pane", "ticket", "role"})

    def test_spec_links_workbench_format_and_declares_write_moments(self) -> None:
        html = SPEC.read_text(encoding="utf-8")
        match = re.search(
            r'<section data-anchor="lane-record".*?</section>',
            html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, "lane record section is missing")
        section = match.group(0)
        self.assertNotIn("goal_state", section)
        self.assertNotIn("phase", section)
        self.assertIn(
            "https://github.com/varelaseb/annotateanything/blob/main/"
            "docs/specs/worklane-provider.spec.html#lane-record",
            section,
        )
        for key in ("last_handoff_at", "ticket", "role"):
            with self.subTest(key=key):
                self.assertIn(f"<code>{key}</code>", section)
        for key in ("issue", "pr", "waiting_on"):
            with self.subTest(key=key):
                self.assertIn(f"<code>{key}</code>", section)
        self.assertIn(
            "Creates it with the shared workbench fields, including owner, "
            "repository, goal, and issue when known",
            section,
        )
        self.assertIn(
            "Shaping opens the draft pull request</td><td>Owner</td><td>"
            "Sets <code>issue</code> if missing and <code>pr</code>.",
            section,
        )
        self.assertIn(
            "Sets <code>waiting_on</code> to spec review or QA review; clears it"
            " when the gate resolves.",
            section,
        )

    def test_meta_operator_hook_names_create_and_delete_fields(self) -> None:
        text = (ROOT / "agents/meta-operator.md").read_text(encoding="utf-8")
        for term in (
            LANES,
            "shared workbench lane-record fields",
            "waiting_on",
            "delete it",
        ):
            with self.subTest(term=term):
                self.assertIn(term, text)

    def test_orchestrator_hook_names_every_field(self) -> None:
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        for term in (
            LANES,
            "last_handoff_at",
            "`issue`",
            "`pr`",
            "`[[workers]]`",
            "`waiting_on`",
            '`"spec review"`',
            '`"QA review"`',
            '`"blocked"`',
            '`""`',
            "`pane`",
            "`ticket`",
            "`role`",
        ):
            with self.subTest(term=term):
                self.assertIn(term, text)

    def test_orchestrator_hook_edits_in_place_with_quoted_handoff_time(self) -> None:
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        for term in ("in place", "never creates or rewrites",
                     "quoted UTC string", "#octo-lane-record-example"):
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
