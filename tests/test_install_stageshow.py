"""The installer fetches the pinned Stageshow skill, never committing it, and a
failed fetch installs everything else, then fails naming it with its fix; the
check names every problem with its fix. Spec: spec/domains/install.spec.html
#install-peers and #install-check; criteria #acceptance-pinned-install,
#acceptance-pinned-install-fail, #acceptance-pinned-no-skillfile, and
#acceptance-check-all. skillfile and npm are stubbed: nothing fetches."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"
OFFLINE = f"{ROOT / 'tests' / 'offline-bin'}"
SKILL_DIRS = (".claude/skills", ".codex/skills", ".agents/skills")
PIN = re.search(r"^github\s+skill\s+stageshow\s+benjitaylor/skills@(\w+)\s+stageshow$",
                (ROOT / "Skillfile").read_text(), re.M).group(1)

# skillfile's observable contract: `skillfile install` deploys each pin in
# Skillfile.lock into agents/skills, with its cache in .skillfile/cache, and
# leaves files it already deployed unchanged.
SKILLFILE = """#!/usr/bin/env python3
import json, sys
from pathlib import Path
assert sys.argv[1:] == ["install", "-q"], sys.argv
pin = json.loads(Path("Skillfile.lock").read_text())["github/skill/stageshow"]
skill = Path("agents/skills/stageshow")
if not skill.exists():
    skill.mkdir(parents=True)
    (skill / ".meta").write_text(json.dumps(pin))
    for name in ("SKILL.md", "package.json", "package-lock.json"):
        (skill / name).write_text("{}")
    Path(".skillfile/cache/stageshow").mkdir(parents=True)
    Path(".skillfile/cache/stageshow/SKILL.md").write_text("{}")
"""
# npm ci installs the lockfile's packages and records them in node_modules.
NPM = """#!/bin/sh
echo "$PWD $*" >>"{log}"
[ "$1" = ci ] && mkdir -p node_modules/playwright-core && echo '{{}}' >node_modules/.package-lock.json
"""


def run(argv, env, cwd=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env, cwd=cwd)


class CloneCase(unittest.TestCase):
    """A fresh clone carrying this clone's installer, Skillfile, lock, and ignores."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.prefix = base / "prefix"
        self.npm_log = base / "npm.log"
        bindir = base / "bin"
        bindir.mkdir()
        for name, body in (("skillfile", SKILLFILE), ("npm", NPM.format(log=self.npm_log))):
            (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        upstream = base / "upstream"
        for rel in ("scripts/install-octo-lite", ".gitignore", "Skillfile", "Skillfile.lock"):
            (upstream / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, upstream / rel)
        (upstream / "agents").mkdir()
        (upstream / "agents/role.md").write_text("role\n")
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "octo-lite"]):
            subprocess.run(["git", "-C", str(upstream), *argv], check=True, env=self.env)
        self.clone = base / "clone"
        subprocess.run(["git", "clone", "-q", str(upstream), str(self.clone)], check=True, env=self.env)
        self.installer = str(self.clone / "scripts/install-octo-lite")
        self.fix = f"run {self.installer} --prefix {self.prefix}"

    def run_installer(self, *extra):
        return run([self.installer, "--prefix", str(self.prefix), *extra], self.env)

    def assert_linked_the_rest(self):
        for rel, source in ((".claude/agents/role.md", "agents/role.md"),
                            (".local/bin/install-octo-lite", "scripts/install-octo-lite")):
            self.assertEqual(os.path.realpath(self.prefix / rel), str(self.clone / source))


class PinnedInstallTest(CloneCase):
    def install(self, *extra):
        r = run([self.installer, "--prefix", str(self.prefix), *extra], self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Stageshow not installed", r.stderr)

    def test_fresh_clone_links_stageshow_at_its_pin_and_stays_clean(self):
        lock = json.loads((self.clone / "Skillfile.lock").read_text())
        self.assertEqual(lock["github/skill/stageshow"]["sha"], PIN)
        self.install()
        skill = self.clone / "agents/skills/stageshow"
        for skill_dir in SKILL_DIRS:
            link = self.prefix / skill_dir / "stageshow"
            with self.subTest(link=str(link)):
                self.assertEqual(os.path.realpath(link), str(skill))
                self.assertEqual(json.loads((link / ".meta").read_text())["sha"], PIN)
                self.assertTrue((link / "node_modules/playwright-core").is_dir(), "no filming deps")
        status = run(["git", "-C", str(self.clone), "status", "--porcelain"], self.env)
        self.assertEqual(status.stdout, "", "the clone must hold no changed or untracked file")
        self.install("--check")

    def test_reinstall_keeps_the_filming_dependencies(self):
        self.install()
        self.install()
        skill = self.clone / "agents/skills/stageshow"
        self.assertEqual(self.npm_log.read_text().splitlines(),
                         [f"{skill} ci --no-audit --no-fund --loglevel=error"])


class FetchFailsTest(CloneCase):
    """The box cannot reach Stageshow's upstream repository."""

    def test_reports_stageshow_not_installed_with_its_fix_and_links_the_rest(self):
        self.env["PATH"] = f"{OFFLINE}:{os.environ['PATH']}"
        r = self.run_installer()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.splitlines()[-1], "Stageshow not installed: skillfile install failed;"
                         f" fix: resolve its error above, then {self.fix}")
        self.assert_linked_the_rest()


class NoSkillfileTest(CloneCase):
    """The box has no skillfile."""

    def setUp(self):
        super().setUp()
        self.env["PATH"] = ":".join(d for d in os.environ["PATH"].split(":")
                                    if not os.path.exists(os.path.join(d, "skillfile")))
        self.skillfile_fix = ("curl -fsSL https://github.com/eljulians/skillfile/releases/latest/download/"
                              f"install.sh | sh, then {self.fix}")

    def test_names_the_command_that_installs_skillfile_and_links_the_rest(self):
        r = self.run_installer()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.splitlines()[-1],
                         f"Stageshow not installed: skillfile not found; fix: {self.skillfile_fix}")
        self.assert_linked_the_rest()

    def test_check_names_every_problem_with_its_fix(self):
        self.run_installer()
        leftover = self.prefix / ".claude/agents/qa-capture.md"
        leftover.symlink_to(self.clone / "agents/role.md")
        r = self.run_installer("--check")
        self.assertEqual(r.returncode, 1, r.stderr)
        problems = [line for line in r.stderr.splitlines() if "; fix: " in line]
        self.assertEqual(problems, [
            f"leftover legacy link: {leftover}; fix: {self.fix}",
            f"Stageshow not installed: skillfile not found; fix: {self.skillfile_fix}",
        ])


if __name__ == "__main__":
    unittest.main()
