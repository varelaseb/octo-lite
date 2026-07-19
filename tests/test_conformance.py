from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_TEXT = (ROOT / "profile", ROOT / "roles", ROOT / "skills", ROOT / "workflows")


class CutoverConformanceTests(unittest.TestCase):
    def test_every_skill_has_compact_style_contract(self) -> None:
        skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertTrue(skills)
        for path in skills:
            text = path.read_text()
            self.assertIn("Be extremely concise. Sacrifice grammar for the sake of concision.", text, path.name)
            self.assertIn("No em-dashes or en-dashes. Ever.", text, path.name)

    def test_active_instructions_have_no_unicode_dashes_or_target_leaks(self) -> None:
        forbidden = ("Turbo-Outreach", "TopicFinder", "codex-uploads", "Notion")
        for root in ACTIVE_TEXT:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".md", ".toml", ".yaml", ".js", ".mjs"}:
                    continue
                text = path.read_text()
                self.assertNotIn("\u2013", text, str(path))
                self.assertNotIn("\u2014", text, str(path))
                for token in forbidden:
                    self.assertNotIn(token, text, str(path))

    def test_issue_shaper_is_progressive_not_a_monolith(self) -> None:
        lines = (ROOT / "skills/octo-lite-issue-shaper/SKILL.md").read_text().splitlines()
        self.assertLessEqual(len(lines), 160)

    def test_workflow_uses_generated_role_names_only(self) -> None:
        text = (ROOT / "workflows/octo-loop-qa.js").read_text()
        for role in ("implementer", "code-reviewer", "qa-capture", "qa-reviewer"):
            self.assertIn(f"agentType: '{role}'", text)
        for stale in ("octo-lite-implementer", "octo-lite-reviewer", "octo-lite-code-reviewer"):
            self.assertNotIn(stale, text)

    def test_install_is_symlink_only_and_checkable(self) -> None:
        installer = ROOT / "scripts/install-octo-lite"
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td)
            subprocess.run([str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True)
            subprocess.run([str(installer), "--prefix", str(prefix), "--check"], check=True)
            self.assertTrue((prefix / ".codex/AGENTS.md").is_symlink())
            self.assertTrue((prefix / ".claude/CLAUDE.md").is_symlink())
            self.assertTrue((prefix / ".claude/workflows/octo-loop-qa.js").is_symlink())
            self.assertEqual((ROOT / "roles").resolve(), (prefix / ".claude/octo-lite/roles").resolve())
            self.assertEqual((ROOT / "skills/tdd").resolve(), (prefix / ".codex/skills/tdd").resolve())

    def test_repo_claude_entrypoint_is_relative_symlink(self) -> None:
        entry = ROOT / "CLAUDE.md"
        self.assertTrue(entry.is_symlink())
        self.assertEqual(Path("AGENTS.md"), entry.readlink())


if __name__ == "__main__":
    unittest.main()
