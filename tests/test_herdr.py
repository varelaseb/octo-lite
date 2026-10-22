"""Tests for the two Herdr wrappers octo-lite still ships.

Both are thin shims over native Herdr commands, so there is nothing to test in
the happy path that Herdr does not already own. What is tested here is only the
handful of failure modes that are real, silent, and were each observed against a
live Herdr 0.9.0:

  * a freshly created pane is not yet at a shell prompt (`agent_pane_busy`)
  * an agent that opens its trusted-folder dialog reports `agent_not_ready` from
    `agent start`, which is a started agent awaiting a keystroke, not a failure
  * the dialog's highlighted row may be "No, exit", so confirming blindly kills
    the agent being spawned
  * a failed spawn must not leave an orphan tab behind
  * `herdr-say` must map a blocked target to exit 75, which is the contract
    `herdr-wake`, Spec Chat's wake provider, relies on
  * a Codex contract sent as a prompt is worked as a task, and a Codex thread
    on the shared daemon outlives its tab
  * a detached child outlives its closed tab unless `herdr-close` reaps it
  * `herdr agent wait` on an agent outlives the agent's closed tab unless
    `herdr-close` ends it
  * a parked agent must hold no process, refuse when working or Codex, and
    resume once under its name when messaged
  * a pane's Claude session record may be one an ended Claude left at a pid
    since reused, or belong to a spare Claude claimed into the pane
  * Herdr ids repeat across sessions, so state, parking, waking, and closing
    must stay in the caller's Herdr session
  * a Claude agent's turn may die at once on an API rate limit, so Herdr sees
    it work though it never processed the message
  * a message queued behind a running turn may never be taken in, and Claude
    records a slash command transformed, never as typed
  * a wake send outliving Spec Chat's bound fails after Spec Chat counted it
    sent, so only the operator can be told
  * a background command's end invokes only a Claude caller, so a wait on an
    agent must wake its caller by message, and end with the caller's tab
"""

import json
import os
import re
import signal
import subprocess
import tempfile
import time
import tomllib
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPAWN = ROOT / "skills/herdr-comms/assets/herdr-spawn"
SAY = ROOT / "skills/herdr-comms/assets/herdr-say"
WAKE = ROOT / "skills/herdr-comms/assets/herdr-wake"
CLOSE = ROOT / "skills/herdr-comms/assets/herdr-close"
AWAIT = ROOT / "skills/herdr-comms/assets/herdr-await"
SESSION = ROOT / "skills/herdr-comms/assets/herdr-claude-session"
STATE = ROOT / "scripts/octo-lite-state"

# A stand-in for the `herdr` binary. Behaviour is driven entirely by environment
# variables so each test can pose one exact failure without a live server.
FAKE_HERDR = r"""#!/usr/bin/env bash
set -eu
echo "$*" >>"$FAKE_LOG"
[[ -z "${FAKE_ENV_LOG:-}" ]] || echo "session=${HERDR_SESSION:-} socket=${HERDR_SOCKET_PATH:-}" >>"$FAKE_ENV_LOG"
sub="$1 ${2:-}"

dialog_state() { [[ -f "$FAKE_DIALOG" ]] && cat "$FAKE_DIALOG" || echo none; }
# FAKE_GONE lists targets Herdr finds no agent for; a started name leaves it.
gone() { [[ -f "${FAKE_GONE:-}" ]] && grep -qxF "$1" "$FAKE_GONE"; }
not_found() { echo '{"error":{"code":"agent_not_found","message":"not found"}}' >&2; exit 1; }

case "$sub" in
  "workspace create")
    echo '{"result":{"workspace":{"workspace_id":"w2"},"tab":{"tab_id":"w2:t1"},"root_pane":{"pane_id":"w2:p1"}}}' ;;
  "tab create")
    echo '{"result":{"tab":{"tab_id":"w1:t1"},"root_pane":{"pane_id":"w1:p1"}}}' ;;
  "workspace get")
    echo "${FAKE_WORKSPACE_GET:-{\}}" ;;
  "agent list")
    echo "${FAKE_AGENT_LIST:-{\}}" ;;
  "tab close"|"workspace close")
    echo "CLOSED" >>"$FAKE_CLOSED"; echo '{"result":{}}' ;;
  "agent start")
    n=0
    [[ -f "$FAKE_START_COUNT" ]] && n="$(cat "$FAKE_START_COUNT")"
    n=$((n + 1)); echo "$n" >"$FAKE_START_COUNT"
    printf '%s\0' "$@" >"$FAKE_START_ARGV"
    if [[ -n "${FAKE_START_FAIL_OTHER:-}" ]]; then
      echo '{"error":{"code":"agent_pane_not_found","message":"no pane"},"id":"cli:agent:start"}' >&2; exit 1
    fi
    if [[ -n "${FAKE_START_BUSY_COUNT:-}" && "$n" -le "$FAKE_START_BUSY_COUNT" ]]; then
      echo '{"error":{"code":"agent_pane_busy","message":"not an available shell"},"id":"cli:agent:start"}' >&2; exit 1
    fi
    if [[ -n "${FAKE_START_NOT_READY:-}" ]]; then
      echo '{"error":{"code":"agent_not_ready","message":"blocked during startup"},"id":"cli:agent:start"}' >&2; exit 1
    fi
    # FAKE_START_GATE holds the start until the test creates that file.
    while [[ -n "${FAKE_START_GATE:-}" && ! -e "$FAKE_START_GATE" ]]; do sleep 0.05; done
    if [[ -f "${FAKE_GONE:-}" ]]; then sed -i "/^$3\$/d" "$FAKE_GONE"; fi
    echo '{"result":{}}' ;;
  "pane read")
    case "$(dialog_state)" in
      no)  printf ' Quick safety check: Is this a project you created or one you trust?\n ❯ No, exit\n   Yes, I trust this folder\n' ;;
      yes) printf ' Quick safety check: Is this a project you created or one you trust?\n   No, exit\n ❯ Yes, I trust this folder\n' ;;
      stuck) printf ' Quick safety check: Is this a project you created or one you trust?\n   No, exit\n ❯ Yes, I trust this folder\n' ;;
      codexno)  printf ' Do you trust the contents of this directory?\n   1. Yes, continue\n \xe2\x80\xba 2. No, quit\n' ;;
      codexyes) printf ' Do you trust the contents of this directory?\n \xe2\x80\xba 1. Yes, continue\n   2. No, quit\n' ;;
      codexquit)  printf ' Do you trust the contents of this directory?\n   1. Trust and continue\n \xe2\x80\xba 2. Quit\n' ;;
      codextrust) printf ' Do you trust the contents of this directory?\n \xe2\x80\xba 1. Trust and continue\n   2. Quit\n' ;;
      theme)    printf ' Choose the text style\n   1. Auto\n \xe2\x9d\xaf 2. Dark mode\n   3. Light mode\n' ;;
      *)   printf 'root@box:/tmp# \n' ;;
    esac ;;
  "pane send-keys")
    key="${4:-}"
    case "$(dialog_state)" in
      codexno)
        # confirming here picks "No, quit" and kills the agent
        [[ "$key" == Enter ]] && echo "CONFIRMED_NO_EXIT" >>"$FAKE_WRONG"
        [[ "$key" == Up ]] && echo codexyes >"$FAKE_DIALOG"
        [[ "$key" == Down ]] && echo codexyes >"$FAKE_DIALOG" ;;
      codexquit)
        # confirming here picks "Quit" and kills the agent
        [[ "$key" == Enter ]] && echo "CONFIRMED_NO_EXIT" >>"$FAKE_WRONG"
        [[ "$key" == Up || "$key" == Down ]] && echo codextrust >"$FAKE_DIALOG" ;;
      codextrust)
        [[ "$key" == Enter ]] && echo none >"$FAKE_DIALOG" ;;
      codexyes)
        [[ "$key" == Enter ]] && echo none >"$FAKE_DIALOG" ;;
      theme)
        [[ "$key" == Enter ]] && echo none >"$FAKE_DIALOG" ;;
      no)
        # Confirming here is the bug this suite exists to catch: it selects
        # "No, exit" and kills the agent that was just spawned.
        [[ "$key" == Enter ]] && echo "CONFIRMED_NO_EXIT" >>"$FAKE_WRONG"
        [[ "$key" == Down ]] && echo yes >"$FAKE_DIALOG" ;;
      yes)
        [[ "$key" == Enter ]] && echo none >"$FAKE_DIALOG" ;;
    esac
    echo '{"result":{}}' ;;
  "agent send-keys")
    # A blocked agent refuses agent-level input; the dialog must be answered at
    # the pane. Failing here keeps the wrappers honest about which one they use.
    echo '{"error":{"code":"agent_blocked","message":"requires interactive input"},"id":"cli:agent:send-keys"}' >&2; exit 1 ;;
  "agent get")
    # FAKE_NEVER_READY poses an agent that starts but never reports a session,
    # which is the window in which a prompt is silently lost.
    if gone "$3"; then
      not_found
    elif [[ -n "${FAKE_AGENT_GET_ERROR:-}" ]]; then
      echo "$FAKE_AGENT_GET_ERROR" >&2; exit 1
    elif [[ -n "${FAKE_AGENT_GET_HANG:-}" ]]; then
      exec sleep 30
    elif [[ -n "${FAKE_AGENT_GET:-}" ]]; then
      # FAKE_AGENT_GET_WARN: a successful get that also warns on stderr.
      [[ -z "${FAKE_AGENT_GET_WARN:-}" ]] || echo "$FAKE_AGENT_GET_WARN" >&2
      # Working while a running turn's time (a blank line) is still to land.
      if [[ -n "${FAKE_TRANSCRIPT:-}" && -s "$FAKE_TRANSCRIPT.later" && -z "$(head -1 "$FAKE_TRANSCRIPT.later")" ]]; then
        jq -c '.result.agent.agent_status = "working"' <<<"$FAKE_AGENT_GET"
      else
        echo "$FAKE_AGENT_GET"
      fi
    elif [[ -n "${FAKE_NEVER_READY:-}" ]]; then
      echo '{"result":{"agent":{}}}'
    elif [[ -n "${FAKE_NO_SESSION:-}" ]]; then
      echo '{"result":{"agent":{"agent_status":"idle"}}}'
    else
      echo '{"result":{"agent":{"agent_session":{"value":"sess-123"},"agent_status":"idle"}}}'
    fi ;;
  "agent prompt")
    gone "$3" && not_found
    if [[ -n "${FAKE_PROMPT_BLOCKED:-}" ]]; then
      echo '{"error":{"code":"agent_blocked","message":"requires interactive input"},"id":"cli:agent:prompt"}' >&2; exit 1
    fi
    if [[ -n "${FAKE_PROMPT_STALLED:-}" ]]; then
      echo '{"error":{"code":"agent_prompt_stalled","message":"no reaction"},"id":"cli:agent:prompt"}' >&2; exit 1
    fi
    if [[ -n "${FAKE_PROMPT_NOT_FOUND:-}" ]]; then
      echo '{"error":{"code":"agent_not_found","message":"not found"},"id":"cli:agent:prompt"}' >&2; exit 1
    fi
    # FAKE_REPLIES: one line per prompt, the Claude agent's reply that its
    # transcript FAKE_TRANSCRIPT records after the record carrying the message,
    # as Claude does: rate_limit, ok, or none. Two words pose a target already
    # working: the message is enqueued, the running turn's reply (the first)
    # lands at once, and the message is taken in later, its reply the second:
    # mid-turn after an ok, at the turn's end after a rate_limit; a second
    # exit: the turn ends, or Claude exits, before taking it in.
    # FAKE_TRANSCRIPT.later holds what lands later, one line per wait (sleep),
    # a blank line the running turn's time.
    # A slash command's user record is Claude's: its name and args in tags.
    if [[ -n "${FAKE_REPLIES:-}" ]]; then
      read -r first second <"$FAKE_REPLIES" || true; sed -i 1d "$FAKE_REPLIES"
      mkdir -p "$(dirname "$FAKE_TRANSCRIPT")"
      at() { date -u +%FT%T.%3NZ; }
      record() { jq -nc --arg m "$text" --arg s "$said" --arg at "$(at)" "{isSidechain: false, timestamp: \$at} + $1"; }
      reply() { case "$1" in
          rate_limit) record '{type: "assistant", isApiErrorMessage: true, error: "rate_limit", apiErrorStatus: 429, message: {content: [{type: "text", text: "API Error: Request rejected (429) · All credentials are cooling down"}]}}' ;;
          ok) record '{type: "assistant", message: {content: [{type: "text", text: "on it"}]}}' ;;
        esac; }
      text="$4" said="$4"
      if [[ "$text" == /* ]]; then
        cmd="${text%% *}" args="${text#"${text%% *}"}"
        said="<command-name>$cmd</command-name>
            <command-message>${cmd#/}</command-message>
            <command-args>${args# }</command-args>"
      fi
      if [[ -z "$second" ]]; then
        { record '{type: "user", message: {role: "user", content: $s}}'; reply "$first"; } >>"$FAKE_TRANSCRIPT"
      else
        submitted="$(at)"
        { record '{type: "queue-operation", operation: "enqueue", content: $m}'; reply "$first"; } >>"$FAKE_TRANSCRIPT"
        { printf '\n%.0s' {1..12}
          if [[ "$second" == exit ]]; then
            :
          elif [[ "$first" == ok ]]; then
            record '{type: "queue-operation", operation: "remove", reason: "absorbed_mid_turn", content: $m}'
            record '{type: "user", message: {role: "user", content: [{type: "tool_result", content: "done"}]}}'
            record "{type: \"attachment\", attachment: {type: \"queued_command\", prompt: \$m}, timestamp: \"$submitted\"}"
          else
            record '{type: "queue-operation", operation: "dequeue"}'
            record '{type: "user", message: {role: "user", content: $s}}'
          fi
          reply "$second"; } >>"$FAKE_TRANSCRIPT.later"
      fi
    fi
    echo '{"result":{"agent":{"agent_status":"working"}}}' ;;
  "agent wait")
    # Herdr's wait without --until: it ends on idle, done, or blocked, its
    # state FAKE_WAIT_STATUS; FAKE_WAIT_EXITED poses the agent exiting first.
    # FAKE_WAIT_GATE holds the wait until the test creates that file.
    # The agent stops at state_change_seq 42, or 44 once FAKE_WORKED exists:
    # it worked (43) and stopped again. A wait --until working ends once it
    # works, and on one that worked and stopped already, only on its next work.
    gone "$3" && not_found
    while [[ -n "${FAKE_WAIT_GATE:-}" && ! -e "$FAKE_WAIT_GATE" ]]; do sleep 0.05; done
    [[ -z "${FAKE_WAIT_EXITED:-}" ]] ||
      { echo '{"error":{"code":"agent_not_running","message":"agent exited"}}' >&2; exit 1; }
    s="${FAKE_WAIT_STATUS:-idle}" seq=42
    [[ -e "$FAKE_WORKED" ]] && seq=44
    if [[ "${5:-}" == working ]]; then
      [[ -e "$FAKE_WORKED" ]] && exec sleep 30
      while [[ ! -e "$FAKE_WORKED" ]]; do sleep 0.05; done
      s=working seq=43
    fi
    jq -nc --arg n "$3" --arg s "$s" --argjson seq "$seq" \
      '{result: {agent: {name: $n, agent_status: $s, state_change_seq: $seq}}, type: "agent_info"}' ;;
  *)
    echo "{}" ;;
esac
"""


class HerdrWrapperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        bindir = d / "bin"
        bindir.mkdir()
        fake = bindir / "herdr"
        fake.write_text(FAKE_HERDR)
        fake.chmod(0o755)
        # A real codex must never run here. The stub records any call, so a
        # spawn that invokes codex itself (e.g. to start its daemon) is visible.
        self.codex_calls = d / "codex.log"
        stub = bindir / "codex"
        stub.write_text(f'#!/usr/bin/env bash\necho "$*" >>"{self.codex_calls}"\n')
        stub.chmod(0o755)
        self.cwd = d / "worktree"
        self.cwd.mkdir()
        self.log = d / "calls.log"
        self.closed = d / "closed.log"
        self.wrong = d / "wrong.log"
        self.dialog = d / "dialog"
        self.env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_LOG": str(self.log),
            "FAKE_CLOSED": str(self.closed),
            "FAKE_WRONG": str(self.wrong),
            "FAKE_DIALOG": str(self.dialog),
            "FAKE_START_COUNT": str(d / "count"),
            "FAKE_START_ARGV": str(d / "start.argv"),
            "HOME": str(d),
            "XDG_STATE_HOME": str(d / "state"),
            "FAKE_GONE": str(d / "gone"),
            "FAKE_WORKED": str(d / "worked"),
        }
        self.gone_file = d / "gone"
        self.env.pop("OCTO_LITE_OPERATING_MODEL", None)
        # The suite runs in the default Herdr session, from no pane, unless a
        # test names one: a Herdr pane's caller env must not reach a wrapper.
        for var in ("HERDR_SESSION", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID"):
            self.env.pop(var, None)

    def spawn(self, extra=(), **env):
        return subprocess.run(
            [str(SPAWN), "--workspace", "w1", "--name", "a1", "--label", "L",
             "--cwd", str(self.cwd), "--role", "r", *extra, "--", "claude"],
            capture_output=True, text=True, env={**self.env, **env},
        )

    def spawn_codex(self, extra=(), **env):
        return self.spawn_as("codex", extra, **env)

    def spawn_as(self, runtime, extra=(), **env):
        return subprocess.run(
            [str(SPAWN), "--workspace", "w1", "--name", "a1", "--label", "L",
             "--cwd", str(self.cwd), "--role", "r", *extra, "--", runtime],
            capture_output=True, text=True, env={**self.env, **env},
        )

    def say(self, *args, **env):
        return subprocess.run(
            [str(SAY), *args], capture_output=True, text=True, env={**self.env, **env}
        )

    # --- spawn -----------------------------------------------------------

    def test_retries_while_the_new_pane_is_still_busy(self):
        self.dialog.write_text("none\n")
        r = self.spawn(FAKE_START_BUSY_COUNT="2", HERDR_SPAWN_START_RETRIES="8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log.read_text().count("agent start"), 3)
        self.assertFalse(self.closed.exists(), "a recoverable retry must not close the tab")

    def test_a_non_busy_start_failure_closes_the_tab(self):
        r = self.spawn(FAKE_START_FAIL_OTHER="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(self.closed.exists(), "a failed spawn must not orphan its tab")

    def test_agent_not_ready_is_a_started_agent_awaiting_the_trust_keystroke(self):
        # Regression: treating agent_not_ready as fatal tore down a tab whose
        # agent had in fact started and was sitting on its trust dialog.
        self.dialog.write_text("yes\n")
        r = self.spawn(FAKE_START_NOT_READY="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.closed.exists())
        self.assertIn("name=a1", r.stdout)

    def test_never_confirms_while_no_exit_is_highlighted(self):
        # Regression: a bare Enter confirms whatever row is highlighted. When
        # that row is "No, exit" it exits the agent being spawned.
        self.dialog.write_text("no\n")
        r = self.spawn()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(
            self.wrong.exists(),
            "confirmed the dialog while 'No, exit' was highlighted",
        )
        self.assertEqual(self.dialog.read_text().strip(), "none")

    def test_answers_the_codex_trust_dialog(self):
        # Codex marks the row with a different glyph and its affirmative reads
        # "1. Yes, continue", so a Claude-shaped matcher never confirms it.
        self.dialog.write_text("codexno\n")
        r = self.spawn_codex()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.wrong.exists(), "confirmed while 'No, quit' was selected")
        self.assertEqual(self.dialog.read_text().strip(), "none")

    def test_answers_the_trust_and_continue_codex_dialog(self):
        # Codex reworded its affirmative to "1. Trust and continue" beside
        # "2. Quit"; the old matcher never confirmed it and spawn failed closed.
        self.dialog.write_text("codexquit\n")
        r = self.spawn_codex()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.wrong.exists(), "confirmed while 'Quit' was selected")
        self.assertEqual(self.dialog.read_text().strip(), "none")

    def test_confirms_the_appearance_wizard(self):
        # Every option is a preference, so this one may be confirmed as it
        # stands; otherwise a first run blocks the spawn forever.
        self.dialog.write_text("theme\n")
        r = self.spawn()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dialog.read_text().strip(), "none")

    def test_an_unrecognised_dialog_reports_what_it_saw(self):
        self.dialog.write_text("stuck\n")
        r = self.spawn(HERDR_SPAWN_TRUST_RETRIES="2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Pane showed", r.stderr)

    def test_fails_closed_and_cleans_up_when_the_dialog_never_clears(self):
        self.dialog.write_text("stuck\n")
        r = self.spawn(HERDR_SPAWN_TRUST_RETRIES="2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("failing closed", r.stderr)
        self.assertTrue(self.closed.exists())

    def test_fails_when_the_agent_never_becomes_ready_for_prompts(self):
        # Regression: the trust dialog clearing is not readiness. Returning
        # success here let callers fire a prompt into a still-booting agent,
        # which Herdr rejects as agent_prompt_stalled and the message is lost.
        self.dialog.write_text("none\n")
        r = self.spawn(FAKE_NEVER_READY="1", HERDR_SPAWN_READY_RETRIES="2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not ready for prompts", r.stderr)
        self.assertTrue(self.closed.exists())

    def start_argv(self):
        return (Path(self.env["FAKE_START_ARGV"]).read_text().split("\0"))[:-1]

    def test_codex_contract_is_developer_instructions_not_a_prompt(self):
        # Regression: a contract sent as the first prompt was worked as a task.
        self.dialog.write_text("none\n")
        agents = Path(self.env["HOME"]) / ".claude/agents"
        agents.mkdir(parents=True, exist_ok=True)
        contract = '# Role\nWrite only in your "worktree".\\ Tab\there.\n'
        (agents / "r.md").write_text(contract)
        r = self.spawn_codex()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("contract=developer-instructions", r.stdout)
        self.assertNotIn("agent prompt", self.log.read_text())
        argv = self.start_argv()
        value = [a for a in argv if a.startswith("developer_instructions=")]
        self.assertEqual(len(value), 1, argv)
        self.assertEqual(argv[argv.index(value[0]) - 1], "-c")
        self.assertEqual(tomllib.loads(value[0])["developer_instructions"], contract)

    def test_codex_takes_the_operating_model_ahead_of_its_contract(self):
        self.dialog.write_text("none\n")
        agents = Path(self.env["HOME"]) / ".claude/agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "r.md").write_text("# Role\n")
        model = self.cwd / "AGENTS.md"
        model.write_text("# Model\n")
        r = self.spawn_codex(extra=["--operating-model", str(model)])
        self.assertEqual(r.returncode, 0, r.stderr)
        value = [a for a in self.start_argv() if a.startswith("developer_instructions=")]
        self.assertEqual(len(value), 1, value)
        self.assertEqual(tomllib.loads(value[0])["developer_instructions"],
                         "# Model\n\n# Role\n")

    def test_claude_appends_the_operating_model_to_its_system_prompt(self):
        self.dialog.write_text("none\n")
        model = self.cwd / "AGENTS.md"
        model.write_text("# Model\n")
        r = self.spawn(extra=["--operating-model", str(model)])
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.start_argv()
        i = argv.index("--append-system-prompt-file")
        self.assertEqual(argv[i + 1], str(model.resolve()))

    def test_the_operating_model_is_inherited_by_every_child(self):
        # The tab gets the model path in its env, and a spawn from inside that
        # tab defaults to it, so no caller has to remember the flag.
        self.dialog.write_text("none\n")
        model = self.cwd / "AGENTS.md"
        model.write_text("# Model\n")
        r = self.spawn(extra=["--operating-model", str(model)])
        self.assertEqual(r.returncode, 0, r.stderr)
        exported = f"--env OCTO_LITE_OPERATING_MODEL={model.resolve()}"
        self.assertIn(exported, self.log.read_text())
        self.log.unlink()
        r = self.spawn(OCTO_LITE_OPERATING_MODEL=str(model.resolve()))
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.start_argv()
        self.assertEqual(argv[argv.index("--append-system-prompt-file") + 1],
                         str(model.resolve()))
        self.assertIn(exported, self.log.read_text())

    def test_pi_appends_the_operating_model_then_its_contract(self):
        # pi has no --agent: both files go in as appended system prompt, model first.
        self.dialog.write_text("none\n")
        agents = Path(self.env["HOME"]) / ".claude/agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "r.md").write_text("# Role\n")
        model = self.cwd / "AGENTS.md"
        model.write_text("# Model\n")
        r = self.spawn_as("pi", extra=["--operating-model", str(model)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("contract=appended-system-prompt", r.stdout)
        argv = self.start_argv()
        self.assertEqual(argv[argv.index("--kind") + 1], "pi")
        self.assertEqual(argv[argv.index("--") + 1:],
                         ["--append-system-prompt", str(model.resolve()),
                          "--append-system-prompt", str(agents / "r.md")])

    def test_pi_without_a_contract_says_so(self):
        self.dialog.write_text("none\n")
        r = self.spawn_as("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("contract=not-found", r.stdout)
        self.assertNotIn("--append-system-prompt", self.start_argv())

    def test_claude_gets_its_role_from_role(self):
        self.dialog.write_text("none\n")
        r = self.spawn()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.start_argv()[-2:], ["--agent", "r"])

    def test_a_resumed_claude_keeps_its_role_and_session(self):
        self.dialog.write_text("none\n")
        r = self.spawn(extra=["--resume", "s-1"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.start_argv()[-4:], ["--agent", "r", "--resume", "s-1"])

    def test_resume_is_claude_only_and_refused_before_any_tab(self):
        for runtime in ("codex", "pi"):
            r = self.spawn_as(runtime, extra=["--resume", "s-1"])
            self.assertEqual(r.returncode, 64, r.stderr)
            self.assertFalse(self.log.exists(), "no tab may be created")

    def test_an_inline_prompt_is_rejected_before_any_tab(self):
        # herdr agent start times out waiting for readiness with an inline prompt.
        for runtime in ("claude", "codex", "pi"):
            r = subprocess.run(
                [str(SPAWN), "--workspace", "w1", "--name", "a1", "--label", "L",
                 "--cwd", str(self.cwd), "--role", "r", "--", runtime, "do the ticket"],
                capture_output=True, text=True, env=self.env,
            )
            self.assertEqual(r.returncode, 64, r.stderr)
            self.assertIn("herdr-say", r.stderr)
            self.assertFalse(self.log.exists(), "no tab may be created")

    def test_no_operating_model_changes_nothing(self):
        self.dialog.write_text("none\n")
        r = self.spawn()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--append-system-prompt-file", self.start_argv())
        self.assertNotIn("OCTO_LITE_OPERATING_MODEL", self.log.read_text())

    def test_the_callers_home_is_forwarded_to_the_tab(self):
        # A tab starts with the Herdr server's env; the caller's HOME goes with
        # it, on both runtimes.
        self.dialog.write_text("none\n")
        for runtime in ("claude", "codex", "pi"):
            r = self.spawn_as(runtime)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"--env HOME={self.env['HOME']}", self.log.read_text())
            self.log.unlink()

    def test_the_home_is_inherited_by_every_child(self):
        # A spawn from inside that tab runs with the forwarded HOME and so
        # forwards the same one again.
        self.dialog.write_text("none\n")
        home = self.cwd / "lane-home"
        home.mkdir()
        r = self.spawn(HOME=str(home))
        self.assertEqual(r.returncode, 0, r.stderr)
        exported = f"--env HOME={home}"
        log = self.log.read_text()
        self.assertIn(exported, log)
        self.log.unlink()
        forwarded = log.split("--env HOME=", 1)[1].split(" --", 1)[0]
        r = self.spawn(HOME=forwarded)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(exported, self.log.read_text())

    def test_a_missing_operating_model_stops_before_any_tab(self):
        r = self.spawn(extra=["--operating-model", str(self.cwd / "nope.md")])
        self.assertEqual(r.returncode, 66)
        self.assertFalse(self.log.exists())

    def test_codex_spawn_never_starts_a_daemon(self):
        # Regression: a thread on the shared app-server outlived its tab.
        self.dialog.write_text("none\n")
        r = self.spawn_codex()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.codex_calls.exists(), self.codex_calls.read_text()
                         if self.codex_calls.exists() else "")
        self.assertIn("--no-daemon", self.start_argv())
        self.assertIn("contract=not-found", r.stdout)

    def test_a_claude_agent_loads_its_own_contract(self):
        self.dialog.write_text("none\n")
        r = self.spawn()
        self.assertIn("contract=loaded-by-agent-flag", r.stdout)

    def test_reports_the_resolved_provider_session(self):
        self.dialog.write_text("none\n")
        r = self.spawn()
        self.assertIn("provider_session_id=sess-123", r.stdout)

    def test_a_host_that_resolves_no_session_still_spawns(self):
        # Herdr resolves a provider session on some hosts and not others. A
        # missing session is not a broken agent, so long as it reports status.
        self.dialog.write_text("none\n")
        r = self.spawn(FAKE_NO_SESSION="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("provider_session_id=herdr:a1", r.stdout)

    # --- close -----------------------------------------------------------

    def tagged(self, tab, space="w-none", **env):
        # setsid, like a detached command child that survives its tab
        p = subprocess.Popen(["sleep", "600"], start_new_session=True,
                             env={**self.env, "HERDR_TAB_ID": tab, "HERDR_WORKSPACE_ID": space, **env})
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def gone(self, p):
        for _ in range(50):
            if p.poll() is not None:
                return True
            time.sleep(0.1)
        return False

    def test_close_ends_every_process_tagged_with_the_tab(self):
        tab = f"w1:t-{uuid.uuid4()}"
        mine, other = self.tagged(tab), self.tagged(f"w1:t-{uuid.uuid4()}")
        r = subprocess.run([str(CLOSE), tab], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"tab close {tab}", self.log.read_text())
        self.assertTrue(self.gone(mine), "a tab-tagged process survived herdr-close")
        self.assertEqual(mine.returncode, -signal.SIGTERM)
        self.assertIsNone(other.poll(), "killed a process from another tab")
        self.assertIn("killed=1", r.stdout)
        self.assertEqual(r.stderr, "", "unreadable /proc entries must be silent")

    def test_close_of_a_space_ends_every_process_started_in_it(self):
        space = f"w-{uuid.uuid4()}"
        owner, worker = self.tagged(f"{space}:t1", space), self.tagged(f"{space}:t2", space)
        other = self.tagged("w-other:t1", f"w-other-{uuid.uuid4()}")
        r = subprocess.run([str(CLOSE), space], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"workspace close {space}", self.log.read_text())
        self.assertNotIn("tab close", self.log.read_text())
        self.assertTrue(self.gone(owner) and self.gone(worker), "a space process survived herdr-close")
        self.assertIsNone(other.poll(), "killed a process from another space")
        self.assertIn(f"space={space} space_close_rc=0 killed=2", r.stdout)

    def test_close_stops_only_processes_of_the_callers_session(self):
        # acceptance-session-close: another session repeats the space id.
        space, other = f"w-{uuid.uuid4()}", f"s-{uuid.uuid4()}"
        here = self.tagged(f"{space}:t1", space)
        there = self.tagged(f"{space}:t1", space, HERDR_SESSION=other)
        r = subprocess.run([str(CLOSE), space], capture_output=True, text=True, env=self.env)
        self.assertIn("killed=1", r.stdout)
        self.assertTrue(self.gone(here), "a space process survived herdr-close")
        self.assertIsNone(there.poll(), "closed a lane of another session")
        r = subprocess.run([str(CLOSE), space], capture_output=True, text=True,
                           env={**self.env, "HERDR_SESSION": other})
        self.assertIn("killed=1", r.stdout)
        self.assertTrue(self.gone(there), "a named session's process survived herdr-close")

    def waiting(self, target, **env):
        # A `herdr agent wait TARGET` of the caller's tab, which Herdr 0.9.0
        # leaves running forever once the target's tab closes.
        waiter = Path(self.tmp.name) / "waiter/herdr"
        waiter.parent.mkdir(exist_ok=True)
        waiter.write_text("#!/usr/bin/env bash\nwhile :; do sleep 0.1; done\n")
        waiter.chmod(0o755)
        p = subprocess.Popen([str(waiter), "agent", "wait", target], start_new_session=True,
                             env={**self.env, **env})
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def test_close_ends_every_wait_of_its_session_on_an_agent_it_closes(self):
        # acceptance-worker-closed-no-wait: a wait by name or pane id, whoever waits.
        other = f"s-{uuid.uuid4()}"
        for close in ("tab", "space"):
            space, n = f"w-{uuid.uuid4()}", f"-{close}"
            tab = f"{space}:t1"
            agents = [("implementer-ann-1" + n, f"{space}:p1", tab, space),
                      (None, f"{space}:p2", tab, space),  # unnamed, waited on by pane id
                      ("implementer-ann-3" + n, f"{space}:p3", f"{space}:t3", space),
                      ("implementer-ann-2" + n, "w-open:p1", "w-open:t1", "w-open")]
            listed = json.dumps({"result": {"agents": [
                {"name": a, "pane_id": p, "tab_id": t, "workspace_id": w} for a, p, t, w in agents]}})
            in_tab = [self.waiting("implementer-ann-1" + n), self.waiting(f"{space}:p1"),
                      self.waiting(f"{space}:p2")]
            in_space = [self.waiting("implementer-ann-3" + n), self.waiting(f"{space}:p3")]
            kept = [self.waiting("implementer-ann-2" + n), self.waiting("w-open:p1"),
                    self.waiting("implementer-ann-1" + n, HERDR_SESSION=other)]
            ended = in_tab if close == "tab" else in_tab + in_space
            kept += in_space if close == "tab" else []
            r = subprocess.run([str(CLOSE), tab if close == "tab" else space], capture_output=True,
                               text=True, env={**self.env, "FAKE_AGENT_LIST": listed})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"killed={len(ended)}", r.stdout)
            for w in ended:
                self.assertTrue(self.gone(w), f"a wait on an agent of the closed {close} survived")
                self.assertEqual(w.returncode, -signal.SIGTERM)
            for w in kept:
                self.assertIsNone(w.poll(), "ended a wait on an agent still open, or of another session")

    def test_close_rejects_an_option_as_a_tab(self):
        for arg in ("--help", "-h"):
            r = subprocess.run([str(CLOSE), arg], capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 64, r.stdout)
            self.assertFalse(self.log.exists(), "an option reached herdr tab close")

    # --- park ------------------------------------------------------------

    def claude(self, pane, tab, space, sid, replies=(), stale=False, sidechain=None, **env):
        # A detached stand-in for an agent's Claude process in a pane, with
        # Claude's own session file for its pid unless sid is None, recording
        # the process start time, or another one when stale: an ended Claude's
        # record at a pid a process of the pane reuses. replies are the
        # timestamps of the replies in its transcript; none, no transcript yet.
        # sidechain is the timestamp of a subagent's assistant record after them.
        p = subprocess.Popen(["sleep", "600"], start_new_session=True, env={
            **self.env, "HERDR_PANE_ID": pane, "HERDR_TAB_ID": tab, "HERDR_WORKSPACE_ID": space, **env})
        self.addCleanup(lambda: (p.kill(), p.wait()))
        if sid:
            home = Path(self.env["HOME"])
            sessions = home / ".claude/sessions"
            sessions.mkdir(parents=True, exist_ok=True)
            start = int(Path(f"/proc/{p.pid}/stat").read_text().split()[21]) + stale
            (sessions / f"{p.pid}.json").write_text(json.dumps({
                "pid": p.pid, "sessionId": sid, "cwd": str(self.cwd),
                "procStart": str(start), "agent": "implementer"}))
            if replies:
                project = home / ".claude/projects" / f"-p-{sid}"
                project.mkdir(parents=True, exist_ok=True)
                (project / f"{sid}.jsonl").write_text("".join(json.dumps(r) + "\n" for at in replies for r in (
                    {"type": "user", "isSidechain": False, "timestamp": at},
                    {"type": "assistant", "isSidechain": False, "timestamp": at})) + "".join(
                    json.dumps({"type": "assistant", "isSidechain": True, "timestamp": sidechain}) + "\n"
                    for _ in [sidechain] if sidechain))
        return p

    def park(self, status="idle", session=True, name="implementer-ann-1", tabs=2, twin=None,
             replies=(), beside=(), **env):
        # twin names another Herdr session holding an agent under the same ids;
        # beside holds (session id, claude kwargs) of more Claude records in the pane.
        space = f"w-{uuid.uuid4()}"
        tab, pane = f"{space}:t1", f"{space}:p1"
        for sid, kw in beside:
            self.claude(pane, tab, space, sid, **kw)
        p = self.claude(pane, tab, space, "s-1" if session else None, replies)
        if twin:
            self.twin = self.claude(pane, tab, space, "s-twin", HERDR_SESSION=twin)
        agent = {"result": {"agent": {"name": name, "pane_id": pane, "tab_id": tab,
                                      "workspace_id": space, "agent_status": status}}}
        # The space is the lane's, labelled with its name; only its tab count decides.
        ws = {"result": {"workspace": {"workspace_id": space, "label": "ann45",
                                       "tab_count": tabs}}}
        listed = {"result": {"agents": [agent["result"]["agent"]]}}
        r = subprocess.run([str(CLOSE), "--park", pane], capture_output=True, text=True,
                           env={**self.env, "FAKE_AGENT_GET": json.dumps(agent),
                                "FAKE_WORKSPACE_GET": json.dumps(ws),
                                "FAKE_AGENT_LIST": json.dumps(listed), **env})
        return p, r, pane, tab, space

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_parking_a_worker_closes_its_tab_and_prints_one_parked_line(self):
        p, r, pane, tab, space = self.park()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"tab close {tab}", self.calls())
        self.assertNotIn("workspace close", self.calls())
        self.assertTrue(self.gone(p), "the parked agent's process survived")
        line = json.loads(r.stdout)
        self.assertEqual({k: line[k] for k in ("kind", "pane", "name", "role", "cwd", "session")},
                         {"kind": "parked", "pane": pane, "name": "implementer-ann-1",
                          "role": "implementer", "cwd": str(self.cwd), "session": "s-1"})
        self.assertRegex(line["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_parking_a_lane_owner_frees_its_whole_space(self):
        # acceptance-park-owner-free: the owner's tab is the only one in its space.
        p, r, pane, tab, space = self.park(name="ann45", tabs=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"workspace close {space}", self.calls())
        self.assertTrue(self.gone(p), "a process of the parked owner is still running")
        self.assertEqual(len(r.stdout.splitlines()), 1, r.stdout)
        self.assertEqual(json.loads(r.stdout)["session"], "s-1")

    def test_parking_ends_every_wait_on_the_parked_agent(self):
        # transport-close-waits: parking included.
        mine, theirs = self.waiting("implementer-ann-1"), self.waiting("implementer-ann-2")
        p, r, *_ = self.park(name="implementer-ann-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.gone(mine), "a wait on the parked agent survived")
        self.assertIsNone(theirs.poll(), "ended a wait on an agent still open")

    def test_parking_an_owner_in_a_shared_space_closes_only_its_tab(self):
        # The space's other tabs are agents that may be working.
        p, r, pane, tab, space = self.park(name="ann45", tabs=2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"tab close {tab}", self.calls())
        self.assertNotIn("workspace close", self.calls())

    def test_parking_an_agent_herdr_reports_done(self):
        # Herdr 0.9.0 reports a Claude agent waiting at its prompt as done.
        p, r, pane, tab, space = self.park(status="done")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"tab close {tab}", self.calls())
        self.assertTrue(self.gone(p), "the parked agent's process survived")
        self.assertEqual(json.loads(r.stdout)["kind"], "parked")

    def test_park_refuses_a_working_blocked_or_codex_agent(self):
        # acceptance-park-refuse: nothing closed, the agent keeps running.
        for kw, code in (({"status": "working"}, 75), ({"status": "blocked"}, 75),
                         ({"session": False}, 65)):
            p, r, *_ = self.park(**kw)
            self.assertEqual(r.returncode, code, r.stderr)
            self.assertEqual(r.stdout, "")
            self.assertNotIn("close", self.calls())
            self.assertIsNone(p.poll(), "a refused park stopped the agent")

    def test_park_names_the_conversation_of_its_own_sessions_agent(self):
        # acceptance-session-park: another session repeats the pane id.
        other = f"s-{uuid.uuid4()}"
        for caller, sid in (({}, "s-1"), ({"HERDR_SESSION": other}, "s-twin")):
            p, r, *_ = self.park(twin=other, **caller)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["session"], sid)
            mine, theirs = (p, self.twin) if not caller else (self.twin, p)
            self.assertTrue(self.gone(mine), "the parked agent's process survived")
            self.assertIsNone(theirs.poll(), "parking stopped another session's agent")

    def test_park_never_reads_a_record_left_at_a_reused_pid(self):
        # acceptance-park-stale-record: the ended Claude's record holds the
        # pane's newest reply, but its pid now runs another process of the pane.
        p, r, *_ = self.park(replies=["2026-10-21T09:00:00.000Z"],
                             beside=[("s-ended", {"stale": True, "replies": ["2026-10-21T10:00:00.000Z"]})])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["session"], "s-1")

    def test_park_names_the_conversation_held_in_the_pane(self):
        # acceptance-park-claimed-spare: a spare Claude claimed into the pane
        # beside an idle foreground one; the one holding the latest reply is
        # the pane's, whichever started first; a subagent's (sidechain) is none.
        for mine, other, sid in (("2026-10-21T09:00:00.000Z", "2026-10-21T08:00:00.000Z", "s-1"),
                                 ("2026-10-21T08:00:00.000Z", "2026-10-21T09:00:00.000Z", "s-spare")):
            p, r, *_ = self.park(replies=[mine], beside=[("s-spare", {
                "replies": [other], "sidechain": "2026-10-21T11:00:00.000Z"})])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["session"], sid)

    def test_claude_session_prints_the_panes_record_and_its_transcript(self):
        # The lookup herdr-say and herdr-close --park share.
        space = f"w-{uuid.uuid4()}"
        p = self.claude(f"{space}:p1", f"{space}:t1", space, "s-1", ["2026-10-21T09:00:00.000Z"])
        fresh = self.claude(f"{space}:p2", f"{space}:t2", space, "s-2")
        run = lambda pane: subprocess.run([str(SESSION), pane], capture_output=True, text=True, env=self.env)
        r = run(f"{space}:p1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 1, r.stdout)
        record = json.loads(r.stdout)
        self.assertEqual((record["pid"], record["sessionId"], record["agent"]), (p.pid, "s-1", "implementer"))
        self.assertEqual(record["transcript"], f"{self.env['HOME']}/.claude/projects/-p-s-1/s-1.jsonl")
        r = run(f"{space}:p2")
        self.assertEqual((r.returncode, json.loads(r.stdout)["transcript"]), (0, None), r.stderr)
        r = run(f"{space}:p3")
        self.assertEqual((r.returncode, r.stdout), (1, ""), r.stderr)

    def test_claude_session_cost_does_not_grow_with_the_transcript(self):
        # The operator's transcript grows past 200MB; a whole read took 7s, so
        # every herdr-say paid it and a wake outlived Spec Chat's 10s bound.
        # Beside a spare whose reply is older, the pane's session holds ~110MB
        # of earlier turns and its latest reply near its end. The bound is this
        # machine's own whole jq read of that transcript, so it holds at any
        # machine speed: a whole read costs that, a read from the end a sliver.
        space = f"w-{uuid.uuid4()}"
        pane, tab = f"{space}:p1", f"{space}:t1"
        self.claude(pane, tab, space, "s-spare", ["2026-10-21T09:00:00.000Z"])
        self.claude(pane, tab, space, "s-1")
        turn = lambda kind, at: json.dumps({"type": kind, "isSidechain": False, "timestamp": at, "message": {
            "content": [{"type": "text", "text": "word " * 4, "n": n} for n in range(40)]}}) + "\n"
        transcript = Path(self.env["HOME"]) / ".claude/projects/-p-s-1/s-1.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text((turn("user", "2026-10-21T08:00:00.000Z") + turn(
            "assistant", "2026-10-21T08:00:00.000Z")) * 25000 + turn(
            "assistant", "2026-10-21T10:00:00.000Z") + turn("user", "2026-10-21T10:00:01.000Z"))
        start = time.monotonic()
        subprocess.run(["jq", "empty", str(transcript)], check=True)
        whole = time.monotonic() - start
        start = time.monotonic()
        r = subprocess.run([str(SESSION), pane], capture_output=True, text=True, env=self.env)
        elapsed = time.monotonic() - start
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["sessionId"], "s-1")
        self.assertLess(elapsed, whole / 2)

    # --- say -------------------------------------------------------------

    def test_say_delivers_through_the_native_prompt_and_waits(self):
        r = self.say("a1", "hello")
        self.assertEqual(r.returncode, 0, r.stderr)
        line = [l for l in self.log.read_text().splitlines() if l.startswith("agent prompt")][0]
        self.assertIn("--wait", line)
        self.assertIn("--until", line)

    def test_say_maps_a_blocked_target_to_exit_75(self):
        # herdr-wake treats 75 as "retry later" and anything else
        # as a transport failure.
        r = self.say("a1", "hello", FAKE_PROMPT_BLOCKED="1")
        self.assertEqual(r.returncode, 75, r.stderr)

    def test_say_does_not_mask_other_failures_as_deferred(self):
        r = self.say("a1", "hello", FAKE_PROMPT_NOT_FOUND="1")
        self.assertNotIn(r.returncode, (0, 75))

    def test_say_accepts_the_caller_compatibility_flags(self):
        r = self.say("--kind", "command", "--artifact", "x.spec.html", "a1", "hello")
        self.assertEqual(r.returncode, 0, r.stderr)

    def replying(self, *replies, pane="w1:p1", on_wait=""):
        # The env posing a Claude agent in pane whose reply to each send is the
        # next of replies; its transcript starts once the first message lands.
        # sleep is a stand-in that records each wait, lands the next line a
        # working agent writes later, then runs on_wait.
        space = pane.split(":")[0]
        self.claude(pane, f"{space}:t1", space, "s-1")
        d = Path(self.tmp.name)
        (d / "replies").write_text("".join(f"{r}\n" for r in replies))
        bindir = d / "sleepbin"
        bindir.mkdir(exist_ok=True)
        self.waits = d / "waits"
        transcript = f"{self.env['HOME']}/.claude/projects/-p-s-1/s-1.jsonl"
        (bindir / "sleep").write_text(
            f'#!/bin/sh\necho "$1" >>"{self.waits}"\n'
            f'[ ! -s "{transcript}.later" ] || {{ head -1 "{transcript}.later" | grep . >>"{transcript}"; '
            f'sed -i 1d "{transcript}.later"; }}\n{on_wait}\n')
        (bindir / "sleep").chmod(0o755)
        return {"PATH": f"{bindir}:{self.env['PATH']}", "FAKE_REPLIES": str(d / "replies"),
                "FAKE_TRANSCRIPT": transcript}

    def say_to_claude(self, *replies, target="implementer-ann-1", pane="w1:p1", on_wait="",
                      message="review ANN-1", **env):
        # A Claude agent in pane, under the name target, replying replies.
        agent = {"result": {"agent": {"name": target, "pane_id": pane, "agent_status": "idle"}}}
        return self.say(target, message, **self.replying(*replies, pane=pane, on_wait=on_wait),
                        FAKE_AGENT_GET=json.dumps(agent), **env)

    def sends(self, target, message="review ANN-1"):
        return self.calls().count(f"agent prompt {target} {message} ")

    def sends_to(self, pane):
        return self.calls().count(f"agent prompt {pane} hand-off ready ")

    def slept(self):
        return [float(w) for w in self.waits.read_text().split()] if self.waits.exists() else []

    def test_say_resends_a_message_its_turn_died_on_a_rate_limit_until_processed(self):
        # acceptance-say-rate-limit, -confirmed: the first two turns die on a
        # 429, the third is a reply; each wait is longer than the last.
        r = self.say_to_claude("rate_limit", "rate_limit", "ok")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.sends("implementer-ann-1"), 3)
        waits = self.slept()
        self.assertEqual(len(waits), 2, waits)
        self.assertGreaterEqual(waits[0], 30)
        self.assertGreater(waits[1], waits[0])

    def test_say_exits_69_when_every_turn_dies_on_a_rate_limit(self):
        # acceptance-say-rate-limit-persistent: about two hours, then not processed.
        r = self.say_to_claude(*["rate_limit"] * 20)
        self.assertEqual(r.returncode, 69, r.stderr)
        n = self.sends("implementer-ann-1")
        waits = self.slept()
        self.assertEqual(len(waits), n - 1, waits)
        self.assertEqual(waits, sorted(waits))
        self.assertTrue(5400 <= sum(waits) <= 9000, waits)
        self.assertIn("implementer-ann-1", r.stderr)
        self.assertIn(f"{n} sends", r.stderr)
        self.assertIn("API Error: Request rejected (429)", r.stderr)
        self.assertEqual(r.stderr.count("\n"), 1, r.stderr)

    def test_say_is_done_at_a_reply_or_none_within_a_few_seconds(self):
        # The message is processed unless its first reply is a rate-limit error.
        for reply in ("ok", "none"):
            r = self.say_to_claude(reply, "rate_limit", pane=f"w-{reply}:p1")
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertEqual(self.sends("implementer-ann-1"), 1)
            self.assertLessEqual(sum(self.slept()), 10)
            self.log.unlink()
            self.waits.unlink(missing_ok=True)

    def test_say_resends_a_message_queued_behind_a_running_turn_whose_own_turn_died(self):
        # acceptance-say-rate-limit-queued: the running turn's ok lands inside
        # the reply window; the message, taken in past it, dies on a 429.
        r = self.say_to_claude("ok rate_limit", "ok", "rate_limit")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.sends("implementer-ann-1"), 2)
        self.assertEqual([w for w in self.slept() if w >= 30], [60])

    def test_say_judges_a_message_queued_behind_a_turn_dying_on_a_rate_limit_by_its_own_reply(self):
        # acceptance-say-running-turn-limited: the running turn's 429 is not
        # this message's; its own reply is ok, so it is sent once.
        r = self.say_to_claude("rate_limit ok", "rate_limit")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.sends("implementer-ann-1"), 1)
        self.assertEqual([w for w in self.slept() if w >= 30], [])

    def test_say_fails_a_queued_message_never_taken_in(self):
        # acceptance-say-never-taken-in: the running turn ends, or the agent's
        # Claude exits (Herdr finds no agent), before taking the message in.
        for end in ("ended", "exited"):
            pane = f"w-{end}:p1"
            later = f"{self.env['HOME']}/.claude/projects/-p-s-1/s-1.jsonl.later"
            exit = f'[ -s "{later}" ] || echo {pane} >"{self.gone_file}"' if end == "exited" else ""
            r = self.say_to_claude("ok exit", pane=pane, on_wait=exit)
            self.assertNotIn(r.returncode, (0, 69, 75), end)
            self.assertRegex(r.stderr, r"^herdr-say: implementer-ann-1: message never taken in\b[^\n]*\n$")
            self.assertEqual(self.sends("implementer-ann-1"), 1)
            self.log.unlink()

    def test_say_judges_a_slash_command_by_the_record_claude_makes_of_it(self):
        # Claude records /goal ARGS as its name and args in tags, so a /goal
        # whose turn dies on a rate limit is sent again like any message.
        r = self.say_to_claude("rate_limit", "ok", message="/goal ship ANN-1")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.sends("implementer-ann-1", "/goal ship ANN-1"), 2)

    def test_say_resends_to_a_resumed_worker_whose_turn_died_on_a_rate_limit(self):
        self.dialog.write_text("none\n")
        self.parked_line("ann45", pane="w1:p7", name="implementer-ann-1", role="implementer")
        self.gone_file.write_text("w1:p7\nimplementer-ann-1\n")
        r = self.say_to_claude("rate_limit", "ok", target="w1:p7", HERDR_WORKSPACE_ID="w1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "pane=w1:p1\n")
        self.assertEqual(self.sends("w1:p1"), 2)

    def test_say_resends_through_the_resume_to_a_worker_parked_during_its_wait(self):
        # acceptance-say-rate-limit-parked: the worker is parked while the send
        # waits out a rate limit, so the re-send resumes it as a first send to
        # a parked worker does. The fake's new tab reuses pane id w1:p1.
        self.dialog.write_text("none\n")
        self.parked_line("ann45", pane="w1:p1", name="implementer-ann-1", role="implementer")
        log = Path(self.env["XDG_STATE_HOME"]) / "octo-lite/lanes/ann45.handoffs.jsonl"
        held = log.rename(log.with_suffix(".held"))
        park = f'[ ! -e "{held}" ] || {{ mv "{held}" "{log}"; echo implementer-ann-1 >"{self.gone_file}"; }}'
        r = self.say_to_claude("rate_limit", "ok", on_wait=park, HERDR_WORKSPACE_ID="w1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "pane=w1:p1\n")
        argv = self.start_argv()
        self.assertEqual(argv[2], "implementer-ann-1")
        self.assertEqual(argv[-4:], ["--agent", "implementer", "--resume", "s-1"])
        self.assertIn("tab create --workspace w1 ", self.calls())
        self.assertEqual((self.sends("implementer-ann-1"), self.sends("w1:p1")), (2, 1))

    def parked_line(self, lane, at="2026-10-14T10:00:00Z", session=None, **fields):
        state = Path(self.env["XDG_STATE_HOME"]) / "octo-lite"
        lanes = (state / "sessions" / session if session else state) / "lanes"
        lanes.mkdir(parents=True, exist_ok=True)
        line = {"at": at, "kind": "parked", "cwd": str(self.cwd), "session": "s-1", **fields}
        with open(lanes / f"{lane}.handoffs.jsonl", "a") as f:
            f.write(json.dumps(line) + "\n")

    def test_say_resumes_a_parked_worker_in_the_callers_space(self):
        self.dialog.write_text("none\n")
        self.parked_line("ann45", at="2026-10-14T09:00:00Z", pane="w1:p7",
                         name="implementer-ann-1", role="implementer", session="s-old")
        self.parked_line("ann45", pane="w1:p7", name="implementer-ann-1", role="implementer")
        self.gone_file.write_text("w1:p7\nimplementer-ann-1\n")
        r = self.say("w1:p7", "hi", HERDR_WORKSPACE_ID="w3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "pane=w1:p1\n")
        argv = self.start_argv()
        self.assertEqual(argv[2], "implementer-ann-1")
        self.assertEqual(argv[-4:], ["--agent", "implementer", "--resume", "s-1"])
        self.assertIn("tab create --workspace w3 ", self.calls())
        self.assertIn("agent prompt w1:p1 hi", self.calls())

    def test_say_resumes_a_parked_owner_in_a_new_lane_space(self):
        # A legacy line without name or role is the owner under the lane's name.
        self.dialog.write_text("none\n")
        self.parked_line("ann45", pane="w9:p2")
        self.gone_file.write_text("w9:p2\nann45\n")
        r = self.say("w9:p2", "what are you waiting on?")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "pane=w1:p1\n")
        self.assertIn(f"workspace create --label ann45 --cwd {self.cwd} --no-focus", self.calls())
        argv = self.start_argv()
        self.assertEqual(argv[2], "ann45")
        self.assertEqual(argv[-4:], ["--agent", "orchestrator", "--resume", "s-1"])
        self.assertIn("agent prompt w1:p1 what are you waiting on?", self.calls())

    def test_a_second_message_to_a_resumed_owner_starts_no_second_copy(self):
        # acceptance-park-wake-once: the old pane is gone, its name is live.
        self.parked_line("ann45", pane="w9:p2")
        self.gone_file.write_text("w9:p2\n")
        r = self.say("w9:p2", "hi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("agent start", self.calls())
        self.assertIn("agent prompt ann45 hi", self.calls())

    def test_say_never_resumes_a_lane_parked_in_another_session(self):
        # acceptance-session-wake: the parked owner is in the default session.
        self.parked_line("ann45", pane="w9:p2")
        self.gone_file.write_text("w9:p2\nann45\n")
        r = self.say("w9:p2", "hi", HERDR_SESSION="s2")
        self.assertNotIn(r.returncode, (0, 75))
        self.assertNotIn("agent start", self.calls())
        self.assertNotIn("workspace create", self.calls())
        self.assertEqual(self.say("--parked", "w9:p2").returncode, 0)
        self.parked_line("ann46", pane="w8:p1", session="s2")
        self.assertEqual(self.say("--parked", "w8:p1").returncode, 1)
        self.assertEqual(self.say("--parked", "w8:p1", HERDR_SESSION="s2").returncode, 0)

    # --- await -----------------------------------------------------------

    def awaits(self, *args, **env):
        # herdr-await run by the owner in pane w5:p2 of its own tab, which a
        # cleanup reaps with whatever the wait left running.
        tab = f"w5:t-{uuid.uuid4()}"
        self.addCleanup(self.reap, tab)
        start = time.monotonic()
        r = subprocess.run([str(AWAIT), *args], capture_output=True, text=True, timeout=10,
                           env={**self.env, "HERDR_PANE_ID": "w5:p2", "HERDR_TAB_ID": tab,
                                "HERDR_WORKSPACE_ID": "w5", **env})
        r.elapsed, r.tab = time.monotonic() - start, tab
        return r

    def reap(self, tab):
        for pid in self.tagged_pids(tab):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def tagged_pids(self, tab, argv=""):
        # Live processes carrying HERDR_TAB_ID=tab whose argv holds argv.
        pids = []
        for env in Path("/proc").glob("[0-9]*/environ"):
            try:
                tags = env.read_bytes().split(b"\0")
                cmd = (env.parent / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            except OSError:
                continue
            if f"HERDR_TAB_ID={tab}".encode() in tags and argv in cmd:
                pids.append(int(env.parent.name))
        return pids

    def woken(self, within=5.0):
        # The message herdr-await sent its caller's pane, or None.
        end = time.monotonic() + within
        while True:
            m = re.search(r"^agent prompt w5:p2 (herdr-await: .*) --wait ", self.calls(), re.M)
            if m or time.monotonic() > end:
                return m and m.group(1)
            time.sleep(0.05)

    def test_await_sends_the_work_then_wakes_its_caller_naming_the_stop(self):
        # transport-await, roles-goal: the wake is a message to the caller's
        # pane, so it reaches a Codex or pi owner as it does a Claude one
        # (acceptance-codex-owner-worker-ended, -pi-owner-worker-ended). The
        # stop names Herdr's state_change_seq, so a re-wait can pass it back.
        r = self.awaits("implementer-ann-1", "brief ANN-1", FAKE_WAIT_STATUS="blocked")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.woken(), "herdr-await: implementer-ann-1 stop=blocked seq=42")
        calls = self.calls().splitlines()
        brief = calls.index(next(c for c in calls if c.startswith("agent prompt implementer-ann-1 brief ANN-1 ")))
        # by name, with no --until: Herdr's own idle, done, or blocked
        wait = calls.index("agent wait implementer-ann-1")
        wake = calls.index(next(c for c in calls if c.startswith("agent prompt w5:p2 ")))
        self.assertLess(brief, wait)
        self.assertLess(wait, wake)

    def test_await_without_a_message_only_waits(self):
        # An owner relaunched from a park re-waits on a worker, sending nothing.
        self.awaits("implementer-ann-1")
        self.assertEqual(self.woken(), "herdr-await: implementer-ann-1 stop=idle seq=42")
        self.assertNotIn("agent prompt implementer-ann-1", self.calls())

    def test_await_since_a_stop_ends_only_once_the_agent_worked_and_stopped_again(self):
        # roles-goal, transport-await: a worker still at its task (idle on its
        # own background command) at the stop its owner read never wakes the
        # owner again until it has worked and stopped.
        r = self.awaits("--since", "42", "implementer-ann-1")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIsNone(self.woken(within=0.5), "woke on a worker that has not moved")
        Path(self.env["FAKE_WORKED"]).touch()
        self.assertEqual(self.woken(), "herdr-await: implementer-ann-1 stop=idle seq=44")

    def test_await_since_a_stop_ends_at_once_on_an_agent_that_moved_before_it_started(self):
        # acceptance-worker-moved-unseen: a worker that works and stops before
        # the wait starts still ends it, where a wait for its next work hangs.
        Path(self.env["FAKE_WORKED"]).touch()
        self.awaits("--since", "42", "implementer-ann-1")
        self.assertEqual(self.woken(), "herdr-await: implementer-ann-1 stop=idle seq=44")

    def test_await_returns_at_once_and_ends_with_its_callers_tab(self):
        # The wait runs apart from its caller, yet as a process of the caller's
        # tab, so closing or parking the caller ends it, waking no one.
        gate = Path(self.tmp.name) / "gate"
        r = self.awaits("implementer-ann-1", "brief ANN-1", FAKE_WAIT_GATE=str(gate))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(r.elapsed, 3)
        self.assertIsNone(self.woken(within=0.5), "woke its caller before the agent stopped")
        self.assertTrue(self.tagged_pids(r.tab, "herdr-await"), "the wait left its caller's tab")
        close = subprocess.run([str(CLOSE), r.tab], capture_output=True, text=True, env=self.env)
        self.assertEqual(close.returncode, 0, close.stderr)
        gate.touch()
        self.assertIsNone(self.woken(within=0.5), "a closed caller's wait still ran")
        self.assertEqual(self.tagged_pids(r.tab, "herdr-await"), [])

    def test_await_wakes_its_caller_on_an_agent_gone(self):
        # Its agent exited, no agent has its name, or its wait was ended (as
        # herdr-close ends the waits on what it closes): each ends as gone.
        self.awaits("implementer-ann-1", "brief ANN-1", FAKE_WAIT_EXITED="1")
        self.assertEqual(self.woken(), "herdr-await: implementer-ann-1 stop=gone (agent_not_running)")
        self.log.unlink()
        self.gone_file.write_text("implementer-ann-2\n")
        self.awaits("implementer-ann-2")
        self.assertEqual(self.woken(), "herdr-await: implementer-ann-2 stop=gone (agent_not_found)")
        self.log.unlink()
        gate = Path(self.tmp.name) / "gate"
        r = self.awaits("implementer-ann-3", FAKE_WAIT_GATE=str(gate))
        for _ in range(100):
            waits = self.tagged_pids(r.tab, "agent wait implementer-ann-3")
            if waits:
                break
            time.sleep(0.05)
        for pid in waits:
            os.kill(pid, signal.SIGTERM)
        self.assertEqual(self.woken(), "herdr-await: implementer-ann-3 stop=gone (herdr agent wait exit 143)")

    def test_await_ends_at_once_on_a_send_that_fails(self):
        # A send not exiting 0 ends the wait before it starts, naming the failure.
        self.gone_file.write_text("implementer-ann-1\n")
        self.awaits("implementer-ann-1", "brief ANN-1")
        woken = self.woken()
        self.assertRegex(woken, r"^herdr-await: implementer-ann-1 stop=send-failed \(herdr-say exit 1: .*agent_not_found.*\)$")
        self.assertNotIn("agent wait", self.calls())

    def test_await_needs_a_name_and_a_caller_pane(self):
        for args, env in (((), {}), (("-h",), {}), (("a", "b", "c"), {}),
                          (("--since", "42"), {}), (("--since", "seq=42", "a"), {}),
                          (("implementer-ann-1",), {"HERDR_PANE_ID": ""})):
            r = self.awaits(*args, **env)
            self.assertEqual(r.returncode, 64, (args, r.stderr))
        self.assertIsNone(self.woken(within=0.3))
        self.assertNotIn("agent", self.calls())

    # --- wake provider (Spec Chat's wake protocol) -------------------------

    def wake(self, *args, status="idle", pane="w1:p1", **env):
        agent = '{"result":{"agent":{"pane_id":"%s","agent_status":"%s"}}}' % (pane, status)
        return subprocess.run([str(WAKE), *args], capture_output=True, text=True,
                              env={**self.env, "FAKE_AGENT_GET": agent, **env})

    def test_wake_check_is_zero_only_for_a_resolving_owner(self):
        self.assertEqual(self.wake("check", "w1:p1").returncode, 0)
        self.assertEqual(self.wake("check", "w1:p2").returncode, 1)

    def operator(self, pane="w5:p2"):
        # The operator pane of the default session's state, as it writes it.
        state = Path(self.env["XDG_STATE_HOME"]) / "octo-lite"
        state.mkdir(parents=True, exist_ok=True)
        (state / "operator.toml").write_text(f'pane = "{pane}"\n')
        return f"agent prompt {pane} "

    def test_wake_send_keeps_delivering_past_its_send_bound(self):
        # transport-wake-bound, acceptance-wake-rate-limit-persistent: Spec
        # Chat runs send in its own session, kills that process group at its
        # bound, and counts it sent (review-serve.py run_wake). This resume is
        # held past the kill, then still delivers; the resumed owner's every
        # turn dies on a rate limit, so the operator is told, once.
        self.dialog.write_text("none\n")
        self.parked_line("ann45", pane="w9:p2")
        self.gone_file.write_text("w9:p2\nann45\n")
        told = self.operator()
        gate = Path(self.tmp.name) / "gate"
        self.addCleanup(gate.touch)
        tmpdir = Path(self.tmp.name) / "tmp"
        tmpdir.mkdir()
        agent = '{"result":{"agent":{"pane_id":"w1:p1","agent_status":"idle"}}}'
        with tempfile.TemporaryFile() as err:
            p = subprocess.Popen([str(WAKE), "send", "w9:p2", "a.spec.html", "hand-off ready"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                 env={**self.env, "FAKE_START_GATE": str(gate), "TMPDIR": str(tmpdir),
                                      **self.replying(*["rate_limit"] * 9), "FAKE_AGENT_GET": agent},
                                 start_new_session=True)
            for _ in range(100):
                if "agent start" in self.calls():
                    break
                time.sleep(0.1)
            self.assertIsNone(p.poll(), "send returned before its herdr-say ended")
            send = Path(f"/proc/{p.pid}/task/{p.pid}/children").read_text().split()
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        self.assertEqual(list(tmpdir.iterdir()), [])
        gate.touch()
        for _ in range(300):
            if not any(Path(f"/proc/{pid}/stat").exists() and Path(f"/proc/{pid}/stat").read_text()
                       .split(")")[-1].split()[0] != "Z" for pid in send):
                break
            time.sleep(0.1)
        self.assertIn("agent prompt w1:p1 hand-off ready", self.calls())
        self.assertEqual(self.sends_to("w1:p1"), 9)
        prompts = [l for l in self.calls().splitlines() if l.startswith(told)]
        self.assertEqual(len(prompts), 1, prompts)
        self.assertIn("w9:p2", prompts[0])
        self.assertIn("a.spec.html", prompts[0])
        self.assertIn("not processed: API rate limit", prompts[0])

    def test_wake_send_failing_within_its_send_bound_tells_only_spec_chat(self):
        # transport-wake-bound: Spec Chat holds a failure within its bound and
        # retries it, so the operator hears of none of its attempts. The owner
        # gone between check and send fails at once; a 69 takes hours.
        told = self.operator()
        r = self.wake("send", "w1:p1", "a.spec.html", "hand-off ready", FAKE_PROMPT_NOT_FOUND="1")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertRegex(r.stderr, r'^herdr-wake: [^\n]*"agent_not_found"[^\n]*\n$')
        self.assertNotIn(told, self.calls())

    def test_wake_check_counts_a_parked_owner_as_present(self):
        self.parked_line("ann45", pane="w1:p2")
        self.assertEqual(self.wake("check", "w1:p2").returncode, 0)
        self.assertEqual(self.wake("check", "w1:p3").returncode, 1)

    def test_wake_send_prompts_the_owner_with_the_message(self):
        r = self.wake("send", "w1:p1", "a.spec.html", "hand-off ready")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("agent prompt w1:p1 hand-off ready", self.log.read_text())

    def test_wake_send_states_match_host_wake(self):
        send = ("send", "w1:p1", "a.spec.html", "m")
        self.assertEqual(self.wake(*send, status="working").returncode, 75)
        self.assertNotIn("agent prompt", self.log.read_text())
        self.assertEqual(self.wake(*send, FAKE_PROMPT_BLOCKED="1").returncode, 75)
        self.assertEqual(self.wake(*send, FAKE_PROMPT_STALLED="1").returncode, 0)
        self.assertNotIn(self.wake(*send, FAKE_PROMPT_NOT_FOUND="1").returncode, (0, 75))
        self.assertNotIn(self.wake(*send, pane="w1:p9").returncode, (0, 75))

    def test_wake_reaches_an_owner_in_the_session_it_names(self):
        # acceptance-session-wake-owner: a service in one session, pinned to
        # its socket, wakes an owner of session s2, parked or live.
        envlog = Path(self.tmp.name) / "env.log"
        here = {"FAKE_ENV_LOG": str(envlog), "HERDR_SOCKET_PATH": "/here.sock"}
        self.assertEqual(self.wake("check", "s2/w1:p1", **here).returncode, 0)
        r = self.wake("send", "s2/w1:p1", "a.spec.html", "hand-off ready", **here)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("agent prompt w1:p1 hand-off ready", self.calls())
        self.assertEqual(set(envlog.read_text().splitlines()), {"session=s2 socket="})
        self.parked_line("ann46", pane="w8:p1", session="s2")
        self.gone_file.write_text("w8:p1\n")
        self.assertEqual(self.wake("check", "s2/w8:p1", **here).returncode, 0)
        self.assertEqual(self.wake("check", "w8:p1", **here).returncode, 1)

    def bare_path(self, herdr=True):
        # A launcher's search path (cron: /usr/bin:/bin) lacks Herdr's dir;
        # Herdr's installer puts it in ~/.local/bin. The launcher path mirrors
        # the system's tools minus any Herdr there, so no test reaches a real one.
        launcher = Path(self.tmp.name) / "launcher"
        launcher.mkdir()
        for d in ("/usr/bin", "/bin"):
            for tool in Path(d).iterdir():
                if tool.name != "herdr" and not (launcher / tool.name).exists():
                    (launcher / tool.name).symlink_to(tool)
        home_bin = Path(self.env["HOME"]) / ".local/bin"
        home_bin.mkdir(parents=True)
        if herdr:
            (home_bin / "herdr").symlink_to(Path(self.tmp.name) / "bin/herdr")
        return {"PATH": str(launcher)}

    def test_wake_reaches_herdr_outside_the_callers_search_path(self):
        # acceptance-wake-search-path
        bare = self.bare_path()
        self.assertEqual(self.wake("check", "w1:p1", **bare).returncode, 0)
        r = self.wake("send", "w1:p1", "a.spec.html", "hand-off ready", **bare)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("agent prompt w1:p1 hand-off ready", self.calls())

    def test_wake_names_herdr_as_not_found(self):
        # acceptance-wake-no-herdr
        bare = self.bare_path(herdr=False)
        for args in (("check", "w1:p1"), ("send", "w1:p1", "a.spec.html", "m")):
            r = self.wake(*args, **bare)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stderr.count("\n"), 1, r.stderr)
            self.assertIn("herdr not found", r.stderr)

    def test_wake_names_an_owner_pane_gone_from_its_session(self):
        # acceptance-wake-owner-gone: gone from Herdr, or resolving elsewhere.
        self.gone_file.write_text("w1:p9\n")
        for owner, session in (("w1:p9", "default"), ("s2/w1:p9", "s2"), ("w1:p2", "default")):
            for args in (("check", owner), ("send", owner, "a.spec.html", "m")):
                r = self.wake(*args)
                self.assertEqual(r.returncode, 1)
                self.assertEqual(r.stderr, f"herdr-wake: owner pane {owner.split('/')[-1]} "
                                           f"not found in Herdr session {session}\n")

    def test_wake_passes_on_herdrs_own_error_in_one_line(self):
        err = '{"error":{"code":"server_unavailable","message":"no server"}}'
        r = self.wake("check", "w1:p1", FAKE_AGENT_GET_ERROR=err + "\nretry later")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.count("\n"), 1, r.stderr)
        self.assertIn("server_unavailable", r.stderr)
        r = self.wake("send", "w1:p1", "a.spec.html", "m", FAKE_PROMPT_NOT_FOUND="1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.count("\n"), 1, r.stderr)
        self.assertIn("agent_not_found", r.stderr)

    def test_wake_names_a_herdr_that_does_not_answer(self):
        # Herdr hangs past the bound on its own get; both run at once.
        ps = [subprocess.Popen([str(WAKE), *args], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True,
                               env={**self.env, "FAKE_AGENT_GET_HANG": "1"})
              for args in (("check", "w1:p1"), ("send", "w1:p1", "a.spec.html", "m"))]
        for p in ps:
            _, err = p.communicate(timeout=20)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(err.count("\n"), 1, err)
            self.assertIn("Herdr not answering", err)

    def test_wake_reads_a_live_owner_past_herdrs_warnings(self):
        warn = {"FAKE_AGENT_GET_WARN": "warning: config is deprecated"}
        r = self.wake("check", "w1:p1", **warn)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        r = self.wake("send", "w1:p1", "a.spec.html", "m", status="working", **warn)
        self.assertEqual((r.returncode, r.stderr), (75, ""))

    def test_wake_reason_stays_one_line_beside_a_malformed_handoff_log(self):
        lanes = Path(self.env["XDG_STATE_HOME"]) / "octo-lite/lanes"
        lanes.mkdir(parents=True)
        (lanes / "ann45.handoffs.jsonl").write_text("not json\n")
        for args in (("check", "w1:p2"), ("send", "w1:p2", "a.spec.html", "m")):
            r = self.wake(*args)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stderr, "herdr-wake: owner pane w1:p2 not found "
                                       "in Herdr session default\n")

    # --- session state ---------------------------------------------------

    def state(self, **env):
        r = subprocess.run([str(STATE)], capture_output=True, text=True, env={**self.env, **env})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_state_of_a_named_session_is_its_own_dir(self):
        # acceptance-session-dir
        self.assertEqual(self.state(HERDR_SESSION="s2"),
                         f"{self.env['XDG_STATE_HOME']}/octo-lite/sessions/s2\n")

    def test_state_of_the_default_session_is_the_top_dir(self):
        # acceptance-session-default: the one holding onboarding.toml
        self.assertEqual(self.state(), f"{self.env['XDG_STATE_HOME']}/octo-lite\n")

    # --- start command ---------------------------------------------------

    def start(self, *extra, **env):
        return subprocess.run(
            [str(ROOT / "scripts/octo-lite-start"), "--cwd", str(self.cwd), *extra],
            capture_output=True, text=True, env={**self.env, **env},
        )

    def test_start_puts_the_owner_alone_in_a_new_lane_space(self):
        self.dialog.write_text("none\n")
        r = self.start("--name", "ann45")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.log.read_text().splitlines()
        self.assertIn(f"workspace create --label ann45 --cwd {self.cwd} --no-focus", calls)
        self.assertTrue(any(c.startswith("tab create --workspace w2 ") for c in calls), calls)
        # the seed tab closes; the owner's tab stays
        self.assertEqual([c for c in calls if c.startswith("tab close")], ["tab close w2:t1"])
        self.assertRegex(r.stdout, r"^workspace=w2 name=ann45 .*pane=w1:p1 ")

    def test_a_failed_owner_start_closes_the_lane_space(self):
        r = self.start(FAKE_START_FAIL_OTHER="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("workspace close w2", self.log.read_text())

    def test_start_spawns_an_orchestrator(self):
        self.dialog.write_text("none\n")
        r = self.start()
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.start_argv()
        self.assertEqual(argv[:3], ["agent", "start", "orchestrator-worktree"])
        self.assertEqual(argv[-2:], ["--agent", "orchestrator"])

    def test_start_codex_takes_the_orchestrator_contract(self):
        self.dialog.write_text("none\n")
        contract = Path(self.env["HOME"]) / ".claude/agents/orchestrator.md"
        contract.parent.mkdir(parents=True)
        contract.write_text("# Orchestrator\n")
        r = self.start("--runtime", "codex", "--name", "n1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("developer_instructions=", " ".join(self.start_argv()))

    def test_start_pi_takes_the_orchestrator_contract(self):
        self.dialog.write_text("none\n")
        contract = Path(self.env["HOME"]) / ".claude/agents/orchestrator.md"
        contract.parent.mkdir(parents=True)
        contract.write_text("# Orchestrator\n")
        r = self.start("--runtime", "pi", "--name", "n1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("contract=appended-system-prompt", r.stdout)
        self.assertEqual(self.start_argv()[-2:], ["--append-system-prompt", str(contract)])


if __name__ == "__main__":
    unittest.main()
