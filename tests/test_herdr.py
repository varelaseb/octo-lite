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
#   agent get <target>           -> JSON incl agent.pane_id and (A2, soak
#                                   finding 2) agent.state_change_seq. The seq
#                                   is controllable: $FAKE_SEQ_FILE holds the
#                                   current value (default 1 when unset), and
#                                   with FAKE_SEQ_ADVANCES=1 the fake prompt
#                                   increments it (a submission landed, e.g.
#                                   into a WORKING pane where --wait cannot
#                                   match a state mid-turn). FAKE_GET_FAIL_AT=N
#                                   with $FAKE_GET_COUNT_FILE fails exactly the
#                                   Nth agent get call (seq read failure
#                                   modeling). $FAKE_CALL_ORDER, when set,
#                                   records agent-get/prompt call order.
#   agent prompt <target> <text> -> atomic paste+submit in one op; the WHOLE
#                                   text (multi-line, special chars) is captured
#                                   verbatim into $FAKE_PROMPT_CAPTURE so a test
#                                   can assert an atomic literal round-trip. It
#                                   refuses (non-zero, logs "prompt-blocked")
#                                   when a trust dialog is active, and fails
#                                   (non-zero, logs "prompt-failed") when the
#                                   server reports a stall/refusal.
#     --wait --timeout <ms>       (A1, soak finding 1): mirrors the live 0.7.5
#                                   flag semantics: --wait requires an observed
#                                   post-submission state change else it reports
#                                   agent_prompt_stalled. FAKE_WAIT_STALL models
#                                   the dirty-composer swallow: rc=0 WITHOUT a
#                                   submission; with --wait the stall is visible
#                                   (agent_prompt_stalled printed, rc still 0,
#                                   logs "prompt-stalled"); WITHOUT --wait the
#                                   output is indistinguishable from a submit
#                                   (rc=0, logs "prompt" - the exact live
#                                   defect). On an observed state change with
#                                   --wait the fake prints the matched
#                                   post-submission state JSON. The full argv is
#                                   recorded in $FAKE_PROMPT_ARGV when set.
#   agent send-keys <target> ...  -> literal keystrokes, no submit; logs
#                                   "send-keys", records argv in
#                                   $FAKE_SEND_KEYS_ARGV and call order in
#                                   $FAKE_CALL_ORDER when set. A3 (ruling-94):
#                                   with FAKE_ENTER_SUBMITS=1 an Enter
#                                   keystroke submits the pasted composer
#                                   exactly like the live pane (the agent
#                                   state_change_seq advances), modeling the
#                                   submission-by-construction follow-up.
#   pane read <pane> ...          -> visible transcript for the modal-safe
#                                   check; with FAKE_PANE_TEXT_AFTER set (and
#                                   $FAKE_PANE_READ_COUNT counting) reads after
#                                   the first return FAKE_PANE_TEXT_AFTER, so a
#                                   test can open a dialog BETWEEN the paste
#                                   and the Enter follow-up.
# `agent send` and top-level `wait` no longer exist in 0.7.5.
FAKE_HERDR_075 = r"""#!/usr/bin/env bash
set -eu
sub="$1 $2"
if [[ "$sub" == "agent get" ]]; then
  [[ -n "${FAKE_CALL_ORDER:-}" ]] && printf 'agent-get\n' >>"$FAKE_CALL_ORDER"
  if [[ -n "${FAKE_GET_COUNT_FILE:-}" ]]; then
    g=0
    [[ -f "$FAKE_GET_COUNT_FILE" ]] && g="$(cat "$FAKE_GET_COUNT_FILE")"
    g=$((g + 1))
    echo "$g" >"$FAKE_GET_COUNT_FILE"
    if [[ -n "${FAKE_GET_FAIL_AT:-}" && "$g" -eq "$FAKE_GET_FAIL_AT" ]]; then
      echo 'herdr: agent get failed' >&2
      exit 1
    fi
  fi
  seq=1
  [[ -n "${FAKE_SEQ_FILE:-}" && -f "${FAKE_SEQ_FILE:-}" ]] && seq="$(cat "$FAKE_SEQ_FILE")"
  printf '{"result":{"agent":{"pane_id":"w1:p1","state_change_seq":%s}}}\n' "$seq"
elif [[ "$sub" == "pane read" ]]; then
  n=0
  [[ -n "${FAKE_PANE_READ_COUNT:-}" && -f "$FAKE_PANE_READ_COUNT" ]] && n="$(cat "$FAKE_PANE_READ_COUNT")"
  n=$((n + 1))
  [[ -n "${FAKE_PANE_READ_COUNT:-}" ]] && echo "$n" >"$FAKE_PANE_READ_COUNT"
  # TOCTOU hook: herdr-ack does not share drain's inbox lock, so a terminal
  # ack can land between drain's status snapshot and the prompt fire. Flip
  # the message state to acknowledged during the modal-check pane read to
  # deterministically model an ack landing in exactly that window.
  if [[ -n "${FAKE_ACK_ON_PANE_READ:-}" && -f "${FAKE_ACK_ON_PANE_READ:-}" ]]; then
    sed -i 's/^status = .*/status = "acknowledged"/' "$FAKE_ACK_ON_PANE_READ"
  fi
  if [[ -n "${FAKE_PANE_TEXT_AFTER:-}" && "$n" -gt 1 ]]; then
    printf '%s\n' "$FAKE_PANE_TEXT_AFTER"
  else
    printf '%s\n' "$FAKE_PANE_TEXT"
  fi
elif [[ "$sub" == "agent prompt" ]]; then
  # agent prompt <target> <text> [--wait --timeout <ms>]: $3 is the target,
  # $4 is the literal text. Atomic: capture the full literal text argument for
  # a round-trip assertion, and the full argv for the --wait grammar assertion.
  [[ -n "${FAKE_PROMPT_ARGV:-}" ]] && printf '%s\n' "$*" >>"$FAKE_PROMPT_ARGV"
  [[ -n "${FAKE_CALL_ORDER:-}" ]] && printf 'prompt\n' >>"$FAKE_CALL_ORDER"
  has_wait=""
  for arg in "$@"; do
    [[ "$arg" == "--wait" ]] && has_wait=1
  done
  [[ -n "${FAKE_PROMPT_CAPTURE:-}" ]] && printf '%s\n' "$4" >>"$FAKE_PROMPT_CAPTURE"
  # T13 hook: snapshot the caller's durable message states at the exact fire
  # instant, so a test can assert state-before-transport (order law).
  if [[ -n "${FAKE_STATE_SNAPSHOT_DIR:-}" && -n "${FAKE_MSG_ROOT:-}" ]]; then
    mkdir -p "$FAKE_STATE_SNAPSHOT_DIR"
    cp "$FAKE_MSG_ROOT"/*.toml "$FAKE_STATE_SNAPSHOT_DIR"/ 2>/dev/null || true
  fi
  # T-L4 hook: prove the caller holds the permanent message lock DURING the
  # fire: parse the [msg:<id>] suffix and try the lock non-blocking.
  if [[ -n "${FAKE_LOCK_ASSERT_FILE:-}" && -n "${FAKE_LOCKS_DIR:-}" ]]; then
    lock_id="$(printf '%s' "$4" | grep -oE 'msg:[0-9]{8}T[0-9]{6}-[0-9]+-[0-9]+' | head -1 | cut -d: -f2)"
    if [[ -n "$lock_id" ]] && ! flock -n "$FAKE_LOCKS_DIR/$lock_id.lock" true 2>/dev/null; then
      echo held >>"$FAKE_LOCK_ASSERT_FILE"
    else
      echo free >>"$FAKE_LOCK_ASSERT_FILE"
    fi
  fi
  if [[ -n "${FAKE_PROMPT_MODAL:-}" ]]; then
    echo prompt-blocked >>"$FAKE_LOG"
    echo 'herdr: prompt blocked by open dialog' >&2
    exit 1
  fi
  if [[ -n "${FAKE_PROMPT_FAIL:-}" ]]; then
    echo prompt-failed >>"$FAKE_LOG"
    echo 'herdr: agent_prompt_stalled' >&2
    exit 1
  fi
  # A2 (soak finding 2): with FAKE_SEQ_ADVANCES the submission actually lands
  # (working pane: submit/queue succeeds even when --wait cannot match a
  # post-submission state mid-turn), so the agent state_change_seq advances.
  if [[ -n "${FAKE_SEQ_ADVANCES:-}" && -n "${FAKE_SEQ_FILE:-}" ]]; then
    s=1
    [[ -f "$FAKE_SEQ_FILE" ]] && s="$(cat "$FAKE_SEQ_FILE")"
    echo $((s + 1)) >"$FAKE_SEQ_FILE"
  fi
  if [[ -n "${FAKE_WAIT_STALL:-}" ]]; then
    # Dirty composer: the prompt returns rc=0 WITHOUT submitting. Only --wait
    # observes the missing state change and reports agent_prompt_stalled
    # (still rc=0: rc alone never carries the submission signal).
    if [[ -n "$has_wait" ]]; then
      echo prompt-stalled >>"$FAKE_LOG"
      echo 'agent_prompt_stalled'
      exit 0
    fi
    echo prompt >>"$FAKE_LOG"
    exit 0
  fi
  echo prompt >>"$FAKE_LOG"
  if [[ -n "$has_wait" ]]; then
    # Observed post-submission state change within the wait window.
    echo '{"result":{"agent":{"state":"idle","state_change_seq":2}}}'
  fi
  # T20 / T-R87b hook: the transport is accepted server-side, then the CALLER
  # dies before its post-transport transition (crash-mid-fire). Close the
  # inherited lock fd first so the caller's death releases its flock.
  if [[ -n "${FAKE_PROMPT_KILL:-}" ]]; then
    exec 9>&- 2>/dev/null || true
    kill -9 "$PPID"
    sleep 1
  fi
elif [[ "$sub" == "agent send-keys" ]]; then
  [[ -n "${FAKE_CALL_ORDER:-}" ]] && printf 'send-keys\n' >>"$FAKE_CALL_ORDER"
  [[ -n "${FAKE_SEND_KEYS_ARGV:-}" ]] && printf '%s\n' "$*" >>"$FAKE_SEND_KEYS_ARGV"
  echo send-keys >>"$FAKE_LOG"
  # A3.1 (ruling-94): with FAKE_ENTER_SUBMITS the explicit Enter follow-up
  # submits the pasted composer exactly as the live pane does, so the agent
  # state_change_seq advances just like a real submission.
  if [[ -n "${FAKE_ENTER_SUBMITS:-}" && -n "${FAKE_SEQ_FILE:-}" && "${4:-}" == "Enter" ]]; then
    s=1
    [[ -f "$FAKE_SEQ_FILE" ]] && s="$(cat "$FAKE_SEQ_FILE")"
    echo $((s + 1)) >"$FAKE_SEQ_FILE"
  fi
else
  exit 2
fi
"""


# herdr 0.7.5 fake for herdr-spawn. Extends the 0.7.5 grammar above with the
# spawn-side surface and records every call verbatim in $FAKE_LOG:
#   tab create                    -> JSON incl the tab and its root pane
#                                    (real 0.7.5 `tab_created` result shape:
#                                    .result.tab + required .result.root_pane)
#   agent start <NAME> --kind <KIND> --pane <ID> [--timeout MS] [-- ...]
#                                 -> REAL 0.7.5 grammar (verified live via
#                                    `herdr agent start --help`): rejects
#                                    --tab/--no-focus as unknown options like
#                                    the live binary, requires --kind and
#                                    --pane, and adopts the given EXISTING pane
#                                    in place (no split, no phantom pane, no
#                                    topology change); argv recorded so tests
#                                    can assert the exact launch grammar
#   agent get <target>            -> the adopted pane (same id tab create gave)
#     FAKE_START_BUSY_COUNT=N     -> TUR-505 hotfix r2 (ruling-93 fidelity):
#                                    the first N `agent start` invocations exit
#                                    non-zero printing the REAL 0.7.5 error
#                                    shape on stderr (verified live: the CLI
#                                    emits {"error":{"code":...,"message":...},
#                                    "id":"cli:agent:start"} and exit 1; the
#                                    live spawn failure printed code
#                                    agent_pane_busy with message "agent target
#                                    pane <id> is not an available shell");
#                                    invocation N+1 onward succeeds. Counting
#                                    persists in $FAKE_START_COUNT_FILE and
#                                    per-invocation timestamps land in
#                                    $FAKE_START_TIMES when set.
#     FAKE_START_FAIL_OTHER=1     -> every `agent start` fails with a NON-busy
#                                    real-shape error (agent_pane_not_found)
#   tab close <tab_id>            -> REAL 0.7.5 grammar (verified live via
#                                    `herdr tab close --help`: positional
#                                    <tab_id>, no flags); recorded so tests can
#                                    assert orphan-tab cleanup
#   agent send-keys <target> ...  -> literal keystrokes (trust-dialog accept);
#                                    fails non-zero with FAKE_SEND_KEYS_FAIL
#   pane read <pane> ...          -> visible transcript; with FAKE_DIALOG_FIRST
#                                    the FIRST read shows the trust dialog and
#                                    later reads show a ready pane; with
#                                    FAKE_DIALOG_ALWAYS every read shows the
#                                    trust dialog (it never clears)
#   pane close                    -> still recorded, but 0.7.5 spawn must never
#                                    call it: there is no phantom pane to close
FAKE_HERDR_075_SPAWN = r"""#!/usr/bin/env bash
set -eu
echo "$*" >>"$FAKE_LOG"
sub="$1 $2"
if [[ "$sub" == "tab create" ]]; then
  echo '{"result":{"tab":{"tab_id":"w1:t1"},"root_pane":{"pane_id":"w1:p1"}}}'
elif [[ "$sub" == "agent start" ]]; then
  shift 2
  kind=""
  pane=""
  while (($#)); do
    case "$1" in
      --tab|--no-focus)
        echo "error: unexpected argument '$1' found" >&2
        exit 2
        ;;
      --kind) kind="${2:-}"; shift 2 ;;
      --pane) pane="${2:-}"; shift 2 ;;
      --timeout) shift 2 ;;
      --) shift; break ;;
      *) shift ;;
    esac
  done
  if [[ -z "$kind" || -z "$pane" ]]; then
    echo "error: the following required arguments were not provided: --kind --pane" >&2
    exit 2
  fi
  [[ -n "${FAKE_START_TIMES:-}" ]] && date +%s.%N >>"$FAKE_START_TIMES"
  n=0
  if [[ -n "${FAKE_START_COUNT_FILE:-}" ]]; then
    [[ -f "$FAKE_START_COUNT_FILE" ]] && n="$(cat "$FAKE_START_COUNT_FILE")"
    n=$((n + 1))
    echo "$n" >"$FAKE_START_COUNT_FILE"
  fi
  if [[ -n "${FAKE_START_FAIL_OTHER:-}" ]]; then
    printf '{"error":{"code":"agent_pane_not_found","message":"agent target pane %s not found"},"id":"cli:agent:start"}\n' "$pane" >&2
    exit 1
  fi
  if [[ -n "${FAKE_START_BUSY_COUNT:-}" && "$n" -le "$FAKE_START_BUSY_COUNT" ]]; then
    printf '{"error":{"code":"agent_pane_busy","message":"agent target pane %s is not an available shell"},"id":"cli:agent:start"}\n' "$pane" >&2
    exit 1
  fi
elif [[ "$sub" == "tab close" ]]; then
  :
elif [[ "$sub" == "agent get" ]]; then
  echo '{"result":{"agent":{"pane_id":"w1:p1"}}}'
elif [[ "$sub" == "agent send-keys" ]]; then
  if [[ -n "${FAKE_SEND_KEYS_FAIL:-}" ]]; then
    exit 1
  fi
elif [[ "$sub" == "pane close" ]]; then
  :
elif [[ "$sub" == "pane read" ]]; then
  n=0
  [[ -n "${FAKE_READ_COUNT_FILE:-}" && -f "${FAKE_READ_COUNT_FILE:-}" ]] && n="$(cat "$FAKE_READ_COUNT_FILE")"
  n=$((n + 1))
  [[ -n "${FAKE_READ_COUNT_FILE:-}" ]] && echo "$n" >"$FAKE_READ_COUNT_FILE"
  # Read-failure modes: FAKE_PANE_READ_FAIL=always makes every pane read exit
  # non-zero; FAKE_PANE_READ_FAIL=after-first lets the first read succeed
  # (e.g. show the dialog via FAKE_DIALOG_FIRST) and fails every later read,
  # modelling a pane read that breaks during post-accept verification.
  if [[ "${FAKE_PANE_READ_FAIL:-}" == "always" ]]; then
    echo 'pane read failed' >&2
    exit 1
  fi
  if [[ "${FAKE_PANE_READ_FAIL:-}" == "after-first" && "$n" -gt 1 ]]; then
    echo 'pane read failed' >&2
    exit 1
  fi
  if [[ -n "${FAKE_DIALOG_ALWAYS:-}" ]]; then
    printf 'Quick safety check: trust this folder\n'
  elif [[ -n "${FAKE_DIALOG_FIRST:-}" && "$n" -eq 1 ]]; then
    printf 'Quick safety check: trust this folder\n'
  else
    printf 'ready\n'
  fi
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
        for stale in ("OCTO_GATE_PING", "OCTO_OPERATOR_OWNER"):
            env.pop(stale, None)
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
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
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
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
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
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
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
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
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

    def test_drain_re_fires_the_full_multi_line_body_and_keeps_state_faithful(self):
        # TUR-505 review round 1: herdr-drain must parse fields like herdr-ack
        # (NUL-delimited key/value), never a positional line readarray. A 3-line
        # body otherwise shifts status out of position, drain fires only the
        # first line, and the rewritten state file corrupts message/created_at.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            body = "line one: proceed\nline two: it's ready\nline three: ship"
            queue = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", body],
                env=dict(env, FAKE_PROMPT_FAIL="1"),
                capture_output=True, text=True,
            )
            self.assertEqual(75, queue.returncode)
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            message_id = states[0].stem
            with states[0].open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("pending", stored["status"])
            created_at = stored["created_at"]

            log.write_text("")
            capture = Path(td) / "prompt-capture"
            drain_env = dict(env, FAKE_PROMPT_CAPTURE=str(capture))
            result = subprocess.run(["bash", str(DRAIN), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            # The atomic prompt re-fires the FULL 3-line body, not line one only.
            sent = capture.read_text()
            self.assertTrue(sent.startswith(body), sent)
            self.assertIn("line two: it's ready", sent)
            self.assertIn("line three: ship", sent)
            # State stays faithful: still pending, body and created_at intact.
            self.assertFalse((Path(td) / "state/octo-lite/inbox/agent1" / message_id).exists())
            with states[0].open("rb") as handle:
                rewritten = tomllib.load(handle)
            self.assertEqual("pending", rewritten["status"])
            self.assertEqual(body, rewritten["message"])
            self.assertEqual(created_at, rewritten["created_at"])

    def test_drain_removes_a_stale_inbox_item_for_a_terminal_message_without_refiring(self):
        # TUR-505 review round 2 finding 1: a message may reach a TERMINAL state
        # (acknowledged, rejected, completed) while its inbox retry item lingers,
        # for example when the recipient acks between transport failure and the
        # next drain. Drain must branch on the actual status: for a terminal
        # message it removes the stale inbox item WITHOUT firing any duplicate
        # atomic prompt and WITHOUT rewriting the terminal state back to pending.
        terminal_cases = {
            "acknowledged": [],
            "rejected": [],
            "completed": ["--artifact", "ref/1"],
        }
        for terminal, extra in terminal_cases.items():
            with self.subTest(terminal), tempfile.TemporaryDirectory() as td:
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
                self.assertTrue(inbox_item.is_file())

                acked = subprocess.run(
                    ["bash", str(ACK), message_id, terminal, "--by", "agent1", *extra],
                    env=env, capture_output=True, text=True,
                )
                self.assertEqual(0, acked.returncode, acked.stderr)

                log.write_text("")
                result = subprocess.run(["bash", str(DRAIN), "agent1"], env=env, capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)
                # No duplicate transport of any kind for a terminal message.
                self.assertEqual([], log.read_text().splitlines())
                # The stale retry item is gone and the terminal state is untouched.
                self.assertFalse(inbox_item.exists())
                with states[0].open("rb") as handle:
                    self.assertEqual(terminal, tomllib.load(handle)["status"])

    def test_drain_rechecks_status_at_fire_time_and_never_refires_a_just_acked_message(self):
        # TUR-505 ruling-75 finding 2 (TOCTOU): herdr-ack writes message state
        # WITHOUT taking drain's inbox lock, so an ack can land between drain's
        # first status snapshot and the prompt fire. The fake herdr flips the
        # state to acknowledged during the modal-check pane read, which sits in
        # exactly that window. Drain must re-check the durable status at fire
        # time and skip: no prompt, terminal state untouched, stale item gone.
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
            self.assertTrue(inbox_item.is_file())
            with states[0].open("rb") as handle:
                self.assertEqual("pending", tomllib.load(handle)["status"])

            log.write_text("")
            drain_env = dict(env, FAKE_ACK_ON_PANE_READ=str(states[0]))
            result = subprocess.run(["bash", str(DRAIN), "agent1"], env=drain_env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            # No duplicate atomic prompt for the just-acked message.
            self.assertEqual([], log.read_text().splitlines())
            # The terminal state is untouched and the stale retry item is gone.
            with states[0].open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])
            self.assertFalse(inbox_item.exists())
            self.assertIn("stale_retry_removed=1", result.stdout)

    def test_drain_locks_each_queued_item_to_prevent_duplicate_delivery(self):
        # TUR-505 phase-1 L1: the message lock is the PERMANENT sidecar
        # locks/<id>.lock, never an inbox-adjacent lock file.
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
            lock_path = Path(td) / "state/octo-lite/locks" / f"{message_id}.lock"

            holder = subprocess.Popen(
                ["flock", str(lock_path), "sleep", "30"], start_new_session=True
            )
            try:
                for _ in range(50):
                    if lock_path.exists():
                        probe = subprocess.run(["flock", "-n", str(lock_path), "true"], capture_output=True)
                        if probe.returncode != 0:
                            break
                    __import__("time").sleep(0.1)
                result = subprocess.run(["bash", str(DRAIN), "agent1"], env=env, capture_output=True, text=True)
                self.assertEqual(0, result.returncode)
                self.assertNotIn("prompt", (log.read_text().splitlines() if log.exists() else []))
                self.assertTrue(inbox_item.is_file())
            finally:
                os.killpg(holder.pid, __import__("signal").SIGTERM)
                holder.wait()

            second = subprocess.run(["bash", str(DRAIN), "agent1"], env=env, capture_output=True, text=True)
            self.assertEqual(0, second.returncode)
            self.assertIn("prompt", log.read_text().splitlines())
            self.assertFalse(inbox_item.exists())
            # L1 permanence: delivery never unlinks the lock sidecar.
            self.assertTrue(lock_path.exists())

    def test_ack_blocks_on_the_message_lock_and_never_writes_state_while_held(self):
        # TUR-505 phase-1 T1: herdr-ack shares the PERMANENT message lock
        # locks/<id>.lock with drain's check-then-fire, so an ack can never
        # write terminal state inside a fire window. While the lock is held
        # elsewhere a short-wait ack must exit non-zero WITHOUT writing state,
        # and the same ack must succeed once released.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, check=True, capture_output=True, text=True,
            )
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            lock_path = Path(td) / "state/octo-lite/locks" / f"{message_id}.lock"

            # Hold the exact drain-side lock in a background subprocess. flock
            # forks the held command, so the holder runs in its own session and
            # the whole process group is killed to actually release the lock.
            holder = subprocess.Popen(
                ["flock", str(lock_path), "sleep", "30"], start_new_session=True
            )
            try:
                for _ in range(50):
                    if lock_path.exists():
                        break
                    __import__("time").sleep(0.1)
                self.assertTrue(lock_path.exists())
                blocked = subprocess.run(
                    ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                    env=dict(env, HERDR_ACK_LOCK_WAIT="1"),
                    capture_output=True, text=True,
                )
                # Bounded wait expired: non-zero, clear error, NO unlocked write.
                self.assertNotEqual(0, blocked.returncode)
                self.assertIn("lock", blocked.stderr)
                with state.open("rb") as handle:
                    self.assertEqual("pending", tomllib.load(handle)["status"])
            finally:
                os.killpg(holder.pid, __import__("signal").SIGTERM)
                holder.wait()

            # Lock released: the same ack now acquires it and acknowledges.
            released = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=dict(env, HERDR_ACK_LOCK_WAIT="1"),
                capture_output=True, text=True,
            )
            self.assertEqual(0, released.returncode, released.stderr)
            with state.open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])

    def test_ack_without_contention_still_acknowledges_and_clears_operator_waits(self):
        # No-contention regression for the shared per-message inbox lock: with
        # nobody holding the lock a normal ack must acquire it, transition the
        # state, and still clear the matching operator-wait stamp.
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            env["OCTO_STREAM"] = "lane-a"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "question", "agent1", "proceed?"],
                env=env, check=True, capture_output=True, text=True,
            )
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            stamp = Path(td) / "state/octo-lite/operator-waits/lane-a.toml"
            self.assertTrue(stamp.is_file())
            acked = subprocess.run(
                ["bash", str(ACK), message_id, "acknowledged", "--by", "agent1"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, acked.returncode, acked.stderr)
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                self.assertEqual("acknowledged", tomllib.load(handle)["status"])
            self.assertFalse(stamp.exists())

    # --- ack lifecycle -------------------------------------------------------

    def test_safe_prompt_marks_pending_then_requires_ack(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "ruling", "agent1", "use screenshots"],
                env=env, check=True, capture_output=True, text=True,
            )
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
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

    def test_info_kind_completes_on_confirmed_submit_and_carries_id_without_ack_instruction(self):
        # TUR-505 phase-1 S2b + state machine: a confirmed info submit is a
        # completed transport (pending->completed under the lock), and the
        # transported body carries the [msg:<id>] suffix with NO ack
        # instruction, so every duplicate is id-correlated (T29).
        with tempfile.TemporaryDirectory() as td:
            env, log = self.environment(td, "ready")
            capture = Path(td) / "prompt-capture"
            env["FAKE_PROMPT_CAPTURE"] = str(capture)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "info", "agent1", "fyi status update"],
                env=env, check=True, capture_output=True, text=True,
            )
            self.assertIn("status=completed", result.stdout)
            message_id = result.stdout.split("message_id=", 1)[1].split()[0]
            state = Path(td) / f"state/octo-lite/messages/{message_id}.toml"
            with state.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("completed", stored["status"])
            self.assertNotIn("Acknowledge with", stored["message"])
            sent = capture.read_text()
            self.assertIn(f"[msg:{message_id}]", sent)
            self.assertNotIn("Acknowledge with", sent)

    def test_send_defers_to_pending_and_stays_retryable_on_hard_transport_failure(self):
        # A hard atomic-prompt failure (not a modal) is still an attempted
        # transport: the prompt may have landed server-side despite the reported
        # stall, so 0.7.5 records pending (never delivered, never a stale queued)
        # and keeps the inbox retry item so herdr-drain re-fires the same atomic
        # prompt, which never double-submits partially-pasted text.
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
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            states = list((Path(td) / "state/octo-lite/messages").glob("*.toml"))
            self.assertEqual(1, len(states))
            with states[0].open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("agent1", stored["target"])
            # A ruling is non-info: confirmed transport stays pending (ACK-WAIT).
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

    # --- herdr-spawn (0.7.5 agent start; bootstrap contract unchanged) ------

    def spawn_environment(self, td, ack_override=None):
        root = Path(td)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        log = root / "herdr.log"
        fake = fake_bin / "herdr"
        fake.write_text(FAKE_HERDR_075_SPAWN)
        fake.chmod(0o755)
        (fake_bin / "claude").write_text(FAKE_BOOTSTRAP_CLAUDE)
        (fake_bin / "claude").chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{fake_bin}:{OCTO_LAUNCH.parent}:{os.environ['PATH']}",
            FAKE_LOG=str(log),
            CALL_LOG=str(log),
            FAKE_READ_COUNT_FILE=str(root / "read-count"),
            FAKE_START_COUNT_FILE=str(root / "start-count"),
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

    def test_spawn_uses_real_075_agent_start_kind_pane_grammar(self):
        # TUR-505 hotfix: the REAL 0.7.5 grammar (verified live via
        # `herdr agent start --help`) is
        #   agent start <NAME> --kind <KIND> --pane <ID> [--timeout MS] [-- ...]
        # with NO --tab and NO --no-focus; the live binary rejects both as
        # unknown options, so any spawn passing them fails. The pane is the
        # tab's root pane that `tab create` already returns as required
        # `.result.root_pane.pane_id` in its `tab_created` result.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            receipt = build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            calls = log.read_text().splitlines()
            start_calls = [call for call in calls if call.startswith("agent start")]
            self.assertEqual(1, len(start_calls), calls)
            start_call = start_calls[0]
            self.assertTrue(
                start_call.startswith(
                    f"agent start orch-1 --kind claude --pane w1:p1 -- claude --resume {receipt['spawn_id']}"
                ),
                start_call,
            )
            self.assertNotIn("--tab", start_call)
            self.assertNotIn("--no-focus", start_call)

    def test_spawn_uses_native_075_agent_start_without_topology_hacks(self):
        # herdr 0.7.5 `agent start --pane` adopts the tab's existing root pane
        # without changing topology, so a normal spawn must never fire the old
        # split-tab-close hack (`pane close` on a phantom root pane) and must
        # not duplicate the tab cwd with an explicit `--cwd` on agent start
        # (the adopted pane already sits at the receipt-verified tab cwd).
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            calls = log.read_text().splitlines()
            self.assertFalse(any(call.startswith("pane close") for call in calls), calls)
            start_calls = [call for call in calls if call.startswith("agent start")]
            self.assertEqual(1, len(start_calls), calls)
            self.assertIn("--pane w1:p1", start_calls[0])
            self.assertNotIn("--cwd", start_calls[0])
            # The receipt-verified cwd is still anchored where the tab is made.
            tab_call = next(call for call in calls if call.startswith("tab create"))
            self.assertIn(f"--cwd {repo}", tab_call)

    def test_spawn_retries_agent_start_on_agent_pane_busy_until_the_shell_is_ready(self):
        # TUR-505 hotfix r2: live verify showed `agent start` firing before the
        # freshly created root pane reaches its shell prompt; the real binary
        # answers exit 1 with the structured stderr error code agent_pane_busy
        # ("pane ... is not an available shell"). Spawn must retry ONLY that
        # error with bounded backoff (0.5s doubling to max 2s) and succeed once
        # the pane is ready, instead of failing the whole spawn immediately.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_START_BUSY_COUNT"] = "2"
            env["FAKE_START_TIMES"] = str(Path(td) / "start-times")
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("bootstrap=acknowledged", result.stdout)
            calls = log.read_text().splitlines()
            start_calls = [call for call in calls if call.startswith("agent start")]
            self.assertEqual(3, len(start_calls), calls)
            # Backoff sleeps actually happened between attempts: 0.5s then 1s.
            times = [float(line) for line in Path(env["FAKE_START_TIMES"]).read_text().split()]
            self.assertEqual(3, len(times))
            self.assertGreaterEqual(times[1] - times[0], 0.4, times)
            self.assertGreaterEqual(times[2] - times[1], 0.9, times)
            # A successful retry leaves no cleanup artifacts behind.
            self.assertFalse(any(call.startswith("tab close") for call in calls), calls)

    def test_spawn_closes_the_orphan_tab_when_agent_pane_busy_retries_exhaust(self):
        # TUR-505 hotfix r2 orphan cleanup: when the pane never reaches a shell
        # prompt and every bounded retry answers agent_pane_busy, spawn must
        # exit non-zero with NO success report and close the tab it created
        # (real 0.7.5 grammar `tab close <tab_id>`), leaving no orphan tab.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_START_BUSY_COUNT"] = "99"
            env["HERDR_SPAWN_START_RETRIES"] = "3"
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)
            self.assertIn("agent_pane_busy", result.stderr)
            calls = log.read_text().splitlines()
            start_calls = [call for call in calls if call.startswith("agent start")]
            self.assertEqual(3, len(start_calls), calls)
            self.assertIn("tab close w1:t1", calls, calls)
            # Cleanup happens after the final failed start, and the spawn never
            # proceeds to the trust-dialog flow on a failed start.
            self.assertFalse(any(call.startswith("agent send-keys") for call in calls), calls)
            self.assertFalse(any(call.startswith("pane read") for call in calls), calls)

    def test_spawn_fails_immediately_and_cleans_up_on_a_non_busy_agent_start_error(self):
        # TUR-505 hotfix r2: ONLY agent_pane_busy retries. Any other structured
        # `agent start` failure (here the real-shape agent_pane_not_found) must
        # fail immediately with exactly one start attempt, no backoff, no
        # success report, and still close the created tab.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_START_FAIL_OTHER"] = "1"
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)
            self.assertIn("agent_pane_not_found", result.stderr)
            calls = log.read_text().splitlines()
            start_calls = [call for call in calls if call.startswith("agent start")]
            self.assertEqual(1, len(start_calls), calls)
            self.assertIn("tab close w1:t1", calls, calls)
            self.assertFalse(any(call.startswith("agent send-keys") for call in calls), calls)

    def test_spawn_auto_accepts_the_trust_dialog_with_literal_send_keys(self):
        # The Claude onboarding trust dialog still appears on a fresh pane. The
        # 0.7.5 spawn must dismiss it with a literal `agent send-keys` Enter
        # (never an atomic prompt, which would submit text into the modal) and
        # still never close any pane while doing so.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_DIALOG_FIRST"] = "1"
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("bootstrap=acknowledged", result.stdout)
            calls = log.read_text().splitlines()
            accepts = [call for call in calls if call.startswith("agent send-keys")]
            self.assertEqual(1, len(accepts), calls)
            self.assertIn("w1:p1", accepts[0])
            self.assertFalse(any(call.startswith("agent prompt") for call in calls), calls)
            self.assertFalse(any(call.startswith("pane close") for call in calls), calls)

    def test_spawn_fails_closed_when_the_trust_dialog_never_clears(self):
        # TUR-505 review round 2 finding 2: spawn must verify the trust dialog
        # actually CLEARED after the accept keystrokes. When every pane re-read
        # still shows the dialog, spawn must exit non-zero with no success
        # report instead of reporting a session trapped at the dialog as spawned.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_DIALOG_ALWAYS"] = "1"
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)
            self.assertIn("trust dialog", result.stderr)
            calls = log.read_text().splitlines()
            # The accept was attempted, so the failure is the dialog persisting.
            self.assertTrue(any(call.startswith("agent send-keys") for call in calls), calls)

    def test_spawn_fails_closed_when_the_trust_dialog_accept_keystroke_fails(self):
        # TUR-505 review round 2 finding 2: a failed `agent send-keys` accept
        # must fail closed, never be swallowed while spawn reports success.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_DIALOG_FIRST"] = "1"
            env["FAKE_SEND_KEYS_FAIL"] = "1"
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)

    def test_spawn_fails_closed_when_every_dialog_verification_pane_read_fails(self):
        # TUR-505 ruling-75 finding 1: a failed `pane read` is NOT-cleared or
        # unknown, never cleared. When every verification read exits non-zero,
        # spawn cannot know whether the trust dialog cleared and must fail
        # closed with no success report instead of reporting spawned.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_PANE_READ_FAIL"] = "always"
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)
            self.assertIn("pane read", result.stderr)

    def test_spawn_fails_closed_when_pane_reads_fail_after_the_accept_keystroke(self):
        # TUR-505 ruling-75 finding 1, post-accept window: the first read shows
        # the trust dialog, the accept keystroke is sent, then every re-read
        # FAILS. Pre-fix spawn treated the failed read as cleared and reported
        # success; it must instead keep retrying and fail closed when the reads
        # never recover, because the dialog state is unknown.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            self.spawn_git_repo(repo)
            receipt_path = Path(td) / "launch.toml"
            build_orchestrator_receipt(repo, receipt_path)

            env, log = self.spawn_environment(td)
            env["FAKE_DIALOG_FIRST"] = "1"
            env["FAKE_PANE_READ_FAIL"] = "after-first"
            result = subprocess.run(
                self.spawn_base_command(receipt_path, cwd=repo), env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertNotIn("bootstrap=acknowledged", result.stdout)
            self.assertIn("pane read", result.stderr)
            calls = log.read_text().splitlines()
            # The accept was attempted; the failure is the unverifiable clear.
            self.assertTrue(any(call.startswith("agent send-keys") for call in calls), calls)

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


class MessageLockProtocolTests(unittest.TestCase):
    """TUR-505 phase-1 shaped contract (rulings 83/86/87): permanent message
    locks (L1-L4), retry cap (S2/S2a), universal [msg:id] suffix (S2b), the
    provisional-then-promote state machine, identity grammar, and crash seams.
    Test names carry the contract T-numbers."""

    ID_1 = "20260722T000000-11-111"
    ID_2 = "20260722T000001-22-222"

    def _env(self, td, pane_text="ready"):
        root = Path(td)
        fake_bin = root / "bin"
        fake_bin.mkdir(exist_ok=True)
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
        for stale in ("OCTO_STREAM", "OCTO_TRANSPORT_ATTEMPT_CAP", "OCTO_PROMPT_CONFIRM_TIMEOUT_MS",
                      "OCTO_GATE_PING", "OCTO_OPERATOR_OWNER"):
            env.pop(stale, None)
        return env, log

    def _base(self, td):
        return Path(td) / "state/octo-lite"

    def _load(self, path):
        with path.open("rb") as handle:
            return tomllib.load(handle)

    def _seed(self, td, id_, *, target="agent1", status="pending", kind="command",
              path="deferred", attempts=None, message="do work", item=True):
        base = self._base(td)
        messages = base / "messages"
        messages.mkdir(parents=True, exist_ok=True)
        lines = [
            "schema_version = 1",
            f'message_id = "{id_}"',
            f'target = "{target}"',
            f'kind = "{kind}"',
            f'status = "{status}"',
        ]
        if path is not None:
            lines.append(f'delivery_path = "{path}"')
        if attempts is not None:
            lines.append(f"transport_attempts = {attempts}")
        lines += [
            'artifact = ""',
            f'message = "{message}"',
            'created_at = "2026-07-22T00:00:00Z"',
        ]
        state = messages / f"{id_}.toml"
        state.write_text("\n".join(lines) + "\n")
        if item:
            inbox = base / "inbox" / target
            inbox.mkdir(parents=True, exist_ok=True)
            (inbox / id_).write_text(id_ + "\n")
        return state

    def _drain(self, env, target="agent1"):
        return subprocess.run(["bash", str(DRAIN), target], env=env, capture_output=True, text=True)

    def _ack(self, env, id_, status, by="agent1", extra=()):
        return subprocess.run(
            ["bash", str(ACK), id_, status, "--by", by, *extra],
            env=env, capture_output=True, text=True,
        )

    def _hold_lock(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        holder = subprocess.Popen(
            ["flock", str(lock_path), "sleep", "30"], start_new_session=True
        )
        for _ in range(50):
            if lock_path.exists():
                probe = subprocess.run(["flock", "-n", str(lock_path), "true"], capture_output=True)
                if probe.returncode != 0:
                    return holder
            __import__("time").sleep(0.1)
        raise AssertionError("holder never acquired the lock")

    def _release(self, holder):
        os.killpg(holder.pid, __import__("signal").SIGTERM)
        holder.wait()

    # --- locks and exclusion (T2, T3, T5, T7, T9, T10, T-L4, T-L4b) ---------

    def test_t2_drain_during_ack_hold_skips_item_and_never_treats_a_lock_as_an_item(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._seed(td, self.ID_1)
            base = self._base(td)
            lock_path = base / "locks" / f"{self.ID_1}.lock"
            item = base / "inbox/agent1" / self.ID_1
            # Drop an old-scheme lock file INSIDE the inbox: never an item.
            legacy_lock = base / "inbox/agent1" / f"{self.ID_1}.lock"
            legacy_lock.write_text("")
            holder = self._hold_lock(lock_path)
            try:
                result = self._drain(env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertFalse(log.exists() and "prompt" in log.read_text())
                self.assertTrue(item.is_file())
                self.assertTrue(legacy_lock.is_file())
                self.assertTrue(lock_path.is_file())
            finally:
                self._release(holder)
            fired = self._drain(env)
            self.assertEqual(0, fired.returncode, fired.stderr)
            self.assertIn("prompt", log.read_text().splitlines())
            self.assertIn("send-keys", log.read_text().splitlines())
            self.assertFalse(item.exists())
            self.assertTrue(legacy_lock.is_file())

    def test_t3_double_drain_delivers_exactly_once(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._seed(td, self.ID_1)
            first = subprocess.Popen(["bash", str(DRAIN), "agent1"], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            second = subprocess.Popen(["bash", str(DRAIN), "agent1"], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            first.wait()
            second.wait()
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())

    def test_t5_lock_is_permanent_across_the_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            say = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=dict(env, FAKE_PROMPT_FAIL="1"), capture_output=True, text=True,
            )
            self.assertEqual(75, say.returncode)
            base = self._base(td)
            message_id = next(iter((base / "messages").glob("*.toml"))).stem
            lock_path = base / "locks" / f"{message_id}.lock"
            self.assertTrue(lock_path.is_file())
            inode = lock_path.stat().st_ino
            drained = self._drain(env)
            self.assertEqual(0, drained.returncode, drained.stderr)
            self.assertTrue(lock_path.is_file())
            acked = self._ack(env, message_id, "acknowledged")
            self.assertEqual(0, acked.returncode, acked.stderr)
            done = self._ack(env, message_id, "completed", extra=("--artifact", "ref/1"))
            self.assertEqual(0, done.returncode, done.stderr)
            # A lingering stale item for the terminal state is removed too.
            (base / "inbox/agent1").mkdir(parents=True, exist_ok=True)
            (base / "inbox/agent1" / message_id).write_text(message_id + "\n")
            removed = self._drain(env)
            self.assertEqual(0, removed.returncode, removed.stderr)
            self.assertTrue(lock_path.is_file())
            self.assertEqual(inode, lock_path.stat().st_ino)

    def test_t7_flock_semantics_hold_across_bash_and_python_runtimes(self):
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "locks" / "x.lock"
            lock_path.parent.mkdir()
            # bash flock(1) holds -> python fcntl.flock non-blocking fails
            holder = self._hold_lock(lock_path)
            try:
                with lock_path.open("a") as handle:
                    with self.assertRaises(OSError):
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                self._release(holder)
            # Wait until the bash holder's process group fully releases.
            for _ in range(50):
                probe = subprocess.run(["flock", "-n", str(lock_path), "true"], capture_output=True)
                if probe.returncode == 0:
                    break
                __import__("time").sleep(0.1)
            # python fcntl.flock holds -> bash flock -n fails
            with lock_path.open("a") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                probe = subprocess.run(["flock", "-n", str(lock_path), "true"], capture_output=True)
                self.assertNotEqual(0, probe.returncode)

    def test_t8_ack_vs_ack_repeat_is_idempotent_and_conflict_is_illegal(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            self._seed(td, self.ID_1)
            first = self._ack(env, self.ID_1, "acknowledged")
            self.assertEqual(0, first.returncode, first.stderr)
            # Same-status re-ack: exit 0 idempotent no-op.
            repeat = self._ack(env, self.ID_1, "acknowledged")
            self.assertEqual(0, repeat.returncode, repeat.stderr)
            # Different-status on a terminal state: illegal-transition error
            # (except acknowledged->completed).
            conflict = self._ack(env, self.ID_1, "rejected")
            self.assertNotEqual(0, conflict.returncode)
            self.assertIn("illegal transition", conflict.stderr)
            state = self._base(td) / "messages" / f"{self.ID_1}.toml"
            self.assertEqual("acknowledged", self._load(state)["status"])

    def test_t9_first_use_creates_the_locks_namespace_race_safely(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            self._seed(td, self.ID_1)
            base = self._base(td)
            self.assertFalse((base / "locks").exists())
            procs = [
                subprocess.Popen(["bash", str(DRAIN), "agent1"], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(2)
            ]
            acker = subprocess.Popen(["bash", str(ACK), self.ID_1, "acknowledged", "--by", "agent1"],
                                     env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for proc in procs:
                proc.wait()
            acker.wait()
            self.assertTrue((base / "locks" / f"{self.ID_1}.lock").is_file())

    def test_t10_three_actor_split_one_fire_one_ack_same_lock_inode(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._seed(td, self.ID_1)
            base = self._base(td)
            lock_path = base / "locks" / f"{self.ID_1}.lock"
            item = base / "inbox/agent1" / self.ID_1
            # Actor A (modelled by the external holder) holds the lock pre-fire.
            holder = self._hold_lock(lock_path)
            inode = lock_path.stat().st_ino
            try:
                # Ack blocks (bounded) while the lock is held: no write.
                blocked = subprocess.run(
                    ["bash", str(ACK), self.ID_1, "acknowledged", "--by", "agent1"],
                    env=dict(env, HERDR_ACK_LOCK_WAIT="1"), capture_output=True, text=True,
                )
                self.assertNotEqual(0, blocked.returncode)
                # Drain-B skips the held item, unlinking nothing.
                drain_b = self._drain(env)
                self.assertEqual(0, drain_b.returncode)
                self.assertTrue(item.is_file())
                self.assertEqual(inode, lock_path.stat().st_ino)
                self.assertFalse(log.exists() and "prompt" in log.read_text())
            finally:
                self._release(holder)
            # A releases; the retry fires exactly once; ack then acknowledges.
            fired = self._drain(env)
            self.assertEqual(0, fired.returncode, fired.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            acked = self._ack(env, self.ID_1, "acknowledged")
            self.assertEqual(0, acked.returncode, acked.stderr)
            state = self._base(td) / "messages" / f"{self.ID_1}.toml"
            self.assertEqual("acknowledged", self._load(state)["status"])
            self.assertEqual(inode, lock_path.stat().st_ino)

    def test_tl4_every_fire_happens_while_holding_the_message_lock(self):
        # T-L4: the fake herdr probes locks/<id>.lock non-blocking AT FIRE TIME
        # for both say's initial fire and drain's retry fire; both must hold it.
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            base = self._base(td)
            assert_file = Path(td) / "lock-assert"
            env["FAKE_LOCKS_DIR"] = str(base / "locks")
            env["FAKE_LOCK_ASSERT_FILE"] = str(assert_file)
            say = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=dict(env, FAKE_PROMPT_FAIL="1"), capture_output=True, text=True,
            )
            self.assertEqual(75, say.returncode)
            drained = self._drain(env)
            self.assertEqual(0, drained.returncode, drained.stderr)
            self.assertEqual(["held", "held"], assert_file.read_text().splitlines())

    def test_tl4_resume_and_lockholders_are_bounded_when_the_lock_is_held(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            self._seed(td, self.ID_1, status="stalled", attempts=3, item=False)
            lock_path = self._base(td) / "locks" / f"{self.ID_1}.lock"
            holder = self._hold_lock(lock_path)
            try:
                resumed = subprocess.run(
                    ["bash", str(DRAIN), "--resume", self.ID_1],
                    env=dict(env, HERDR_DRAIN_LOCK_WAIT="1"), capture_output=True, text=True,
                )
                self.assertNotEqual(0, resumed.returncode)
                state = self._base(td) / "messages" / f"{self.ID_1}.toml"
                self.assertEqual("stalled", self._load(state)["status"])
            finally:
                self._release(holder)
            resumed = subprocess.run(
                ["bash", str(DRAIN), "--resume", self.ID_1],
                env=dict(env, HERDR_DRAIN_LOCK_WAIT="1"), capture_output=True, text=True,
            )
            self.assertEqual(0, resumed.returncode, resumed.stderr)

    def test_tl4b_say_vs_drain_at_cap_one_fires_exactly_once(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["OCTO_TRANSPORT_ATTEMPT_CAP"] = "1"
            say = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, say.returncode, say.stderr)
            # Drain immediately after: the confirmed direct message is ACK-WAIT
            # (path=direct), so no second fire ever happens at cap 1.
            drained = self._drain(env)
            self.assertEqual(0, drained.returncode, drained.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())

    # --- state machine (T4, T6, T13, T13b, T15, T24) -------------------------

    def test_t4_non_fireable_item_removed_without_transport_or_rewrite(self):
        cases = {
            "stalled": {"status": "stalled", "attempts": 3},
            "acknowledged": {"status": "acknowledged"},
            "rejected": {"status": "rejected"},
            "completed": {"status": "completed"},
            "ack-wait-direct": {"status": "pending", "path": "direct"},
            "ack-wait-unresolved": {"status": "pending", "path": "unresolved-ask"},
        }
        for name, spec in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as td:
                env, log = self._env(td)
                state = self._seed(
                    td, self.ID_1,
                    status=spec["status"],
                    path=spec.get("path", "deferred"),
                    attempts=spec.get("attempts"),
                )
                before = state.read_text()
                item = self._base(td) / "inbox/agent1" / self.ID_1
                result = self._drain(env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertFalse(log.exists() and "prompt" in log.read_text())
                self.assertFalse(item.exists())
                self.assertEqual(before, state.read_text())

    def test_t6_delivery_path_matrix(self):
        with self.subTest("direct-info-completed"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "info", "agent1", "fyi"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("completed", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())
        with self.subTest("direct-non-info-pending"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())
        with self.subTest("modal-queued-then-drain-fires"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td, "Quick safety check: trust this folder")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("queued", stored["status"])
            self.assertEqual("modal-queued", stored["delivery_path"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
            drained = self._drain(dict(env, FAKE_PANE_TEXT="ready"))
            self.assertEqual(0, drained.returncode, drained.stderr)
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())
        with self.subTest("deferred-pending-retry"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do"],
                env=dict(env, FAKE_PROMPT_FAIL="1"), capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
        with self.subTest("unresolved-operator-ask"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            fake = Path(td) / "bin/herdr"
            fake.write_text(
                "#!/usr/bin/env bash\nset -eu\n"
                'if [[ "$1 $2" == "agent get" ]]; then echo \'{"result":{"agent":{}}}\'; else exit 0; fi\n'
            )
            env["OCTO_STREAM"] = "lane-a"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "question", "operator-1", "ok?"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(66, result.returncode, result.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("unresolved-ask", stored["delivery_path"])
            self.assertFalse(log.exists())
        with self.subTest("unresolved-other-no-state"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            fake = Path(td) / "bin/herdr"
            fake.write_text(
                "#!/usr/bin/env bash\nset -eu\n"
                'if [[ "$1 $2" == "agent get" ]]; then echo \'{"result":{"agent":{}}}\'; else exit 0; fi\n'
            )
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(66, result.returncode)
            msg_dir = self._base(td) / "messages"
            self.assertEqual([], list(msg_dir.glob("*.toml")) if msg_dir.exists() else [])

    def test_t13_state_exists_with_correct_status_before_any_transport(self):
        # State-before-transport order law: at fire time the durable state file
        # is already present at status pending (snapshot by the fake herdr).
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            snapshot = Path(td) / "at-fire"
            env["FAKE_MSG_ROOT"] = str(self._base(td) / "messages")
            env["FAKE_STATE_SNAPSHOT_DIR"] = str(snapshot)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            states = list(snapshot.glob("*.toml"))
            self.assertEqual(1, len(states), "no durable state existed at fire time")
            self.assertEqual("pending", self._load(states[0])["status"])

    def test_t13b_publication_seam_state_is_durable_before_the_item_is_visible(self):
        # At the instant the inbox item becomes visible (its atomic publish
        # rename), the state file already exists with the correct status.
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td, "Quick safety check: trust this folder")
            fail_bin = Path(td) / "seambin"
            fail_bin.mkdir()
            seam_log = Path(td) / "seam-log"
            real_mv = shutil.which("mv")
            (fail_bin / "mv").write_text(
                f"""#!/usr/bin/env bash
set -eu
dest="${{@: -1}}"
if [[ "$dest" == */inbox/* ]]; then
  if ls "$SEAM_STATE_GLOB_DIR"/*.toml >/dev/null 2>&1; then
    echo state-present >>"$SEAM_LOG"
  else
    echo state-missing >>"$SEAM_LOG"
  fi
fi
exec {real_mv} "$@"
"""
            )
            (fail_bin / "mv").chmod(0o755)
            env["PATH"] = f"{fail_bin}:{env['PATH']}"
            env["SEAM_LOG"] = str(seam_log)
            env["SEAM_STATE_GLOB_DIR"] = str(self._base(td) / "messages")
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode)
            self.assertEqual(["state-present"], seam_log.read_text().splitlines())

    def test_t15_illegal_transition_set_is_rejected_without_a_write(self):
        illegal = [
            ("queued", "acknowledged", ()),      # never-transported law
            ("acknowledged", "rejected", ()),
            ("rejected", "acknowledged", ()),
            ("rejected", "completed", ("--artifact", "ref/1")),
            ("completed", "acknowledged", ()),
            ("completed", "rejected", ()),
        ]
        for current, requested, extra in illegal:
            with self.subTest(f"{current}->{requested}"), tempfile.TemporaryDirectory() as td:
                env, _ = self._env(td)
                path = "modal-queued" if current == "queued" else "deferred"
                state = self._seed(td, self.ID_1, status=current, path=path, item=False)
                before = state.read_text()
                result = self._ack(env, self.ID_1, requested, extra=extra)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(before, state.read_text())
        # Legal-completeness spot-checks.
        for requested, extra in (("acknowledged", ()), ("rejected", ()), ("completed", ("--artifact", "r"))):
            with self.subTest(f"stalled->{requested}"), tempfile.TemporaryDirectory() as td:
                env, _ = self._env(td)
                self._seed(td, self.ID_1, status="stalled", attempts=3, item=False)
                result = self._ack(env, self.ID_1, requested, extra=extra)
                self.assertEqual(0, result.returncode, result.stderr)
        with self.subTest("t15b-same-terminal-repeat"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            self._seed(td, self.ID_1, status="rejected", item=False)
            repeat = self._ack(env, self.ID_1, "rejected")
            self.assertEqual(0, repeat.returncode, repeat.stderr)
        with self.subTest("acknowledged->completed-legal"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            self._seed(td, self.ID_1, status="acknowledged", item=False)
            done = self._ack(env, self.ID_1, "completed", extra=("--artifact", "ref/1"))
            self.assertEqual(0, done.returncode, done.stderr)

    def test_t24_completion_rules(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            self._seed(td, self.ID_1, item=False)
            artifactless = self._ack(env, self.ID_1, "completed")
            self.assertNotEqual(0, artifactless.returncode)
            wrong = self._ack(env, self.ID_1, "acknowledged", by="intruder")
            self.assertNotEqual(0, wrong.returncode)
            acked = self._ack(env, self.ID_1, "acknowledged")
            self.assertEqual(0, acked.returncode, acked.stderr)
            done = self._ack(env, self.ID_1, "completed", extra=("--artifact", "ref/1"))
            self.assertEqual(0, done.returncode, done.stderr)
            state = self._base(td) / "messages" / f"{self.ID_1}.toml"
            self.assertEqual("ref/1", self._load(state)["artifact"])

    # --- retry cap (T22 family) ---------------------------------------------

    def test_t22_fires_equal_cap_then_stalls(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["OCTO_TRANSPORT_ATTEMPT_CAP"] = "2"
            env["FAKE_PROMPT_FAIL"] = "1"
            say = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, say.returncode)
            message_id = next(iter((self._base(td) / "messages").glob("*.toml"))).stem
            second = self._drain(env)
            self.assertEqual(0, second.returncode, second.stderr)
            third = self._drain(env)
            self.assertEqual(0, third.returncode, third.stderr)
            self.assertIn("status=stalled", third.stdout)
            # Exactly cap fires happened for the epoch that stayed unconfirmed.
            self.assertEqual(["prompt-failed", "prompt-failed"], log.read_text().splitlines())
            state = self._base(td) / "messages" / f"{message_id}.toml"
            stored = self._load(state)
            self.assertEqual("stalled", stored["status"])
            self.assertEqual(2, stored["transport_attempts"])
            self.assertFalse((self._base(td) / "inbox/agent1" / message_id).exists())
            # Stalled never auto-fires (T15: stalled auto-fire illegal).
            fourth = self._drain(env)
            self.assertEqual(0, fourth.returncode)
            self.assertEqual(["prompt-failed", "prompt-failed"], log.read_text().splitlines())

    def test_t22e_crash_between_increment_and_fire_burns_the_attempt_without_a_fire(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["OCTO_TRANSPORT_ATTEMPT_CAP"] = "1"
            state = self._seed(td, self.ID_1)
            kill_bin = Path(td) / "killbin"
            kill_bin.mkdir()
            real_mv = shutil.which("mv")
            (kill_bin / "mv").write_text(
                f"""#!/usr/bin/env bash
set -eu
dest="${{@: -1}}"
src="$1"
match=""
if [[ "$dest" == "$FAKE_MV_KILL_DEST" ]] && grep -q "$FAKE_MV_KILL_MATCH" "$src" 2>/dev/null; then
  match=1
fi
{real_mv} "$@"
if [[ -n "$match" ]]; then
  kill -9 "$PPID"
  sleep 1
fi
"""
            )
            (kill_bin / "mv").chmod(0o755)
            crash_env = dict(env)
            crash_env["PATH"] = f"{kill_bin}:{crash_env['PATH']}"
            crash_env["FAKE_MV_KILL_DEST"] = str(state)
            crash_env["FAKE_MV_KILL_MATCH"] = "transport_attempts = 1"
            crashed = self._drain(crash_env)
            self.assertNotEqual(0, crashed.returncode)
            # The attempt persisted, the fire never happened.
            self.assertFalse(log.exists())
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual(1, stored["transport_attempts"])
            # Next drain: attempts == cap -> stalled, total fires < cap.
            stalled = self._drain(env)
            self.assertEqual(0, stalled.returncode, stalled.stderr)
            self.assertIn("status=stalled", stalled.stdout)
            self.assertFalse(log.exists())

    def test_t22b_resume_starts_a_new_epoch_and_refires(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._seed(td, self.ID_1, status="stalled", attempts=3, item=False)
            resumed = subprocess.run(
                ["bash", str(DRAIN), "--resume", self.ID_1], env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            state = self._base(td) / "messages" / f"{self.ID_1}.toml"
            stored = self._load(state)
            # New epoch fired: attempts reset to 0 then incremented to 1.
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            self.assertEqual(1, stored["transport_attempts"])
            self.assertEqual("pending", stored["status"])
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            self._seed(td, self.ID_1, status="pending", item=False)
            not_stalled = subprocess.run(
                ["bash", str(DRAIN), "--resume", self.ID_1], env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, not_stalled.returncode)
            malformed = subprocess.run(
                ["bash", str(DRAIN), "--resume", "../../etc/passwd"], env=env, capture_output=True, text=True,
            )
            self.assertEqual(64, malformed.returncode)

    def test_t22c_legacy_state_without_attempts_reads_zero_and_first_increment_writes_it(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["FAKE_PROMPT_FAIL"] = "1"
            state = self._seed(td, self.ID_1, attempts=None)
            drained = self._drain(env)
            self.assertEqual(0, drained.returncode, drained.stderr)
            stored = self._load(state)
            self.assertEqual(1, stored["transport_attempts"])
            self.assertEqual("pending", stored["status"])

    def test_t22d_invalid_cap_env_falls_back_to_default_with_a_warning(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["OCTO_TRANSPORT_ATTEMPT_CAP"] = "banana"
            env["FAKE_PROMPT_FAIL"] = "1"
            self._seed(td, self.ID_1, attempts=2)
            drained = self._drain(env)
            self.assertEqual(0, drained.returncode, drained.stderr)
            self.assertIn("OCTO_TRANSPORT_ATTEMPT_CAP", drained.stderr)
            # Default cap 3 admits the third attempt.
            self.assertEqual(["prompt-failed"], log.read_text().splitlines())

    # --- ruling-87 pins (T-R87b, T-R87c) ------------------------------------

    def test_tr87b_queued_first_fire_order_both_crash_seams(self):
        with self.subTest("kill-post-transition-pre-fire"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            state = self._seed(td, self.ID_1, status="queued", path="modal-queued")
            kill_bin = Path(td) / "killbin"
            kill_bin.mkdir()
            real_mv = shutil.which("mv")
            (kill_bin / "mv").write_text(
                f"""#!/usr/bin/env bash
set -eu
dest="${{@: -1}}"
src="$1"
match=""
if [[ "$dest" == "$FAKE_MV_KILL_DEST" ]] && grep -q 'status = "pending"' "$src" 2>/dev/null; then
  match=1
fi
{real_mv} "$@"
if [[ -n "$match" ]]; then
  kill -9 "$PPID"
  sleep 1
fi
"""
            )
            (kill_bin / "mv").chmod(0o755)
            crash_env = dict(env)
            crash_env["PATH"] = f"{kill_bin}:{crash_env['PATH']}"
            crash_env["FAKE_MV_KILL_DEST"] = str(state)
            crashed = self._drain(crash_env)
            self.assertNotEqual(0, crashed.returncode)
            stored = self._load(state)
            # Death pre-fire leaves pending (legal stall path), never a
            # queued state carrying burned attempts, and the item survives.
            self.assertEqual("pending", stored["status"])
            self.assertFalse(log.exists())
            self.assertTrue((self._base(td) / "inbox/agent1" / self.ID_1).is_file())
            refired = self._drain(env)
            self.assertEqual(0, refired.returncode, refired.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
        with self.subTest("transported-never-queued"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["FAKE_PROMPT_KILL"] = "1"
            self._seed(td, self.ID_1, status="queued", path="modal-queued")
            crashed = self._drain(env)
            self.assertNotEqual(0, crashed.returncode)
            state = self._base(td) / "messages" / f"{self.ID_1}.toml"
            # A transported message can never still be queued.
            self.assertIn("prompt", log.read_text().splitlines())
            self.assertNotEqual("queued", self._load(state)["status"])

    def test_tr87c_target_containment_rejects_the_escape_exemplar_everywhere(self):
        escape = "../../escape:p1"
        with self.subTest("say"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", escape, "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(64, result.returncode)
            self.assertFalse(log.exists())
            # No path was ever derived outside the inbox root.
            self.assertFalse((Path(td) / "escape").exists())
            state_root = self._base(td)
            self.assertFalse((state_root / "inbox").exists())
            self.assertFalse((state_root.parent.parent / "escape").exists())
        with self.subTest("drain"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            result = subprocess.run(
                ["bash", str(DRAIN), escape], env=env, capture_output=True, text=True,
            )
            self.assertEqual(64, result.returncode)
        with self.subTest("resume"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            # A stalled state whose durable target field is the traversal
            # exemplar must be rejected before any path derivation.
            self._seed(td, self.ID_1, target=escape, status="stalled", attempts=3, item=False)
            result = subprocess.run(
                ["bash", str(DRAIN), "--resume", self.ID_1], env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((self._base(td).parent.parent / "escape").exists())

    # --- identity (T14, T16, T17, T17b) -------------------------------------

    def test_t14_malformed_or_alias_ids_are_rejected_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            for bad in ("../../etc/passwd", "abc", "20260722T000000-1-1x", "20260722T0000001-1"):
                with self.subTest(bad):
                    result = self._ack(env, bad, "acknowledged")
                    self.assertEqual(64, result.returncode)
            # Drain: malformed basenames and foreign files are never touched.
            self._seed(td, self.ID_1)
            inbox = self._base(td) / "inbox/agent1"
            (inbox / "notes.txt").write_text("foreign\n")
            (inbox / "m1").write_text("m1\n")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((inbox / "notes.txt").is_file())
            self.assertTrue((inbox / "m1").is_file())

    def test_t16_basename_content_mismatch_is_rejected_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._seed(td, self.ID_1)
            item = self._base(td) / "inbox/agent1" / self.ID_1
            item.write_text(self.ID_2 + "\n")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(log.exists() and "prompt" in log.read_text())
            self.assertTrue(item.is_file())
            self.assertEqual(self.ID_2 + "\n", item.read_text())

    def test_t17_collision_regenerates_the_id_and_keeps_both_states_intact(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            fail_bin = Path(td) / "lnbin"
            fail_bin.mkdir()
            real_ln = shutil.which("ln")
            counter = Path(td) / "ln-count"
            counter.write_text("0")
            (fail_bin / "ln").write_text(
                f"""#!/usr/bin/env bash
set -eu
n="$(cat "$LN_COUNT")"
n=$((n + 1))
echo "$n" >"$LN_COUNT"
if (( n <= ${{LN_FAIL_FIRST:-0}} )); then
  exit 1
fi
exec {real_ln} "$@"
"""
            )
            (fail_bin / "ln").chmod(0o755)
            env["PATH"] = f"{fail_bin}:{env['PATH']}"
            env["LN_COUNT"] = str(counter)
            env["LN_FAIL_FIRST"] = "2"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            messages = self._base(td) / "messages"
            states = list(messages.glob("*.toml"))
            self.assertEqual(1, len(states))
            # No partial temporary left behind.
            self.assertEqual([], list(messages.glob("*.tmp")))

    def test_t17b_collision_exhaustion_exits_nonzero_with_no_partial_state(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            fail_bin = Path(td) / "lnbin"
            fail_bin.mkdir()
            (fail_bin / "ln").write_text("#!/usr/bin/env bash\nexit 1\n")
            (fail_bin / "ln").chmod(0o755)
            env["PATH"] = f"{fail_bin}:{env['PATH']}"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            messages = self._base(td) / "messages"
            self.assertEqual([], list(messages.glob("*")) if messages.exists() else [])

    # --- crash seams (T20, T23b, T26) ---------------------------------------

    def test_t20_crash_mid_fire_refires_with_the_same_msg_id(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            capture = Path(td) / "capture"
            env["FAKE_PROMPT_CAPTURE"] = str(capture)
            self._seed(td, self.ID_1)
            crashed = self._drain(dict(env, FAKE_PROMPT_KILL="1"))
            self.assertNotEqual(0, crashed.returncode)
            state = self._base(td) / "messages" / f"{self.ID_1}.toml"
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            item = self._base(td) / "inbox/agent1" / self.ID_1
            self.assertTrue(item.is_file())
            refired = self._drain(env)
            self.assertEqual(0, refired.returncode, refired.stderr)
            sends = capture.read_text().splitlines()
            self.assertEqual(2, len(sends))
            self.assertEqual(sends[0], sends[1])
            self.assertIn(f"[msg:{self.ID_1}", sends[0])
            stored = self._load(state)
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse(item.exists())

    def test_t23b_legacy_item_without_delivery_path_is_promoted_and_fired(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            state = self._seed(td, self.ID_1, path=None)
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            stored = self._load(state)
            # Promoted (deferred) then confirmed-direct on success.
            self.assertEqual("direct", stored["delivery_path"])
            self.assertEqual("pending", stored["status"])
            self.assertFalse((self._base(td) / "inbox/agent1" / self.ID_1).exists())

    def test_t26_ack_crash_pre_write_leaves_pending_and_reack_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            state = self._seed(td, self.ID_1, item=False)
            fail_bin = Path(td) / "failbin"
            fail_bin.mkdir()
            real_mv = shutil.which("mv")
            (fail_bin / "mv").write_text(
                f"""#!/usr/bin/env bash
set -eu
if [[ "${{@: -1}}" == "${{FAKE_MV_FAIL_DEST:-}}" ]]; then
  exit 1
fi
exec {real_mv} "$@"
"""
            )
            (fail_bin / "mv").chmod(0o755)
            crash_env = dict(env)
            crash_env["PATH"] = f"{fail_bin}:{crash_env['PATH']}"
            crash_env["FAKE_MV_FAIL_DEST"] = str(state)
            crashed = self._ack(crash_env, self.ID_1, "acknowledged")
            self.assertNotEqual(0, crashed.returncode)
            self.assertEqual("pending", self._load(state)["status"])
            retried = self._ack(env, self.ID_1, "acknowledged")
            self.assertEqual(0, retried.returncode, retried.stderr)
            self.assertEqual("acknowledged", self._load(state)["status"])

    # --- litter (T11, T12, T29) ---------------------------------------------

    def test_t11_foreign_and_malformed_entries_are_untouched_by_drain(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            inbox = self._base(td) / "inbox/agent1"
            inbox.mkdir(parents=True)
            (inbox / "README").write_text("foreign\n")
            (inbox / f"{self.ID_1}.lock").write_text("")
            (inbox / ".partial.tmp").write_text("x\n")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(log.exists())
            self.assertTrue((inbox / "README").is_file())
            self.assertTrue((inbox / f"{self.ID_1}.lock").is_file())
            self.assertTrue((inbox / ".partial.tmp").is_file())

    def test_t12_dot_temporary_is_invisible_until_published_then_drains(self):
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._seed(td, self.ID_1, item=False)
            inbox = self._base(td) / "inbox/agent1"
            inbox.mkdir(parents=True, exist_ok=True)
            temp = inbox / f".{self.ID_1}.tmp"
            temp.write_text(self.ID_1 + "\n")
            first = self._drain(env)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertFalse(log.exists())
            self.assertTrue(temp.is_file())
            temp.rename(inbox / self.ID_1)
            second = self._drain(env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())

    def test_t29_info_bodies_carry_the_msg_id_with_no_ack_instruction_on_retry_too(self):
        with tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            capture = Path(td) / "capture"
            env["FAKE_PROMPT_CAPTURE"] = str(capture)
            self._seed(td, self.ID_1, kind="info", message="fyi update")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            sent = capture.read_text()
            self.assertIn(f"[msg:{self.ID_1}]", sent)
            self.assertNotIn("Acknowledge with", sent)
            state = self._base(td) / "messages" / f"{self.ID_1}.toml"
            self.assertEqual("completed", self._load(state)["status"])


def _load_operator_sweep_module():
    import importlib.machinery
    import importlib.util

    sweep = ROOT / "scripts/operator-sweep"
    loader = importlib.machinery.SourceFileLoader("operator_sweep_a1", str(sweep))
    spec = importlib.util.spec_from_file_location("operator_sweep_a1", sweep, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ObservedConfirmationTests(unittest.TestCase):
    """TUR-505 amendment A1 (soak finding 1): rc never confirms delivery.
    Confirmation is OBSERVED STATE via `agent prompt --wait --timeout`; only a
    matched post-submission state confirms. agent_prompt_stalled, timeout,
    nonzero rc, or any unmatched outcome is UNCONFIRMED and fails closed:
    status stays-or-becomes pending, the inbox item is retained-or-created for
    drain retry, and the attempts law applies unchanged. Test names carry the
    contract TA1 letters."""

    ID_1 = "20260722T000000-11-111"

    _env = MessageLockProtocolTests._env
    _base = MessageLockProtocolTests._base
    _load = MessageLockProtocolTests._load
    _seed = MessageLockProtocolTests._seed
    _drain = MessageLockProtocolTests._drain

    def test_ta1a_rc_zero_wait_stall_never_confirms_and_fails_closed_to_pending(self):
        # The live swallow: prompt rc=0 but --wait observes NO state change
        # (agent_prompt_stalled). Pre-fix the info kind went completed (the
        # captured red); post-fix every kind stays pending with its retry item
        # and the attempt incremented.
        with self.subTest("say-info"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["FAKE_WAIT_STALL"] = "1"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "info", "agent1", "fyi update"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("status=completed", result.stdout)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
            self.assertEqual(["prompt-stalled", "send-keys"], log.read_text().splitlines())
        with self.subTest("say-non-info"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["FAKE_WAIT_STALL"] = "1"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode, result.stdout + result.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            # Never a false confirmed-pending promotion to path=direct.
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
        with self.subTest("drain"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["FAKE_WAIT_STALL"] = "1"
            state = self._seed(td, self.ID_1, kind="info", message="fyi update")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("status=completed", result.stdout)
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertTrue((self._base(td) / "inbox/agent1" / self.ID_1).is_file())
            self.assertEqual(["prompt-stalled", "send-keys"], log.read_text().splitlines())

    def test_ta1b_observed_state_change_confirms_exactly_as_before(self):
        with self.subTest("say-info-completed"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "info", "agent1", "fyi update"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=completed", result.stdout)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("completed", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
        with self.subTest("say-non-info-direct-promotion"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            # Pending, no item, promoted direct: the ACK-WAIT promotion intact.
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())
        with self.subTest("drain-confirmed"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            state = self._seed(td, self.ID_1)
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse((self._base(td) / "inbox/agent1" / self.ID_1).exists())
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())

    def test_ta1c_confirm_timeout_env_knob_with_invalid_default_and_warning(self):
        with self.subTest("say-custom-timeout"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            argv = Path(td) / "prompt-argv"
            env["FAKE_PROMPT_ARGV"] = str(argv)
            env["OCTO_PROMPT_CONFIRM_TIMEOUT_MS"] = "2500"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(argv.read_text().splitlines()[-1].endswith("--wait --timeout 2500"))
        with self.subTest("say-invalid-default-warn"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            argv = Path(td) / "prompt-argv"
            env["FAKE_PROMPT_ARGV"] = str(argv)
            env["OCTO_PROMPT_CONFIRM_TIMEOUT_MS"] = "soon"
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("OCTO_PROMPT_CONFIRM_TIMEOUT_MS", result.stderr)
            self.assertTrue(argv.read_text().splitlines()[-1].endswith("--wait --timeout 15000"))
        with self.subTest("drain-invalid-default-warn"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            argv = Path(td) / "prompt-argv"
            env["FAKE_PROMPT_ARGV"] = str(argv)
            env["OCTO_PROMPT_CONFIRM_TIMEOUT_MS"] = "-3"
            self._seed(td, self.ID_1)
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("OCTO_PROMPT_CONFIRM_TIMEOUT_MS", result.stderr)
            self.assertTrue(argv.read_text().splitlines()[-1].endswith("--wait --timeout 15000"))

    def test_ta1d_say_and_drain_fire_with_wait_and_timeout_argv(self):
        with self.subTest("say"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            argv = Path(td) / "prompt-argv"
            env["FAKE_PROMPT_ARGV"] = str(argv)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            lines = argv.read_text().splitlines()
            self.assertEqual(1, len(lines))
            self.assertTrue(lines[0].startswith("agent prompt w1:p1 "), lines[0])
            self.assertTrue(lines[0].endswith("--wait --timeout 15000"), lines[0])
        with self.subTest("drain"), tempfile.TemporaryDirectory() as td:
            env, _ = self._env(td)
            argv = Path(td) / "prompt-argv"
            env["FAKE_PROMPT_ARGV"] = str(argv)
            self._seed(td, self.ID_1)
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            lines = argv.read_text().splitlines()
            self.assertEqual(1, len(lines))
            self.assertTrue(lines[0].startswith("agent prompt w1:p1 "), lines[0])
            self.assertTrue(lines[0].endswith("--wait --timeout 15000"), lines[0])

    def test_ta1e_capped_wait_stalls_still_surface_via_the_sweep_stalled_line(self):
        # Existing S3 law, asserted unchanged over states produced by the new
        # wait-stall path: repeated rc=0 stalls burn attempts to the cap, the
        # message goes stalled, and the sweep surfaces the loud
        # transport-stalled line (never a silent swallow).
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            env["FAKE_WAIT_STALL"] = "1"
            env["OCTO_TRANSPORT_ATTEMPT_CAP"] = "1"
            say = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, say.returncode, say.stdout + say.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            message_id = state.stem
            self.assertTrue((self._base(td) / "inbox/agent1" / message_id).is_file())
            stalled = self._drain(env)
            self.assertEqual(0, stalled.returncode, stalled.stderr)
            self.assertIn("status=stalled", stalled.stdout)
            stored = self._load(state)
            self.assertEqual("stalled", stored["status"])
            self.assertEqual(1, stored["transport_attempts"])
            module = _load_operator_sweep_module()
            report = module.transport_message_report(
                self._base(td) / "messages",
                self._base(td) / "inbox",
                self._base(td) / "locks",
            )
            stalled_lines = "\n".join(report["stalled_lines"])
            self.assertIn("TRANSPORT STALLED", stalled_lines)
            self.assertIn(message_id, stalled_lines)


class SeqConfirmationFallbackTests(unittest.TestCase):
    """TUR-505 amendment A2 (soak finding 2), NARROWED BY A3.3 (ruling-94):
    NON-INFO confirmation = (--wait matched state) OR (state_change_seq
    ADVANCED across the prompt). A send into a WORKING pane delivers
    (submit/queue) but --wait cannot match idle/done/blocked mid-turn, so the
    confirm-timeout was a false negative that burned retries despite
    delivery. The seq is read via `agent get` (structured field, no pane
    text) immediately BEFORE the prompt and again AFTER the --wait outcome;
    advanced = confirmed even on --wait timeout; unchanged + no match = fail
    closed exactly as A1; any seq read failure = fail closed. A3.3 executed
    the recorded downgrade trigger: info-kind confirmation is matched-state
    ONLY, so every seq-path case here is non-info (info coverage lives in
    the A3 structural tests). Test names carry the contract TA2 letters."""

    ID_1 = "20260722T000000-11-111"

    _env = MessageLockProtocolTests._env
    _base = MessageLockProtocolTests._base
    _load = MessageLockProtocolTests._load
    _seed = MessageLockProtocolTests._seed
    _drain = MessageLockProtocolTests._drain

    def _seq_env(self, td, *, seq="5", advances=True):
        env, log = self._env(td)
        seq_file = Path(td) / "seq"
        seq_file.write_text(seq + "\n")
        env["FAKE_SEQ_FILE"] = str(seq_file)
        env["FAKE_WAIT_STALL"] = "1"
        if advances:
            env["FAKE_SEQ_ADVANCES"] = "1"
        return env, log

    def test_ta2a_wait_timeout_with_advanced_seq_confirms_the_working_pane_send(self):
        # The live false negative: --wait cannot match a state mid-turn
        # (agent_prompt_stalled) but the submission landed and the seq
        # advanced. Pre-fix this stayed pending/unconfirmed (the captured
        # red); post-fix it is CONFIRMED with exactly one fire and no retry.
        # A3.3: seq confirmation is NON-INFO only (info = matched-state only,
        # covered by the A3 structural tests).
        with self.subTest("say-non-info-direct-promotion"), tempfile.TemporaryDirectory() as td:
            env, log = self._seq_env(td)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())
            # Exactly one fire, and a follow-up drain never re-fires.
            self.assertEqual(["prompt-stalled", "send-keys"], log.read_text().splitlines())
            redrain = self._drain(env)
            self.assertEqual(0, redrain.returncode, redrain.stderr)
            self.assertEqual(["prompt-stalled", "send-keys"], log.read_text().splitlines())
        with self.subTest("drain-confirmed-item-removed"), tempfile.TemporaryDirectory() as td:
            env, log = self._seq_env(td)
            state = self._seed(td, self.ID_1, kind="command", message="do work")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertFalse((self._base(td) / "inbox/agent1" / self.ID_1).exists())
            self.assertEqual(["prompt-stalled", "send-keys"], log.read_text().splitlines())

    def test_ta2b_true_swallow_with_unchanged_seq_stays_fail_closed_pending(self):
        # A1 law intact: rc=0 + agent_prompt_stalled + seq UNCHANGED is a true
        # swallow and fails closed to pending with its retry item.
        with self.subTest("say"), tempfile.TemporaryDirectory() as td:
            env, log = self._seq_env(td, advances=False)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("status=completed", result.stdout)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
        with self.subTest("drain"), tempfile.TemporaryDirectory() as td:
            env, log = self._seq_env(td, advances=False)
            state = self._seed(td, self.ID_1, kind="command", message="do work")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertTrue((self._base(td) / "inbox/agent1" / self.ID_1).is_file())

    def test_ta2c_seq_read_failure_on_either_side_is_unconfirmed_fail_closed(self):
        # agent get call order per invocation: 1 pane resolution, 2 pre-prompt
        # seq read, 3 post-outcome seq read. Even though the seq WOULD have
        # advanced, a failed read on either side never confirms (degrade-safe).
        for label, fail_at in (("say-pre-read", "2"), ("say-post-read", "3")):
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                env, log = self._seq_env(td)
                env["FAKE_GET_COUNT_FILE"] = str(Path(td) / "get-count")
                env["FAKE_GET_FAIL_AT"] = fail_at
                result = subprocess.run(
                    ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                    env=env, capture_output=True, text=True,
                )
                self.assertEqual(75, result.returncode, result.stdout + result.stderr)
                self.assertNotIn("status=completed", result.stdout)
                state = next(iter((self._base(td) / "messages").glob("*.toml")))
                stored = self._load(state)
                self.assertEqual("pending", stored["status"])
                self.assertEqual("deferred", stored["delivery_path"])
                self.assertEqual(1, stored["transport_attempts"])
                self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
        with self.subTest("drain-post-read"), tempfile.TemporaryDirectory() as td:
            env, log = self._seq_env(td)
            env["FAKE_GET_COUNT_FILE"] = str(Path(td) / "get-count")
            env["FAKE_GET_FAIL_AT"] = "3"
            state = self._seed(td, self.ID_1, kind="command", message="do work")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertTrue((self._base(td) / "inbox/agent1" / self.ID_1).is_file())

    def test_ta2d_seq_reads_bracket_the_prompt_pre_prompt_and_post_outcome(self):
        # Order law: the pre seq read is the agent get immediately before the
        # prompt, and the post seq read follows the --wait outcome AND the
        # A3.1 Enter follow-up (the seq must observe the Enter-caused
        # submission, and the Enter must land before any confirmation).
        expected = ["agent-get", "agent-get", "prompt", "send-keys", "agent-get"]
        with self.subTest("say"), tempfile.TemporaryDirectory() as td:
            env, _ = self._seq_env(td)
            order = Path(td) / "call-order"
            env["FAKE_CALL_ORDER"] = str(order)
            result = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(expected, order.read_text().splitlines())
        with self.subTest("drain"), tempfile.TemporaryDirectory() as td:
            env, _ = self._seq_env(td)
            order = Path(td) / "call-order"
            env["FAKE_CALL_ORDER"] = str(order)
            self._seed(td, self.ID_1)
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(expected, order.read_text().splitlines())

    def test_ta2e_repeated_true_swallows_still_cap_to_stalled_with_sweep_line(self):
        # Cap and S3 machinery unchanged for true swallows (seq never
        # advances): attempts burn to the cap, the message stalls, and the
        # sweep surfaces the loud transport-stalled line.
        with tempfile.TemporaryDirectory() as td:
            env, log = self._seq_env(td, advances=False)
            env["OCTO_TRANSPORT_ATTEMPT_CAP"] = "1"
            say = subprocess.run(
                ["bash", str(SAY), "--kind", "command", "agent1", "do work"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(75, say.returncode, say.stdout + say.stderr)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            message_id = state.stem
            stalled = self._drain(env)
            self.assertEqual(0, stalled.returncode, stalled.stderr)
            self.assertIn("status=stalled", stalled.stdout)
            stored = self._load(state)
            self.assertEqual("stalled", stored["status"])
            self.assertEqual(1, stored["transport_attempts"])
            module = _load_operator_sweep_module()
            report = module.transport_message_report(
                self._base(td) / "messages",
                self._base(td) / "inbox",
                self._base(td) / "locks",
            )
            stalled_lines = "\n".join(report["stalled_lines"])
            self.assertIn("TRANSPORT STALLED", stalled_lines)
            self.assertIn(message_id, stalled_lines)


class StructuralDeliveryModeGateTests(unittest.TestCase):
    """TUR-505 amendments A3 + A3-OVERNIGHT (rulings 94/96): structural end of
    the operator Enter burden. A3.1 agent-pane delivery is submission by
    construction: the atomic paste is followed by an explicit
    `agent send-keys <pane> Enter` (agents never hand-type, the composer can
    only hold our paste), with the modal-safe dialog check BEFORE the Enter
    (dialog present -> defer to pending, NO Enter). A3.2 operator-pane
    delivery is mode-gated by the durable flag XDG/octo-lite/operator-mode
    (awake | asleep, missing file = asleep): awake -> a send whose target ==
    owner_route (derived from operator-owner.toml at runtime, never
    hardcoded) injects NOTHING (no prompt, no send-keys; durable state +
    inbox item persist, 75-family queued-for-pull exit); asleep -> the owner
    pane is treated like an agent pane (paste + Enter wakes the operator).
    SOLE exception: the edge-triggered operator-gate ping, marked by
    OCTO_GATE_PING=1 set only at operator-sweep's _emit_operator_gate call
    site. A3.3 info confirmation is matched-state ONLY: a seq advance alone
    never completes an info message. Test names carry the A3 letters."""

    ID_1 = "20260722T000000-11-111"

    _env = MessageLockProtocolTests._env
    _base = MessageLockProtocolTests._base
    _load = MessageLockProtocolTests._load
    _seed = MessageLockProtocolTests._seed
    _drain = MessageLockProtocolTests._drain

    def _owner(self, td, route="agent1"):
        base = self._base(td)
        base.mkdir(parents=True, exist_ok=True)
        (base / "operator-owner.toml").write_text(f'owner_route = "{route}"\n')

    def _mode(self, td, mode):
        base = self._base(td)
        base.mkdir(parents=True, exist_ok=True)
        (base / "operator-mode").write_text(mode + "\n")

    def _say(self, env, kind, target, message):
        return subprocess.run(
            ["bash", str(SAY), "--kind", kind, target, message],
            env=env, capture_output=True, text=True,
        )

    def test_a3a_agent_pane_paste_then_enter_with_dialog_check_before_enter(self):
        with self.subTest("say-prompt-then-enter-argv-order"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            order = Path(td) / "call-order"
            send_argv = Path(td) / "send-keys-argv"
            prompt_argv = Path(td) / "prompt-argv"
            env["FAKE_CALL_ORDER"] = str(order)
            env["FAKE_SEND_KEYS_ARGV"] = str(send_argv)
            env["FAKE_PROMPT_ARGV"] = str(prompt_argv)
            result = self._say(env, "command", "agent1", "do work")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            # Paste first, explicit Enter follow-up second (order asserted).
            self.assertEqual(
                ["agent-get", "agent-get", "prompt", "send-keys"],
                order.read_text().splitlines(),
            )
            self.assertEqual(
                ["agent send-keys w1:p1 Enter"], send_argv.read_text().splitlines(),
            )
            self.assertTrue(prompt_argv.read_text().splitlines()[0].startswith("agent prompt w1:p1 "))
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
        with self.subTest("drain-prompt-then-enter-argv-order"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            order = Path(td) / "call-order"
            send_argv = Path(td) / "send-keys-argv"
            env["FAKE_CALL_ORDER"] = str(order)
            env["FAKE_SEND_KEYS_ARGV"] = str(send_argv)
            self._seed(td, self.ID_1)
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                ["agent-get", "agent-get", "prompt", "send-keys"],
                order.read_text().splitlines(),
            )
            self.assertEqual(
                ["agent send-keys w1:p1 Enter"], send_argv.read_text().splitlines(),
            )
        with self.subTest("dialog-open-before-enter-defers-no-enter"), tempfile.TemporaryDirectory() as td:
            # A dialog opens BETWEEN the paste and the Enter follow-up: the
            # pre-Enter dialog check defers to pending and NO Enter fires
            # (modal-safe law preserved, never force-submit a trust dialog).
            env, log = self._env(td)
            env["FAKE_WAIT_STALL"] = "1"
            env["FAKE_PANE_READ_COUNT"] = str(Path(td) / "pane-reads")
            env["FAKE_PANE_TEXT_AFTER"] = "Quick safety check: trust this folder"
            result = self._say(env, "command", "agent1", "do work")
            self.assertEqual(75, result.returncode, result.stdout + result.stderr)
            self.assertEqual(["prompt-stalled"], log.read_text().splitlines())
            self.assertNotIn("send-keys", log.read_text())
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())

    def test_a3b_awake_owner_route_send_is_queue_only_and_gate_ping_injects(self):
        with self.subTest("awake-owner-route-queue-only"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._owner(td, "agent1")
            self._mode(td, "awake")
            order = Path(td) / "call-order"
            env["FAKE_CALL_ORDER"] = str(order)
            result = self._say(env, "command", "agent1", "for the operator")
            # Queued-for-pull (75-family), honest pending until operator ack.
            self.assertEqual(75, result.returncode, result.stdout + result.stderr)
            self.assertIn("queued for operator pull", result.stderr)
            # ZERO pane injection: no prompt, no send-keys, no herdr call at all.
            self.assertFalse(log.exists())
            self.assertFalse(order.exists())
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
        with self.subTest("gate-ping-exception-still-injects"), tempfile.TemporaryDirectory() as td:
            # SOLE exception (ruling-94): the edge-triggered operator-gate ping
            # (OCTO_GATE_PING=1, set only by operator-sweep's
            # _emit_operator_gate) injects even while the operator is awake.
            env, log = self._env(td)
            self._owner(td, "agent1")
            self._mode(td, "awake")
            env["OCTO_GATE_PING"] = "1"
            result = self._say(env, "info", "agent1", "Operator gate")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            self.assertEqual("completed", self._load(state)["status"])

    def test_a3c_info_completes_on_matched_state_only(self):
        with self.subTest("say-seq-advance-alone-leaves-info-pending"), tempfile.TemporaryDirectory() as td:
            # Even a GENUINE submission signal (Enter fired and the seq
            # advanced) never completes info without a matched state: the
            # recorded A2-residual downgrade trigger, executed.
            env, log = self._env(td)
            seq_file = Path(td) / "seq"
            seq_file.write_text("5\n")
            env["FAKE_SEQ_FILE"] = str(seq_file)
            env["FAKE_WAIT_STALL"] = "1"
            env["FAKE_SEQ_ADVANCES"] = "1"
            env["FAKE_ENTER_SUBMITS"] = "1"
            result = self._say(env, "info", "agent1", "fyi update")
            self.assertEqual(75, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("status=completed", result.stdout)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertTrue((self._base(td) / "inbox/agent1" / state.stem).is_file())
        with self.subTest("drain-seq-advance-alone-leaves-info-pending"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            seq_file = Path(td) / "seq"
            seq_file.write_text("5\n")
            env["FAKE_SEQ_FILE"] = str(seq_file)
            env["FAKE_WAIT_STALL"] = "1"
            env["FAKE_SEQ_ADVANCES"] = "1"
            env["FAKE_ENTER_SUBMITS"] = "1"
            state = self._seed(td, self.ID_1, kind="info", message="fyi update")
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("status=completed", result.stdout)
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("deferred", stored["delivery_path"])
            self.assertTrue((self._base(td) / "inbox/agent1" / self.ID_1).is_file())
        with self.subTest("say-matched-state-completes"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            result = self._say(env, "info", "agent1", "fyi update")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("status=completed", result.stdout)
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("completed", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())

    def test_a3d_owner_file_change_redirects_the_queue_only_target(self):
        # Runtime derivation, never a hardcoded name: rewriting
        # operator-owner.toml redirects which target is queue-only.
        with tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._mode(td, "awake")
            self._owner(td, "agent1")
            first = self._say(env, "command", "agent1", "queued while owned")
            self.assertEqual(75, first.returncode, first.stdout + first.stderr)
            self.assertFalse(log.exists())
            # Ownership moves to agent2: agent1 is now an ordinary agent pane.
            self._owner(td, "agent2")
            second = self._say(env, "command", "agent1", "injected after handoff")
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            third = self._say(env, "command", "agent2", "queued for the new owner")
            self.assertEqual(75, third.returncode, third.stdout + third.stderr)
            self.assertIn("queued for operator pull", third.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())

    def test_a3e_busy_pane_paste_plus_enter_submits_and_settles_honestly(self):
        # The 95% case (soak-watch trigger FIRED): a busy pane where --wait
        # cannot match a state mid-turn and the paste alone does NOT submit.
        # Pre-fix (the captured red): no Enter ever fired, the seq stayed
        # unchanged, the message stayed pending, and the operator had to
        # press Enter by hand. Post-fix the explicit Enter submits (the fake
        # advances the seq exactly like the live pane) and the state settles
        # honestly as a confirmed submission.
        with self.subTest("say"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            seq_file = Path(td) / "seq"
            seq_file.write_text("5\n")
            env["FAKE_SEQ_FILE"] = str(seq_file)
            env["FAKE_WAIT_STALL"] = "1"
            env["FAKE_ENTER_SUBMITS"] = "1"
            result = self._say(env, "command", "agent1", "do work")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(["prompt-stalled", "send-keys"], log.read_text().splitlines())
            state = next(iter((self._base(td) / "messages").glob("*.toml")))
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertFalse((self._base(td) / "inbox/agent1" / state.stem).exists())
        with self.subTest("drain"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            seq_file = Path(td) / "seq"
            seq_file.write_text("5\n")
            env["FAKE_SEQ_FILE"] = str(seq_file)
            env["FAKE_WAIT_STALL"] = "1"
            env["FAKE_ENTER_SUBMITS"] = "1"
            state = self._seed(td, self.ID_1)
            result = self._drain(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["prompt-stalled", "send-keys"], log.read_text().splitlines())
            stored = self._load(state)
            self.assertEqual("pending", stored["status"])
            self.assertEqual("direct", stored["delivery_path"])
            self.assertEqual(1, stored["transport_attempts"])
            self.assertFalse((self._base(td) / "inbox/agent1" / self.ID_1).exists())

    def test_a3f_mode_gate_both_directions_missing_default_and_flag_flip(self):
        with self.subTest("missing-flag-defaults-asleep-injects"), tempfile.TemporaryDirectory() as td:
            # Ruled default until the morning signal: missing file = ASLEEP,
            # so the owner pane gets paste + Enter (messages wake the operator).
            env, log = self._env(td)
            self._owner(td, "agent1")
            result = self._say(env, "command", "agent1", "wake up")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
        with self.subTest("explicit-asleep-injects"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._owner(td, "agent1")
            self._mode(td, "asleep")
            result = self._say(env, "command", "agent1", "wake up")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
        with self.subTest("flag-flip-honored-on-next-send"), tempfile.TemporaryDirectory() as td:
            env, log = self._env(td)
            self._owner(td, "agent1")
            self._mode(td, "awake")
            queued = self._say(env, "command", "agent1", "first: queue only")
            self.assertEqual(75, queued.returncode, queued.stdout + queued.stderr)
            self.assertFalse(log.exists())
            self._mode(td, "asleep")
            injected = self._say(env, "command", "agent1", "second: inject")
            self.assertEqual(0, injected.returncode, injected.stdout + injected.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())
            self._mode(td, "awake")
            requeued = self._say(env, "command", "agent1", "third: queue again")
            self.assertEqual(75, requeued.returncode, requeued.stdout + requeued.stderr)
            self.assertEqual(["prompt", "send-keys"], log.read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
