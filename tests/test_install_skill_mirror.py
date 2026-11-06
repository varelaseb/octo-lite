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
# skillfile stubbed unreachable: installer runs never fetch.
OFFLINE = f"{ROOT / 'tests' / 'offline-bin'}:{os.environ['PATH']}"


def problems(run):
    """The problems a run names, but Stageshow's: offline, it is never fetched."""
    return [line for line in run.stderr.splitlines()
            if "; fix: " in line and not line.startswith("Stageshow not installed")]
# Only genuinely third-party skills stay skillfile-managed. spec-chat is a
# peer repository linked from a clone, so it is not part of this invariant.
MANAGED_SKILLS = ("tdd",)


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
            env={**os.environ, "PATH": OFFLINE},
        )

    def test_install_mirrors_managed_skill_into_both_platforms(self) -> None:
        result = self._install()
        self.assertEqual([], problems(result), result.stderr)
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
        self.assertEqual([], problems(self._install()))
        check = self._install("--check")
        self.assertEqual([], problems(check), check.stderr)

    def test_run_through_path_symlink_resolves_root_to_clone(self) -> None:
        self.assertEqual([], problems(self._install()))
        link = self.prefix / ".local" / "bin" / "install-octo-lite"
        if not link.is_symlink():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(INSTALLER)
        check = subprocess.run(
            [str(link), "--prefix", str(self.prefix), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual([], problems(check), check.stdout + check.stderr)

    def test_check_fails_when_managed_mirror_is_broken(self) -> None:
        self.assertEqual([], problems(self._install()))
        (self.prefix / ".codex" / "skills" / MANAGED_SKILLS[0]).unlink()
        check = self._install("--check")
        self.assertNotEqual([], problems(check), "--check must flag a broken managed-skill mirror")

    def test_real_file_collision_skips_without_overwrite(self) -> None:
        target = self.prefix / ".claude" / "skills" / "commit"
        target.parent.mkdir(parents=True)
        target.write_text("operator-owned\n", encoding="utf-8")

        result = self._install()

        self.assertEqual([], problems(result))
        self.assertIn("skipped:", result.stdout)
        self.assertEqual("operator-owned\n", target.read_text(encoding="utf-8"))

    def test_role_contracts_are_symlinked_for_both_clis(self) -> None:
        result = self._install()
        self.assertEqual([], problems(result), result.stderr)
        for platform in (".claude", ".codex"):
            target = self.prefix / platform / "agents" / "implementer.md"
            self.assertTrue(target.is_symlink(), target)
            self.assertEqual(
                (ROOT / "agents" / "implementer.md").resolve(),
                target.resolve(),
            )


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
