"""octo-lite's box lock admits a box's heavy jobs by the CPUs each asks for,
in line, while memory stays free, pins each job to its CPUs and tells it their
count, runs a nested job at once on its outer job's CPUs, caps the jobs naming
a resource, keeps a job that locks heavy.lock whole safe, and is also
box-heavy. Spec: spec/domains/box-lock.spec.html, every criterion, one test
each. Real flocks under a temporary XDG_STATE_HOME; the lock's CPU count and
free memory are faked, never the box's."""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_install_stageshow import CloneCase

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "scripts" / "octo-lite-lock"
ALIAS = ROOT / "scripts" / "box-heavy"
WAIT = re.compile(r"flock: getting lock took ([0-9.]+) seconds\n")
SETTLE = 1.2  # seconds a waiting job is given to run if it wrongly would, past its first tries
REAL = os.cpu_count()
# The lock run on a box of argv[2] CPUs with the free memory in meminfo file
# argv[3], each fake CPU pinned as a real one, CPU i as i modulo the machine's.
BOX = """
import os, sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
spec = spec_from_loader("lock", SourceFileLoader("lock", sys.argv[1]))
lock = module_from_spec(spec)
spec.loader.exec_module(lock)
lock.cpus = lambda: int(sys.argv[2])
lock.MEMINFO = Path(sys.argv[3])
real, pin = os.cpu_count(), os.sched_setaffinity
os.sched_setaffinity = lambda pid, ids: pin(pid, {i % real for i in ids})
sys.exit(lock.main(sys.argv[4:]))
"""
# A heavy job: it records the CPUs it may use, as nproc reads them to size its
# workers, which they are, and the count it is told, says it runs, and runs
# until the test ends it.
RECORD = ('nproc >"$0.cpus"; sed -n "s/^Cpus_allowed_list:\\s*//p" /proc/self/status >"$0.on"; '
          'echo "${BOX_HEAVY_CORES-}" >"$0.told"; touch "$0.ran"; echo ran')
UNTIL_END = 'until [ -e "$0.end" ]; do sleep 0.02; done'
JOB = f"{RECORD}; {UNTIL_END}"
# A heavy job that leaves a server running as it ends, until the test ends it.
SERVER = '(until [ -e "$0.end" ]; do sleep 0.02; done) & echo $! >"$0.server"; touch "$0.ran"'
# A heavy job that cleans up on Ctrl-C, taking a while, then exits 5.
TRAP = ('trap \'sleep 1; touch "$0.cleaned"; exit 5\' INT; touch "$0.ran"; '
        'until [ -e "$0.end" ]; do sleep 0.02; done')


def ctrl_c_default() -> None:
    """In a spawned child: Ctrl-C at its default, as at a terminal, even
    when the test runner ignores it, as one started with & does."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:  # gone, or exiting as it is read
        return False


class BoxLockCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.box = self.tmp / "state/octo-lite"
        self.meminfo = self.tmp / "meminfo"
        self.set_free(62)
        # nproc reads OMP_*; a suite run under the lock is no outer job here
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("OMP_") and k != "BOX_HEAVY_CORES"}
        self.env = {**env, "XDG_STATE_HOME": str(self.tmp / "state")}
        self.jobs: dict[str, subprocess.Popen] = {}
        self.servers: list[int] = []
        self.addCleanup(self.stop)

    def set_free(self, gb: int) -> None:
        """The faked box has gb GB of memory free."""
        new = self.tmp / "meminfo.new"
        new.write_text(f"MemTotal: {64 * 10**9 // 1024} kB\nMemFree: 1024 kB\n"
                       f"MemAvailable: {gb * 10**9 // 1024} kB\n")
        new.replace(self.meminfo)

    def spawn(self, name: str, argv: list[str], **popen) -> subprocess.Popen:
        """Start argv, its stdout and stderr both to name's .out."""
        with open(self.tmp / f"{name}.out", "w") as out:
            self.jobs[name] = subprocess.Popen(argv, stdout=out, stderr=out, env=self.env, **popen)
        return self.jobs[name]

    def boxed(self, name: str, *ask: str, cpus=16, job=JOB, command=LOCK) -> list[str]:
        """The command line running heavy job name under the box lock of a box of cpus CPUs."""
        return [sys.executable, "-B", "-c", BOX, str(command), str(cpus), str(self.meminfo),
                *ask, "sh", "-c", job, str(self.tmp / name)]

    def start(self, name: str, *ask: str, **box) -> subprocess.Popen:
        return self.spawn(name, self.boxed(name, *ask, **box))

    def old(self, name: str) -> subprocess.Popen:
        """Start heavy job name the old way, locking heavy.lock whole."""
        self.box.mkdir(parents=True, exist_ok=True)
        return self.spawn(name, ["flock", str(self.box / "heavy.lock"), "sh", "-c", JOB,
                                 str(self.tmp / name)])

    def stop(self) -> None:
        """End every job and wait for its lock to end: a waiting one takes its
        CPUs as others end, and its job ends at once."""
        for name in self.jobs:
            self.end(name)
        for proc in self.jobs.values():
            proc.wait(60)
        for server in self.servers:
            while alive(server):
                time.sleep(0.02)

    def end(self, name: str) -> None:
        (self.tmp / f"{name}.end").touch()

    def ran(self, *names: str) -> list[str]:
        return [name for name in names if (self.tmp / f"{name}.ran").exists()]

    def wait_ran(self, *names: str, count: int | None = None) -> None:
        count = len(names) if count is None else count
        deadline = time.monotonic() + 30
        while len(self.ran(*names)) < count:
            self.assertLess(time.monotonic(), deadline, f"{count} of {names} never ran")
            time.sleep(0.02)

    def wait_on(self, name: str, file: str) -> None:
        """Wait until name's lock holds, or waits for, file of the box lock's,
        as /proc/locks lists it: "1: [-> ]FLOCK ADVISORY WRITE pid dev:inode 0 EOF"."""
        path, pid = self.box / file, str(self.jobs[name].pid)
        deadline = time.monotonic() + 30
        while not (path.exists() and any(
                field[-4] == pid and field[-3].endswith(f":{path.stat().st_ino}")
                for field in map(str.split, Path("/proc/locks").read_text().splitlines()))):
            self.assertLess(time.monotonic(), deadline, f"{name} never reached {file}")
            time.sleep(0.02)

    def assert_waits(self, name: str, file: str = "heavy-line.lock") -> None:
        """name's lock has reached file and its job still does not run."""
        self.wait_on(name, file)
        time.sleep(SETTLE)
        self.assertEqual(self.ran(name), [])

    def assert_wait(self, *names: str, ran: int) -> None:
        """Exactly ran of names run, the rest waiting."""
        self.wait_ran(*names, count=ran)
        time.sleep(SETTLE)
        self.assertEqual(len(self.ran(*names)), ran)

    def waited(self, name: str) -> float:
        """The wait name's lock printed on its own line, its job's output after it."""
        self.end(name)
        self.jobs[name].wait(30)
        out = (self.tmp / f"{name}.out").read_text()
        wait = WAIT.match(out)
        self.assertTrue(wait, out)
        self.assertEqual(out[wait.end():], "ran\n")
        return float(wait[1])

    def read(self, name: str, what: str) -> str:
        return (self.tmp / f"{name}.{what}").read_text().strip()

    def cpus(self, name: str) -> int:
        return int(self.read(name, "cpus"))

    def needs(self, real: int) -> None:
        if REAL < real:
            self.skipTest(f"needs {real} real CPUs")


class CoresTest(BoxLockCase):
    def test_a_job_waits_for_cpus_held_by_others_and_is_told_its_wait(self):
        # #acceptance-lock-wait: a box of 4 CPUs, two jobs of 2 holding all
        for name in ("one", "two"):
            self.start(name, "--cores", "2", cpus=4)
        self.wait_ran("one", "two")
        self.start("mine", "--cores", "2", cpus=4)
        self.assert_waits("mine")
        self.end("one")
        self.wait_ran("mine")
        self.assertGreater(self.waited("mine"), SETTLE / 2)

    def test_jobs_asking_for_no_more_cpus_than_the_box_has_all_run_at_once(self):
        # #acceptance-lock-many: 16 CPUs, 4 + 4 + 4 + 2 + 1 + 1 asked, none ending
        asks = {"suite0": (), "suite1": (), "suite2": ("--cores", "4"), "build": ("--cores", "2"),
                "install0": ("--cores", "1"), "install1": ("--cores", "1")}
        for name, ask in asks.items():
            self.start(name, *ask)
        self.wait_ran(*asks)

    def test_a_job_waits_until_as_many_cpus_as_it_asks_for_are_free(self):
        # #acceptance-lock-full: 16 CPUs, 14 held, 4 asked
        for name in ("seven0", "seven1"):
            self.start(name, "--cores", "7")
        self.wait_ran("seven0", "seven1")
        self.start("mine")
        self.assert_waits("mine")
        self.end("seven1")
        self.wait_ran("mine")

    def test_the_first_in_line_keeps_cpus_as_they_free_and_runs_before_jobs_behind(self):
        # #acceptance-lock-in-turn: 4 CPUs, each held by a job of 1; a job of 4
        # first in line, two jobs of 1 behind it
        held = [f"held{cpu}" for cpu in range(4)]
        for name in held:  # in turn, so held<cpu> holds CPU cpu
            self.start(name, "--cores", "1", cpus=4)
            self.wait_ran(name)
        self.start("big", "--cores", "4", cpus=4)
        self.wait_on("big", "heavy-line.lock")
        for name in ("small0", "small1"):
            self.start(name, "--cores", "1", cpus=4)
            self.wait_on(name, "heavy-line.lock")
        for cpu, name in enumerate(held):
            self.end(name)
            self.wait_on("big", f"heavy-cpu-{cpu}.lock")
        self.wait_ran("big")
        self.assertEqual(self.ran("small0", "small1"), [])
        self.end("big")
        self.wait_ran("small0", "small1")

    def test_the_first_in_line_waits_for_free_memory_while_another_job_runs(self):
        # #acceptance-lock-memory: 16 CPUs, 4 held, 5 GB free
        self.start("other")
        self.wait_ran("other")
        self.set_free(5)
        self.start("mine")
        self.assert_waits("mine")
        self.set_free(7)
        self.wait_ran("mine")

    def test_a_job_runs_with_little_memory_free_when_no_other_heavy_job_runs(self):
        # #acceptance-lock-memory-alone: 2 GB free, never more
        self.set_free(2)
        self.start("mine")
        self.wait_ran("mine")

    def test_a_box_of_fewer_cpus_than_asked_runs_the_job_on_every_cpu(self):
        # #acceptance-lock-small-box: a box of 2 CPUs, 4 asked
        self.needs(2)
        self.start("job", cpus=2)
        self.wait_ran("job")
        self.assertEqual((self.cpus("job"), self.read("job", "told")), (2, "2"))

    def test_a_server_the_job_leaves_holds_no_cpu(self):
        # #acceptance-lock-background: a box of 4 CPUs, all asked
        self.start("first", "--cores", "4", cpus=4, job=SERVER).wait(30)
        self.servers.append(int(self.read("first", "server")))
        self.start("second", "--cores", "4", cpus=4)
        self.wait_ran("second")
        self.assertTrue(alive(self.servers[0]), "the server still runs")

    def test_a_failed_job_fails_the_command_with_its_own_output(self):
        # #acceptance-lock-result, on this machine's own CPUs and memory
        run = subprocess.run([str(LOCK), "sh", "-c", "echo out; echo err >&2; exit 3"],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 3)
        self.assertEqual(run.stdout, "out\n")
        self.assertRegex(run.stderr, rf"\A{WAIT.pattern}err\n\Z")

    def test_a_job_sizes_its_workers_to_the_cpus_it_asked_for(self):
        # #acceptance-lock-cores: a box of 16 CPUs, 3 asked
        self.needs(3)
        self.start("job", "--cores", "3")
        self.wait_ran("job")
        self.assertEqual(self.cpus("job"), 3)

    def test_a_job_sizes_its_workers_to_the_count_it_is_told(self):
        # #acceptance-lock-cores-told: a box of 16 CPUs, 6 asked
        self.start("job", "--cores", "6")
        self.wait_ran("job")
        self.assertEqual(self.read("job", "told"), "6")

    def test_a_job_naming_no_number_runs_on_what_a_full_suite_needs(self):
        # #acceptance-lock-default: a box of 16 CPUs, a full suite needing 4
        self.start("job")
        self.wait_ran("job")
        self.assertEqual((self.cpus("job"), self.read("job", "told")), (min(4, REAL), "4"))

    def test_a_heavy_job_inside_a_heavy_job_runs_at_once_on_its_cpus(self):
        # #acceptance-lock-nested: a box of this machine's CPUs, the outer job
        # holding 2, others the rest, the inner job asking for 4
        self.needs(3)
        self.start("others", "--cores", str(REAL - 2), cpus=REAL)
        self.wait_ran("others")
        inner = shlex.join(self.boxed("inner", cpus=REAL))
        self.addCleanup(self.end, "inner")
        self.start("outer", "--cores", "2", cpus=REAL,
                   job=f'{RECORD}; {inner} >"$0.inner.out" 2>&1; {UNTIL_END}')
        self.wait_ran("outer", "inner")
        self.assertEqual((self.cpus("inner"), self.read("inner", "told")), (2, "2"))
        self.assertEqual(self.read("inner", "on"), self.read("outer", "on"))


class CapTest(BoxLockCase):
    def test_jobs_naming_a_resource_run_only_as_many_as_it_fits(self):
        # #acceptance-lock-cap: 16 CPUs fit 4 captures, the QA database 2
        names = [f"capture{i}" for i in range(3)]
        for name in names:
            self.start(name, "--cap", "qa-db=2")
        self.assert_wait(*names, ran=2)
        self.end(self.ran(*names)[0])
        self.wait_ran(*names, count=3)

    def test_a_job_naming_no_resource_takes_free_cpus_at_once(self):
        # #acceptance-lock-cap-free: 2 captures run, a third waits, 8 CPUs free
        names = [f"capture{i}" for i in range(3)]
        for name in names:
            self.start(name, "--cap", "qa-db=2")
        self.assert_wait(*names, ran=2)
        self.start("suite")
        self.wait_ran("suite")


class AliasTest(BoxLockCase):
    def test_box_heavy_waits_as_the_lock_does_then_runs_on_the_cpus_asked(self):
        # #acceptance-lock-alias: a box of 4 CPUs, 2 held, 3 asked
        self.needs(3)
        self.start("other", "--cores", "2", cpus=4)
        self.wait_ran("other")
        self.start("mine", "--cores", "3", cpus=4, command=ALIAS)
        self.assert_waits("mine")
        self.end("other")
        self.wait_ran("mine")
        self.assertEqual((self.cpus("mine"), self.read("mine", "told")), (3, "3"))


class OldWayTest(BoxLockCase):
    def test_an_old_job_waits_until_no_heavy_job_runs(self):
        # #acceptance-lock-old-waits: 16 CPUs, 4 held
        self.start("mine")
        self.wait_ran("mine")
        self.old("old")
        self.assert_waits("old", "heavy.lock")
        self.end("mine")
        self.wait_ran("old")

    def test_a_job_waits_while_an_old_job_holds_the_box(self):
        # #acceptance-lock-old-holds
        self.old("old")
        self.wait_ran("old")
        self.start("mine")
        self.assert_waits("mine", "heavy.lock")
        self.end("old")
        self.wait_ran("mine")
        self.assertGreater(self.waited("mine"), SETTLE / 2)


class InstallTest(CloneCase):
    def test_install_again_links_the_lock_under_both_names(self):
        # #acceptance-lock-installed
        for _ in range(2):
            install = self.run_installer()
            self.assertEqual(install.returncode, 0, install.stderr)
        for name in ("octo-lite-lock", "box-heavy"):
            with self.subTest(name=name):
                self.assertEqual(os.path.realpath(self.prefix / ".local/bin" / name),
                                 str(self.clone / "scripts/octo-lite-lock"))

    def test_the_check_names_a_box_heavy_of_the_boxs_own_with_its_fix(self):
        # #acceptance-lock-alias-occupied: install leaves it, the check names it
        own = self.prefix / ".local/bin/box-heavy"
        own.parent.mkdir(parents=True)
        own.write_text("#!/bin/sh\n")
        install = self.run_installer()
        self.assertEqual(install.returncode, 0, install.stderr)
        self.assertIn(f"skipped: {own} (occupied by file)", install.stdout)
        self.assertEqual(own.read_text(), "#!/bin/sh\n")
        check = self.run_installer("--check")
        self.assertNotEqual(check.returncode, 0)
        self.assertEqual(check.stderr.splitlines(),
                         [f"bad link: {own} (occupied by file); fix: move it aside, then {self.fix}"])


class SignalTest(BoxLockCase):
    def test_ctrl_c_is_left_to_the_job(self):
        # #lock-recipe: ends as the job ended, a job cleaning up on Ctrl-C too
        proc = self.spawn("job", [str(LOCK), "sh", "-c", TRAP, str(self.tmp / "job")],
                          start_new_session=True, preexec_fn=ctrl_c_default)
        self.wait_ran("job")
        os.killpg(proc.pid, signal.SIGINT)  # Ctrl-C, to the command's process group
        self.assertEqual(proc.wait(10), 5)
        self.assertTrue((self.tmp / "job.cleaned").exists(), "the job finished its cleanup")
        self.assertNotIn("Traceback", (self.tmp / "job.out").read_text())

    def test_a_script_stops_on_a_job_ended_by_ctrl_c(self):
        # #lock-recipe: ends as the job ended, killed by Ctrl-C too, so bash
        # stops its script as with no wrapper
        script = ('"$0" sh -c \'touch "$0.ran"; exec sleep 5\' "$1"; '
                  '"$0" true; echo second-ran')
        proc = self.spawn("job", ["bash", "-c", script, str(LOCK), str(self.tmp / "job")],
                          start_new_session=True, preexec_fn=ctrl_c_default)
        self.wait_ran("job")
        os.killpg(proc.pid, signal.SIGINT)  # Ctrl-C, to the script's process group
        self.assertEqual(proc.wait(10), -signal.SIGINT)
        self.assertNotIn("second-ran", (self.tmp / "job.out").read_text())

    def test_a_job_killed_by_sigkill_kills_the_command_by_it_too(self):
        # #lock-recipe: ends as the job ended, by a signal whose disposition
        # no one can set too: SIGKILL, and 32, which glibc keeps for itself
        for sig in (signal.SIGKILL, 32):
            with self.subTest(sig=sig):
                run = subprocess.run([str(LOCK), "sh", "-c", f"kill -{int(sig)} $$"],
                                     capture_output=True, text=True, env=self.env)
                self.assertEqual(run.returncode, -sig)
                self.assertRegex(run.stderr, rf"\A{WAIT.pattern}\Z")

    def test_a_background_job_still_ignores_ctrl_c(self):
        # #lock-recipe: a script's background job ignores Ctrl-C, as with no wrapper
        job = 'grep "^SigIgn" /proc/$$/status >"$0.ignored"'
        self.spawn("job", ["sh", "-c", '"$0" sh -c "$1" "$2" & wait',
                           str(LOCK), job, str(self.tmp / "job")]).wait(10)
        ignored = int((self.tmp / "job.ignored").read_text().split()[1], 16)
        self.assertTrue(ignored & 1 << signal.SIGINT - 1, "the job ignores SIGINT")


if __name__ == "__main__":
    unittest.main()
