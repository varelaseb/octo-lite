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
        # Each "pane read" call increments a counter file so a test can make the modal
        # appear only after the Nth read: this reproduces the exact race where a dialog
        # opens after paste but before Enter, which a single static pane text cannot.
        fake.write_text(
            """#!/usr/bin/env bash
set -eu
if [[ "$1 $2" == "agent get" ]]; then
  echo '{"result":{"agent":{"pane_id":"w1:p1"}}}'
elif [[ "$1 $2" == "pane read" ]]; then
  n=0
  [[ -n "${FAKE_PANE_READ_COUNT:-}" && -f "$FAKE_PANE_READ_COUNT" ]] && n="$(cat "$FAKE_PANE_READ_COUNT")"
  n=$((n + 1))
  [[ -n "${FAKE_PANE_READ_COUNT:-}" ]] && echo "$n" >"$FAKE_PANE_READ_COUNT"
  if [[ -n "${FAKE_PANE_TEXT_SWITCH_AFTER:-}" && "$n" -gt "$FAKE_PANE_TEXT_SWITCH_AFTER" ]]; then
    printf '%s\\n' "$FAKE_PANE_TEXT_AFTER"
  else
    printf '%s\\n' "$FAKE_PANE_TEXT"
  fi
elif [[ "$1 $2" == "agent send" ]]; then
  if [[ -n "${FAKE_SEND_FAIL:-}" ]]; then
    echo send-failed >>"$FAKE_LOG"
    exit 1
  fi
  echo send >>"$FAKE_LOG"
elif [[ "$1 $2" == "pane run" ]]; then
  if [[ -n "${FAKE_RUN_FAIL:-}" ]]; then
    echo run-failed >>"$FAKE_LOG"
    exit 1
  fi
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

    def test_say_defers_to_pending_when_modal_appears_after_paste_and_never_presses_enter(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PANE_TEXT_AFTER"] = "Quick safety check: trust this folder"
            env["FAKE_PANE_TEXT_SWITCH_AFTER"] = "1"
            env["FAKE_PANE_READ_COUNT"] = str(Path(td) / "pane-read-count")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertEqual(["send"], log.read_text().splitlines())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            message_id = states[0].stem
            inbox = Path(td) / "state/octo-lite/inbox/agent1" / message_id
            self.assertTrue(inbox.is_file())

    def test_say_marks_pending_after_exactly_two_pane_reads_never_checking_post_enter_text(self):
        # herdr-say must never infer composer state or delivery from pane transcript
        # text. Only two pane reads ever happen (the pre-send and pre-enter modal
        # safety checks); a zero exit from `pane run` alone ends the attempt, with
        # no third read of the pane to "verify" the composer or transcript.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            read_count_path = Path(td) / "pane-read-count"
            env["FAKE_PANE_READ_COUNT"] = str(read_count_path)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["send", "run"], log.read_text().splitlines())
            self.assertIn("status=pending", result.stdout)
            self.assertEqual(2, int(read_count_path.read_text()))
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            message_id = states[0].stem
            self.assertFalse((Path(td) / "state/octo-lite/inbox/agent1" / message_id).exists())

    def test_say_defers_to_pending_when_enter_fails_and_does_not_claim_delivered(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_RUN_FAIL"] = "1"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertEqual(["send", "run-failed"], log.read_text().splitlines())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

    def test_drain_only_presses_enter_for_a_pending_message_and_never_resends(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PANE_TEXT_AFTER"] = "Quick safety check: trust this folder"
            env["FAKE_PANE_TEXT_SWITCH_AFTER"] = "1"
            env["FAKE_PANE_READ_COUNT"] = str(Path(td) / "pane-read-count")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

            # The pane is safe now: draining a pending message must only press Enter,
            # never re-send the text, or the pane would see the message twice.
            log.write_text("")
            drain_env = dict(env)
            drain_env.pop("FAKE_PANE_TEXT_SWITCH_AFTER", None)
            drain = ROOT / "skills/herdr-comms/assets/herdr-drain"
            result = subprocess.run(["bash", str(drain), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["run"], log.read_text().splitlines())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            message_id = states[0].stem
            self.assertFalse((Path(td) / "state/octo-lite/inbox/agent1" / message_id).exists())

    def test_drain_marks_pending_done_after_exactly_one_pane_read_never_checking_post_enter_text(self):
        # Same boundary as herdr-say, hit from herdr-drain's retry path: a zero exit
        # from `pane run` alone ends the retry loop, with no read of the pane after
        # Enter to "verify" the composer or transcript.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PANE_TEXT_AFTER"] = "Quick safety check: trust this folder"
            env["FAKE_PANE_TEXT_SWITCH_AFTER"] = "1"
            env["FAKE_PANE_READ_COUNT"] = str(Path(td) / "pane-read-count")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem

            log.write_text("")
            read_count_path = Path(td) / "drain-pane-read-count"
            drain_env = dict(env, FAKE_PANE_TEXT="ready", FAKE_PANE_READ_COUNT=str(read_count_path))
            drain_env.pop("FAKE_PANE_TEXT_SWITCH_AFTER", None)
            drain_env.pop("FAKE_PANE_TEXT_AFTER", None)
            drain = ROOT / "skills/herdr-comms/assets/herdr-drain"
            result = subprocess.run(["bash", str(drain), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["run"], log.read_text().splitlines())
            self.assertEqual(1, int(read_count_path.read_text()))
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            self.assertFalse((Path(td) / "state/octo-lite/inbox/agent1" / message_id).exists())

    def test_drain_retries_enter_only_and_stays_pending_when_enter_transport_fails(self):
        # A genuine transport-level failure (nonzero exit from `pane run` itself,
        # never a pane-text match) keeps the message pending and in the inbox for
        # the next retry, and drain must never re-send the text on this path.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PANE_TEXT_AFTER"] = "Quick safety check: trust this folder"
            env["FAKE_PANE_TEXT_SWITCH_AFTER"] = "1"
            env["FAKE_PANE_READ_COUNT"] = str(Path(td) / "pane-read-count")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem

            log.write_text("")
            drain_env = dict(env, FAKE_PANE_TEXT="ready", FAKE_RUN_FAIL="1")
            drain_env.pop("FAKE_PANE_TEXT_SWITCH_AFTER", None)
            drain_env.pop("FAKE_PANE_TEXT_AFTER", None)
            drain = ROOT / "skills/herdr-comms/assets/herdr-drain"
            result = subprocess.run(["bash", str(drain), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["run-failed"], log.read_text().splitlines())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            self.assertTrue((Path(td) / "state/octo-lite/inbox/agent1" / message_id).is_file())

    def test_drain_leaves_a_pending_message_queued_while_the_modal_is_still_open(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["FAKE_PANE_TEXT_AFTER"] = "Quick safety check: trust this folder"
            env["FAKE_PANE_TEXT_SWITCH_AFTER"] = "1"
            env["FAKE_PANE_READ_COUNT"] = str(Path(td) / "pane-read-count")
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem

            # The modal is still open on the next drain attempt: never send or run.
            log.write_text("")
            still_open_env = dict(env, FAKE_PANE_TEXT="Quick safety check: trust this folder")
            still_open_env.pop("FAKE_PANE_TEXT_SWITCH_AFTER", None)
            drain = ROOT / "skills/herdr-comms/assets/herdr-drain"
            result = subprocess.run(["bash", str(drain), "agent1"], env=still_open_env, capture_output=True, text=True)
            self.assertEqual(75, result.returncode)
            self.assertEqual([], log.read_text().splitlines())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])
            self.assertTrue((Path(td) / "state/octo-lite/inbox/agent1" / message_id).is_file())

    def test_drain_persists_pending_before_clearing_the_retry_item_for_a_queued_message(self):
        # A queued (never-sent) message that drain now transports successfully must
        # persist status=pending before dropping the inbox retry item, or a legitimate
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
            drain = ROOT / "skills/herdr-comms/assets/herdr-drain"
            result = subprocess.run(["bash", str(drain), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["send", "run"], log.read_text().splitlines())
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
            drain = ROOT / "skills/herdr-comms/assets/herdr-drain"
            result = subprocess.run(["bash", str(drain), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)

            with states[0].open("rb") as handle:
                self.assertEqual("queued", tomllib.load(handle)["status"])
            self.assertTrue(inbox_item.is_file())

    def test_safe_prompt_marks_pending_then_requires_ack(self):
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
            self.assertIn("status=pending", result.stdout)
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env,
                check=True,
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

    def test_failed_target_resolution_leaves_a_wait_the_operator_can_clear_by_ack(self):
        # TUR-447: a --kind question with OCTO_STREAM stamps a per-stream operator
        # wait BEFORE target resolution. If resolution then FAILS (unresolved
        # target, exit 66) the message-state file must still exist so herdr-ack of
        # that exact message id can acknowledge and clear the orphan wait via its
        # advertised path. At prior HEAD no state file was written, so herdr-ack
        # rejected the id as unknown and the wait was unclearable.
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

            # The advertised clear path: herdr-ack of that exact message id must
            # succeed and remove the orphan wait stamp.
            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "operator-1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode, acked.stderr)
            self.assertFalse(stamp_path.is_file())

    def test_errored_target_resolution_leaves_a_wait_the_operator_can_clear_by_ack(self):
        # TUR-447 cycle1 pass5b: the empty-pane case above resolves cleanly to an
        # empty pane_id (agent get exits 0). But when `herdr agent get` exits
        # NON-ZERO (a hard error, not empty) the pane command substitution must not
        # abort herdr-say under set -euo pipefail before the write_state pending
        # guard. Both an empty AND an errored resolution must fall through to exit
        # 66 with a clearable message-state file, so herdr-ack of that exact id can
        # acknowledge and clear the orphan operator wait. At prior HEAD the command
        # substitution killed herdr-say (rc != 66) and wrote no message state, so
        # the stamped wait was orphaned and unacknowledgeable.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "herdr"
            # agent get exits NON-ZERO: a hard error, distinct from the empty-pane
            # case. herdr-say must still exit 66 after the wait stamp is written.
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

            # The advertised clear path: herdr-ack of that exact message id must
            # succeed and remove both the message state and the orphan wait stamp.
            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "operator-1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode, acked.stderr)
            self.assertFalse(stamp_path.is_file())
            with states[0].open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])

    def test_info_kind_never_carries_an_ack_instruction_or_claims_acknowledged(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "info", "agent1", "fyi status update"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("status=pending", result.stdout)
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("pending", stored["status"])
            self.assertNotIn("Acknowledge with", stored["message"])

    def test_send_queues_on_transport_failure_without_recording_false_pending(self):
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

        # Receipt role is orchestrator, but --role and its flags/label claim
        # meta-operator: spawn must refuse before bootstrap, never trust the CLI role.
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

        # Receipt worktree is repo A, but --cwd is ROOT, a different real git root:
        # spawn must refuse before bootstrap, never trust the CLI cwd.
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
        # A mic-labeled orchestrator spawn; rc controls the --rc launch flag.
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
        # herdr-label-remote-control-gate: a mic-labeled spawn without the --rc
        # launch flag is a launch-gate failure before bootstrap and pane creation.
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
        # herdr-label-remote-control: the 🧠 operator session requires remote
        # control durably at launch; a spawn without --rc fails closed.
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
        # With --rc at launch the mic-labeled spawn proceeds through the normal
        # verified-bootstrap path; unlabeled spawns stay valid without --rc
        # (covered by the existing happy-path test).
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
        # There is no separately persistent issue-shaper session or tab: shaping is a
        # capability the one issue orchestrator loads, never a distinct spawn role.
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
