"""octo-lite's command-time hook tells an agent how long each shell command
took, a box lock wait apart, and warns of a slow iteration loop; it only
informs. Spec: spec/domains/command-time.spec.html, every criterion; the
payloads follow Claude Code 2.1's PostToolUse and PostToolUseFailure inputs
(duration_ms) and Codex 0.166's PreToolUse and PostToolUse inputs (none)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "octo-lite-command-time"
INSTALLER = ROOT / "scripts" / "install-octo-lite"
LOOP = "Slow iteration loop"
SECONDS = re.compile(r"(?:(\d+)m )?([0-9.]+)s")


def seconds(text: str) -> float:
    minutes, secs = SECONDS.fullmatch(text).groups()
    return int(minutes or 0) * 60 + float(secs)


class HookCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.state = self.tmp / "state"
        self.env = {**os.environ, "XDG_STATE_HOME": str(self.state), "HOME": str(self.tmp)}
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        (self.repo / "app.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "seed"], check=True)
        self.calls = 0

    def hook(self, payload: dict | str) -> subprocess.CompletedProcess:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([str(HOOK)], input=text, capture_output=True, text=True, env=self.env)

    def told(self, result: subprocess.CompletedProcess, event: str = "PostToolUse") -> str:
        """The one line the agent is told, checked to only inform."""
        self.assertEqual(0, result.returncode, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual({"hookSpecificOutput"}, set(out), "inform only: no decision, no stop")
        self.assertEqual({"hookEventName", "additionalContext"}, set(out["hookSpecificOutput"]))
        self.assertEqual(event, out["hookSpecificOutput"]["hookEventName"])
        return out["hookSpecificOutput"]["additionalContext"]

    def claude(self, command: str, ms: float, *, cwd: Path | None = None, session: str = "s1",
               output: str = "", event: str = "PostToolUse", task: str | None = None,
               **tool_input) -> subprocess.CompletedProcess:
        self.calls += 1
        payload = {
            "session_id": session, "transcript_path": "/dev/null", "cwd": str(cwd or self.repo),
            "permission_mode": "bypassPermissions", "hook_event_name": event, "tool_name": "Bash",
            "tool_input": {"command": command, "description": "run", **tool_input},
            "tool_use_id": f"toolu_{self.calls}", "duration_ms": ms,
        }
        if event == "PostToolUseFailure":
            payload |= {"error": f"Exit code 1\n{output}", "is_interrupt": False}
        else:
            payload["tool_response"] = {"stdout": "", "stderr": output, "interrupted": False}
            if task:  # Claude 2.1's Bash output while the command runs on in the background
                payload["tool_response"]["backgroundTaskId"] = task
        return self.hook(payload)

    def codex(self, event: str, command: str, call: str, output: str = "") -> subprocess.CompletedProcess:
        payload = {
            "session_id": "019a-codex", "turn_id": "t1", "transcript_path": None, "cwd": str(self.repo),
            "hook_event_name": event, "model": "gpt", "permission_mode": "default",
            "tool_name": "Bash", "tool_input": {"command": command}, "tool_use_id": call,
        }
        if event == "PostToolUse":
            payload["tool_response"] = output
        return self.hook(payload)


class CommandTimeTests(HookCase):
    def test_claude_agent_is_told_how_long_the_command_took(self) -> None:
        self.assertEqual("octo-lite: this command took 1.2s.", self.told(self.claude("ls", 1234)))
        self.assertEqual("octo-lite: this command took 2m 05s.", self.told(self.claude("ls", 125000)))

    def test_failed_claude_command_is_told_too(self) -> None:
        line = self.told(self.claude("false", 800, event="PostToolUseFailure"), "PostToolUseFailure")
        self.assertEqual("octo-lite: this command took 0.8s.", line)

    def test_codex_agent_is_told_from_its_start_stamp(self) -> None:
        pre = self.codex("PreToolUse", "sleep 0.3", "call_1")
        self.assertEqual((0, ""), (pre.returncode, pre.stdout), "the start stamp tells nothing")
        time.sleep(0.3)
        line = self.told(self.codex("PostToolUse", "sleep 0.3", "call_1", "ok"))
        took = re.fullmatch(r"octo-lite: this command took (\S+)\.", line)
        self.assertTrue(took, line)
        self.assertGreaterEqual(seconds(took.group(1)), 0.3)

    def test_background_command_gets_no_line(self) -> None:
        result = self.claude("sleep 100", 12, run_in_background=True, task="b7k2q")
        self.assertEqual((0, ""), (result.returncode, result.stdout))

    def test_command_still_running_when_its_call_returns_gets_no_line_and_no_record(self) -> None:
        moved = self.claude("python3 -m unittest", 120000, task="b9x4m")  # timed out, moved on
        self.codex("PreToolUse", "python3 -m unittest", "call_2")
        outlived = self.codex(  # Codex 0.166 unified exec past its yield
            "PostToolUse", "python3 -m unittest", "call_2",
            "Chunk ID: 5c1e\nWall time: 10.0012 seconds\nProcess running with session ID 81\n"
            "Original token count: 4\nOutput:\nrunning 12 tests\n")
        for result in (moved, outlived):
            self.assertEqual((0, ""), (result.returncode, result.stdout))
        self.assertEqual([], list((self.state / "octo-lite/command-time").glob("*.json")))

    def test_records_older_than_a_week_are_dropped_when_a_session_starts(self) -> None:
        store = self.state / "octo-lite/command-time"
        store.mkdir(parents=True)
        old, stamp, recent = store / "old.json", store / "call_9.start", store / "recent.json"
        for path, days in ((old, 8), (stamp, 8), (recent, 1)):
            path.write_text("{}")
            os.utime(path, (time.time() - days * 86400,) * 2)
        self.told(self.claude("ls", 10, session="fresh"))
        self.assertEqual({"fresh.json", "recent.json"}, {p.name for p in store.iterdir()})


class BoxLockTests(HookCase):
    """A real flock holder fixture: another job holds heavy.lock a while."""

    def hold_lock(self) -> Path:
        lock = self.state / "octo-lite" / "heavy.lock"
        lock.parent.mkdir(parents=True)
        holder = subprocess.Popen(["flock", str(lock), "sleep", "1.2"])
        self.addCleanup(holder.wait)
        while subprocess.run(["flock", "-n", str(lock), "true"]).returncode == 0:
            time.sleep(0.02)
        return lock

    def run_command(self, command: str) -> tuple[float, str]:
        start = time.monotonic()
        done = subprocess.run(["sh", "-c", command], capture_output=True, text=True, env=self.env)
        return (time.monotonic() - start) * 1000, done.stdout + done.stderr

    def test_reported_wait_is_told_apart_from_the_run(self) -> None:
        command = f"flock --verbose {self.hold_lock()} sleep 0.1"
        ms, output = self.run_command(command)
        line = self.told(self.claude(command, ms, output=output))
        told = re.fullmatch(r"octo-lite: this command waited (\S+) for the box lock, then ran (\S+)\.", line)
        self.assertTrue(told, line)
        waited, ran = map(seconds, told.groups())
        self.assertGreaterEqual(waited, 0.5)
        self.assertLess(ran, waited)

    def test_unreported_wait_is_named_with_the_way_to_report_it(self) -> None:
        command = f"flock {self.hold_lock()} sleep 0.1"
        ms, output = self.run_command(command)
        line = self.told(self.claude(command, ms, output=output))
        told = re.fullmatch(r"octo-lite: this command took (\S+), including its wait for the box lock; "
                            r"take the lock with flock --verbose to tell the wait apart\.", line)
        self.assertTrue(told, line)
        self.assertGreaterEqual(seconds(told.group(1)), 0.5)


class SlowLoopTests(HookCase):
    SUITE = "python3 -m unittest"

    def edit(self, name: str = "app.py") -> None:
        path = self.repo / name
        path.write_text(path.read_text() + "y = 2\n" if path.exists() else "z = 3\n")

    def test_slow_rerun_after_an_edit_is_warned(self) -> None:
        self.edit()  # a file already changed before the first run
        self.assertNotIn(LOOP, self.told(self.claude(self.SUITE, 70000)))
        self.edit()  # changed again: its status is unchanged, its content is not
        line = self.told(self.claude(f"  {self.SUITE}\n", 75000))
        self.assertEqual(
            "octo-lite: this command took 1m 15s. Slow iteration loop: you have run this command"
            " 2 times this session, 2m 25s in all. Run only the tests for what you touched,"
            " and the full suite once, on the final head.", line)
        self.edit("new_test.py")
        self.assertIn("3 times this session, 3m 35s in all", self.told(self.claude(self.SUITE, 70000)))

    def test_fast_run_between_slow_runs_keeps_the_loop(self) -> None:
        self.told(self.claude(self.SUITE, 70000))
        self.edit()
        self.told(self.claude(self.SUITE, 3000))  # say, an import error
        self.edit()
        self.assertIn("3 times this session, 2m 23s in all", self.told(self.claude(self.SUITE, 70000)))

    def test_slow_rerun_with_no_edit_is_not_warned(self) -> None:
        self.told(self.claude(self.SUITE, 70000))
        self.assertEqual("octo-lite: this command took 1m 10s.", self.told(self.claude(self.SUITE, 70000)))

    def test_fast_rerun_after_an_edit_is_not_warned(self) -> None:
        self.told(self.claude(self.SUITE, 5000))
        self.edit()
        self.assertEqual("octo-lite: this command took 5.0s.", self.told(self.claude(self.SUITE, 5000)))

    def test_long_reported_wait_with_a_brief_run_is_not_slow(self) -> None:
        command = f"flock --verbose {self.state}/octo-lite/heavy.lock {self.SUITE}"
        wait = "flock: getting lock took 65.000000 seconds\nflock: executing python3\n"
        self.told(self.claude(command, 70000, output=wait))
        self.edit()
        line = self.told(self.claude(command, 70000, output=wait))
        self.assertEqual("octo-lite: this command waited 1m 05s for the box lock, then ran 5.0s.", line)

    def test_outside_a_repository_or_another_session_is_no_loop(self) -> None:
        elsewhere = self.tmp / "plain"
        elsewhere.mkdir()
        self.told(self.claude(self.SUITE, 70000, cwd=elsewhere))
        (elsewhere / "f").write_text("x")
        self.assertNotIn(LOOP, self.told(self.claude(self.SUITE, 70000, cwd=elsewhere)))
        self.told(self.claude(self.SUITE, 70000, session="a"))
        self.edit()
        self.assertNotIn(LOOP, self.told(self.claude(self.SUITE, 70000, session="b")))


class InformOnlyTests(HookCase):
    def test_warned_rerun_still_only_informs(self) -> None:
        self.told(self.claude(SlowLoopTests.SUITE, 70000))
        (self.repo / "app.py").write_text("x = 2\n")
        result = self.claude(SlowLoopTests.SUITE, 70000, event="PostToolUseFailure", output="FAILED")
        self.assertIn(LOOP, self.told(result, "PostToolUseFailure"))

    def test_hook_leaves_the_agents_git_index_alone(self) -> None:
        """git status refreshes and rewrites a stale index under index.lock,
        which fails the agent's own concurrent git add or commit."""
        app, index = self.repo / "app.py", self.repo / ".git/index"
        stamp = app.stat().st_mtime_ns - 5 * 10**9
        os.utime(app, ns=(stamp, stamp))  # stat changed, content not: the index is stale
        before = index.stat()
        self.told(self.claude(SlowLoopTests.SUITE, 70000))
        after = index.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))

    def test_hook_that_cannot_keep_its_records_adds_nothing(self) -> None:
        self.state.write_text("not a directory")
        for result in (self.claude("ls", 1234), self.codex("PreToolUse", "ls", "c1"),
                       self.codex("PostToolUse", "ls", "c1"), self.hook("not json")):
            self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))


class HooksInformRuleTests(HookCase):
    """Project rule #acceptance-hooks-inform-rule: every hook octo-lite
    registers, read from the settings the installer writes, only informs."""

    def test_every_registered_hook_only_informs(self) -> None:
        prefix = self.tmp / "prefix"
        done = subprocess.run([str(INSTALLER), "--prefix", str(prefix)], capture_output=True,
                              text=True, env=self.env, stdin=subprocess.DEVNULL)
        self.assertEqual(0, done.returncode, done.stderr)
        registered = []
        for settings in (prefix / ".claude/settings.json", prefix / ".codex/hooks.json"):
            for event, groups in json.loads(settings.read_text())["hooks"].items():
                registered += [(event, h["command"]) for g in groups for h in g["hooks"]]
        self.assertTrue(registered)
        for event, command in registered:
            self.assertTrue(Path(command).resolve().is_relative_to(ROOT), command)
            payload = {"session_id": "s", "turn_id": "t", "cwd": str(self.repo), "hook_event_name": event,
                       "tool_name": "Bash", "tool_use_id": "u", "tool_input": {"command": "true"},
                       "tool_response": "", "duration_ms": 70000}
            for stdin in (json.dumps(payload), json.dumps(payload), "{"):
                with self.subTest(event=event, stdin=stdin[:20]):
                    result = subprocess.run(["sh", "-c", command], input=stdin, capture_output=True,
                                            text=True, env=self.env)
                    self.assertEqual(0, result.returncode, "exit 2 blocks in Codex PreToolUse")
                    if result.stdout:
                        self.told(result, event)


if __name__ == "__main__":
    unittest.main()
