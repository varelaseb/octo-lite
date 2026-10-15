"""install-octo-lite --project links the skills a target declares on its
AGENTS.md `Repo skills:` line from the given checkout, and warns on a stale
link without touching it. Spec: spec/domains/octo-lite.spec.html
#install-repo-skills; criteria #acceptance-repo-skills-link and
#acceptance-repo-skills-stale."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"
SKILL_DIRS = (".claude/skills", ".codex/skills", ".agents/skills")


def make_checkout(path: Path, line: str, skills: tuple[str, ...]) -> Path:
    for rel in skills:
        (path / rel).mkdir(parents=True)
        (path / rel / "SKILL.md").write_text(f"---\nname: {Path(rel).name}\n---\n")
    (path / "AGENTS.md").write_text(f"# Agent Instructions\n\n{line}\n- Spec format: markdown\n")
    return path


class InstallRepoSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name).resolve()
        self.prefix = tmp / "prefix"
        skills = ("skills/ui-rules", "tools/lint/house-style")
        self.checkout = make_checkout(
            tmp / "main", "- Repo skills: skills/ui-rules, tools/lint/house-style", skills
        )
        self.other_clone = make_checkout(
            tmp / "old-clone", "- Repo skills: skills/ui-rules, tools/lint/house-style", skills
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _install(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(INSTALLER), "--prefix", str(self.prefix), *extra],
            capture_output=True,
            text=True,
        )

    def test_links_each_declared_skill_from_checkout(self) -> None:
        result = self._install("--project", str(self.checkout))
        self.assertEqual(0, result.returncode, result.stderr)
        for rel in ("skills/ui-rules", "tools/lint/house-style"):
            for skill_dir in SKILL_DIRS:
                link = self.prefix / skill_dir / Path(rel).name
                with self.subTest(link=str(link)):
                    self.assertTrue(link.is_symlink(), f"missing {link}")
                    self.assertEqual(str(self.checkout / rel), os.path.realpath(link))
        check = self._install("--check", "--project", str(self.checkout))
        self.assertEqual(0, check.returncode, check.stderr)

    def test_check_fails_when_declared_skill_is_not_linked(self) -> None:
        self.assertEqual(0, self._install().returncode)
        check = self._install("--check", "--project", str(self.checkout))
        self.assertNotEqual(0, check.returncode, "--check must flag a declared skill left unlinked")

    def _plant_stale(self) -> Path:
        stale = self.prefix / ".claude" / "skills" / "ui-rules"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.symlink_to(self.other_clone / "skills" / "ui-rules")
        return stale

    def _assert_stale_warned(self, result: subprocess.CompletedProcess, stale: Path) -> None:
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        warning = [l for l in result.stderr.splitlines() if "stale" in l and str(stale) in l]
        self.assertTrue(warning, f"no stale warning naming {stale}: {result.stderr}")
        self.assertIn(str(self.other_clone), warning[0])
        self.assertEqual(str(self.other_clone / "skills" / "ui-rules"), os.readlink(stale))

    def test_install_warns_on_stale_link_leaves_it_and_continues(self) -> None:
        stale = self._plant_stale()
        result = self._install("--project", str(self.checkout))
        self._assert_stale_warned(result, stale)
        # The rest of the declared skills still link from the checkout.
        codex = self.prefix / ".codex" / "skills" / "ui-rules"
        self.assertEqual(str(self.checkout / "skills" / "ui-rules"), os.path.realpath(codex))
        house = self.prefix / ".claude" / "skills" / "house-style"
        self.assertEqual(str(self.checkout / "tools" / "lint" / "house-style"), os.path.realpath(house))

    def test_check_warns_on_stale_link_and_exits_zero(self) -> None:
        self.assertEqual(0, self._install("--project", str(self.checkout)).returncode)
        stale = self.prefix / ".claude" / "skills" / "ui-rules"
        stale.unlink()
        stale.symlink_to(self.other_clone / "skills" / "ui-rules")
        self._assert_stale_warned(self._install("--check", "--project", str(self.checkout)), stale)

    def test_dangling_link_into_removed_clone_is_stale(self) -> None:
        stale = self._plant_stale()
        (self.other_clone / "skills" / "ui-rules" / "SKILL.md").unlink()
        (self.other_clone / "skills" / "ui-rules").rmdir()
        self._assert_stale_warned(self._install("--project", str(self.checkout)), stale)


if __name__ == "__main__":
    unittest.main()
