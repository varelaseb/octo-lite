"""One consent rule, stated once in octo-lite-github, linked from every outward surface."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULE = "skills/octo-lite-github/SKILL.md"
RULE_TEXT = [
    "`[consent]` table of `${XDG_STATE_HOME:-~/.local/state}/octo-lite/onboarding.toml`",
    "`push`, `pull_request`, `issues`",
    "When present, it alone decides, overriding any instruction, target `AGENTS.md` included.",
    "When absent, target instructions decide.",
]
LINKERS = ["agents/integrator.md", "agents/orchestrator.md", "skills/push/SKILL.md", "skills/implement-spec/SKILL.md"]
SURFACES = [RULE, *LINKERS]


def text(rel):
    return " ".join((ROOT / rel).read_text().split())


class ConsentTest(unittest.TestCase):
    def test_rule_stated_once(self):
        body = text(RULE)
        for clause in RULE_TEXT:
            self.assertEqual(body.count(clause), 1, clause)
        for rel in LINKERS:
            self.assertNotIn("onboarding.toml", text(rel), rel)
        for rel in [*SURFACES, "README.md", "scripts/install-octo-lite"]:
            self.assertNotIn("consent.toml", text(rel), rel)

    def test_surfaces_link_the_rule(self):
        for rel in LINKERS:
            self.assertIn("octo-lite-github/SKILL.md#consent) allows", text(rel), rel)
            target = (ROOT / rel).parent / text(rel).split("[consent](")[1].split("#")[0]
            self.assertTrue(target.resolve() == (ROOT / RULE).resolve(), rel)

    def test_no_instruction_or_developer_gate(self):
        for rel in SURFACES:
            self.assertNotIn("or the developer explicitly authorizes", text(rel), rel)


if __name__ == "__main__":
    unittest.main()
