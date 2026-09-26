"""Lane record example contract checks."""

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
            {"", "spec review", "QA review", "merge", "blocked", "operator"},
        )
        self.assertIsInstance(record["workers"], list)
        self.assertEqual(record["workers"][0]["pane"], "w5:pC1")
        self.assertEqual(record["workers"][0]["ticket"], "ANN-64")
        self.assertEqual(record["workers"][0]["role"], "implementer")
        tickets = {t["key"]: t for t in record["tickets"]}
        self.assertEqual(tickets["ANN-64"]["state"], "active")
        for ticket in tickets.values():
            self.assertIn(ticket["state"], {"waiting", "ready", "active", "done"})
            self.assertIsInstance(ticket["passes"], int)
            self.assertRegex(ticket["since"], UTC)

    def test_operator_launch_example_writes_started_at(self) -> None:
        text = OPERATOR.read_text(encoding="utf-8")
        match = re.search(r"```toml\n(.*?)```", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "operator launch example is missing")
        record = tomllib.loads(match.group(1))
        self.assertRegex(record["started_at"], UTC)
        self.assertIn("operator.toml", text)


if __name__ == "__main__":
    unittest.main()
