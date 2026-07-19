import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAY = ROOT / "skills/herdr-comms/assets/herdr-say"
ACK = ROOT / "skills/herdr-comms/assets/herdr-ack"


class HerdrHelperTests(unittest.TestCase):
    def environment(self, td, pane_text):
        root = Path(td)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        fake = fake_bin / "herdr"
        fake.write_text(
            """#!/usr/bin/env bash
set -eu
if [[ "$1 $2" == "agent get" ]]; then
  echo '{"result":{"agent":{"pane_id":"w1:p1"}}}'
elif [[ "$1 $2" == "pane read" ]]; then
  printf '%s\\n' "$FAKE_PANE_TEXT"
elif [[ "$1 $2" == "agent send" ]]; then
  echo send >>"$FAKE_LOG"
elif [[ "$1 $2" == "pane run" ]]; then
  echo run >>"$FAKE_LOG"
else
  exit 2
fi
"""
        )
        fake.chmod(0o755)
        log = root / "herdr.log"
        env = dict(os.environ)
        env.update(
            PATH=f"{fake_bin}:{env['PATH']}",
            XDG_STATE_HOME=str(root / "state"),
            FAKE_PANE_TEXT=pane_text,
            FAKE_LOG=str(log),
        )
        return env, log

    def test_modal_queues_without_pressing_enter(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "Quick safety check: trust this folder")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertFalse(log.exists())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("queued", tomllib.load(handle)["status"])

    def test_safe_prompt_submits_then_requires_ack(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "ruling", "agent1", "use screenshots"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(["send", "run"], log.read_text().splitlines())
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env,
                check=True,
            )
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])


if __name__ == "__main__":
    unittest.main()
