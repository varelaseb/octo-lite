"""Fresh-install test of octo-lite's own onboarding (ADR peer boundaries):
consent asked and kept, onboarding.toml published in octo-lite's own state,
and the start command installed on PATH."""

import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install-octo-lite"


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.prefix = Path(tmp.name) / "prefix"
        # --prefix is the one root: an exported XDG home must stay untouched.
        self.sentinel = Path(tmp.name) / "xdg"
        self.sentinel.mkdir()
        self.env = {**os.environ, "XDG_STATE_HOME": str(self.sentinel / "state"),
                    "XDG_CONFIG_HOME": str(self.sentinel / "config")}
        self.onboarding = self.prefix / ".local/state/octo-lite/onboarding.toml"

    def install(self, *extra, answers=""):
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), *extra],
                           input=answers, capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
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

    def test_check_writes_no_state(self):
        self.install()
        self.onboarding.unlink()
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), "--check"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.onboarding.exists())

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
        self.env["PATH"] = "/usr/bin:/bin"
        self.install()
        self.assertFalse(self.wake.exists())

    # --- Dangling link safety (F-D2) -----------------------------------------

    def test_foreign_dangling_link_is_reported_and_left_untouched(self):
        """A dangling link not pointing into this repo is never deleted."""
        skills = self.prefix / ".claude/skills"
        skills.mkdir(parents=True)
        foreign = skills / "my-own-skill"
        foreign.symlink_to("/nonexistent/foreign/path")
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(foreign.is_symlink(), "foreign dangling link was deleted")
        self.assertIn("not ours", r.stderr)

    def test_foreign_dangling_link_at_install_path_is_left(self):
        """A foreign dangling link at a path the installer links is not replaced."""
        skills = self.prefix / ".claude/skills"
        skills.mkdir(parents=True)
        foreign = skills / "commit"
        foreign.symlink_to("/nonexistent/foreign/commit")
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(foreign), "/nonexistent/foreign/commit")
        self.assertIn(f"skipped: {foreign}", r.stdout)

    def test_own_dangling_link_is_pruned(self):
        """A dangling link pointing into this repo is pruned."""
        skills = self.prefix / ".claude/skills"
        skills.mkdir(parents=True)
        own = skills / "deleted-skill"
        own.symlink_to(str(ROOT / "nonexistent-deleted-skill"))
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
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
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
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
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
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
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), "--check"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("version floors", r.stdout)
        self.assertIn("git:", r.stdout)

    def test_check_output_says_checked(self):
        """--check says 'checked', plain install says 'installed' (F-D7)."""
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix)],
                           capture_output=True, text=True, env=self.env)
        self.assertIn("installed", r.stdout)
        r = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), "--check"],
                           capture_output=True, text=True, env=self.env)
        self.assertIn("checked", r.stdout)


if __name__ == "__main__":
    unittest.main()
