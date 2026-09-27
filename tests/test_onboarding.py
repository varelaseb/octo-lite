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
        self.consent = self.prefix / ".config/octo-lite/consent.toml"
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
        self.assertFalse(self.consent.exists())

    def test_onboard_asks_keeps_consent_and_is_done(self):
        state = self.install("--onboard", answers="y\nn\n\n")
        self.assertEqual(state["status"], "done")
        self.assertEqual(tomllib.loads(self.consent.read_text()),
                         {"push": True, "pull_request": False, "issues": False})
        # kept: a second onboarding does not ask again or change the answers
        self.install("--onboard", answers="n\ny\ny\n")
        self.assertTrue(tomllib.loads(self.consent.read_text())["push"])

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

    def test_herdr_box_registers_the_waker_and_undo_removes_it(self):
        self.with_herdr()
        self.install()
        waker = str(self.prefix / ".local/bin/herdr-wake")
        self.assertEqual(tomllib.loads(self.wake.read_text()), {
            "check": [waker, "check", "{owner}"],
            "send": [waker, "send", "{owner}", "{artifact}", "{message}"],
        })
        self.assertEqual(Path(waker).resolve(), (ROOT / "skills/herdr-comms/assets/herdr-wake").resolve())
        self.install("--undo")
        self.assertFalse(self.wake.exists())

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
