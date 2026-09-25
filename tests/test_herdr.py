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
  * a Codex contract sent as a prompt is worked as a task, and a Codex thread
    on the shared daemon outlives its tab
  * a detached child outlives its closed tab unless `herdr-close` reaps it
"""

import os
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
CLOSE = ROOT / "skills/herdr-comms/assets/herdr-close"

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
        }

    def spawn(self, extra=(), **env):
        return subprocess.run(
            [str(SPAWN), "--workspace", "w1", "--name", "a1", "--label", "L",
             "--cwd", str(self.cwd), "--role", "r", *extra, "--", "claude"],
            capture_output=True, text=True, env={**self.env, **env},
        )

    def spawn_codex(self, extra=(), **env):
        return subprocess.run(
            [str(SPAWN), "--workspace", "w1", "--name", "a1", "--label", "L",
             "--cwd", str(self.cwd), "--role", "r", *extra, "--", "codex"],
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

    def test_no_operating_model_changes_nothing(self):
        self.dialog.write_text("none\n")
        r = self.spawn()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--append-system-prompt-file", self.start_argv())

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

    def tagged(self, tab):
        # setsid, like a detached command child that survives its tab
        p = subprocess.Popen(["sleep", "600"], start_new_session=True,
                             env={**self.env, "HERDR_TAB_ID": tab})
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def gone(self, p):
        for _ in range(50):
            if p.poll() is not None:
                return True
            time.sleep(0.1)
        return False

    def test_close_ends_every_process_tagged_with_the_tab(self):
        tab = f"t-{uuid.uuid4()}"
        mine, other = self.tagged(tab), self.tagged(f"t-{uuid.uuid4()}")
        r = subprocess.run([str(CLOSE), tab], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"tab close {tab}", self.log.read_text())
        self.assertTrue(self.gone(mine), "a tab-tagged process survived herdr-close")
        self.assertEqual(mine.returncode, -signal.SIGTERM)
        self.assertIsNone(other.poll(), "killed a process from another tab")
        self.assertIn("killed=1", r.stdout)
        self.assertEqual(r.stderr, "", "unreadable /proc entries must be silent")

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
