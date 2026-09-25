"""Every surface that pushes, opens PRs, or files issues carries the consent gate."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = "only when the target `AGENTS.md` or the developer explicitly authorizes it"
SURFACES = [
    "agents/merger.md",
    "skills/push/SKILL.md",
    "skills/octo-lite-github/SKILL.md",
    "skills/implement-spec/SKILL.md",
]


class ConsentTest(unittest.TestCase):
    def test_outward_actions_need_a_yes(self):
        for rel in SURFACES:
            text = " ".join((ROOT / rel).read_text().split())
            self.assertIn(GATE, text, rel)


if __name__ == "__main__":
    unittest.main()
