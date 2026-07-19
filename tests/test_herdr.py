import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflows.lib.role_resolver import build_launch_receipt, load_registry, render_receipt, resolve_role


ROOT = Path(__file__).resolve().parents[1]
SAY = ROOT / "skills/herdr-comms/assets/herdr-say"
ACK = ROOT / "skills/herdr-comms/assets/herdr-ack"
SPAWN = ROOT / "skills/herdr-comms/assets/herdr-spawn"
OCTO_LAUNCH = ROOT / "scripts/octo-launch"

# Fakes the bootstrap print-mode provider call herdr-spawn triggers indirectly
# through `octo-launch bootstrap`. A `--session-id` call answers a BOOTSTRAP_ACK
# computed from the exact receipt on disk, optionally with one field overridden to
# prove herdr-spawn refuses to start a pane on any mismatch.
FAKE_BOOTSTRAP_CLAUDE = r"""#!/usr/bin/env bash
printf 'claude %s\n' "$*" >>"$CALL_LOG"
prompt="$(cat)"
receipt_path="$(printf '%s' "$prompt" | grep -oE '/[^ ]*\.toml' | head -1)"
args=("$@")
session=""
for i in "${!args[@]}"; do
  if [[ "${args[$i]}" == "--session-id" ]]; then
    session="${args[$((i+1))]}"
  fi
done
python3 - "$receipt_path" "$session" <<'PY'
import json
import os
import sys
import tomllib

receipt_path, session_id = sys.argv[1], sys.argv[2]
with open(receipt_path, "rb") as handle:
    receipt = tomllib.load(handle)
ack = {
    "schema_version": receipt["schema_version"],
    "spawn_id": receipt["spawn_id"],
    "provider_session_id": session_id,
    "launch_revision": receipt["launch_revision"],
    "role": receipt["role"]["name"],
    "worktree": receipt["workspace"]["worktree"],
    "starting_head": receipt["workspace"]["starting_head"],
    "ready": True,
    "blocker": "",
}
override = os.environ.get("FAKE_ACK_OVERRIDE")
if override:
    key, value = override.split("=", 1)
    ack[key] = value
print(json.dumps({"session_id": session_id, "result": json.dumps(ack)}))
PY
"""


def build_orchestrator_receipt(repo: Path, receipt_path: Path) -> dict:
    registry = load_registry(ROOT)
    resolved = resolve_role(registry, "orchestrator", set())
    receipt = build_launch_receipt(
        ROOT,
        resolved,
        spawn_id=str(uuid.uuid4()),
        parent="epic-opus",
        reply_route="herdr:epic-opus",
        repo=repo,
        worktree=repo,
        execution_location="remote",
        operator_loopback=False,
        review_delivery="reachable_url_required",
    )
    receipt_path.write_text(render_receipt(receipt))
    return receipt


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

    def spawn_environment(self, td, ack_override=None):
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
  printf 'ready\\n'
fi
"""
        )
        fake.chmod(0o755)
        (fake_bin / "claude").write_text(FAKE_BOOTSTRAP_CLAUDE)
        (fake_bin / "claude").chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{fake_bin}:{OCTO_LAUNCH.parent}:{os.environ['PATH']}",
            FAKE_LOG=str(log),
            CALL_LOG=str(log),
            HERDR_SPAWN_BOOTSTRAP_RETRIES="2",
        )
        if ack_override:
            env["FAKE_ACK_OVERRIDE"] = ack_override
        return env, log

    def spawn_base_command(self, receipt):
        return [
            str(SPAWN), "--workspace", "w1", "--name", "orch-1", "--cwd", str(ROOT),
            "--role", "orchestrator", "--label", "443/6 · operating model",
            "--receipt", str(receipt), "--",
            "claude", "--model", "claude-opus-4-8[1m]", "--effort", "high",
            "--permission-mode", "auto", "--agent", "orchestrator", "prompt",
        ]

    def test_spawn_verifies_bootstrap_before_any_pane_and_resumes_the_exact_verified_session(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text("# Target\n")
            subprocess.run(["git", "-C", str(repo), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)
            receipt_path = Path(td) / "launch.toml"
            receipt = build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            result = subprocess.run(
                self.spawn_base_command(receipt_path), env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("bootstrap=acknowledged", result.stdout)
            self.assertIn(f"provider_session_id={receipt['spawn_id']}", result.stdout)

            readback = tomllib.loads(receipt_path.read_text())
            self.assertTrue(readback["bootstrap"]["verified"])
            self.assertEqual(receipt["spawn_id"], readback["bootstrap"]["provider_session_id"])

            calls = log.read_text().splitlines()
            start_call = next(line for line in calls if line.startswith("agent start"))
            self.assertIn(f"--resume {receipt['spawn_id']}", start_call)
            # The resumed command is the exact bootstrap-verified session, immediately
            # after the executable, never a fresh unverified start.
            self.assertIn(f"claude --resume {receipt['spawn_id']}", start_call)

    def test_spawn_creates_no_pane_on_any_bootstrap_mismatch(self):
        scenarios = {
            "spoofed_role": "role=code-reviewer",
            "wrong_provider_session": "provider_session_id=" + str(uuid.uuid4()),
            "wrong_worktree": "worktree=/tmp/not-the-real-worktree",
            "wrong_starting_head": "starting_head=" + ("0" * 40),
            "wrong_launch_revision": "launch_revision=" + ("0" * 64),
        }
        for name, override in scenarios.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as td:
                repo = Path(td) / "repo"
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
                subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
                (repo / "AGENTS.md").write_text("# Target\n")
                subprocess.run(["git", "-C", str(repo), "add", "AGENTS.md"], check=True)
                subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)
                receipt_path = Path(td) / "launch.toml"
                build_orchestrator_receipt(repo, receipt_path)

                env, log = self.spawn_environment(td, ack_override=override)
                result = subprocess.run(
                    self.spawn_base_command(receipt_path), env=env, capture_output=True, text=True,
                )
                self.assertNotEqual(0, result.returncode, name)
                self.assertNotIn("bootstrap=acknowledged", result.stdout, name)
                calls = log.read_text().splitlines() if log.exists() else []
                self.assertFalse(any(call.startswith("tab create") for call in calls), name)
                self.assertFalse(any(call.startswith("agent start") for call in calls), name)
                readback = tomllib.loads(receipt_path.read_text())
                self.assertFalse(readback["bootstrap"]["verified"], name)

    def test_spawn_creates_no_pane_on_unreadable_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            receipt_path = Path(td) / "launch.toml"
            receipt_path.write_text("not valid toml{{{")
            env, log = self.spawn_environment(td)
            result = subprocess.run(
                self.spawn_base_command(receipt_path), env=env, capture_output=True, text=True,
            )
            self.assertEqual(2, result.returncode)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)
            self.assertFalse(log.exists())

    def test_spawn_still_enforces_label_and_model_before_any_bootstrap_call(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text("# Target\n")
            subprocess.run(["git", "-C", str(repo), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            invalid = self.spawn_base_command(receipt_path)
            invalid[invalid.index("443/6 · operating model")] = "TUR-443 operating model"
            result = subprocess.run(invalid, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(log.exists())
            readback = tomllib.loads(receipt_path.read_text())
            self.assertFalse(readback["bootstrap"]["verified"])


if __name__ == "__main__":
    unittest.main()
