import json
import os
import shutil
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
DRAIN = ROOT / "skills/herdr-comms/assets/herdr-drain"
OPERATOR_SAY = ROOT / "skills/herdr-comms/assets/operator-say"
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


# herdr 0.7.5 fake. Implements the documented 0.7.5 grammar:
#   agent get <target>           -> JSON incl agent.pane_id
#   agent prompt <target> <text> -> atomic paste+submit in one op; the WHOLE
#                                   text (multi-line, special chars) is captured
#                                   verbatim into $FAKE_PROMPT_CAPTURE so a test
#                                   can assert an atomic literal round-trip. It
#                                   refuses (non-zero, logs "prompt-blocked")
#                                   when a trust dialog is active, and fails
#                                   (non-zero, logs "prompt-failed") when the
#                                   server reports a stall/refusal.
#   agent send-keys <target> ...  -> literal keystrokes, no submit; logs "send-keys".
#   pane read <pane> ...          -> visible transcript for the modal-safe check.
# `agent send` and top-level `wait` no longer exist in 0.7.5.
FAKE_HERDR_075 = r"""#!/usr/bin/env bash
set -eu
sub="$1 $2"
if [[ "$sub" == "agent get" ]]; then
  echo '{"result":{"agent":{"pane_id":"w1:p1"}}}'
elif [[ "$sub" == "pane read" ]]; then
  n=0
  [[ -n "${FAKE_PANE_READ_COUNT:-}" && -f "$FAKE_PANE_READ_COUNT" ]] && n="$(cat "$FAKE_PANE_READ_COUNT")"
  n=$((n + 1))
  [[ -n "${FAKE_PANE_READ_COUNT:-}" ]] && echo "$n" >"$FAKE_PANE_READ_COUNT"
  printf '%s\n' "$FAKE_PANE_TEXT"
elif [[ "$sub" == "agent prompt" ]]; then
  # agent prompt <target> <text>: $3 is the target, $4 is the literal text.
  # Atomic: capture the full literal text argument for a round-trip assertion.
  [[ -n "${FAKE_PROMPT_CAPTURE:-}" ]] && printf '%s' "$4" >"$FAKE_PROMPT_CAPTURE"
  if [[ -n "${FAKE_PROMPT_MODAL:-}" ]]; then
    echo prompt-blocked >>"$FAKE_LOG"
    exit 1
  fi
  if [[ -n "${FAKE_PROMPT_FAIL:-}" ]]; then
    echo prompt-failed >>"$FAKE_LOG"
    exit 1
  fi
  echo prompt >>"$FAKE_LOG"
elif [[ "$sub" == "agent send-keys" ]]; then
  echo send-keys >>"$FAKE_LOG"
else
  exit 2
fi
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
        fake.write_text(FAKE_HERDR_075)
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

    # --- 0.7.5 atomic-prompt contract ---------------------------------------

    def test_say_submits_atomically_in_one_op_and_marks_pending(self):
        # herdr 0.7.5: a safe prompt is delivered by a single atomic `agent prompt`
        # (paste + submit in one server-owned op). No paste/settle/bare-Enter dance,
        # so exactly one prompt op appears in the log and the message is pending.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt"], log.read_text().splitlines())
            self.assertIn("status=pending", result.stdout)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

    def test_say_round_trips_a_multi_line_body_literally_through_the_atomic_prompt(self):
        # The exact TUR-485 case: a multi-line body with a single quote. Under the
        # old `agent send` + bare-Enter dance this forced a single-line/no-quote
        # workaround; the 0.7.5 atomic prompt preserves it verbatim.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            capture = Path(td) / "prompt-capture"
            env["FAKE_PROMPT_CAPTURE"] = str(capture)
            body = "line one: proceed\nline two: it's ready\nline three: ship"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "ruling", "agent1", body],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt"], log.read_text().splitlines())
            sent = capture.read_text()
            self.assertTrue(sent.startswith(body), sent)
            # The multi-line body survived intact inside the single atomic op.
            self.assertIn("line two: it's ready", sent)

    def test_multi_line_body_round_trips_through_say_then_ack(self):
        # End-to-end TUR-485 retirement: herdr-say sends a multi-line-bodied
        # message and herdr-ack of that exact id succeeds (pending -> acknowledged),
        # where the pre-fix herdr-ack rejected it with illegal-transition because a
        # message line masqueraded as the status field.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            body = "please review\nand confirm\nthe change"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", body],
                env=env, check=True, capture_output=True, text=True,
            )
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode, acked.stderr)
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("acknowledged", stored["status"])
            self.assertEqual(body, stored["message"])

    # --- modal-safe: never bulldoze a trust dialog --------------------------

    def test_modal_queues_without_firing_the_atomic_prompt(self):
        # An open trust dialog: herdr-say must never fire the atomic prompt (which
        # would submit into the modal); it durably queues instead.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "Quick safety check: trust this folder")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertFalse(log.exists())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("queued", tomllib.load(handle)["status"])

    def test_say_defers_to_pending_when_the_atomic_prompt_reports_a_blocked_dialog(self):
        # 0.7.5: if the pre-check misses a modal that opens server-side, the atomic
        # prompt itself refuses (agent_prompt_stalled / dialog detected, non-zero).
        # herdr-say must defer to pending and keep the message in the inbox for
        # herdr-drain, never claim delivery or force-submit.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PROMPT_MODAL"] = "1"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertEqual(["prompt-blocked"], log.read_text().splitlines())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            message_id = states[0].stem
            inbox = Path(td) / "state/octo-lite/inbox/agent1" / message_id
            self.assertTrue(inbox.is_file())

    def test_say_defers_to_pending_when_the_atomic_prompt_stalls_and_does_not_claim_delivered(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PROMPT_FAIL"] = "1"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertEqual(["prompt-failed"], log.read_text().splitlines())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

    # --- herdr-drain 0.7.5 ---------------------------------------------------

    def test_drain_retries_the_atomic_prompt_for_a_pending_message(self):
        # A pending message (an earlier atomic prompt did not land) is retried by
        # firing the atomic prompt again; the atomic op is safe to repeat.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PROMPT_FAIL"] = "1"
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

            log.write_text("")
            drain_env = dict(env)
            drain_env.pop("FAKE_PROMPT_FAIL", None)
            result = subprocess.run(["bash", str(DRAIN), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt"], log.read_text().splitlines())
            self.assertFalse((Path(td) / "state/octo-lite/inbox/agent1" / message_id).exists())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

    def test_drain_leaves_a_pending_message_queued_while_the_modal_is_still_open(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PROMPT_FAIL"] = "1"
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem

            # The modal is still open on the next drain attempt: never fire a prompt.
            log.write_text("")
            still_open_env = dict(env, FAKE_PANE_TEXT="Quick safety check: trust this folder")
            still_open_env.pop("FAKE_PROMPT_FAIL", None)
            result = subprocess.run(["bash", str(DRAIN), "agent1"], env=still_open_env, capture_output=True, text=True)
            self.assertEqual(75, result.returncode)
            self.assertEqual([], log.read_text().splitlines())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            self.assertTrue((Path(td) / "state/octo-lite/inbox/agent1" / message_id).is_file())

    def test_drain_retries_prompt_and_stays_pending_when_the_prompt_transport_fails(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PROMPT_FAIL"] = "1"
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem

            log.write_text("")
            drain_env = dict(env)  # FAKE_PROMPT_FAIL still set: transport keeps failing
            result = subprocess.run(["bash", str(DRAIN), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt-failed"], log.read_text().splitlines())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            self.assertTrue((Path(td) / "state/octo-lite/inbox/agent1" / message_id).is_file())

    def test_drain_persists_pending_before_clearing_the_retry_item_for_a_queued_message(self):
        # A queued (never-transported) message that drain now delivers must persist
        # status=pending before dropping the inbox retry item, or a legitimate
        # herdr-ack afterward would see the stale queued status and reject.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "Quick safety check: trust this folder")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem
            with states[0].open("rb") as handle:
                self.assertEqual("queued", tomllib.load(handle)["status"])

            log.write_text("")
            drain_env = dict(env, FAKE_PANE_TEXT="ready")
            result = subprocess.run(["bash", str(DRAIN), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt"], log.read_text().splitlines())
            self.assertFalse((Path(td) / "state/octo-lite/inbox/agent1" / message_id).exists())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

            ack = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, ack.returncode, ack.stderr)

    def test_drain_keeps_the_retry_item_and_queued_status_when_pending_persistence_fails(self):
        # If the durable pending write cannot be persisted, the retry item must stay
        # so a later drain attempt can retry, instead of silently losing the message.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "Quick safety check: trust this folder")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem
            inbox_item = Path(td) / "state/octo-lite/inbox/agent1" / message_id

            log.write_text("")
            fail_bin = Path(td) / "failbin"
            fail_bin.mkdir()
            fake_mv = fail_bin / "mv"
            real_mv = shutil.which("mv")
            fake_mv.write_text(
                f"""#!/usr/bin/env bash
set -eu
if [[ "${{@: -1}}" == "${{FAKE_MV_FAIL_DEST:-}}" ]]; then
  exit 1
fi
exec {real_mv} "$@"
"""
            )
            fake_mv.chmod(0o755)
            drain_env = dict(env, FAKE_PANE_TEXT="ready")
            drain_env["PATH"] = f"{fail_bin}:{drain_env['PATH']}"
            drain_env["FAKE_MV_FAIL_DEST"] = str(states[0])
            result = subprocess.run(["bash", str(DRAIN), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)

            with states[0].open("rb") as handle:
                self.assertEqual("queued", tomllib.load(handle)["status"])
            self.assertTrue(inbox_item.is_file())

    def test_drain_locks_each_queued_item_to_prevent_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=dict(env, FAKE_PROMPT_FAIL="1"),
                capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem
            inbox_item = Path(td) / "state/octo-lite/inbox/agent1" / message_id
            lock_path = Path(f"{inbox_item}.lock")

            holder = subprocess.Popen(["flock", str(lock_path), "sleep", "3"])
            try:
                for _ in range(20):
                    if lock_path.exists():
                        break
                    __import__("time").sleep(0.1)
                result = subprocess.run(["bash", str(DRAIN), "agent1"], env=env, capture_output=True, text=True)
                self.assertEqual(0, result.returncode)
                self.assertNotIn("prompt", (log.read_text().splitlines() if log.exists() else []))
                self.assertTrue(inbox_item.is_file())
            finally:
                holder.terminate()
                holder.wait()

            second = subprocess.run(["bash", str(DRAIN), "agent1"], env=env, capture_output=True, text=True)
            self.assertEqual(0, second.returncode)
            self.assertIn("prompt", log.read_text().splitlines())
            self.assertFalse(inbox_item.exists())

    # --- ack lifecycle -------------------------------------------------------

    def test_safe_prompt_marks_pending_then_requires_ack(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "ruling", "agent1", "use screenshots"],
                env=env, check=True, capture_output=True, text=True,
            )
            self.assertEqual(["prompt"], log.read_text().splitlines())
            self.assertIn("status=pending", result.stdout)
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env, check=True,
            )
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])

    def test_ack_allows_the_full_pending_acknowledged_completed_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, check=True, capture_output=True, text=True,
            )
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]

            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env, check=True, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode)
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])

            completed = subprocess.run(
                ["bash", str(ACK), message_id, "completed", "--by", "agent1", "--artifact", "ref/1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            with state.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("completed", stored["status"])
            self.assertEqual("ref/1", stored["artifact"])

    def test_ack_rejects_acknowledging_a_message_that_is_already_completed(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, check=True, capture_output=True, text=True,
            )
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            subprocess.run(
                ["bash", str(ACK), message_id, "completed", "--by", "agent1", "--artifact", "ref/1"],
                env=env, check=True, capture_output=True, text=True,
            )
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            regress = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, regress.returncode)
            with state.open("rb") as handle:
                self.assertEqual("completed", tomllib.load(handle)["status"])

    def test_ack_requires_a_prior_transport_attempt(self):
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

    def test_info_kind_never_carries_an_ack_instruction_or_claims_acknowledged(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "info", "agent1", "fyi status update"],
                env=env, check=True, capture_output=True, text=True,
            )
            self.assertIn("status=pending", result.stdout)
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("pending", stored["status"])
            self.assertNotIn("Acknowledge with", stored["message"])

    def test_send_queues_on_transport_failure_without_recording_false_pending(self):
        # A hard atomic-prompt transport failure (not a modal) with no prior attempt
        # leaves the message queued and retryable, never a false pending.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PROMPT_FAIL"] = "1"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            message_id = states[0].stem
            inbox = Path(td) / "state/octo-lite/inbox/agent1" / message_id
            self.assertTrue(inbox.is_file())

    # --- operator-say still delegates to herdr-say ---------------------------

    def test_operator_say_delegates_to_herdr_say_with_the_owner_route(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            owner_file = Path(td) / "operator-owner.toml"
            owner_file.write_text('owner_route = "agent1"\n')
            env["OCTO_OPERATOR_OWNER"] = str(owner_file)
            result = subprocess.run(
                ["bash", str(OPERATOR_SAY), "--kind", "ruling", "proceed with the plan"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt"], log.read_text().splitlines())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("agent1", stored["target"])
            self.assertEqual("pending", stored["status"])

    # --- Source B operator-wait stamp + D5 pending-write scope ---------------

    def test_failed_target_resolution_leaves_a_wait_the_operator_can_clear_by_ack(self):
        # TUR-447: a --kind question with OCTO_STREAM stamps a per-stream operator
        # wait BEFORE target resolution. If resolution then FAILS (unresolved
        # target, exit 66) the message-state file must still exist so herdr-ack of
        # that exact message id can acknowledge and clear the orphan wait.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "herdr"
            # agent get resolves to an EMPTY pane_id: herdr-say cannot resolve the
            # target and must exit 66 after the wait stamp is already written.
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                'if [[ "$1 $2" == "agent get" ]]; then\n'
                "  echo '{\"result\":{\"agent\":{}}}'\n"
                "else\n"
                "  exit 0\n"
                "fi\n"
            )
            fake.chmod(0o755)
            env = dict(os.environ)
            env.update(
                PATH=f"{fake_bin}:{env['PATH']}",
                XDG_STATE_HOME=str(root / "state"),
                OCTO_STREAM="scratch-ask",
            )
            ask = "Approve promotion of TUR-447 to Live?"
            said = subprocess.run(
                ["bash", str(SAY), "--kind", "question", "operator-1", ask],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(66, said.returncode, said.stderr)

            waits_dir = root / "state/octo-lite/operator-waits"
            stamp_path = waits_dir / "scratch-ask.toml"
            self.assertTrue(stamp_path.is_file(), said.stderr)
            with stamp_path.open("rb") as handle:
                stamp = tomllib.load(handle)
            message_id = stamp["message_id"]

            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "operator-1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode, acked.stderr)
            self.assertFalse(stamp_path.is_file())

    def test_errored_target_resolution_leaves_a_wait_the_operator_can_clear_by_ack(self):
        # TUR-447 cycle1 pass5b: when `herdr agent get` exits NON-ZERO (a hard
        # error, not empty) the pane command substitution must not abort herdr-say
        # under set -euo pipefail before the write_state pending guard. Both empty
        # AND errored resolution must fall through to exit 66 with a clearable
        # message-state file.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "herdr"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                'if [[ "$1 $2" == "agent get" ]]; then\n'
                "  echo 'hard error' >&2\n"
                "  exit 3\n"
                "else\n"
                "  exit 0\n"
                "fi\n"
            )
            fake.chmod(0o755)
            env = dict(os.environ)
            env.update(
                PATH=f"{fake_bin}:{env['PATH']}",
                XDG_STATE_HOME=str(root / "state"),
                OCTO_STREAM="scratch-ask",
            )
            ask = "Approve promotion of TUR-447 to Live?"
            said = subprocess.run(
                ["bash", str(SAY), "--kind", "question", "operator-1", ask],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(66, said.returncode, said.stderr)

            states = list((root / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states), said.stderr)
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

            waits_dir = root / "state/octo-lite/operator-waits"
            stamp_path = waits_dir / "scratch-ask.toml"
            self.assertTrue(stamp_path.is_file(), said.stderr)
            with stamp_path.open("rb") as handle:
                stamp = tomllib.load(handle)
            message_id = stamp["message_id"]
            self.assertEqual(message_id, states[0].stem)

            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "operator-1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode, acked.stderr)
            self.assertFalse(stamp_path.is_file())
            with states[0].open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])

    def test_operator_wait_clears_by_ack_for_a_multi_line_ask(self):
        # TUR-505: the operator-wait stamp + message state must round-trip through
        # herdr-ack even when the ask body is multi-line, which the pre-fix ack
        # parse would misread as an illegal transition.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "herdr"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                'if [[ "$1 $2" == "agent get" ]]; then\n'
                "  echo '{\"result\":{\"agent\":{}}}'\n"
                "else\n"
                "  exit 0\n"
                "fi\n"
            )
            fake.chmod(0o755)
            env = dict(os.environ)
            env.update(
                PATH=f"{fake_bin}:{env['PATH']}",
                XDG_STATE_HOME=str(root / "state"),
                OCTO_STREAM="scratch-ask",
            )
            ask = "Approve this?\nContext line one\nContext line two"
            said = subprocess.run(
                ["bash", str(SAY), "--kind", "question", "operator-1", ask],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(66, said.returncode, said.stderr)
            stamp_path = root / "state/octo-lite/operator-waits/scratch-ask.toml"
            self.assertTrue(stamp_path.is_file(), said.stderr)
            with stamp_path.open("rb") as handle:
                message_id = tomllib.load(handle)["message_id"]

            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "operator-1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode, acked.stderr)
            self.assertFalse(stamp_path.is_file())
            state = root / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("acknowledged", stored["status"])
            self.assertEqual(ask, stored["message"])

    def test_non_operator_unresolved_target_stays_retryable_not_ack_acknowledgeable(self):
        # TUR-447 D5: the unresolved-target pending guard exists only to make a
        # stamped operator-wait (kind==question && OCTO_STREAM) clearable by
        # herdr-ack. A NON-operator message (kind=info, no OCTO_STREAM) stamps no
        # wait, so an unresolved target must NOT write a herdr-ack-acknowledgeable
        # pending state; it must fail (exit 66) and stay retryable.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "herdr"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                'if [[ "$1 $2" == "agent get" ]]; then\n'
                "  echo '{\"result\":{\"agent\":{}}}'\n"
                "else\n"
                "  exit 0\n"
                "fi\n"
            )
            fake.chmod(0o755)
            env = dict(os.environ)
            env.update(
                PATH=f"{fake_bin}:{env['PATH']}",
                XDG_STATE_HOME=str(root / "state"),
            )
            env.pop("OCTO_STREAM", None)
            said = subprocess.run(
                ["bash", str(SAY), "--kind", "info", "agent1", "fyi status update"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(66, said.returncode, said.stderr)

            msg_dir = root / "state/octo-lite/messages"
            states = list(msg_dir.glob("*.toml")) if msg_dir.exists() else []
            self.assertEqual([], states, said.stderr)

            waits_dir = root / "state/octo-lite/operator-waits"
            self.assertFalse(waits_dir.exists() and any(waits_dir.iterdir()))

    def test_operator_wait_unresolved_target_still_writes_ack_clearable_state(self):
        # TUR-447 D5 counterpart: the operator-wait case (question + OCTO_STREAM)
        # must STILL write the clearable pending message-state on an unresolved
        # target, so herdr-ack clears the stamped wait.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "herdr"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                'if [[ "$1 $2" == "agent get" ]]; then\n'
                "  echo '{\"result\":{\"agent\":{}}}'\n"
                "else\n"
                "  exit 0\n"
                "fi\n"
            )
            fake.chmod(0o755)
            env = dict(os.environ)
            env.update(
                PATH=f"{fake_bin}:{env['PATH']}",
                XDG_STATE_HOME=str(root / "state"),
                OCTO_STREAM="scratch-ask",
            )
            said = subprocess.run(
                ["bash", str(SAY), "--kind", "question", "operator-1", "Approve?"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(66, said.returncode, said.stderr)
            states = list((root / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states), said.stderr)
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

    # --- herdr-spawn (unchanged bootstrap contract) -------------------------

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

    def spawn_base_command(self, receipt, cwd=None):
        return [
            str(SPAWN), "--workspace", "w1", "--name", "orch-1", "--cwd", str(cwd or ROOT),
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
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
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
                    self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
                )
                self.assertNotEqual(0, result.returncode, name)
                self.assertNotIn("bootstrap=acknowledged", result.stdout, name)
                calls = log.read_text().splitlines() if log.exists() else []
                self.assertFalse(any(call.startswith("tab create") for call in calls), name)
                self.assertFalse(any(call.startswith("agent start") for call in calls), name)
                readback = tomllib.loads(receipt_path.read_text())
                self.assertFalse(readback["bootstrap"]["verified"], name)

    def test_spawn_rejects_role_or_cwd_that_diverges_from_receipt(self):
        def git_repo(path):
            subprocess.run(["git", "init", "-q", str(path)], check=True)
            subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
            (path / "AGENTS.md").write_text("# Target\n")
            subprocess.run(["git", "-C", str(path), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(path), "commit", "-qm", "target"], check=True)

        def assert_blocked_before_bootstrap(result, log):
            self.assertNotEqual(0, result.returncode)
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(call.startswith("claude") for call in calls))
            self.assertFalse(any(call.startswith("tab create") for call in calls))
            self.assertFalse(any(call.startswith("agent start") for call in calls))

        with self.subTest("role_diverges_from_receipt"), tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)
            env, log = self.spawn_environment(td)
            argv = [
                str(SPAWN), "--workspace", "w1", "--name", "meta-1", "--cwd", str(repo),
                "--role", "meta-operator", "--label", "🧠 operator",
                "--receipt", str(receipt_path), "--",
                "claude", "--model", "claude-fable-5", "--effort", "xhigh",
                "--permission-mode", "auto", "--agent", "meta-operator", "prompt",
            ]
            result = subprocess.run(argv, env=env, capture_output=True, text=True)
            assert_blocked_before_bootstrap(result, log)

        with self.subTest("cwd_diverges_from_receipt"), tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)
            env, log = self.spawn_environment(td)
            result = subprocess.run(
                self.spawn_base_command(receipt_path), env=env, capture_output=True, text=True,
            )
            assert_blocked_before_bootstrap(result, log)

    def spawn_mic_command(self, receipt, cwd=None, rc=False):
        claude = ["claude"]
        if rc:
            claude.append("--rc")
        claude += [
            "--model", "claude-opus-4-8[1m]", "--effort", "high",
            "--permission-mode", "auto", "--agent", "orchestrator", "prompt",
        ]
        return [
            str(SPAWN), "--workspace", "w1", "--name", "orch-1", "--cwd", str(cwd or ROOT),
            "--role", "orchestrator", "--label", "🎤 443/6 · operating model",
            "--receipt", str(receipt), "--", *claude,
        ]

    def spawn_git_repo(self, path):
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
        (path / "AGENTS.md").write_text("# Target\n")
        subprocess.run(["git", "-C", str(path), "add", "AGENTS.md"], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-qm", "target"], check=True)

    def test_spawn_fails_closed_on_mic_label_without_remote_control_at_launch(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)
            env, log = self.spawn_environment(td)
            result = subprocess.run(
                self.spawn_mic_command(receipt_path, cwd=repo, rc=False),
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(call.startswith("tab create") for call in calls))
            self.assertFalse(any(call.startswith("agent start") for call in calls))

    def test_spawn_fails_closed_on_operator_label_without_remote_control_at_launch(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            registry = load_registry(ROOT)
            resolved = resolve_role(registry, "meta-operator", set())
            receipt = build_launch_receipt(
                ROOT, resolved, spawn_id=str(uuid.uuid4()), parent="human",
                reply_route="human", repo=repo, worktree=repo,
                execution_location="remote", operator_loopback=False,
                review_delivery="reachable_url_required",
            )
            receipt_path.write_text(render_receipt(receipt))
            env, log = self.spawn_environment(td)
            argv = [
                str(SPAWN), "--workspace", "w1", "--name", "meta-1", "--cwd", str(repo),
                "--role", "meta-operator", "--label", "🧠 operator",
                "--receipt", str(receipt_path), "--",
                "claude", "--model", "claude-fable-5", "--effort", "xhigh",
                "--permission-mode", "auto", "--agent", "meta-operator", "prompt",
            ]
            result = subprocess.run(argv, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(call.startswith("tab create") for call in calls))
            self.assertFalse(any(call.startswith("agent start") for call in calls))

    def test_spawn_admits_mic_label_with_remote_control_at_launch(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            receipt = build_orchestrator_receipt(repo, receipt_path)
            env, log = self.spawn_environment(td)
            result = subprocess.run(
                self.spawn_mic_command(receipt_path, cwd=repo, rc=True),
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("bootstrap=acknowledged", result.stdout)
            self.assertIn(f"provider_session_id={receipt['spawn_id']}", result.stdout)

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

    def test_spawn_rejects_issue_shaper_as_a_role_with_no_persistent_tab(self):
        with tempfile.TemporaryDirectory() as td:
            receipt_path = Path(td) / "launch.toml"
            receipt_path.write_text("unused\n")
            env, log = self.spawn_environment(td)
            argv = [
                str(SPAWN), "--workspace", "w1", "--name", "shaper-1", "--cwd", str(ROOT),
                "--role", "issue-shaper", "--label", "443 · shaping",
                "--receipt", str(receipt_path), "--",
                "claude", "--model", "claude-opus-4-8[1m]", "--effort", "high",
                "--permission-mode", "auto", "--agent", "issue-shaper", "prompt",
            ]
            result = subprocess.run(argv, env=env, capture_output=True, text=True)
            self.assertEqual(65, result.returncode)
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
            invalid = self.spawn_base_command(receipt_path, cwd=repo)
            invalid[invalid.index("443/6 · operating model")] = "TUR-443 operating model"
            result = subprocess.run(invalid, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(log.exists())
            readback = tomllib.loads(receipt_path.read_text())
            self.assertFalse(readback["bootstrap"]["verified"])


if __name__ == "__main__":
    unittest.main()
