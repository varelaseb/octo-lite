import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAY = ROOT / "skills/herdr-comms/assets/herdr-say"
ACK = ROOT / "skills/herdr-comms/assets/herdr-ack"
SPAWN = ROOT / "skills/herdr-comms/assets/herdr-spawn"


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

    def test_orchestrator_spawn_enforces_label_model_auto_and_bootstrap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "herdr.log"
            fake = fake_bin / "herdr"
            fake.write_text(
                """#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
if [[ "$1 $2" == "tab create" ]]; then
  echo '{"result":{"tab":{"tab_id":"w1:t1"},"root_pane":{"pane_id":"w1:p0"}}}'
elif [[ "$1 $2" == "agent get" ]]; then
  echo '{"result":{"agent":{"pane_id":"w1:p1"}}}'
elif [[ "$1 $2" == "pane read" ]]; then
  echo 'BOOTSTRAP_ACK spawn-1'
fi
"""
            )
            fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", FAKE_LOG=str(log))
            base = [
                str(SPAWN), "--workspace", "w1", "--name", "spawn-1", "--cwd", str(ROOT),
                "--role", "orchestrator", "--label", "443/6 · operating model", "--",
                "claude", "--model", "claude-opus-4-8[1m]", "--effort", "high",
                "--permission-mode", "auto", "--agent", "orchestrator", "prompt",
            ]
            valid = subprocess.run(base, env=env, check=True, capture_output=True, text=True)
            self.assertIn("bootstrap=acknowledged", valid.stdout)
            log.unlink()
            invalid = list(base)
            invalid[invalid.index("443/6 · operating model")] = "TUR-443 operating model"
            result = subprocess.run(invalid, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(log.exists())


if __name__ == "__main__":
    unittest.main()
