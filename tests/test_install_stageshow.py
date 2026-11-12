"""The installer fetches the pinned Stageshow skill, never committing it, and a
failed fetch installs everything else, then fails naming it with its fix; the
check names every problem with its fix. Spec: spec/domains/install.spec.html
#install-peers and #install-check; criteria #acceptance-pinned-install,
#acceptance-pinned-install-fail, #acceptance-pinned-no-skillfile, and
#acceptance-check-all; and every install run passes as the first, each skill
folder holding only its tracked files: #install-recorder,
#acceptance-install-again, and #acceptance-after-pull-recorder-deps. skillfile
and npm are stubbed: nothing fetches."""

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
# Runtime tools stubbed at their floors: a verifying run finds them on any box.
FLOORS = ROOT / "tests" / "floor-bin"
SKILL_DIRS = (".claude/skills", ".codex/skills", ".agents/skills")
PIN = re.search(r"^github\s+skill\s+stageshow\s+benjitaylor/skills@(\w+)\s+stageshow$",
                (ROOT / "Skillfile").read_text(), re.M).group(1)

# skillfile's observable contract: `skillfile install` deploys each pin in
# Skillfile.lock into agents/skills, with its cache in .skillfile/cache, and
# leaves files it already deployed unchanged. It writes a local skill's tracked
# files only, so a local skill folder holding a file git does not track fails it.
SKILLFILE = """#!/usr/bin/env python3
import json, subprocess, sys
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
for entry in Path("Skillfile").read_text().splitlines():
    field = entry.split()
    if field[:2] != ["local", "skill"] or not Path(field[3]).is_dir():
        continue
    name, folder = field[2:4]
    files = sum(f.is_file() for f in Path(folder).rglob("*"))
    written = len(subprocess.run(["git", "ls-files", "--", folder], capture_output=True,
                                 text=True, check=True).stdout.splitlines())
    if written < files:
        sys.exit(f"error: failed to install '{name}' to octo-lite skill (agents/skills):"
                 f" only {written} of {files} expected file(s) were written")
"""
# npm ci installs the lockfile's packages and records them in node_modules;
# npm exec runs the recorder driver's browser install.
NPM = """#!/bin/sh
echo "$PWD $*" >>"{log}"
[ "$1" = ci ] && mkdir -p node_modules/playwright-core && echo '{{}}' >node_modules/.package-lock.json
exit 0
"""


def run(argv, env, cwd=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env, cwd=cwd)


class CloneCase(unittest.TestCase):
    """A fresh clone carrying this clone's installer, Skillfile, lock, and
    ignores, and the round video recorder's stand-in folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.prefix = base / "prefix"
        self.npm_log = base / "npm.log"
        self.bindir = bindir = base / "bin"
        bindir.mkdir()
        for name, body in (("skillfile", SKILLFILE), ("npm", NPM.format(log=self.npm_log))):
            (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bindir}:{FLOORS}:{os.environ['PATH']}",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        upstream = base / "upstream"
        scripts = [str(path.relative_to(ROOT)) for path in (ROOT / "scripts").iterdir() if path.is_file()]
        for rel in (*scripts, ".gitignore", "Skillfile", "Skillfile.lock"):
            (upstream / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, upstream / rel)
        (upstream / "agents").mkdir()
        (upstream / "agents/role.md").write_text("role\n")
        for name in ("package.json", "package-lock.json"):
            (upstream / name).write_text("{}")
        recorder = upstream / "skills/implement-spec/assets/prototype-video"
        recorder.mkdir(parents=True)
        (recorder / "prototype-video").write_text("#!/bin/sh\n")
        (recorder / "prototype-video").chmod(0o755)
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "octo-lite"]):
            subprocess.run(["git", "-C", str(upstream), *argv], check=True, env=self.env)
        self.clone = base / "clone"
        subprocess.run(["git", "clone", "-q", str(upstream), str(self.clone)], check=True, env=self.env)
        self.recorder = self.clone / recorder.relative_to(upstream)
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

    def assert_skills_hold_only_tracked_files(self):
        status = run(["git", "-C", str(self.clone), "status", "--porcelain", "--ignored", "--", "skills"], self.env)
        self.assertEqual(status.stdout, "", "a skill folder must hold only its tracked files")

    def test_second_install_passes_as_the_first(self):
        # spec/domains/install.spec.html#acceptance-install-again, and
        # box-lock.spec.html#acceptance-lock-installed: each helper linked
        self.install()
        self.install()
        self.assert_skills_hold_only_tracked_files()
        helpers = sorted(path.name for path in (self.clone / "scripts").iterdir())
        self.assertIn("octo-lite-lock", helpers)
        for name in helpers:
            with self.subTest(helper=name):
                self.assertEqual(os.path.realpath(self.prefix / ".local/bin" / name),
                                 str(self.clone / "scripts" / name))

    def test_after_pull_removes_recorder_deps_left_in_its_folder(self):
        # spec/domains/install.spec.html#acceptance-after-pull-recorder-deps
        stray = self.recorder / "node_modules/playwright-core"
        stray.mkdir(parents=True)
        (stray / "package.json").write_text("{}")
        self.install("--after-pull")
        self.assert_skills_hold_only_tracked_files()

    def test_reinstall_keeps_the_filming_dependencies(self):
        self.install()
        self.install()
        skill = self.clone / "agents/skills/stageshow"
        self.assertEqual([line for line in self.npm_log.read_text().splitlines()
                          if line.startswith(f"{skill} ")],
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
        (self.bindir / "skillfile").unlink()
        self.env["PATH"] = ":".join(d for d in self.env["PATH"].split(":")
                                    if not os.path.exists(os.path.join(d, "skillfile")))
        self.skillfile_fix = ("curl -fsSL https://github.com/eljulians/skillfile/releases/latest/download/"
                              f"install.sh | sh, then {self.fix}")

    def test_names_the_command_that_installs_skillfile_and_links_the_rest(self):
        r = self.run_installer()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.splitlines()[-1],
                         f"Stageshow not installed: skillfile not found; fix: {self.skillfile_fix}")
        self.assert_linked_the_rest()

    def test_every_mode_names_it_over_an_earlier_stageshow(self):
        """An earlier install's Stageshow stays with its filming dependencies
        current, but no pin change can arrive: check, install, and after-pull
        give one verdict, named last."""
        deps = self.clone / "agents/skills/stageshow/node_modules"
        deps.mkdir(parents=True)
        (deps / ".package-lock.json").write_text("{}")
        named = f"Stageshow not installed: skillfile not found; fix: {self.skillfile_fix}"
        for mode in ((), ("--check",), ("--after-pull",)):
            with self.subTest(mode=mode):
                r = self.run_installer(*mode)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertEqual(r.stderr.splitlines()[-1], named)

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
