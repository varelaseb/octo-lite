"""The installer fetches the pinned Stageshow skill, never committing it, and a
failed fetch installs everything else, then fails naming it with its fix; the
check names every problem with its fix. Spec: spec/domains/install.spec.html
#install-peers and #install-check; criteria #acceptance-pinned-install,
#acceptance-pinned-install-fail, #acceptance-pinned-no-skillfile, and
#acceptance-check-all; and every install run passes as the first, each skill
folder holding only its tracked files: #install-recorder,
#acceptance-install-again, and #acceptance-after-pull-recorder-deps. Stageshow
gets octo-lite's patch, after a pull too, and its driver's Chromium, which
--check names when missing, and no browser install removes another lane's
browser: #install-stageshow-browser, #acceptance-check-no-browser, and
#acceptance-browser-install-keeps. skillfile and npm are stubbed: nothing
fetches."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_install_keys import give_keys

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"
OFFLINE = f"{ROOT / 'tests' / 'offline-bin'}"
# Runtime tools stubbed at their floors: a verifying run finds them on any box.
FLOORS = ROOT / "tests" / "floor-bin"
SKILL_DIRS = (".claude/skills", ".codex/skills", ".agents/skills")
PIN = re.search(r"^github\s+skill\s+stageshow\s+benjitaylor/skills@(\w+)\s+stageshow$",
                (ROOT / "Skillfile").read_text(), re.M).group(1)

# skillfile's observable contract, as skillfile 1.9.2 behaves: `skillfile
# install` fetches each pin of Skillfile.lock into .skillfile/cache, here from
# the stand-in GitHub's tree at that sha, again whenever the lock's sha differs
# from the cached one, and deploys each file of it missing from agents/skills,
# applying its patch in .skillfile/patches as git apply does, leaving files it
# already deployed unchanged, across pin changes too. A patch that no longer
# applies leaves .skillfile/conflict and the file missing, and fails it. It
# writes a local skill's tracked files only, so a local skill folder holding a
# file git does not track fails it.
SKILLFILE = """#!/usr/bin/env python3
import json, shutil, subprocess, sys
from pathlib import Path
assert sys.argv[1:] == ["install", "-q"], sys.argv
pin = json.loads(Path("Skillfile.lock").read_text())["github/skill/stageshow"]
cache, skill = Path(".skillfile/cache/skills/stageshow"), Path("agents/skills/stageshow")
meta = cache / ".meta"
if not meta.exists() or json.loads(meta.read_text())["sha"] != pin["sha"]:
    shutil.rmtree(cache, ignore_errors=True)
    shutil.copytree(Path(__file__).parents[1] / "github" / pin["sha"], cache)
    meta.write_text(json.dumps(pin))
for upstream in cache.rglob("*"):
    rel = upstream.relative_to(cache)
    if upstream.is_dir() or (skill / rel).exists():
        continue
    (skill / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(upstream, skill / rel)
    patch = Path(".skillfile/patches/skills/stageshow", f"{rel}.patch").resolve()
    if patch.exists() and subprocess.run(["git", "apply", patch], cwd=skill).returncode:
        (skill / rel).unlink()
        Path(".skillfile/conflict").write_text(str(rel))
        sys.exit(f"error: patch for {rel} does not apply")
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
# npm exec runs a driver's browser install, a Chromium named for the folder it
# runs in, or with --dry-run lists where that goes. Unless told to skip it, the
# install removes each browser no driver it installed for names, as
# Playwright's does.
NPM = """#!/bin/sh
echo "$PWD $*" >>"{log}"
browser="$PLAYWRIGHT_BROWSERS_PATH/chromium-${{PWD##*/}}"
case "$*" in
  ci\\ *) mkdir -p node_modules/playwright-core && echo '{{}}' >node_modules/.package-lock.json ;;
  "exec -- playwright-core install --dry-run chromium") echo "  Install location:    $browser" ;;
  "exec -- playwright-core install chromium")
    mkdir -p "$browser" "$PLAYWRIGHT_BROWSERS_PATH/.links"
    touch "$browser/INSTALLATION_COMPLETE" "$PLAYWRIGHT_BROWSERS_PATH/.links/${{browser##*/}}"
    [ -n "$PLAYWRIGHT_SKIP_BROWSER_GC" ] || for b in "$PLAYWRIGHT_BROWSERS_PATH"/*; do
      [ -e "$PLAYWRIGHT_BROWSERS_PATH/.links/${{b##*/}}" ] || rm -rf "$b"
    done ;;
esac
exit 0
"""

PATCH = ".skillfile/patches/skills/stageshow/scripts/browser.mjs.patch"


def browser_patch(line):
    """A real diff adding LINE to the stub's upstream browser.mjs."""
    return "".join(difflib.unified_diff(["upstream\n"], ["upstream\n", line],
                                        "a/scripts/browser.mjs", "b/scripts/browser.mjs"))


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
        give_keys(self.prefix)
        self.npm_log = base / "npm.log"
        self.bindir = bindir = base / "bin"
        bindir.mkdir()
        for name, body in (("skillfile", SKILLFILE), ("npm", NPM.format(log=self.npm_log))):
            (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.github = base / "github"
        self.upstream_at(PIN)
        self.browsers = base / "browsers"
        self.env = {**os.environ, "PATH": f"{bindir}:{FLOORS}:{os.environ['PATH']}",
                    "PLAYWRIGHT_BROWSERS_PATH": str(self.browsers),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        upstream = base / "upstream"
        scripts = [str(path.relative_to(ROOT)) for path in (ROOT / "scripts").iterdir() if path.is_file()]
        patches = [str(path.relative_to(ROOT)) for path in (ROOT / ".skillfile/patches").rglob("*.patch")]
        for rel in (*scripts, *patches, ".gitignore", "Skillfile", "Skillfile.lock"):
            (upstream / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, upstream / rel, follow_symlinks=False)
        (upstream / PATCH).write_text(browser_patch("patched\n"))
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
        self.stageshow = self.clone / "agents/skills/stageshow"

    def upstream_at(self, sha, browser="upstream\n"):
        """Stageshow's tree at SHA on the stand-in GitHub the skillfile stub
        fetches from, its browser lookup reading BROWSER."""
        tree = self.github / sha
        (tree / "scripts").mkdir(parents=True)
        for name in ("SKILL.md", "package.json", "package-lock.json"):
            (tree / name).write_text("upstream\n")
        (tree / "scripts/browser.mjs").write_text(browser)

    def bump_pin(self, sha):
        """Pulls a Skillfile.lock pinning Stageshow at SHA."""
        lock = json.loads((self.clone / "Skillfile.lock").read_text())
        lock["github/skill/stageshow"]["sha"] = sha
        (self.clone / "Skillfile.lock").write_text(json.dumps(lock, indent=2) + "\n")

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
        # spec/domains/install.spec.html#acceptance-install-again: each helper linked
        self.install()
        self.install()
        self.assert_skills_hold_only_tracked_files()
        for helper in (self.clone / "scripts").iterdir():
            with self.subTest(helper=helper.name):
                self.assertEqual(os.path.realpath(self.prefix / ".local/bin" / helper.name),
                                 os.path.realpath(helper))

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
        self.assertEqual([line for line in self.npm_log.read_text().splitlines()
                          if line.startswith(f"{self.stageshow} ci ")],
                         [f"{self.stageshow} ci --no-audit --no-fund --loglevel=error"])


class StageshowBrowserTest(CloneCase):
    """Stageshow's browser: octo-lite's patch to its lookup and the Chromium
    its driver installs."""

    def install(self, *extra):
        r = self.run_installer(*extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def browser_lookup(self):
        return (self.stageshow / "scripts/browser.mjs").read_text()

    def assert_after_pull_deploys_the_pulled_patch(self, older):
        """Installs under a patch adding the line OLDER, or none for "", then
        pulls the current one: --after-pull deploys it, once, keeping the
        filming dependencies."""
        patch = self.clone / PATCH
        text = patch.read_text()
        if older:
            patch.write_text(browser_patch(older))
        else:
            patch.unlink()
        self.install()
        self.assertEqual(self.browser_lookup(), "upstream\n" + older)
        patch.write_text(text)
        self.install("--after-pull")
        self.assertEqual(self.browser_lookup(), "upstream\npatched\n", "the pulled patch must apply")
        self.assertEqual([line for line in self.npm_log.read_text().splitlines()
                          if line.startswith(f"{self.stageshow} ci ")],
                         [f"{self.stageshow} ci --no-audit --no-fund --loglevel=error"],
                         "the filming dependencies must be kept")
        self.install("--after-pull")
        self.assertEqual(self.browser_lookup(), "upstream\npatched\n", "the patch applies once")

    def test_after_pull_patches_a_stageshow_fetched_without_the_patch(self):
        # spec/domains/install.spec.html#install-stageshow-browser: pulling and
        # installing are safe in any order
        self.assert_after_pull_deploys_the_pulled_patch("")

    def test_after_pull_deploys_the_patch_over_an_older_one(self):
        # spec/domains/install.spec.html#install-after-pull: the after-pull step
        # brings the box onto the pulled code, its patch too
        self.assert_after_pull_deploys_the_pulled_patch("older patch\n")

    def test_check_names_stageshow_without_its_browser(self):
        # spec/domains/install.spec.html#acceptance-check-no-browser
        self.install()
        shutil.rmtree(self.browsers / "chromium-stageshow")
        r = self.run_installer("--check")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.splitlines(), [
            f"Stageshow not installed: no browser, its Chromium not installed; fix: {self.fix}"])

    def test_browser_installs_keep_another_lanes_browser(self):
        # spec/domains/install.spec.html#acceptance-browser-install-keeps
        other = self.browsers / "chromium-other-lane"
        other.mkdir(parents=True)
        (other / "INSTALLATION_COMPLETE").touch()
        self.install()
        self.assertTrue((self.browsers / "chromium-stageshow/INSTALLATION_COMPLETE").exists())
        self.assertTrue((self.browsers / "chromium-clone/INSTALLATION_COMPLETE").exists())
        self.assertTrue(other.is_dir(), "another lane's browser must stay on the box")

    def test_a_pin_the_patch_no_longer_applies_to_fails_naming_the_fix(self):
        # spec/domains/install.spec.html#install-stageshow-browser and
        # #acceptance-check-lines: a pin change the patch no longer applies to,
        # after an install that left the filming dependencies and Chromium
        self.install()
        self.upstream_at("d" * 40, browser="drifted upstream\n")
        self.bump_pin("d" * 40)
        line = ("Stageshow not installed: octo-lite's patch no longer applies to its pin; fix: pull a fixed"
                f" octo-lite, run skillfile resolve --abort in {self.clone}, then {self.fix}")
        r = self.run_installer()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.splitlines()[-1], line)
        self.assert_linked_the_rest()
        r = self.run_installer("--check")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.splitlines(), [line])


class FetchFailsTest(CloneCase):
    """The box cannot reach Stageshow's upstream repository."""

    def test_reports_stageshow_not_installed_with_its_fix_and_links_the_rest(self):
        self.env["PATH"] = f"{OFFLINE}:{os.environ['PATH']}"
        r = self.run_installer()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.splitlines()[-1], "Stageshow not installed: skillfile install failed;"
                         f" fix: resolve its error above, then {self.fix}")
        self.assert_linked_the_rest()

    def test_leaves_an_earlier_stageshow_as_it_found_it(self):
        # spec/domains/install.spec.html#install-stageshow-browser: pulling and
        # installing are safe in any order, a failed fetch over an earlier
        # install's current Stageshow too
        r = self.run_installer()
        self.assertEqual(r.returncode, 0, r.stderr)
        browser = self.stageshow / "scripts/browser.mjs"
        found = browser.read_text()
        self.env["PATH"] = f"{OFFLINE}:{os.environ['PATH']}"
        r = self.run_installer()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(browser.is_file(), "a failed fetch must leave the deployed patched file")
        self.assertEqual(browser.read_text(), found)


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
