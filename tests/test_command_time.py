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
# skillfile and npm stubbed unreachable: installer runs never fetch.
OFFLINE = f"{ROOT / 'tests' / 'offline-bin'}:{os.environ['PATH']}"
LOOP = "Slow iteration loop"
# On PYTHONPATH, a disk of the fullness FAKE_DISK holds (fixtures/disk).
FAKE_DISK = ROOT / "tests" / "fixtures" / "disk"
# Herdr, as herdr-say reaches it: each prompt's target and text, one JSON line.
FAKE_HERDR = """#!/usr/bin/env bash
[[ "$1 $2" != "agent prompt" ]] || jq -nc --arg pane "$3" --arg text "$4" '[$pane, $text]' >>"$FAKE_SENT"
echo '{"result":{}}'
"""
# du over a box: sizes in KiB, children first, as du prints them, after
# FAKE_DU_SLEEP seconds; it logs its niceness and arguments.
FAKE_DU = """#!/usr/bin/env bash
echo "$(nice) $*" >>"$FAKE_DU_LOG"
sleep "${FAKE_DU_SLEEP:-0}"
printf '%s\\t%s\\n' 31457280 /home/admin/worktrees/lane-a 31457300 /home/admin/worktrees \\
  10485760 /home/admin/.cache/octo-lite 10485800 /home/admin/.cache \\
  41943200 /home/admin 41943300 /home 4 /srv/small 94371840 /
"""
SECONDS = re.compile(r"(?:(\d+)m )?([0-9.]+)s")


def problems(run):
    """The problems a run names, but Stageshow's and the recorder's: offline,
    neither is fetched."""
    return [line for line in run.stderr.splitlines()
            if "; fix: " in line
            and not line.startswith(("Stageshow not installed", "prototype-video not installed"))]


def seconds(text: str) -> float:
    minutes, secs = SECONDS.fullmatch(text).groups()
    return int(minutes or 0) * 60 + float(secs)


class HookCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.state = self.tmp / "state"
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for name, text in (("herdr", FAKE_HERDR), ("du", FAKE_DU)):
            (bindir / name).write_text(text)
            (bindir / name).chmod(0o755)
        self.disk, self.sent, self.du = self.tmp / "disk", self.tmp / "sent.jsonl", self.tmp / "du.log"
        self.disk.write_text("50")
        self.env = {**os.environ, "XDG_STATE_HOME": str(self.state), "HOME": str(self.tmp),
                    "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_DISK": str(self.disk),
                    "PYTHONPATH": os.pathsep.join(filter(None, (str(FAKE_DISK), os.environ.get("PYTHONPATH")))),
                    "FAKE_SENT": str(self.sent), "FAKE_DU_LOG": str(self.du)}
        self.env.pop("HERDR_SESSION", None)
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
    """A real flock holder fixture, another job holding heavy.lock a while,
    and real searches naming the box lock or quoting its wait line."""

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

    def test_command_naming_the_box_lock_is_told_nothing_of_it(self) -> None:
        command = f"grep -rn heavy.lock {self.repo}"
        _, output = self.run_command(command)
        self.assertEqual("octo-lite: this command took 1.2s.",
                         self.told(self.claude(command, 1234, output=output)))

    def test_wait_line_quoted_inside_a_longer_line_reports_no_wait(self) -> None:
        (self.repo / "notes.py").write_text('WAIT = "flock: getting lock took 65.000000 seconds"\n')
        command = f"grep -rn 'getting lock took' {self.repo}"
        _, output = self.run_command(command)
        self.assertIn("flock: getting lock took 65.000000 seconds", output)
        self.assertEqual("octo-lite: this command took 1m 10s.",
                         self.told(self.claude(command, 70000, output=output)))
        self.codex("PreToolUse", command, "call_q")
        line = self.told(self.codex("PostToolUse", command, "call_q", f"Output:\n{output}"))
        self.assertRegex(line, r"^octo-lite: this command took \S+\.$")


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
        fast = self.told(self.claude(self.SUITE, 3000))  # say, an import error
        self.assertEqual("octo-lite: this command took 3.0s.", fast)
        self.edit()
        self.assertIn("3 times this session, 2m 23s in all", self.told(self.claude(self.SUITE, 70000)))

    def test_edit_before_a_fast_run_is_not_since_the_last_run(self) -> None:
        self.told(self.claude(self.SUITE, 70000))
        self.edit()
        self.told(self.claude(self.SUITE, 3000))
        self.assertEqual("octo-lite: this command took 1m 10s.", self.told(self.claude(self.SUITE, 70000)))

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


class DiskWarningTests(HookCase):
    """spec/domains/disk.spec.html#warning, every acceptance-disk-warn-*
    criterion: the fixture disk (fixtures/disk) filled past each level by a
    lane agent's command; the operator's pane gets herdr-say's prompt."""

    FOLDERS = ("Folders holding the most: /home/admin/worktrees/lane-a 30.0 GiB,"
               " /home/admin/.cache/octo-lite 10.0 GiB, /srv/small 4.0 KiB.")
    TAIL = "Nothing was removed; each lane frees only what it made."

    def setUp(self) -> None:
        super().setUp()
        self.operator()

    def operator(self, session: str | None = None, pane: str = "w9:p1") -> None:
        state = self.state / "octo-lite" / ("sessions/" + session if session else "")
        state.mkdir(parents=True, exist_ok=True)
        (state / "operator.toml").write_text(f'pane = "{pane}"\n')

    def run_at(self, full: int, **env: str) -> str:
        """A lane agent's command, run with the disk at full%: the line it is told."""
        self.disk.write_text(str(full))
        saved, self.env = self.env, {**self.env, **env}
        try:
            return self.told(self.claude("npm ci", 1234))
        finally:
            self.env = saved

    def messages(self, count: int, within: float = 10.0) -> list:
        """The operator's messages, once there are count of them, else at the bound."""
        end = time.monotonic() + within
        while time.monotonic() < end:
            sent = [json.loads(line) for line in self.sent.read_text().splitlines()] if self.sent.exists() else []
            if len(sent) >= count:
                break
            time.sleep(0.05)
        time.sleep(0.3)  # and no more after it
        return [json.loads(line) for line in self.sent.read_text().splitlines()] if self.sent.exists() else []

    def warning(self, full: int, free: str) -> str:
        return f"octo-lite disk warning: the box's disk is {full}% full, {free} free. {self.FOLDERS} {self.TAIL}"

    def test_operator_is_told_once_the_disk_passes_85(self) -> None:
        # acceptance-disk-warn-first: df's Use%, 5% kept for root.
        self.assertEqual("octo-lite: this command took 1.2s.", self.run_at(84))
        self.assertEqual([], self.messages(1, within=1))
        self.assertEqual("octo-lite: this command took 1.2s.", self.run_at(86))
        self.assertEqual([["w9:p1", self.warning(86, "13.3 GiB")]], self.messages(1))
        self.assertRegex(self.du.read_text(), r"^[1-9]\d* -x\S* .*/$", "a niced du of the root filesystem")

    def test_operator_is_told_no_more_while_the_disk_stays_under_90(self) -> None:
        # acceptance-disk-warn-once.
        self.run_at(86)
        for full in (86, 87, 89, 85):
            self.run_at(full)
        self.assertEqual(1, len(self.messages(2, within=1.5)))

    def test_operator_is_told_once_more_past_90(self) -> None:
        # acceptance-disk-warn-second.
        self.run_at(86)
        self.messages(1)
        self.run_at(91)
        self.run_at(93)
        self.assertEqual([["w9:p1", self.warning(86, "13.3 GiB")], ["w9:p1", self.warning(91, "8.6 GiB")]],
                         self.messages(3, within=2))

    def test_a_jump_past_both_levels_is_one_message(self) -> None:
        # warning-levels: one message, both levels told.
        self.run_at(92)
        self.run_at(86)
        self.assertEqual([["w9:p1", self.warning(92, "7.6 GiB")]], self.messages(2, within=1.5))

    def test_each_level_is_told_again_once_the_disk_was_back_under_80(self) -> None:
        # acceptance-disk-warn-again.
        self.run_at(91)
        self.messages(1)
        self.run_at(80)
        self.run_at(86)
        self.assertEqual(1, len(self.messages(2, within=1.5)), "re-armed before the disk was under 80%")
        self.run_at(79)
        self.run_at(86)
        self.assertEqual([self.warning(91, "8.6 GiB"), self.warning(86, "13.3 GiB")],
                         [text for _, text in self.messages(2)])

    def test_the_check_starts_no_process_until_a_level_is_newly_reached(self) -> None:
        # warning-check: the read is cheap. Under 85%, rearming included, and
        # past a level already told, the hook starts no process: one would cost
        # every command of every agent.
        spawns = self.tmp / "spawns.log"
        self.run_at(86)
        self.messages(1)
        for full in (87, 50, 82, 79):
            self.run_at(full, FAKE_SPAWNS=str(spawns))
        self.assertFalse(spawns.exists(), spawns.read_text() if spawns.exists() else "")
        self.run_at(86)
        self.assertEqual(2, len(self.messages(2)), "not told again after the disk was under 80%")

    def test_a_told_level_outlasts_the_weekly_record_sweep(self) -> None:
        # warning-levels: told once until the disk is under 80%, however long
        # it stays full; a new session's sweep of week-old records keeps it.
        self.run_at(86)
        self.messages(1)
        old = time.time() - 8 * 86400
        for record in (self.state / "octo-lite/command-time").iterdir():
            os.utime(record, (old, old))
        self.told(self.claude("ls", 10, session="s-new"))
        self.assertEqual(1, len(self.messages(2, within=1.5)), "told again once its record was a week old")

    def test_concurrent_agents_tell_a_level_once(self) -> None:
        # warning-levels: once per session, however many agents cross it at once.
        self.disk.write_text("86")
        payload = {"session_id": "s", "cwd": str(self.repo), "hook_event_name": "PostToolUse",
                   "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": ""},
                   "duration_ms": 10}
        hooks = [subprocess.Popen([str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                  env=self.env) for _ in range(6)]
        for n, hook in enumerate(hooks):
            hook.communicate(json.dumps({**payload, "session_id": f"s{n}", "tool_use_id": f"u{n}"}))
        self.assertEqual(1, len(self.messages(2, within=2)))

    def test_each_session_has_its_operator_and_levels(self) -> None:
        # warning-levels: per session, the operator in its operator.toml.
        self.operator("s2", pane="w4:p7")
        self.run_at(86)
        self.run_at(86, HERDR_SESSION="s2")
        self.assertEqual(["w4:p7", "w9:p1"], sorted(pane for pane, _ in self.messages(2)))

    def test_with_no_operator_the_agent_is_told_beside_its_result(self) -> None:
        # acceptance-disk-warn-no-operator, warning-no-operator.
        (self.state / "octo-lite/operator.toml").unlink()
        told = (f"octo-lite: this command took 1.2s. octo-lite disk warning: the box's disk is 86% full,"
                f" 13.3 GiB free. {self.TAIL}")
        self.assertEqual(told, self.run_at(86))
        self.assertEqual("octo-lite: this command took 1.2s.", self.run_at(87))
        self.assertEqual([], self.messages(1, within=1))

    def test_the_warning_only_informs(self) -> None:
        # acceptance-disk-warn-inform, warning-inform: the command's result
        # reaches the agent at once, as without the warning, while the warning
        # names folders; it removes nothing; a failed read adds nothing.
        keep = self.tmp / "scratch" / "tmp.x1"
        keep.mkdir(parents=True)
        (keep / "run.log").write_text("kept")
        started = time.monotonic()
        self.assertEqual("octo-lite: this command took 1.2s.", self.run_at(95, FAKE_DU_SLEEP="3"))
        self.assertLess(time.monotonic() - started, 2.5, "the hook waited on the warning")
        self.assertEqual(1, len(self.messages(1)))
        self.assertEqual("kept", (keep / "run.log").read_text())
        self.disk.write_text("not a number")
        self.assertEqual("octo-lite: this command took 1.2s.", self.told(self.claude("ls", 1234)))


class HooksInformRuleTests(HookCase):
    """Project rule #acceptance-hooks-inform-rule: every hook octo-lite
    registers, read from the settings the installer writes, only informs."""

    def test_every_registered_hook_only_informs(self) -> None:
        prefix = self.tmp / "prefix"
        done = subprocess.run([str(INSTALLER), "--prefix", str(prefix)], capture_output=True, text=True,
                              env={**self.env, "PATH": OFFLINE}, stdin=subprocess.DEVNULL)
        self.assertEqual([], problems(done), done.stderr)
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
