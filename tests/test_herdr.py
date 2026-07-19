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
  if [[ -n "${FAKE_SEND_FAIL:-}" ]]; then
    echo send-failed >>"$FAKE_LOG"
    exit 1
  fi
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

    def test_send_queues_on_transport_failure_without_recording_false_submitted(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_SEND_FAIL"] = "1"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertNotIn("run", log.read_text().splitlines() if log.exists() else [])
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("queued", tomllib.load(handle)["status"])
            message_id = states[0].stem
            inbox = Path(td) / "state/octo-lite/inbox/agent1" / message_id
            self.assertTrue(inbox.is_file())

    def test_drain_locks_each_queued_item_to_prevent_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=dict(env, FAKE_SEND_FAIL="1"),
                capture_output=True,
                text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem
            inbox_item = Path(td) / "state/octo-lite/inbox/agent1" / message_id
            lock_path = Path(f"{inbox_item}.lock")
            drain = ROOT / "skills/herdr-comms/assets/herdr-drain"

            holder = subprocess.Popen(["flock", str(lock_path), "sleep", "3"])
            try:
                for _ in range(20):
                    if lock_path.exists():
                        break
                    __import__("time").sleep(0.1)
                result = subprocess.run(["bash", str(drain), "agent1"], env=env, capture_output=True, text=True)
                self.assertEqual(0, result.returncode)
                self.assertNotIn("send", (log.read_text().splitlines() if log.exists() else []))
                self.assertTrue(inbox_item.is_file())
            finally:
                holder.terminate()
                holder.wait()

            second = subprocess.run(["bash", str(drain), "agent1"], env=env, capture_output=True, text=True)
            self.assertEqual(0, second.returncode)
            self.assertIn("send", log.read_text().splitlines())
            self.assertFalse(inbox_item.exists())

    def test_ack_requires_prior_submission(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self.environment(td, "Quick safety check: trust this folder")
            queued = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queued.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem
            result = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            with states[0].open("rb") as handle:
                self.assertEqual("queued", tomllib.load(handle)["status"])

    def test_ack_requires_exact_recipient_even_for_pane_targets(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "w1:p1", "do work"],
                env=env, check=True, capture_output=True, text=True,
            )
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            wrong = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "someone-else"],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, wrong.returncode)
            right = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "w1:p1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, right.returncode)

    def spawn_environment(self, td, pane_text):
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
  printf '%s\\n' "$FAKE_PANE_TEXT"
fi
"""
        )
        fake.chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{fake_bin}:{os.environ['PATH']}",
            FAKE_LOG=str(log),
            FAKE_PANE_TEXT=pane_text,
            HERDR_SPAWN_BOOTSTRAP_RETRIES="2",
        )
        return env, log

    def test_orchestrator_spawn_enforces_label_model_auto_and_bootstrap(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.spawn_environment(td, "ready")
            receipt = Path(td) / "launch.toml"
            receipt.write_text(
                'schema_version = 1\nspawn_id = "spawn-1"\nready = true\n\n'
                '[bootstrap]\nverified = true\nprovider_session_id = "provider-1"\n'
            )
            base = [
                str(SPAWN), "--workspace", "w1", "--name", "spawn-1", "--cwd", str(ROOT),
                "--role", "orchestrator", "--label", "443/6 · operating model",
                "--receipt", str(receipt), "--",
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

    def test_spawn_rejects_pane_text_spoofing_an_unverified_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            env, _log = self.spawn_environment(td, "BOOTSTRAP_ACK spawn-1")
            receipt = Path(td) / "launch.toml"
            receipt.write_text(
                'schema_version = 1\nspawn_id = "spawn-1"\nready = false\n\n'
                '[bootstrap]\nverified = false\nprovider_session_id = ""\n'
            )
            base = [
                str(SPAWN), "--workspace", "w1", "--name", "spawn-1", "--cwd", str(ROOT),
                "--role", "orchestrator", "--label", "443/6 · operating model",
                "--receipt", str(receipt), "--",
                "claude", "--model", "claude-opus-4-8[1m]", "--effort", "high",
                "--permission-mode", "auto", "--agent", "orchestrator", "prompt",
            ]
            result = subprocess.run(base, env=env, capture_output=True, text=True)
            self.assertEqual(2, result.returncode)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)


if __name__ == "__main__":
    unittest.main()
