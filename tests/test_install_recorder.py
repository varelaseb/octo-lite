"""The installer installs the round video recorder with the browser driver it
pins and a browser for it, as it fetches Stageshow's filming dependencies, and
links it, on a box without Stageshow; a failed fetch fails the run naming it
with its fix, as Stageshow's does. Spec: spec/domains/install.spec.html
#install-recorder and #install-peers. The recorder is a stand-in folder at its fixed interface;
skillfile and npm are stubbed: nothing fetches."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "tests" / "offline-bin"
RECORDER = "skills/implement-spec/assets/prototype-video"

# npm ci installs the lockfile's packages and records them in node_modules;
# npm exec runs the driver's browser install. The subcommand named fail fails.
NPM = """#!/bin/sh
echo "$PWD $*" >>"{log}"
[ "$1" = "{fail}" ] && exit 1
[ "$1" = ci ] && mkdir -p node_modules && echo '{{}}' >node_modules/.package-lock.json
exit 0
"""


def run(argv, env):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


class RecorderInstallTest(unittest.TestCase):
    """A fresh clone carrying this clone's installer and ignores, the recorder's
    stand-in folder, on a box where the Stageshow fetch fails."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.prefix = base / "prefix"
        self.npm_log = base / "npm.log"
        self.bindir = base / "bin"
        self.bindir.mkdir()
        self.npm(fail="none")
        self.env = {**os.environ, "PATH": f"{self.bindir}:{OFFLINE}:{os.environ['PATH']}",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        upstream = base / "upstream"
        for rel in ("scripts/install-octo-lite", ".gitignore", "Skillfile", "Skillfile.lock"):
            (upstream / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, upstream / rel)
        (upstream / "agents").mkdir()
        (upstream / "agents/role.md").write_text("role\n")
        stand_in = upstream / RECORDER
        stand_in.mkdir(parents=True)
        for name in ("package.json", "package-lock.json"):
            (stand_in / name).write_text("{}")
        (stand_in / "prototype-video").write_text("#!/bin/sh\n")
        (stand_in / "prototype-video").chmod(0o755)
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "octo-lite"]):
            subprocess.run(["git", "-C", str(upstream), *argv], check=True, env=self.env)
        self.clone = base / "clone"
        subprocess.run(["git", "clone", "-q", str(upstream), str(self.clone)], check=True, env=self.env)
        self.recorder = self.clone / RECORDER
        self.installer = str(self.clone / "scripts/install-octo-lite")
        self.fix = f"run {self.installer} --prefix {self.prefix}"

    def npm(self, fail):
        stub = self.bindir / "npm"
        stub.write_text(NPM.format(log=self.npm_log, fail=fail))
        stub.chmod(0o755)

    def install(self, *extra):
        """The problems a run names, but Stageshow's, which fails every run."""
        r = run([self.installer, "--prefix", str(self.prefix), *extra], self.env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stderr.splitlines()[-1].startswith("Stageshow not installed"), r.stderr)
        return [line for line in r.stderr.splitlines()
                if "; fix: " in line and not line.startswith("Stageshow not installed")]

    def test_installs_and_links_the_recorder_without_stageshow(self):
        self.assertEqual(self.install(), [])
        self.assertEqual(self.npm_log.read_text().splitlines(), [
            f"{self.recorder} ci --no-audit --no-fund --loglevel=error",
            f"{self.recorder} exec -- playwright-core install chromium"])
        link = self.prefix / ".local/bin/prototype-video"
        self.assertEqual(os.path.realpath(link), str(self.recorder / "prototype-video"))
        status = run(["git", "-C", str(self.clone), "status", "--porcelain"], self.env)
        self.assertEqual(status.stdout, "", "the clone must hold no changed or untracked file")
        self.assertEqual(self.install("--check"), [])

    def test_reinstall_keeps_the_driver_and_checks_the_browser(self):
        self.install()
        self.install()
        self.assertEqual(self.npm_log.read_text().splitlines(), [
            f"{self.recorder} ci --no-audit --no-fund --loglevel=error",
            f"{self.recorder} exec -- playwright-core install chromium",
            f"{self.recorder} exec -- playwright-core install chromium"])

    def test_failed_fetch_reports_the_recorder_and_links_the_rest(self):
        # Only --check skips the fetch, so a browser fetch failure is install's alone.
        for fail, reason, checked in (
                ("ci", "npm ci failed", [f"prototype-video not installed: browser driver not installed; fix: {self.fix}"]),
                ("exec", "browser install failed", [])):
            with self.subTest(fail=fail):
                shutil.rmtree(self.recorder / "node_modules", ignore_errors=True)
                self.npm(fail=fail)
                self.assertEqual(self.install(), [f"prototype-video not installed: {reason};"
                                                  f" fix: resolve its error above, then {self.fix}"])
                self.assertTrue((self.prefix / ".claude/agents/role.md").is_symlink())
                self.assertEqual(self.install("--check"), checked)


if __name__ == "__main__":
    unittest.main()
