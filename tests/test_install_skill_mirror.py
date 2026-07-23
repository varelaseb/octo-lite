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
MANAGED_SKILL = "tdd"


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
        claude = self.prefix / ".claude" / "skills" / MANAGED_SKILL
        codex = self.prefix / ".codex" / "skills" / MANAGED_SKILL
        self.assertTrue(claude.exists(), f"missing {claude}")
        self.assertTrue(codex.exists(), f"missing {codex}")
        self.assertEqual(
            os.path.realpath(claude),
            os.path.realpath(codex),
            "managed skill must resolve identically from .claude/skills and .codex/skills",
        )
        self.assertEqual(
            os.path.realpath(claude),
            str((ROOT / "agents" / "skills" / MANAGED_SKILL).resolve()),
            "mirror source must be the agents/skills managed tree",
        )

    def test_check_passes_after_clean_install(self) -> None:
        self.assertEqual(0, self._install().returncode)
        check = self._install("--check")
        self.assertEqual(0, check.returncode, check.stderr)

    def test_check_fails_when_managed_mirror_is_broken(self) -> None:
        self.assertEqual(0, self._install().returncode)
        (self.prefix / ".codex" / "skills" / MANAGED_SKILL).unlink()
        check = self._install("--check")
        self.assertNotEqual(0, check.returncode, "--check must flag a broken managed-skill mirror")


class ManagedSkillResolutionTests(unittest.TestCase):
    """The role resolver must resolve the vendored tdd skill from the managed
    agents/skills tree, not only from skills/ (ADR 0002)."""

    def test_vendored_tdd_resolves_from_agents_skills(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from workflows.lib import role_resolver

        self.assertFalse(
            (ROOT / "skills" / MANAGED_SKILL / "SKILL.md").exists(),
            "tdd must no longer live under skills/",
        )
        self.assertTrue((ROOT / "agents" / "skills" / MANAGED_SKILL / "SKILL.md").is_file())
        # Resolves without raising because it is found in agents/skills.
        self.assertTrue(role_resolver._skill_blob(ROOT, MANAGED_SKILL))
        with self.assertRaises(ValueError):
            role_resolver._skill_blob(ROOT, "no-such-skill-xyz")


if __name__ == "__main__":
    unittest.main()
