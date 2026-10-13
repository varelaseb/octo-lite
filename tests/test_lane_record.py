"""Contract checks: octo-lite's published lane record format and its one
acceptance record, read back by their own spec keys."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec/domains/octo-lite.spec.html"
OPERATOR = ROOT / "agents/meta-operator.md"
UTC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


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

        self.assertRegex(record["owner"], r"^w\d+:p")
        self.assertIsInstance(record["repository"], str)
        self.assertIsInstance(record["issue"], str)
        self.assertIsInstance(record["pr"], int)
        self.assertIsInstance(record["last_handoff_at"], str)
        self.assertRegex(record["started_at"], UTC)
        self.assertIn(
            record["waiting_on"],
            {"", "blocked", "operator"},
        )
        self.assertNotIn("workers", record)
        tickets = {t["key"]: t for t in record["tickets"]}
        self.assertEqual(tickets["ANN-64"]["state"], "active")
        for ticket in tickets.values():
            self.assertIn(ticket["state"], {"waiting", "ready", "active", "done"})
            self.assertIsInstance(ticket["passes"], int)
            self.assertRegex(ticket["since"], UTC)

    def test_acceptance_has_one_record_the_pr_receipt(self) -> None:
        contracts = [*ROOT.glob("agents/*.md"), *ROOT.glob("skills/**/SKILL.md")]
        for path in contracts:
            self.assertNotIn("octo-lite/acceptance/", path.read_text(encoding="utf-8"), path)
        html = SPEC.read_text(encoding="utf-8")
        table = re.search(r'id="handoff-operator".*?<tbody>(.*?)</tbody>', html, flags=re.DOTALL)
        self.assertIsNotNone(table, "operator log table is missing")
        kinds = re.findall(r"<tr[^>]*><td><code>(\w+)</code>", table.group(1))
        self.assertEqual(kinds, ["note", "prod"])
        self.assertNotRegex(OPERATOR.read_text(encoding="utf-8"), r"gate relay|merge executed")

    def test_owner_posts_spec_receipt_on_accept_spec_handoff(self) -> None:
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"Accept spec hand-off.*gh pr comment.*Spec acceptance receipt: human")

    def test_operator_launch_example_writes_started_at(self) -> None:
        text = OPERATOR.read_text(encoding="utf-8")
        match = re.search(r"```toml\n(.*?)```", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "operator launch example is missing")
        record = tomllib.loads(match.group(1))
        self.assertRegex(record["started_at"], UTC)
        self.assertIn("operator.toml", text)


if __name__ == "__main__":
    unittest.main()
