"""octo-lite's box lock admits a box's heavy jobs into slots counted from its
CPUs and memory, pins each job to its share of the CPUs, caps the jobs naming
a resource, and keeps a job that locks heavy.lock whole safe. Spec:
spec/domains/box-lock.spec.html, every criterion; #acceptance-lock-installed is
proven in tests/test_install_stageshow.py. Real flocks under a temporary
XDG_STATE_HOME; a box of another size fakes the lock's CPU and memory reads."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "scripts" / "octo-lite-lock"
WAIT = re.compile(r"flock: getting lock took ([0-9.]+) seconds\n")
SETTLE = 1.2  # seconds a waiting job is given to start, past its first tries
# The lock run on a box of the given CPUs and GB: its reads faked, each fake
# CPU pinned as a real one, CPU i as i modulo the machine's.
BOX = """
import json, os, sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
spec = spec_from_loader("lock", SourceFileLoader("lock", sys.argv[1]))
lock = module_from_spec(spec)
spec.loader.exec_module(lock)
box = json.loads(sys.argv[2])
lock.cpus = lambda: box["cpus"]
lock.memory = lambda: box["gb"] * 10**9
lock.CPUS = box.get("per_slot", lock.CPUS)
real, pin = os.cpu_count(), os.sched_setaffinity
os.sched_setaffinity = lambda pid, ids: pin(pid, {i % real for i in ids})
sys.exit(lock.main(sys.argv[3:]))
"""
# A heavy job: it records the CPUs it may use, as nproc reads them to size
# its workers, says it runs, and runs until the test ends it.
JOB = 'nproc >"$0.cpus"; touch "$0.ran"; echo ran; until [ -e "$0.end" ]; do sleep 0.02; done'
# A heavy job that leaves a server running as it ends, until the test ends it.
SERVER = '(until [ -e "$0.end" ]; do sleep 0.02; done) & echo $! >"$0.server"; touch "$0.ran"'


def load():
    sys.dont_write_bytecode = True  # no __pycache__ beside the script
    spec = spec_from_loader("lock", SourceFileLoader("lock", str(LOCK)))
    lock = module_from_spec(spec)
    spec.loader.exec_module(lock)
    return lock


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


class BoxLockCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.heavy = self.tmp / "state/octo-lite/heavy.lock"
        env = {k: v for k, v in os.environ.items() if not k.startswith("OMP_")}  # nproc reads them
        self.env = {**env, "XDG_STATE_HOME": str(self.tmp / "state")}
        self.jobs: dict[str, subprocess.Popen] = {}
        self.servers: list[int] = []
        self.addCleanup(self.stop)

    def spawn(self, name: str, argv: list[str]) -> subprocess.Popen:
        with open(self.tmp / f"{name}.out", "w") as out:
            self.jobs[name] = subprocess.Popen(argv, stdout=out, env=self.env)
        return self.jobs[name]

    def start(self, name: str, *lock: str, cpus=16, gb=62, job=JOB, **box) -> subprocess.Popen:
        """Start heavy job name under the box lock of a box of cpus CPUs and gb GB."""
        box = json.dumps({"cpus": cpus, "gb": gb, **box})
        return self.spawn(name, [sys.executable, "-B", "-c", BOX, str(LOCK), box, *lock,
                                 "sh", "-c", job, str(self.tmp / name)])

    def old(self, name: str) -> subprocess.Popen:
        """Start heavy job name the old way, locking heavy.lock whole."""
        self.heavy.parent.mkdir(parents=True, exist_ok=True)
        return self.spawn(name, ["flock", str(self.heavy), "sh", "-c", JOB, str(self.tmp / name)])

    def stop(self) -> None:
        """End every job and wait for its lock to end: a waiting one takes a
        slot as others end, and its job ends at once."""
        for name in self.jobs:
            self.end(name)
        for proc in self.jobs.values():
            proc.wait(30)
        for server in self.servers:
            while alive(server):
                time.sleep(0.02)

    def end(self, name: str) -> None:
        (self.tmp / f"{name}.end").touch()

    def ran(self, *names: str) -> list[str]:
        return [name for name in names if (self.tmp / f"{name}.ran").exists()]

    def wait_ran(self, *names: str, count: int | None = None) -> None:
        count = len(names) if count is None else count
        deadline = time.monotonic() + 10
        while len(self.ran(*names)) < count:
            self.assertLess(time.monotonic(), deadline, f"{count} of {names} never ran")
            time.sleep(0.02)

    def assert_wait(self, *names: str, ran: int) -> None:
        """Exactly ran of names run, the rest waiting."""
        self.wait_ran(*names, count=ran)
        time.sleep(SETTLE)
        self.assertEqual(len(self.ran(*names)), ran)

    def waited(self, name: str) -> float:
        """The wait name's lock printed on its own line, its job's output after it."""
        self.end(name)
        self.jobs[name].wait(10)
        out = (self.tmp / f"{name}.out").read_text()
        wait = WAIT.match(out)
        self.assertTrue(wait, out)
        self.assertEqual(out[wait.end():], "ran\n")
        return float(wait[1])

    def cpus(self, name: str) -> int:
        return int((self.tmp / f"{name}.cpus").read_text())


class SlotsTest(BoxLockCase):
    def test_sizing_table(self):
        # #lock-sizing-table, as a box of that many GB or GiB reads its memory
        lock = load()
        for cpus, gb, slots, share in ((2, 4, 1, 2), (4, 8, 1, 4), (16, 62, 4, 4),
                                       (32, 64, 8, 4), (32, 32, 5, 6)):
            for memory in (gb * 10**9, gb * 2**30):
                with self.subTest(cpus=cpus, memory=memory):
                    self.assertEqual(lock.slots(cpus, memory), slots)
                    self.assertEqual(cpus // lock.slots(cpus, memory), share)

    def test_a_job_waits_for_the_one_slot_and_is_told_its_wait(self):
        # #acceptance-lock-one-slot
        self.start("other", cpus=4, gb=8)
        self.wait_ran("other")
        self.start("mine", cpus=4, gb=8)
        self.assert_wait("mine", ran=0)
        self.end("other")
        self.wait_ran("mine")
        self.assertGreater(self.waited("mine"), SETTLE / 2)

    def test_as_many_jobs_as_slots_all_run_at_once(self):
        # #acceptance-lock-slots: 16 CPUs, 62 GB fit 4
        names = [f"job{i}" for i in range(4)]
        for name in names:
            self.start(name)
        self.wait_ran(*names)

    def test_one_more_job_than_slots_waits_for_one_to_end(self):
        # #acceptance-lock-full
        names = [f"job{i}" for i in range(4)]
        for name in names:
            self.start(name)
        self.wait_ran(*names)
        self.start("more")
        self.assert_wait("more", ran=0)
        self.end("job2")
        self.wait_ran("more")

    def test_memory_bounds_the_slots(self):
        # #acceptance-lock-memory-bound: 16 CPUs fit 4, 12 GB fit 2
        names = [f"job{i}" for i in range(4)]
        for name in names:
            self.start(name, cpus=16, gb=12)
        self.assert_wait(*names, ran=2)

    def test_cpus_bound_the_slots(self):
        # #acceptance-lock-cpu-bound: 30 GB fit 5, 8 CPUs fit 2
        names = [f"job{i}" for i in range(5)]
        for name in names:
            self.start(name, cpus=8, gb=30)
        self.assert_wait(*names, ran=2)

    def test_a_box_smaller_than_a_slot_runs_its_job_on_every_cpu(self):
        # #acceptance-lock-small-box: 2 CPUs, 4 GB
        if os.cpu_count() < 2:
            self.skipTest("a box of 2 CPUs needs 2 real ones")
        self.start("job", cpus=2, gb=4)
        self.wait_ran("job")
        self.assertEqual(self.cpus("job"), 2)

    def test_a_server_the_job_leaves_holds_no_slot(self):
        # #acceptance-lock-background
        self.start("first", cpus=4, gb=8, job=SERVER).wait(10)
        self.servers.append(int((self.tmp / "first.server").read_text()))
        self.start("second", cpus=4, gb=8)
        self.wait_ran("second")
        self.assertTrue(alive(self.servers[0]), "the server still runs")
        self.assertLess(self.waited("second"), 1)

    def test_a_failed_job_fails_the_command_with_its_own_output(self):
        # #acceptance-lock-result, on this machine's own box
        run = subprocess.run([str(LOCK), "sh", "-c", "echo out; echo err >&2; exit 3"],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 3)
        self.assertRegex(run.stdout, rf"\A{WAIT.pattern}out\n\Z")
        self.assertEqual(run.stderr, "err\n")


class ShareTest(BoxLockCase):
    def test_a_job_sizes_its_workers_to_its_share(self):
        # #acceptance-lock-share. Several slots of 4 real CPUs need 8, more
        # than many machines have: the fixture's slot counts 1 CPU, its box
        # this machine's CPUs and 12 GB, so 2 slots.
        box = os.cpu_count()
        if box < 2:
            self.skipTest("2 slots need 2 real CPUs")
        for name in ("one", "two"):
            self.start(name, cpus=box, gb=12, per_slot=1)
        self.wait_ran("one", "two")
        for name in ("one", "two"):
            self.assertEqual(self.cpus(name), box // 2)


class CapTest(BoxLockCase):
    def test_jobs_naming_a_resource_run_only_as_many_as_it_fits(self):
        # #acceptance-lock-cap: 4 slots, the QA database fits 2 captures
        names = [f"capture{i}" for i in range(3)]
        for name in names:
            self.start(name, "--cap", "qa-db=2")
        self.assert_wait(*names, ran=2)
        self.end(self.ran(*names)[0])
        self.wait_ran(*names, count=3)

    def test_a_job_naming_no_resource_takes_a_free_slot_at_once(self):
        # #acceptance-lock-cap-slots
        for name in ("capture0", "capture1"):
            self.start(name, "--cap", "qa-db=2")
        self.wait_ran("capture0", "capture1")
        self.start("suite")
        self.wait_ran("suite")
        self.assertLess(self.waited("suite"), 1)


class OldWayTest(BoxLockCase):
    def test_an_old_job_waits_until_no_heavy_job_runs(self):
        # #acceptance-lock-old-waits: 4 slots, one holding a job
        self.start("mine")
        self.wait_ran("mine")
        self.old("old")
        self.assert_wait("old", ran=0)
        self.end("mine")
        self.wait_ran("old")

    def test_a_job_waits_while_an_old_job_holds_the_box(self):
        # #acceptance-lock-old-holds
        self.old("old")
        self.wait_ran("old")
        self.start("mine")
        self.assert_wait("mine", ran=0)
        self.end("old")
        self.wait_ran("mine")
        self.assertGreater(self.waited("mine"), SETTLE / 2)


if __name__ == "__main__":
    unittest.main()
