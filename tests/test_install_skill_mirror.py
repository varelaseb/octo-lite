"""ADR 0002 skill-management: scripts/install-octo-lite must place the
skillfile-managed agents/skills tree into .claude/skills and .codex/skills, and
--check must verify that mirror invariant: every managed skill present in
agents/skills resolves identically from .claude/skills and .codex/skills.
Seams named by ADR 0002 decision-install-targets + decision-install-check."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"
MANAGED_SKILLS = ("tdd", "spec-chat-review", "spec-chat-shape")


class InstallSkillMirrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.prefix = Path(self._tmp.name) / "prefix"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _install(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(INSTALLER), "--prefix", str(self.prefix), *extra],
            capture_output=True,
            text=True,
        )

    def test_install_mirrors_managed_skill_into_both_platforms(self) -> None:
        result = self._install()
        self.assertEqual(0, result.returncode, result.stderr)
        for managed_skill in MANAGED_SKILLS:
            with self.subTest(managed_skill=managed_skill):
                claude = self.prefix / ".claude" / "skills" / managed_skill
                codex = self.prefix / ".codex" / "skills" / managed_skill
                self.assertTrue(claude.exists(), f"missing {claude}")
                self.assertTrue(codex.exists(), f"missing {codex}")
                self.assertEqual(
                    os.path.realpath(claude),
                    os.path.realpath(codex),
                    "managed skill must resolve identically from .claude/skills and .codex/skills",
                )
                self.assertEqual(
                    os.path.realpath(claude),
                    str((ROOT / "agents" / "skills" / managed_skill).resolve()),
                    "mirror source must be the agents/skills managed tree",
                )

    def test_check_passes_after_clean_install(self) -> None:
        self.assertEqual(0, self._install().returncode)
        check = self._install("--check")
        self.assertEqual(0, check.returncode, check.stderr)

    def test_check_fails_when_managed_mirror_is_broken(self) -> None:
        self.assertEqual(0, self._install().returncode)
        (self.prefix / ".codex" / "skills" / MANAGED_SKILLS[0]).unlink()
        check = self._install("--check")
        self.assertNotEqual(0, check.returncode, "--check must flag a broken managed-skill mirror")


class VendoredSkillLocationTest(unittest.TestCase):
    """The vendored tdd skill is materialized into agents/skills, not skills/
    (ADR 0002)."""

    def test_vendored_tdd_lives_only_in_agents_skills(self) -> None:
        self.assertFalse(
            (ROOT / "skills" / MANAGED_SKILLS[0] / "SKILL.md").exists(),
            "tdd must no longer live under skills/",
        )
        self.assertTrue((ROOT / "agents" / "skills" / MANAGED_SKILLS[0] / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
