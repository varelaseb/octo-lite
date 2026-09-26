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
        self.prefix = Path(tmp.name)
        self.env = {k: v for k, v in os.environ.items() if k not in ("XDG_CONFIG_HOME", "XDG_STATE_HOME")}
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
        bindir.mkdir()
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


if __name__ == "__main__":
    unittest.main()
