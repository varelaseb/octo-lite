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
    spec-chat's `wake-herdr.py` adapter relies on
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPAWN = ROOT / "skills/herdr-comms/assets/herdr-spawn"
SAY = ROOT / "skills/herdr-comms/assets/herdr-say"

# A stand-in for the `herdr` binary. Behaviour is driven entirely by environment
# variables so each test can pose one exact failure without a live server.
FAKE_HERDR = r"""#!/usr/bin/env bash
set -eu
echo "$*" >>"$FAKE_LOG"
sub="$1 ${2:-}"

dialog_state() { [[ -f "$FAKE_DIALOG" ]] && cat "$FAKE_DIALOG" || echo none; }

case "$sub" in
  "tab create")
    echo '{"result":{"tab":{"tab_id":"w1:t1"},"root_pane":{"pane_id":"w1:p1"}}}' ;;
  "tab close")
    echo "CLOSED" >>"$FAKE_CLOSED"; echo '{"result":{}}' ;;
  "agent start")
    n=0
    [[ -f "$FAKE_START_COUNT" ]] && n="$(cat "$FAKE_START_COUNT")"
    n=$((n + 1)); echo "$n" >"$FAKE_START_COUNT"
    if [[ -n "${FAKE_START_FAIL_OTHER:-}" ]]; then
      echo '{"error":{"code":"agent_pane_not_found","message":"no pane"},"id":"cli:agent:start"}' >&2; exit 1
    fi
    if [[ -n "${FAKE_START_BUSY_COUNT:-}" && "$n" -le "$FAKE_START_BUSY_COUNT" ]]; then
      echo '{"error":{"code":"agent_pane_busy","message":"not an available shell"},"id":"cli:agent:start"}' >&2; exit 1
    fi
    if [[ -n "${FAKE_START_NOT_READY:-}" ]]; then
      echo '{"error":{"code":"agent_not_ready","message":"blocked during startup"},"id":"cli:agent:start"}' >&2; exit 1
    fi
    echo '{"result":{}}' ;;
  "pane read")
    case "$(dialog_state)" in
      no)  printf ' Quick safety check: Is this a project you created or one you trust?\n ❯ No, exit\n   Yes, I trust this folder\n' ;;
      yes) printf ' Quick safety check: Is this a project you created or one you trust?\n   No, exit\n ❯ Yes, I trust this folder\n' ;;
      stuck) printf ' Quick safety check: Is this a project you created or one you trust?\n   No, exit\n ❯ Yes, I trust this folder\n' ;;
      codexno)  printf ' Do you trust the contents of this directory?\n   1. Yes, continue\n \xe2\x80\xba 2. No, quit\n' ;;
      codexyes) printf ' Do you trust the contents of this directory?\n \xe2\x80\xba 1. Yes, continue\n   2. No, quit\n' ;;
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
    if [[ -n "${FAKE_NEVER_READY:-}" ]]; then
      echo '{"result":{"agent":{}}}'
    elif [[ -n "${FAKE_NO_SESSION:-}" ]]; then
      echo '{"result":{"agent":{"agent_status":"idle"}}}'
    else
      echo '{"result":{"agent":{"agent_session":{"value":"sess-123"},"agent_status":"idle"}}}'
    fi ;;
  "agent prompt")
    if [[ -n "${FAKE_PROMPT_BLOCKED:-}" ]]; then
      echo '{"error":{"code":"agent_blocked","message":"requires interactive input"},"id":"cli:agent:prompt"}' >&2; exit 1
    fi
    if [[ -n "${FAKE_PROMPT_NOT_FOUND:-}" ]]; then
      echo '{"error":{"code":"agent_not_found","message":"not found"},"id":"cli:agent:prompt"}' >&2; exit 1
    fi
    echo '{"result":{"agent":{"agent_status":"working"}}}' ;;
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
            "HOME": str(d),
        }

    def spawn(self, **env):
        return subprocess.run(
            [str(SPAWN), "--workspace", "w1", "--name", "a1", "--label", "L",
             "--cwd", str(self.cwd), "--role", "r", "--", "claude"],
            capture_output=True, text=True, env={**self.env, **env},
        )

    def spawn_codex(self, **env):
        return subprocess.run(
            [str(SPAWN), "--workspace", "w1", "--name", "a1", "--label", "L",
             "--cwd", str(self.cwd), "--role", "r", "--", "codex"],
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

    def test_delivers_the_role_contract_to_a_codex_agent(self):
        # Codex has no custom-agent file, so an undelivered contract is an agent
        # that never read where it may write.
        self.dialog.write_text("none\n")
        agents = Path(self.env["HOME"]) / ".claude/agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "r.md").write_text("# Role\nWrite only in your worktree.\n")
        r = self.spawn_codex()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("contract=delivered", r.stdout)
        # the fake logs the whole invocation, and the prompt spans lines
        log = self.log.read_text()
        self.assertIn("agent prompt", log)
        self.assertIn("Write only in your worktree", log)

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

    # --- say -------------------------------------------------------------

    def test_say_delivers_through_the_native_prompt_and_waits(self):
        r = self.say("a1", "hello")
        self.assertEqual(r.returncode, 0, r.stderr)
        line = [l for l in self.log.read_text().splitlines() if l.startswith("agent prompt")][0]
        self.assertIn("--wait", line)
        self.assertIn("--until", line)

    def test_say_maps_a_blocked_target_to_exit_75(self):
        # spec-chat's wake-herdr.py treats 75 as "retry later" and anything else
        # as a transport failure.
        r = self.say("a1", "hello", FAKE_PROMPT_BLOCKED="1")
        self.assertEqual(r.returncode, 75, r.stderr)

    def test_say_does_not_mask_other_failures_as_deferred(self):
        r = self.say("a1", "hello", FAKE_PROMPT_NOT_FOUND="1")
        self.assertNotIn(r.returncode, (0, 75))

    def test_say_accepts_the_caller_compatibility_flags(self):
        r = self.say("--kind", "command", "--artifact", "x.spec.html", "a1", "hello")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
