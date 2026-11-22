"""Each key a feature of octo-lite needs is asked for by --onboard and proved
by --check; --undo leaves its file. The X token is the first such key.
Spec: spec/domains/install.spec.html#install-keys and #install-x-token;
criteria #acceptance-keys-rule (project rule) and every #acceptance-x-token-*
but -after-pull, which tests/test_onboarding.py's after-pull box proves. X is
tests/floor-bin/curl: no test calls X."""

from __future__ import annotations

import os
import pty
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"
# skillfile and npm stubbed unreachable: installer runs never fetch.
# Runtime tools stubbed at their floors, and X with them: a verifying run finds
# them on any box.
OFFLINE = f"{ROOT / 'tests/offline-bin'}:{ROOT / 'tests/floor-bin'}:{os.environ['PATH']}"
# Every key the installer asks for: name, file under the prefix, variable, a
# key its service proves, and one it refuses. A change that makes a feature
# need a key adds it here, and its service to tests/floor-bin.
KEYS = [("X token", ".config/workbench/x.env", "X_BEARER_TOKEN", "proved-token", "refused-token")]
CONSENT = ["y", "n", "y"]


def give_keys(prefix: Path) -> None:
    """A box holding every key, each one its service proves."""
    for _, rel, variable, proved, _ in KEYS:
        (prefix / rel).parent.mkdir(parents=True, exist_ok=True)
        (prefix / rel).write_text(f"{variable}={proved}\n")


def problems(run):
    """The problems a run names, but Stageshow's and the recorder's: offline,
    neither is fetched."""
    return [line for line in run.stderr.splitlines()
            if "; fix: " in line
            and not line.startswith(("Stageshow not installed", "prototype-video not installed"))]


class KeysTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.prefix = Path(tmp.name).resolve() / "prefix"
        self.env = {**os.environ, "PATH": OFFLINE}
        for _, _, variable, _, _ in KEYS:
            self.env.pop(variable, None)
        self.fix = f"run {INSTALLER} --prefix {self.prefix}"
        self.x_env = self.prefix / ".config/workbench/x.env"

    def run_installer(self, *extra: str, piped: str = "") -> subprocess.CompletedProcess:
        return subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), *extra],
                              input=piped, capture_output=True, text=True, env=self.env)

    def at_terminal(self, *typed: str) -> subprocess.CompletedProcess:
        """Onboarding at a terminal, which the operator types each line at."""
        terminal, stdin = pty.openpty()
        self.addCleanup(os.close, terminal)
        run = subprocess.Popen([str(INSTALLER), "--prefix", str(self.prefix), "--onboard"],
                               stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=self.env)
        os.close(stdin)
        os.write(terminal, "".join(f"{line}\n" for line in typed).encode())
        out, err = run.communicate(timeout=300)
        return subprocess.CompletedProcess(run.args, run.returncode, out, err)

    def assert_holds_only(self, path: Path, line: str) -> None:
        self.assertEqual(path.read_text(), f"{line}\n")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_onboarding_at_a_terminal_keeps_the_given_x_token_and_names_only_its_file(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-ask
        r = self.at_terminal(*CONSENT, "typed-token")
        self.assertEqual(problems(r), [])
        self.assert_holds_only(self.x_env, "X_BEARER_TOKEN=typed-token")
        self.assertIn(f"X token for {self.x_env} (Enter skips): ", r.stderr)
        self.assertIn(f"X token written: {self.x_env}", r.stdout)
        self.assertNotIn("typed-token", r.stdout + r.stderr)

    def test_onboarding_adopts_an_x_credential_file_and_asks_nothing(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-adopt
        self.x_env.parent.mkdir(parents=True)
        self.x_env.write_text("X_BEARER_TOKEN=kept-token\n")
        self.x_env.chmod(0o600)
        self.env["X_BEARER_TOKEN"] = "env-token"
        r = self.at_terminal(*CONSENT, "typed-token")
        self.assertEqual(problems(r), [])
        self.assert_holds_only(self.x_env, "X_BEARER_TOKEN=kept-token")
        self.assertNotIn("X token for", r.stderr)
        self.assertIn(f"X token adopted: {self.x_env}", r.stdout)

    def test_piped_onboarding_takes_the_x_token_from_the_environment_never_a_piped_answer(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-piped
        piped = "".join(f"{line}\n" for line in (*CONSENT, "piped-token"))
        self.env["X_BEARER_TOKEN"] = "env-token"
        r = self.run_installer("--onboard", piped=piped)
        self.assertEqual(problems(r), [])
        self.assert_holds_only(self.x_env, "X_BEARER_TOKEN=env-token")
        self.assertNotIn("env-token", r.stdout + r.stderr)
        # with none in the environment, the piped answer is still never read
        # as a token, and skipping writes nothing
        self.x_env.unlink()
        del self.env["X_BEARER_TOKEN"]
        r = self.run_installer("--onboard", piped=piped)
        self.assertEqual(problems(r), [])
        self.assertFalse(self.x_env.exists())
        self.assertIn(f"X token not given, nothing written: {self.x_env}", r.stdout)

    def test_check_names_a_missing_x_token_with_its_fix(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-missing,
        # octo-lite.spec.html#roles-research-x (mode 0600)
        self.run_installer()
        fix = f"put the one line X_BEARER_TOKEN=<X token> in {self.x_env}, mode 0600"
        r = self.run_installer("--check")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(problems(r), [f"missing X token: {self.x_env}; fix: {fix}, or {self.fix} --onboard"])
        # a file without the line: --onboard adopts it and changes nothing, so
        # the fix is the line alone
        self.x_env.parent.mkdir(parents=True)
        for held in ("", "X_BEARER_TOKEN=\n", "TOKEN=kept\n"):
            with self.subTest(held=held):
                self.x_env.write_text(held)
                r = self.run_installer("--check")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertEqual(problems(r), [f"missing X token: {self.x_env}; fix: {fix}"])

    def test_check_names_a_refused_x_token_with_x_answer_and_its_fix(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-refused
        self.run_installer()
        self.x_env.parent.mkdir(parents=True)
        self.x_env.write_text("X_BEARER_TOKEN=refused-token\n")
        r = self.run_installer("--check")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(problems(r), [
            f"X token refused by X (401 Unauthorized): {self.x_env}; fix: get a new token,"
            f" or a plan with recent search, and put it in {self.x_env}"])
        self.assertNotIn("refused-token", r.stdout + r.stderr)

    def test_check_proves_a_quoted_x_token_unquoted_and_never_runs_it(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-quoted, #install-x-token:
        # the line's value, one pair of matching quotes around it dropped, as a
        # shell assignment holds it, reaches X; the file is never sourced, so a
        # planted command never runs
        self.run_installer()
        self.x_env.parent.mkdir(parents=True)
        ran = self.prefix / "ran"
        for held in ("'proved-token'", '"proved-token"', f'"$(touch {ran})proved"'):
            with self.subTest(held):
                self.x_env.write_text(f"X_BEARER_TOKEN={held}\n")
                r = self.run_installer("--check")
                self.assertEqual(problems(r), [], r.stderr)
                self.assertIn(f"X token proved by X: {self.x_env}", r.stdout)
                self.assertFalse(ran.exists(), "ran the X credential file")

    def assert_not_proved_and_no_problem(self, *answers: tuple[str, str]) -> None:
        self.run_installer()
        self.x_env.parent.mkdir(parents=True)
        for token, said in answers:
            with self.subTest(token):
                self.x_env.write_text(f"X_BEARER_TOKEN={token}\n")
                r = self.run_installer("--check")
                self.assertEqual(problems(r), [])
                self.assertIn(f"X token not proved, {said}: {self.x_env}", r.stdout)

    def test_check_says_x_did_not_answer_and_names_no_problem(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-offline
        self.assert_not_proved_and_no_problem(("unreachable-token", "X did not answer"),
                                              ("unavailable-token", "X did not answer (503)"))

    def test_check_says_x_answered_429_and_names_no_problem(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-limited, #install-keys:
        # a key the service may not use right now, such as X's 429 for a rate
        # limit or a spent monthly cap, is a line on standard output naming its
        # answer and no problem
        self.assert_not_proved_and_no_problem(("limited-token", "X answered (429 Too Many Requests)"),
                                              ("capped-token", "X answered (429 UsageCapExceeded)"))

    def test_undo_leaves_the_x_credential_file_onboarding_wrote(self) -> None:
        # spec/domains/install.spec.html#acceptance-x-token-undo
        self.env["X_BEARER_TOKEN"] = "env-token"
        self.run_installer("--onboard", piped="y\ny\ny\n")
        r = self.run_installer("--undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_holds_only(self.x_env, "X_BEARER_TOKEN=env-token")
        self.assertIn(f"kept X token: {self.x_env}", r.stdout)

    def test_every_key_is_asked_once_kept_and_proved(self) -> None:
        """Project rule spec/domains/install.spec.html#acceptance-keys-rule: on a
        box without them, onboarding at a terminal asks for each key once and
        keeps it, and the check proves it, naming one missing or refused as one
        problem line with its fix."""
        for name, rel, variable, proved, refused in KEYS:
            with self.subTest(name):
                path = self.prefix / rel
                r = self.at_terminal(*CONSENT, proved)
                self.assertEqual(r.stderr.count(f"{name} for {path}"), 1, r.stderr)
                self.assert_holds_only(path, f"{variable}={proved}")
                r = self.at_terminal(*CONSENT, "another-key")
                self.assertNotIn(f"{name} for", r.stderr)
                self.assert_holds_only(path, f"{variable}={proved}")
                r = self.run_installer("--check")
                self.assertEqual(problems(r), [])
                self.assertIn(f"{name} proved", r.stdout)
                for held, start in ((refused, f"{name} refused"), (None, f"missing {name}")):
                    path.unlink()
                    if held:
                        path.write_text(f"{variable}={held}\n")
                    r = self.run_installer("--check")
                    self.assertEqual([p.startswith(start) for p in problems(r)], [True], r.stderr)
                    self.assertNotIn(refused, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
