from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts/octo-probe"


class ProviderProbeTests(unittest.TestCase):
    def fake_environment(self, td: str, *, fail: bool = False):
        base = Path(td)
        fake_bin = base / "bin"
        fake_bin.mkdir()
        log = base / "calls"
        for name in ("claude", "codex"):
            path = fake_bin / name
            path.write_text(
                "#!/usr/bin/env bash\n"
                "echo \"$0 $*\" >>\"$PROBE_LOG\"\n"
                + ("echo revoked >&2\nexit 1\n" if fail else "echo PROBE_OK\n")
            )
            path.chmod(0o755)
        return dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", PROBE_LOG=str(log)), log

    def test_exact_openai_and_anthropic_probes_are_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env, log = self.fake_environment(td)
            review = subprocess.run([str(PROBE), "code-reviewer"], env=env, check=True, capture_output=True, text=True)
            build = subprocess.run([str(PROBE), "implementer"], env=env, check=True, capture_output=True, text=True)
            lines = log.read_text().splitlines()
            self.assertIn("codex exec -m gpt-5.6-sol", lines[0])
            self.assertNotIn("--last", lines[0])
            self.assertIn("claude -p --model claude-sonnet-5", lines[1])
            self.assertFalse(json.loads(review.stdout)["fleet_outage"])
            self.assertEqual("lane_or_session", json.loads(build.stdout)["classification"])

    def test_failed_single_probe_never_declares_fleet_outage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env, _ = self.fake_environment(td, fail=True)
            result = subprocess.run([str(PROBE), "code-reviewer"], env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            report = json.loads(result.stdout)
            self.assertFalse(report["fleet_outage"])
            self.assertEqual("provider_account_or_network", report["classification"])


if __name__ == "__main__":
    unittest.main()
