"""Fresh-install test of octo-lite's own onboarding (ADR peer boundaries):
consent asked and kept, onboarding.toml published in octo-lite's own state,
and the start command installed on PATH."""

import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install-octo-lite"
SPAWN = ROOT / "skills/herdr-comms/assets/herdr-spawn"
# skillfile stubbed unreachable: installer runs never fetch.
OFFLINE = f"{ROOT / 'tests/offline-bin'}:{os.environ['PATH']}"


def problems(run):
    """The problems a run names, but Stageshow's: offline, it is never fetched."""
    return [line for line in run.stderr.splitlines()
            if "; fix: " in line and not line.startswith("Stageshow not installed")]


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.prefix = Path(tmp.name) / "prefix"
        # --prefix is the one root: an exported XDG home must stay untouched.
        self.sentinel = Path(tmp.name) / "xdg"
        self.sentinel.mkdir()
        self.env = {**os.environ, "PATH": OFFLINE, "XDG_STATE_HOME": str(self.sentinel / "state"),
                    "XDG_CONFIG_HOME": str(self.sentinel / "config")}
        self.onboarding = self.prefix / ".local/state/octo-lite/onboarding.toml"

    def run_installer(self, *extra, answers=""):
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), *extra],
                           input=answers, capture_output=True, text=True, env=self.env)
        self.assertEqual(problems(r), [], r.stderr)
        return r

    def install(self, *extra, answers=""):
        self.run_installer(*extra, answers=answers)
        return tomllib.loads(self.onboarding.read_text())

    def test_plain_install_is_pending_and_asks_nothing(self):
        state = self.install()
        self.assertEqual(state["status"], "pending")
        self.assertTrue(state["doc"].endswith("README.md#onboarding"))
        self.assertNotIn("consent", state)

    def test_onboard_keeps_consent_in_onboarding_file_and_is_done(self):
        state = self.install("--onboard", answers="y\nn\n\n")
        self.assertEqual(state["status"], "done")
        kept = {"push": True, "pull_request": False, "issues": False}
        self.assertEqual(state["consent"], kept)
        self.assertEqual(list(self.onboarding.parent.iterdir()), [self.onboarding])
        # kept: a second onboarding does not ask again or change the answers
        self.assertEqual(self.install("--onboard", answers="n\ny\ny\n")["consent"], kept)
        # a plain install keeps the answers and the done status
        state = self.install()
        self.assertEqual((state["status"], state["consent"]), ("done", kept))
        self.assertFalse((self.prefix / ".config/octo-lite").exists())

    def test_after_pull_runs_this_clone_with_the_last_prefix_and_project(self):
        checkout = self.prefix.parent / "project"
        checkout.mkdir()
        (checkout / "AGENTS.md").write_text("# project\n")
        step = [str(INSTALLER.resolve()), "--after-pull", "--prefix", str(self.prefix.resolve())]
        state = self.install("--onboard", "--project", str(checkout), answers="y\ny\ny\n")
        self.assertEqual(state["after_pull"], [*step, "--project", str(checkout.resolve())])
        # every run rewrites it, below a kept [consent] table
        state = self.install()
        self.assertEqual((state["after_pull"], state["status"]), (step, "done"))

    def test_check_writes_no_state(self):
        self.install()
        self.onboarding.unlink()
        self.run_installer("--check")
        self.assertFalse(self.onboarding.exists())

    def test_every_run_records_the_clone_commit(self):
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(self.install()["commit"], head)

    def test_start_command_is_on_path(self):
        self.install()
        start = self.prefix / ".local/bin/octo-lite-start"
        self.assertEqual(start.resolve(), (ROOT / "scripts/octo-lite-start").resolve())

    # --- Spec Chat wake provider ------------------------------------------

    def with_herdr(self):
        bindir = self.prefix / "fakebin"
        bindir.mkdir(parents=True)
        (bindir / "herdr").write_text("#!/bin/sh\n")
        (bindir / "herdr").chmod(0o755)
        self.env["PATH"] = f"{bindir}:{self.env['PATH']}"

    wake = property(lambda self: self.prefix / ".local/state/spec-chat/hosting/default/providers/wake.toml")

    def test_herdr_box_registers_the_waker_and_undo_keeps_it(self):
        """Gap 6: undo keeps wake.toml because spec-chat depends on it."""
        self.with_herdr()
        self.install()
        waker = str(self.prefix / ".local/bin/herdr-wake")
        self.assertEqual(tomllib.loads(self.wake.read_text()), {
            "check": [waker, "check", "{owner}"],
            "send": [waker, "send", "{owner}", "{artifact}", "{message}"],
        })
        self.assertEqual(Path(waker).resolve(), (ROOT / "skills/herdr-comms/assets/herdr-wake").resolve())
        self.install("--undo")
        self.assertTrue(self.wake.exists(), "wake.toml should survive undo")

    def test_prefix_writes_nothing_under_exported_xdg(self):
        self.with_herdr()
        self.install("--onboard", answers="y\ny\ny\n")
        self.assertTrue(self.wake.exists())
        self.assertEqual(list(self.sentinel.iterdir()), [])

    def test_install_keeps_a_foreign_wake_file(self):
        self.with_herdr()
        self.wake.parent.mkdir(parents=True)
        self.wake.write_text('check = ["other"]\n')
        self.install()
        self.assertEqual(self.wake.read_text(), 'check = ["other"]\n')

    def test_undo_keeps_a_changed_wake_file(self):
        self.with_herdr()
        self.install()
        self.wake.write_text('check = ["other"]\n')
        self.install("--undo")
        self.assertTrue(self.wake.exists())

    def test_no_herdr_no_wake_file(self):
        self.env["PATH"] = f"{ROOT / 'tests/offline-bin'}:/usr/bin:/bin"
        self.install()
        self.assertFalse(self.wake.exists())

    # --- Dangling link safety (F-D2) -----------------------------------------

    def test_foreign_dangling_link_is_reported_and_left_untouched(self):
        """A dangling link not pointing into this repo is never deleted."""
        skills = self.prefix / ".claude/skills"
        skills.mkdir(parents=True)
        foreign = skills / "my-own-skill"
        foreign.symlink_to("/nonexistent/foreign/path")
        r = self.run_installer()
        self.assertTrue(foreign.is_symlink(), "foreign dangling link was deleted")
        self.assertIn("not ours", r.stderr)

    def test_foreign_dangling_link_at_install_path_is_left(self):
        """A foreign dangling link at a path the installer links is not replaced."""
        skills = self.prefix / ".claude/skills"
        skills.mkdir(parents=True)
        foreign = skills / "commit"
        foreign.symlink_to("/nonexistent/foreign/commit")
        r = self.run_installer()
        self.assertEqual(os.readlink(foreign), "/nonexistent/foreign/commit")
        self.assertIn(f"skipped: {foreign}", r.stdout)

    def test_own_dangling_link_is_pruned(self):
        """A dangling link pointing into this repo is pruned."""
        skills = self.prefix / ".claude/skills"
        skills.mkdir(parents=True)
        own = skills / "deleted-skill"
        own.symlink_to(str(ROOT / "nonexistent-deleted-skill"))
        r = self.run_installer()
        self.assertFalse(own.exists() or own.is_symlink(), "own dangling link was not pruned")
        self.assertIn("pruned", r.stdout)

    def test_dangling_link_into_other_same_origin_clone_is_pruned(self):
        """A dangling link into another clone of this repo (same origin) is ours."""
        origin = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"],
                                capture_output=True, text=True, check=True).stdout.strip()
        clone = self.prefix.parent / "other-clone"
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", origin], check=True)
        agents = self.prefix / ".claude/agents"
        agents.mkdir(parents=True)
        own = agents / "merger.md"
        own.symlink_to(str(clone / "agents/merger.md"))
        r = self.run_installer()
        self.assertFalse(own.is_symlink(), "same-origin dangling link was not pruned")
        self.assertNotIn("not ours", r.stderr)

    def test_live_link_into_nested_same_origin_worktree_is_adopted(self):
        """A live link into a same-origin clone nested in this repo is adopted."""
        origin = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"],
                                capture_output=True, text=True, check=True).stdout.strip()
        (ROOT / ".claude/worktrees").mkdir(parents=True, exist_ok=True)
        nested = tempfile.TemporaryDirectory(dir=ROOT / ".claude/worktrees")
        self.addCleanup(nested.cleanup)
        clone = Path(nested.name)
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", origin], check=True)
        (clone / "agents").mkdir()
        (clone / "agents/implementer.md").write_text("x")
        agents = self.prefix / ".claude/agents"
        agents.mkdir(parents=True)
        link = agents / "implementer.md"
        link.symlink_to(str(clone / "agents/implementer.md"))
        r = self.run_installer()
        self.assertIn(f"adopted: {link}", r.stdout)

    def test_foreign_dangling_link_in_bin_is_left(self):
        """A dangling link in ~/.local/bin not pointing into this repo is left."""
        bindir = self.prefix / ".local/bin"
        bindir.mkdir(parents=True)
        foreign = bindir / "my-own-tool"
        foreign.symlink_to("/nonexistent/user/tool")
        self.install()
        self.assertTrue(foreign.is_symlink(), "foreign dangling bin link was deleted")

    # --- Spec Chat skill linking removed (F-D3) ------------------------------

    def test_spec_chat_skills_are_not_linked(self):
        """octo-lite no longer links spec-chat skills (ADR-004)."""
        self.install()
        for name in ("spec-chat-shape", "spec-chat-review"):
            self.assertFalse((self.prefix / ".claude/skills" / name).exists(),
                             f"{name} should not be linked by octo-lite")
            self.assertFalse((self.prefix / ".codex/skills" / name).exists(),
                             f"{name} should not be linked by octo-lite")

    # --- Version floors -------------------------------------------------------

    def test_check_reports_version_floors(self):
        """--check prints version floor status for runtime tools."""
        self.run_installer()
        r = self.run_installer("--check")
        self.assertIn("version floors", r.stdout)
        self.assertIn("git:", r.stdout)

    def test_check_names_a_dangling_link_of_ours_once_fixed_by_install(self):
        """Install replaces a dangling link of ours, so the check names it once
        with install as its fix, never as a link to move aside."""
        self.run_installer()
        for rel in (".claude/skills/commit", ".agents/skills/commit"):
            with self.subTest(rel):
                link = self.prefix / rel
                link.unlink()
                link.symlink_to(ROOT / "skills/gone")
                r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), "--check"],
                                   capture_output=True, text=True, env=self.env)
                self.assertEqual(problems(r), [f"dangling legacy link: {link};"
                                               f" fix: run {INSTALLER} --prefix {self.prefix}"])
                self.run_installer()
                self.assertEqual(link.resolve(), ROOT / "skills/commit")

    def test_check_names_a_dangling_legacy_link_once(self):
        """A dangling legacy link of ours, in a linked directory or not, is
        named once by the check and removed by installing."""
        self.run_installer()
        for rel in (".codex/octo-lite/roles", ".codex/octo-lite-role-skills.json"):
            with self.subTest(rel):
                link = self.prefix / rel
                link.symlink_to(ROOT / "gone-legacy")
                r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), "--check"],
                                   capture_output=True, text=True, env=self.env)
                self.assertEqual(problems(r), [f"dangling legacy link: {link};"
                                               f" fix: run {INSTALLER} --prefix {self.prefix}"])
                self.run_installer()
                self.assertFalse(link.is_symlink())

    def test_dangling_legacy_link_not_ours_is_left_by_check_and_install(self):
        """A legacy path dangling into a deleted clone of someone else's is
        not ours in either mode: named so, never removed."""
        self.run_installer()
        link = self.prefix / ".claude/agents/octo-lite-implementer.md"
        link.symlink_to(self.prefix.parent / "deleted-clone/agents/octo-lite-implementer.md")
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), "--check"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(problems(r), [])
        self.assertIn(f"dangling link (not ours): {link}", r.stderr)
        r = self.run_installer()
        self.assertTrue(link.is_symlink(), "install removed a link the check called not ours")
        self.assertIn(f"dangling link (not ours): {link}", r.stderr)

    def test_check_output_says_checked(self):
        """--check says 'checked', plain install says 'installed' (F-D7)."""
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertIn("installed", r.stdout)
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), "--check"],
                           capture_output=True, text=True, env=self.env)
        self.assertIn("checked", r.stdout)


# Herdr as herdr-spawn sees it: a tab, an agent started with no dialog, a status.
FAKE_HERDR = """#!/bin/sh
case "$1 $2" in
  "tab create") echo '{"result":{"tab":{"tab_id":"w1:t1"},"root_pane":{"pane_id":"w1:p1"}}}' ;;
  "agent get") echo '{"result":{"agent":{"agent_status":"idle"}}}' ;;
esac
"""


class AfterPullTest(unittest.TestCase):
    """A host fast-forwards an installed clone, then runs the published
    after_pull argv with no shell, or no host does and a lane owner spawns a
    worker (spec/domains/install.spec.html#install-after-pull)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.prefix = base / "prefix"
        self.onboarding = self.prefix / ".local/state/octo-lite/onboarding.toml"
        # Stageshow is installed: skillfile finds its pin deployed, and its
        # filming dependencies are current. Herdr is faked.
        self.bin = base / "bin"
        self.bin.mkdir()
        for name, body in (("skillfile", "#!/bin/sh\n"), ("herdr", FAKE_HERDR)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.prefix),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env.pop("XDG_STATE_HOME", None)
        self.upstream = base / "upstream"
        (self.upstream / "scripts").mkdir(parents=True)
        (self.upstream / "agents").mkdir()
        (self.upstream / "agents/role.md").write_text("role\n")
        shutil.copy2(INSTALLER, self.upstream / "scripts/install-octo-lite")
        self.git(self.upstream, "init", "-q")
        self.commit("installer")
        self.clone = base / "clone"
        self.git(base, "clone", "-q", str(self.upstream), str(self.clone))
        deps = self.clone / "agents/skills/stageshow/node_modules"
        deps.mkdir(parents=True)
        (deps / ".package-lock.json").write_text("{}")
        self.run_ok([str(self.clone / "scripts/install-octo-lite"), "--prefix", str(self.prefix)])
        # upstream ships a new helper; the host fast-forwards the clone
        helper = self.upstream / "scripts/new-helper"
        helper.write_text("#!/bin/sh\n")
        helper.chmod(0o755)
        self.commit("new helper")
        self.git(self.clone, "pull", "-q", "--ff-only")
        self.linked = self.prefix / ".local/bin/new-helper"

    def git(self, cwd, *args):
        subprocess.run(["git", "-C", str(cwd), *args], check=True, env=self.env)

    def commit(self, message):
        self.git(self.upstream, "add", "-A")
        self.git(self.upstream, "commit", "-q", "-m", message)

    def run_ok(self, argv):
        r = subprocess.run(argv, capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def after_pull(self):
        argv = tomllib.loads(self.onboarding.read_text())["after_pull"]
        return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, env=self.env)

    def spawn(self, name):
        return subprocess.Popen(
            [str(SPAWN), "--workspace", "w1", "--name", name, "--label", name,
             "--cwd", str(self.clone), "--role", "implementer", "--", "claude"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=self.env)

    def started(self, spawn):
        out, err = spawn.communicate()
        self.assertEqual(spawn.returncode, 0, err)
        self.assertIn("name=", out)
        return err

    def plant_leftover(self):
        leftover = self.prefix / "elsewhere"
        leftover.write_text("")
        self.linked.symlink_to(leftover)

    def test_after_pull_links_the_new_helper(self):
        r = self.after_pull()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.linked.resolve(), (self.clone / "scripts/new-helper").resolve())

    def test_after_pull_fails_naming_the_failed_check_with_its_fix(self):
        self.plant_leftover()
        r = self.after_pull()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(f"bad link: {self.linked} (occupied by symlink -> {self.prefix / 'elsewhere'});"
                      " fix: move it aside, then run ", r.stderr)

    def test_spawn_runs_the_after_pull_step_and_starts(self):
        # spec/domains/install.spec.html#acceptance-after-pull-spawn
        self.started(self.spawn("w1"))
        self.assertEqual(self.linked.resolve(), (self.clone / "scripts/new-helper").resolve())
        head = subprocess.run(["git", "-C", str(self.clone), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(tomllib.loads(self.onboarding.read_text())["commit"], head)

    def test_a_failing_step_is_printed_by_the_first_spawn_only(self):
        # spec/domains/install.spec.html#acceptance-after-pull-spawn-fail
        self.plant_leftover()
        first = self.started(self.spawn("w1"))
        second = self.started(self.spawn("w2"))
        self.assertRegex(first, f"bad link: {self.linked} .*; fix: ")
        self.assertNotIn("bad link", second)

    def test_a_failed_stageshow_fetch_fails_the_step_and_the_spawn_prints_it(self):
        # The pulled pin cannot be fetched; the last install's Stageshow stays.
        (self.bin / "skillfile").write_text("#!/bin/sh\nexit 1\n")
        named = "Stageshow not installed: skillfile install failed; fix: "
        self.assertIn(named, self.started(self.spawn("w1")))
        r = self.after_pull()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(named, r.stderr.splitlines()[-1])

    def with_a_declared_skill_gone(self):
        project = self.prefix.parent / "project"
        project.mkdir()
        (project / "AGENTS.md").write_text("Repo skills: skills/gone\n")
        text = self.onboarding.read_text()
        self.onboarding.write_text(text.replace("]\ncommit", f', "--project", "{project}"]\ncommit', 1))
        return f"missing source: {project}/skills/gone; fix: "

    def test_a_declared_skill_gone_fails_the_step_only_once_it_is_done(self):
        named = self.with_a_declared_skill_gone()
        r = self.after_pull()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(named, r.stderr)
        self.assertIn("version floors", r.stdout)

    def test_after_pull_names_each_problem_once(self):
        """Install and verify are one pass: a problem both would name, a
        declared skill gone or Stageshow neither fetched nor installed, and a
        link not ours, is one line of the step's error output."""
        named = self.with_a_declared_skill_gone()
        (self.bin / "skillfile").write_text("#!/bin/sh\nexit 1\n")
        shutil.rmtree(self.clone / "agents/skills/stageshow/node_modules")
        (self.prefix / ".claude/skills/not-ours").symlink_to(self.prefix.parent / "gone")
        r = self.after_pull()
        self.assertEqual(r.returncode, 1, r.stderr)
        lines = r.stderr.splitlines()
        for start in (named, "Stageshow not installed", "dangling link (not ours)"):
            self.assertEqual(1, sum(line.startswith(start) for line in lines), r.stderr)
        self.assertEqual(len(lines), len(set(lines)), r.stderr)

    def test_a_declared_skill_gone_is_printed_by_the_first_spawn_only(self):
        named = self.with_a_declared_skill_gone()
        self.assertIn(named, self.started(self.spawn("w1")))
        self.assertEqual(self.started(self.spawn("w2")), "")

    def test_parallel_spawns_run_the_step_once(self):
        # An owner spawns several workers at once: one runs the step, the
        # others wait for it and find the clone current.
        log, wrapper = self.prefix / "steps.log", self.prefix / "step"
        wrapper.write_text(f'#!/bin/sh\necho run >>"{log}"\nsleep 1\nexec "$@"\n')
        wrapper.chmod(0o755)
        text = self.onboarding.read_text()
        self.onboarding.write_text(text.replace("after_pull = [", f'after_pull = ["{wrapper}", ', 1))
        for spawn in [self.spawn(f"w{i}") for i in range(3)]:
            self.assertEqual(self.started(spawn), "")
        self.assertEqual(log.read_text(), "run\n")
        self.assertEqual(self.linked.resolve(), (self.clone / "scripts/new-helper").resolve())


if __name__ == "__main__":
    unittest.main()
