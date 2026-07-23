from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from octo_lite.launch import (
    LANE_ENV_KEYS,
    PROVISION_RECORD_SOURCE,
    GateError,
    LaneProvision,
    _prepare_worktree,
    cleanup_clean_abort,
    default_install_check,
    lane_env_from_record,
    lane_invocation_env,
    provision_lane_worktree,
    run_lane_loop,
    validate_provision_record,
    verify_lane_worktree_reality,
)


def _valid_record(worktree: Path, worktree_root: Path) -> dict:
    return {
        "schema_version": 1,
        "source": PROVISION_RECORD_SOURCE,
        "lane": "issue13",
        "control_repo": str(worktree_root / "control"),
        "worktree": str(worktree),
        "worktree_root": str(worktree_root),
        "repo_slug": "acme/widgets",
        "branch": "octo-lite/issue13",
        "starting_head": "0" * 40,
        "resolver_root": str(worktree),
        "install_check": "clean",
        "provisioned_at": "2026-07-23T00:00:00+00:00",
    }

ROOT = Path(__file__).resolve().parents[1]
REPO_SLUG = "acme/widgets"
REMOTE = f"https://github.com/{REPO_SLUG}.git"


def _init_control_repo(repo: Path, *, remote: str = REMOTE) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
    shutil.copy(ROOT / "roles.toml", repo / "roles.toml")
    shutil.copytree(ROOT / "roles", repo / "roles")
    (repo / "AGENTS.md").write_text("# Target\n")
    (repo / "CLAUDE.md").write_text("# Target\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


class LaneProvisionTests(unittest.TestCase):
    # gh#8 host-provisioned isolated worktree (spec launch-provisioning-trust-root,
    # workspace-admission-provisions, launch-provision-verify,
    # launch-provision-exclusivity, workspace-provision-idempotent,
    # launch-provision-record, launch-provision-record-out-of-tree,
    # launch-provision-record-schema, launch-provision-env-seam).

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.base = base
        self.control_repo = base / "control"
        self.worktree_root = base / "worktrees"
        self.head = _init_control_repo(self.control_repo)
        self.lane = "lane-1"
        self.branch = "octo-lite/lane-1"
        self.worktree = self.worktree_root / self.lane

    def provision(self, **overrides):
        values = dict(
            control_repo=self.control_repo,
            worktree_root=self.worktree_root,
            worktree=self.worktree,
            lane=self.lane,
            branch=self.branch,
            head=self.head,
            repo_slug=REPO_SLUG,
            install_check=lambda repo: "clean",
            now=lambda: "2026-07-21T00:00:00+00:00",
        )
        values.update(overrides)
        return provision_lane_worktree(**values)

    # RED-1
    def test_lane_provision_creates_worktree(self) -> None:
        result = self.provision()
        self.assertTrue(self.worktree.is_dir())
        self.assertEqual(self.head, _git(self.worktree, "rev-parse", "HEAD"))
        self.assertEqual(self.branch, _git(self.worktree, "branch", "--show-current"))
        self.assertEqual(self.lane, result.record["lane"])

    # gh#13 backfill: adopt an EXISTING pre-fix hand-created worktree that carries
    # no lane record. `_make_unrecorded_worktree` provisions once then removes the
    # record to model a worktree that predates the record machinery.
    def _make_unrecorded_worktree(self):
        result = self.provision()
        record_path = Path(result.record_path)
        record_path.unlink()
        return record_path

    def test_adopt_existing_writes_record_without_recreating(self) -> None:
        record_path = self._make_unrecorded_worktree()
        head_before = _git(self.worktree, "rev-parse", "HEAD")
        result = self.provision(adopt_existing=True, head=None)
        self.assertTrue(record_path.is_file())
        self.assertEqual(str(self.worktree), result.record["worktree"])
        self.assertEqual(head_before, result.record["starting_head"])
        self.assertEqual(self.branch, result.record["branch"])
        validate_provision_record(result.record)

    def test_adopt_existing_tolerates_and_preserves_mid_delivery_dirty_tree(self) -> None:
        self._make_unrecorded_worktree()
        dirty = self.worktree / "wip.txt"
        dirty.write_text("in progress\n")
        result = self.provision(adopt_existing=True, head=None)
        self.assertTrue(Path(result.record_path).is_file())
        # The uncommitted mid-delivery work is untouched.
        self.assertEqual("in progress\n", dirty.read_text())
        self.assertIn("wip.txt", _git(self.worktree, "status", "--porcelain"))

    def test_adopt_existing_is_idempotent(self) -> None:
        self._make_unrecorded_worktree()
        first = self.provision(adopt_existing=True, head=None)
        # Re-running the same adoption (still no starting commit, record now
        # present) must succeed and yield the same record, not fail HEAD checks.
        second = self.provision(adopt_existing=True, head=None)
        self.assertEqual(first.record["starting_head"], second.record["starting_head"])
        self.assertEqual(first.record["worktree"], second.record["worktree"])
        validate_provision_record(second.record)

    def test_adopt_existing_still_enforces_branch_identity(self) -> None:
        self._make_unrecorded_worktree()
        with self.assertRaises(GateError):
            self.provision(adopt_existing=True, head=None, branch="octo-lite/wrong")

    def test_adopt_existing_rejects_a_missing_worktree(self) -> None:
        absent = self.worktree_root / "absent"
        with self.assertRaises(GateError):
            self.provision(
                adopt_existing=True, head=None, worktree=absent,
                lane="absent-lane", branch="octo-lite/absent-lane",
            )

    def test_non_adopt_still_rejects_an_unprovisioned_existing_worktree(self) -> None:
        self._make_unrecorded_worktree()
        with self.assertRaises(GateError) as ctx:
            self.provision()
        self.assertIn("not provisioned", str(ctx.exception))

    def test_workspace_admit_adopt_cli_requires_identity_flags(self) -> None:
        # The octo-control --adopt-existing branch requires the four identity
        # flags (starting-commit optional) and fails closed when one is missing.
        import importlib.machinery
        import importlib.util
        from types import SimpleNamespace

        control = ROOT / "scripts/octo-control"
        loader = importlib.machinery.SourceFileLoader("octo_control_adopt", str(control))
        spec = importlib.util.spec_from_file_location("octo_control_adopt", control, loader=loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        args = SimpleNamespace(
            adopt_existing=True, control_repo=str(self.control_repo), lane=None,
            branch="octo-lite/lane-1", repo_slug=REPO_SLUG, worktree=str(self.worktree),
            worktree_root=str(self.worktree_root), starting_commit=None,
            minimum_free_bytes=1, conflict=[], provider_overloaded=False,
        )
        with self.assertRaises(module.GateError):
            module.command_workspace_admit(args)

    # REG-1 (code-review finding 1, launch.py:694): an unsanitized lane must
    # never control the record path. A traversal, nested, or absolute lane is
    # rejected before any disk mutation, and never escapes .octo-provisions.
    def test_lane_sanitization_rejects_path_injection(self) -> None:
        escapees = [
            ("../sibling-escape", self.worktree_root / "sibling-escape.json"),
            ("a/nested", self.worktree_root / ".octo-provisions" / "a" / "nested.json"),
            (str(self.base / "abs-escape"), self.base / "abs-escape.json"),
            ("..", None),
        ]
        for index, (malicious_lane, escape_path) in enumerate(escapees):
            target = self.worktree_root / f"target-{index}"
            with self.assertRaises(GateError):
                self.provision(lane=malicious_lane, worktree=target, branch=f"octo-lite/mal-{index}")
            if escape_path is not None:
                self.assertFalse(escape_path.exists(), f"lane {malicious_lane!r} escaped to {escape_path}")
            self.assertFalse(target.exists(), f"lane {malicious_lane!r} still created a worktree")

    # REG-2 (code-review finding 2, launch.py:590): a malformed or foreign
    # record already present in the exclusivity scan must FAIL CLOSED, never
    # be silently skipped.
    def test_exclusivity_fails_closed_on_malformed_foreign_record(self) -> None:
        records_dir = self.worktree_root / ".octo-provisions"
        records_dir.mkdir(parents=True)
        (records_dir / "other-lane.json").write_text("{not valid json")
        with self.assertRaises(GateError):
            self.provision()

    # REG-3 (code-review finding 3, launch.py:696): a lane reservation lock
    # must prevent concurrent same-lane requests for different worktree
    # paths/branches from both proceeding: the second request must block
    # until the first is fully finished, never race ahead concurrently.
    def test_concurrent_same_lane_requests_are_serialized_by_a_reservation_lock(self) -> None:
        release_first = threading.Event()
        second_started = threading.Event()
        results: dict[str, object] = {}

        def blocking_first_install_check(repo):
            release_first.wait(timeout=5)
            return "clean"

        def signal_second_install_check(repo):
            second_started.set()
            return "clean"

        other_worktree = self.worktree_root / "lane-1-other"
        other_branch = "octo-lite/lane-1-other"

        def run_first():
            try:
                results["first"] = self.provision(install_check=blocking_first_install_check)
            except GateError as error:
                results["first"] = error

        def run_second():
            try:
                results["second"] = self.provision(
                    worktree=other_worktree, branch=other_branch,
                    install_check=signal_second_install_check,
                )
            except GateError as error:
                results["second"] = error

        first_thread = threading.Thread(target=run_first)
        first_thread.start()
        # Give the first request time to reach its (blocked) reservation window.
        time.sleep(0.2)

        second_thread = threading.Thread(target=run_second)
        second_thread.start()
        # The second same-lane request must NOT be able to run concurrently
        # with the still-in-flight first request.
        second_ran_concurrently = second_started.wait(timeout=1)
        release_first.set()
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

        self.assertFalse(
            second_ran_concurrently,
            "second same-lane request proceeded concurrently with the first (no reservation lock)",
        )
        self.assertIsInstance(results["first"], LaneProvision)
        self.assertIsInstance(results["second"], GateError)
        self.assertTrue(self.worktree.exists())
        self.assertFalse(other_worktree.exists())

    # REG-4 (code-review finding 4, octo-control:959 + launch.py): the frozen
    # `--starting-commit <ref>` must be RESOLVED to a full sha before it is
    # compared to the worktree HEAD and recorded, so a branch name or
    # abbreviated sha provisions correctly instead of creating an orphan
    # worktree.
    def test_starting_commit_ref_is_resolved_before_provisioning(self) -> None:
        short_head = self.head[:10]
        result = self.provision(head=short_head)
        self.assertEqual(self.head, result.record["starting_head"])
        self.assertEqual(self.head, _git(self.worktree, "rev-parse", "HEAD"))

    # REG-9 (re-review finding 1, launch.py:708): `git rev-parse <ref>` does
    # NOT peel an ANNOTATED TAG to its commit, it returns the tag OBJECT sha,
    # but `git worktree add` checks out the peeled commit. An annotated tag
    # must provision cleanly, record the PEELED COMMIT sha (never the tag
    # object sha), and leave no orphan worktree behind.
    def test_starting_commit_annotated_tag_is_peeled_to_its_commit(self) -> None:
        tag = "v-lane-1"
        _git(self.control_repo, "tag", "-a", tag, "-m", "annotated tag")
        tag_object_sha = _git(self.control_repo, "rev-parse", tag)
        # Sanity: an annotated tag object sha differs from the commit it
        # points at, otherwise this test would not exercise the peel bug.
        self.assertNotEqual(self.head, tag_object_sha)

        result = self.provision(head=tag)

        self.assertEqual(self.head, result.record["starting_head"])
        self.assertNotEqual(tag_object_sha, result.record["starting_head"])
        self.assertEqual(self.head, _git(self.worktree, "rev-parse", "HEAD"))
        listing = _git(self.control_repo, "worktree", "list", "--porcelain")
        self.assertEqual(1, listing.count(f"worktree {self.worktree.resolve()}"))

    # RED-1b: characterizes the UNCHANGED existing worker-pass behavior; the
    # lane-provision path is a distinct new function, never a behavior change to
    # _prepare_worktree itself.
    def test_worker_pass_fresh_absent_unchanged(self) -> None:
        self.worktree.mkdir(parents=True)
        with self.assertRaises(GateError):
            _prepare_worktree(
                self.control_repo, self.worktree_root, self.worktree, self.head, self.branch,
                read_only=False, minimum_free_bytes=1, conflicts=[], provider_overloaded=False,
            )

    # RED-2a
    def test_verify_rejects_origin_slug_mismatch(self) -> None:
        self.provision()
        with self.assertRaises(GateError):
            self.provision(repo_slug="other/repo")

    # RED-2b
    def test_verify_rejects_head_mismatch(self) -> None:
        self.provision()
        with self.assertRaises(GateError):
            self.provision(head="f" * 40)

    # RED-2c
    def test_verify_rejects_branch_mismatch(self) -> None:
        self.provision()
        _git(self.worktree, "checkout", "-b", "drift-branch")
        with self.assertRaises(GateError):
            self.provision()

    # RED-2d
    def test_verify_rejects_dirty_tree(self) -> None:
        self.provision()
        (self.worktree / "scratch.txt").write_text("dirty\n")
        with self.assertRaises(GateError):
            self.provision()

    # RED-2e
    def test_verify_rejects_toplevel_mismatch(self) -> None:
        self.provision()
        nested = self.worktree / "nested"
        nested.mkdir()
        with self.assertRaises(GateError):
            verify_lane_worktree_reality(self.control_repo, nested, self.head, self.branch, REPO_SLUG)

    # RED-2f
    def test_verify_rejects_foreign_common_dir(self) -> None:
        other = self.base / "unrelated-repo"
        _init_control_repo(other, remote="https://github.com/other/thing.git")
        with self.assertRaises(GateError):
            verify_lane_worktree_reality(self.control_repo, other, self.head, self.branch, REPO_SLUG)

    # RED-3a
    def test_exclusivity_refuses_different_lane_same_path(self) -> None:
        self.provision()
        with self.assertRaises(GateError):
            provision_lane_worktree(
                control_repo=self.control_repo,
                worktree_root=self.worktree_root,
                worktree=self.worktree,
                lane="lane-2",
                branch="octo-lite/lane-2",
                head=self.head,
                repo_slug=REPO_SLUG,
                install_check=lambda repo: "clean",
                now=lambda: "2026-07-21T00:00:00+00:00",
            )

    # RED-3b: same path, same lane, DIFFERENT branch -> distinct from RED-3a.
    def test_exclusivity_refuses_different_branch_same_path(self) -> None:
        self.provision()
        with self.assertRaises(GateError) as ctx:
            self.provision(branch="octo-lite/lane-1-other")
        self.assertNotIn("different lane", str(ctx.exception))

    # RED-3c
    def test_exclusivity_refuses_control_repo_path(self) -> None:
        with self.assertRaises(GateError):
            self.provision(worktree=self.control_repo)

    # RED-4
    def test_idempotent_same_lane_reuses(self) -> None:
        first = self.provision()
        second = self.provision()
        self.assertEqual(first.record["worktree"], second.record["worktree"])
        listing = _git(self.control_repo, "worktree", "list", "--porcelain")
        self.assertEqual(1, listing.count(f"worktree {self.worktree.resolve()}"))

    # RED-5a
    def test_record_written_out_of_tree(self) -> None:
        result = self.provision()
        self.assertFalse(str(result.record_path).startswith(str(self.worktree) + os.sep))
        status = _git(self.worktree, "status", "--porcelain")
        self.assertEqual("", status)
        self.assertEqual(json.loads(result.record_path.read_text()), result.record)

    # RED-5b
    def test_record_schema_frozen(self) -> None:
        result = self.provision()
        expected_keys = {
            "schema_version", "source", "lane", "control_repo", "worktree_repo", "worktree",
            "worktree_root", "repo_slug", "branch", "starting_head", "resolver_root",
            "install_check", "provisioned_at",
        }
        self.assertEqual(expected_keys, set(result.record))
        self.assertEqual(1, result.record["schema_version"])
        self.assertEqual("host-provisioned-worktree", result.record["source"])
        self.assertEqual(result.record["worktree"], result.record["resolver_root"])
        self.assertIn(result.record["install_check"], {"clean", "drifted"})
        validate_provision_record(result.record)

        extra = dict(result.record, unexpected="x")
        with self.assertRaises(GateError):
            validate_provision_record(extra)

        missing = dict(result.record)
        del missing["lane"]
        with self.assertRaises(GateError):
            validate_provision_record(missing)

        foreign_source = dict(result.record, source="child-claimed")
        with self.assertRaises(GateError):
            validate_provision_record(foreign_source)

        wrong_type = dict(result.record, schema_version="1")
        with self.assertRaises(GateError):
            validate_provision_record(wrong_type)

    # REG-5 (code-review finding 5, launch.py:548): exact schema validation
    # must reject a non-SHA starting_head and a date-only or timezone-less
    # provisioned_at.
    def test_record_schema_rejects_non_sha_starting_head_and_naive_provisioned_at(self) -> None:
        result = self.provision()

        non_sha_head = dict(result.record, starting_head="not-a-sha")
        with self.assertRaises(GateError):
            validate_provision_record(non_sha_head)

        short_head = dict(result.record, starting_head=self.head[:10])
        with self.assertRaises(GateError):
            validate_provision_record(short_head)

        date_only = dict(result.record, provisioned_at="2026-07-21")
        with self.assertRaises(GateError):
            validate_provision_record(date_only)

        timezone_less = dict(result.record, provisioned_at="2026-07-21T00:00:00")
        with self.assertRaises(GateError):
            validate_provision_record(timezone_less)

    # REG-10 (re-review finding 2, launch.py:566): `datetime.fromisoformat`
    # accepts NON-RFC3339 forms (ISO week dates, compact/basic timestamps)
    # that must still be REJECTED, while genuine RFC3339 values (the Z form
    # and the numeric-offset form) must still PASS.
    def test_record_schema_rejects_non_rfc3339_forms_but_accepts_rfc3339(self) -> None:
        result = self.provision()

        week_date = dict(result.record, provisioned_at="2026-W30-2T00:00:00+00:00")
        with self.assertRaises(GateError):
            validate_provision_record(week_date)

        compact = dict(result.record, provisioned_at="20260721T000000+0000")
        with self.assertRaises(GateError):
            validate_provision_record(compact)

        zulu = dict(result.record, provisioned_at="2026-07-21T00:00:00Z")
        validate_provision_record(zulu)

        numeric_offset = dict(result.record, provisioned_at="2026-07-21T00:00:00+00:00")
        validate_provision_record(numeric_offset)

    # REG-11 (re-review finding, launch.py:503/580): RFC3339 section 5.6
    # explicitly permits a leap-second value (seconds field 60), but
    # `datetime.fromisoformat` raises on second=60, so a pure fromisoformat
    # path false-rejects a valid RFC3339 leap-second timestamp. Both the Z
    # form and the numeric-offset form must be ACCEPTED.
    def test_record_schema_accepts_rfc3339_leap_second(self) -> None:
        result = self.provision()

        zulu_leap = dict(result.record, provisioned_at="1990-12-31T23:59:60Z")
        validate_provision_record(zulu_leap)

        numeric_offset_leap = dict(result.record, provisioned_at="1990-12-31T23:59:60+00:00")
        validate_provision_record(numeric_offset_leap)

    # REG-12 (re-review finding, launch.py:506/579): the offset portion of
    # _RFC3339_DATE_TIME_RE was loosely bound ([+-]\d{2}:\d{2}), so an
    # out-of-range offset (minute >= 60 or hour >= 24) matched the regex and
    # was then silently NORMALIZED by `datetime.fromisoformat`, which accepts
    # and folds out-of-range offset components instead of rejecting them.
    # RFC3339 section 5.6 bounds the offset hour to 00-23 and offset minute
    # to 00-59; both invalid forms below must be REJECTED, and in-range
    # numeric offsets (including the boundary values 23 and 59) must still
    # be ACCEPTED.
    def test_record_schema_rejects_out_of_range_offset(self) -> None:
        result = self.provision()

        invalid_offset_minute = dict(result.record, provisioned_at="2026-07-21T00:00:00+00:60")
        with self.assertRaises(GateError):
            validate_provision_record(invalid_offset_minute)

        invalid_offset_hour = dict(result.record, provisioned_at="2026-07-21T00:00:00+24:00")
        with self.assertRaises(GateError):
            validate_provision_record(invalid_offset_hour)

        boundary_offset = dict(result.record, provisioned_at="2026-07-21T00:00:00+23:59")
        validate_provision_record(boundary_offset)

        negative_offset = dict(result.record, provisioned_at="2026-07-21T00:00:00-08:00")
        validate_provision_record(negative_offset)

        half_hour_offset = dict(result.record, provisioned_at="2026-07-21T00:00:00+05:30")
        validate_provision_record(half_hour_offset)

    # RED-6
    def test_lane_invocation_env_seam_frozen(self) -> None:
        result = self.provision()
        cwd, env = lane_invocation_env(result)
        self.assertEqual(self.worktree.resolve(), cwd)
        self.assertEqual(
            {
                "OCTO_WORKTREE", "OCTO_WORKTREE_ROOT", "OCTO_CONTROL_REPO", "OCTO_REPO_SLUG",
                "OCTO_STARTING_HEAD", "OCTO_LANE", "OCTO_PROVISION_RECORD",
            },
            set(env),
        )
        self.assertEqual(str(self.worktree.resolve()), env["OCTO_WORKTREE"])
        self.assertEqual(str(result.record_path), env["OCTO_PROVISION_RECORD"])
        self.assertEqual(self.lane, env["OCTO_LANE"])
        self.assertEqual(self.head, env["OCTO_STARTING_HEAD"])

    # RED-6b
    def test_launcher_starts_loop_through_seam(self) -> None:
        result = self.provision()
        envelope = {"issue": "TUR-1", "mode": "implement"}
        calls = []

        def runner(cwd, env, args):
            calls.append((cwd, env, args))
            return {"ok": True}

        output = run_lane_loop(result, envelope, runner=runner)
        self.assertEqual({"ok": True}, output)
        self.assertEqual(1, len(calls))
        cwd, env, args = calls[0]
        expected_cwd, expected_env = lane_invocation_env(result)
        self.assertEqual(expected_cwd, cwd)
        self.assertEqual(expected_env, env)
        self.assertEqual(envelope, args)


class CleanupProvisionRecordGuardTests(unittest.TestCase):
    # TUR-447 d1 provision-record-guard (workspace-cleanup-clean-abort,
    # launch-provision-record-schema): clean-abort removal is gated on
    # host-provision ownership. Only a worktree a matching host-provision record
    # proves workspace-admit created and owns may be removed on the error path; a
    # hand-created FOREIGN worktree, even clean and at the exact expected HEAD, is
    # PRESERVED, never force-removed. This is the ops-2 live-harm defect: the
    # bootstrap-failure cleanup removed a real hand-created worktree three times.

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.control_repo = base / "control"
        self.worktree_root = base / "worktrees"
        self.head = _init_control_repo(self.control_repo)
        # Ownership must be proven by the on-disk host-provision record, never an
        # ambient inherited lane env pointing somewhere unrelated.
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("OCTO_PROVISION_RECORD", None)

    def provision(self, worktree: Path, lane: str, branch: str) -> LaneProvision:
        return provision_lane_worktree(
            control_repo=self.control_repo,
            worktree_root=self.worktree_root,
            worktree=worktree,
            lane=lane,
            branch=branch,
            head=self.head,
            repo_slug=REPO_SLUG,
            install_check=lambda repo: "clean",
            now=lambda: "2026-07-21T00:00:00+00:00",
        )

    def test_cleanup_preserves_foreign_worktree_without_provision_record(self) -> None:
        # A hand-created worktree (real prior work, e.g. a tur-326 branch) that is
        # clean and at the exact expected HEAD has NO host-provision record, so the
        # error-path cleanup must PRESERVE it.
        foreign = self.worktree_root / "tur-326"
        self.worktree_root.mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(self.control_repo), "worktree", "add", "-b", "tur-326", str(foreign), self.head],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(self.head, _git(foreign, "rev-parse", "HEAD"))
        self.assertEqual("", _git(foreign, "status", "--porcelain"))

        cleanup_clean_abort(self.control_repo, foreign, self.head)

        self.assertTrue(foreign.is_dir(), "hand-created foreign worktree was force-removed")
        listing = _git(self.control_repo, "worktree", "list", "--porcelain")
        self.assertEqual(1, listing.count(f"worktree {foreign.resolve()}"))

        # A host-provision record owning a DIFFERENT worktree proves nothing about
        # this one: the foreign worktree is still preserved.
        self.provision(self.worktree_root / "lane-1", "lane-1", "octo-lite/lane-1")
        cleanup_clean_abort(self.control_repo, foreign, self.head)
        self.assertTrue(foreign.is_dir(), "foreign worktree removed on a mismatched record")

    def test_cleanup_removes_only_provision_record_owned_worktree(self) -> None:
        # A worktree WITH a matching host-provision record (source
        # host-provisioned-worktree, schema_version 1, record.worktree == this
        # worktree) is still removed when pristine, exactly as before.
        owned = self.worktree_root / "lane-1"
        result = self.provision(owned, "lane-1", "octo-lite/lane-1")
        record = json.loads(result.record_path.read_text())
        self.assertEqual("host-provisioned-worktree", record["source"])
        self.assertEqual(1, record["schema_version"])
        self.assertEqual(str(owned.resolve()), record["worktree"])

        cleanup_clean_abort(self.control_repo, owned, self.head)

        self.assertFalse(owned.exists(), "provision-record-owned pristine worktree must still be removed")

    def test_stale_record_path_reuse_does_not_authorize_removal(self) -> None:
        # TUR-447 cycle-2 P1-2b (workspace-cleanup-clean-abort): ownership is
        # bound to the provision INSTANCE, not the pathname. A stale provision
        # record for path X plus a hand-recreated worktree at the SAME
        # conventional path X (the exact live tur-326 deletion shape) proves
        # nothing: the foreign worktree is PRESERVED.
        owned = self.worktree_root / "lane-1"
        result = self.provision(owned, "lane-1", "octo-lite/lane-1")
        subprocess.run(
            ["git", "-C", str(self.control_repo), "worktree", "remove", str(owned)],
            check=True, capture_output=True, text=True,
        )
        self.assertTrue(result.record_path.is_file(), "stale-record precondition")

        # Hand-recreated at the SAME path on a DIFFERENT branch: real foreign
        # work, clean and at the exact expected HEAD.
        subprocess.run(
            ["git", "-C", str(self.control_repo), "worktree", "add", "-b", "tur-326", str(owned), self.head],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(self.head, _git(owned, "rev-parse", "HEAD"))
        self.assertEqual("", _git(owned, "status", "--porcelain"))

        cleanup_clean_abort(self.control_repo, owned, self.head)

        self.assertTrue(owned.is_dir(), "stale record re-authorized removing a hand-recreated worktree")

        # A DETACHED hand-recreated worktree at the same path proves no branch
        # identity at all: equally preserved.
        subprocess.run(
            ["git", "-C", str(self.control_repo), "worktree", "remove", str(owned)],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.control_repo), "worktree", "add", "--detach", str(owned), self.head],
            check=True, capture_output=True, text=True,
        )

        cleanup_clean_abort(self.control_repo, owned, self.head)

        self.assertTrue(owned.is_dir(), "stale record re-authorized removing a detached hand-created worktree")

    def test_cleanup_retires_provision_record(self) -> None:
        # TUR-447 cycle-2 P1-2a (workspace-cleanup-clean-abort): a successful
        # provisioned clean-abort removal RETIRES the provision record, so the
        # record can never authorize a future deletion at the same path.
        owned = self.worktree_root / "lane-1"
        result = self.provision(owned, "lane-1", "octo-lite/lane-1")

        cleanup_clean_abort(self.control_repo, owned, self.head)

        self.assertFalse(owned.exists(), "owned pristine worktree is still removed")
        self.assertFalse(result.record_path.exists(), "provision record survived its worktree removal")

        # With the record retired, a NEW hand-created worktree at the same
        # conventional path, even on the SAME branch, is foreign: preserved.
        subprocess.run(
            ["git", "-C", str(self.control_repo), "worktree", "add", str(owned), "octo-lite/lane-1"],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(self.head, _git(owned, "rev-parse", "HEAD"))

        cleanup_clean_abort(self.control_repo, owned, self.head)

        self.assertTrue(owned.is_dir(), "foreign worktree removed after record retirement")

    def test_record_retired_before_worktree_removal(self) -> None:
        # TUR-447 cycle-3 P1 (workspace-cleanup-clean-abort): the proving
        # provision record is RETIRED before git worktree remove, so any crash
        # or failure between the two steps biases fail-safe toward a worktree
        # LEAK, never a re-openable deletion. When the removal itself fails,
        # the record must ALREADY be gone and the worktree preserved; the
        # surviving worktree is then recordless, so every later cleanup at the
        # same path preserves it.
        owned = self.worktree_root / "lane-1"
        result = self.provision(owned, "lane-1", "octo-lite/lane-1")

        real_run = subprocess.run

        def failing_remove(args, **kwargs):
            if isinstance(args, (list, tuple)) and "worktree" in args and "remove" in args:
                raise subprocess.CalledProcessError(
                    1, list(args), output="", stderr="simulated removal failure"
                )
            return real_run(args, **kwargs)

        with mock.patch("octo_lite.launch.subprocess.run", side_effect=failing_remove):
            cleanup_clean_abort(self.control_repo, owned, self.head)

        self.assertTrue(owned.is_dir(), "failed removal must leave the worktree in place")
        self.assertFalse(
            result.record_path.exists(),
            "record survived a failed removal: retire-first ordering violated",
        )

        # Record gone + worktree present is the safe latched state: a
        # subsequent cleanup attempt at this path treats it as foreign.
        cleanup_clean_abort(self.control_repo, owned, self.head)
        self.assertTrue(owned.is_dir(), "recordless surviving worktree removed by a later cleanup")

    def test_unlink_failure_preserves_worktree(self) -> None:
        # TUR-447 cycle-3 P1 (workspace-cleanup-clean-abort): a failed record
        # retirement (any OSError) HALTS the removal entirely instead of being
        # silently ignored. An unretirable record must never let its worktree
        # be deleted, because the surviving record could later re-authorize
        # deleting a hand-recreated worktree at the same path.
        owned = self.worktree_root / "lane-1"
        result = self.provision(owned, "lane-1", "octo-lite/lane-1")

        with mock.patch.object(
            Path, "unlink", autospec=True, side_effect=OSError("simulated unlink failure")
        ):
            cleanup_clean_abort(self.control_repo, owned, self.head)

        self.assertTrue(owned.is_dir(), "unlink failure must preserve the worktree, never remove it")
        self.assertTrue(result.record_path.is_file(), "record still present after failed retirement")
        listing = _git(self.control_repo, "worktree", "list", "--porcelain")
        self.assertEqual(1, listing.count(f"worktree {owned.resolve()}"))


class InstallCheckOwnerRoutingTests(unittest.TestCase):
    # RED-8 (owner-routing half; the record-state half lives in
    # test_workspace_wiring.py). Exercises the REAL scripts/install-octo-lite
    # --check against an isolated --prefix, never the real $HOME.

    def test_default_install_check_reports_seeded_drift_without_repairing_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            prefix = base / "prefix"
            installer = ROOT / "scripts" / "install-octo-lite"
            subprocess.run(
                [str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True,
            )
            self.assertEqual("clean", default_install_check(ROOT, prefix=prefix))

            target = prefix / ".codex" / "AGENTS.md"
            target.unlink()
            foreign = prefix / "elsewhere.md"
            foreign.write_text("foreign\n")
            target.symlink_to(foreign)
            before = target.readlink()

            self.assertEqual("drifted", default_install_check(ROOT, prefix=prefix))
            self.assertEqual(before, target.readlink())
            self.assertEqual("foreign\n", foreign.read_text())


class LaneEnvFromRecordTests(unittest.TestCase):
    # gh#13 Blocker B (spec launch-provision-env-seam): the host reads the
    # out-of-tree host-authored record and derives exactly the 7 frozen OCTO_*
    # vars it injects into the loop process, failing closed on a worktree
    # mismatch or a non-host / malformed record.
    def test_returns_the_seven_frozen_seam_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "wt"
            worktree.mkdir()
            record = _valid_record(worktree, root)
            path = root / "issue13.json"
            path.write_text(json.dumps(record))
            env = lane_env_from_record(path, expected_worktree=worktree)
        self.assertEqual(set(env), set(LANE_ENV_KEYS))
        self.assertEqual(env["OCTO_WORKTREE"], str(worktree))
        self.assertEqual(env["OCTO_WORKTREE_ROOT"], str(root))
        self.assertEqual(env["OCTO_CONTROL_REPO"], str(root / "control"))
        self.assertEqual(env["OCTO_REPO_SLUG"], "acme/widgets")
        self.assertEqual(env["OCTO_STARTING_HEAD"], "0" * 40)
        self.assertEqual(env["OCTO_LANE"], "issue13")
        self.assertEqual(env["OCTO_PROVISION_RECORD"], str(path.resolve()))

    def test_rejects_worktree_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "wt"
            worktree.mkdir()
            other = root / "other"
            other.mkdir()
            path = root / "issue13.json"
            path.write_text(json.dumps(_valid_record(worktree, root)))
            with self.assertRaises(GateError):
                lane_env_from_record(path, expected_worktree=other)

    def test_rejects_non_host_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "wt"
            worktree.mkdir()
            record = _valid_record(worktree, root)
            record["source"] = "child-supplied"
            path = root / "issue13.json"
            path.write_text(json.dumps(record))
            with self.assertRaises(GateError):
                lane_env_from_record(path, expected_worktree=worktree)

    def test_rejects_unreadable_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            with self.assertRaises(GateError):
                lane_env_from_record(missing, expected_worktree=Path(tmp))

    def test_rejects_record_inside_the_worktree_tree(self) -> None:
        # launch-provision-record-out-of-tree: a record authored inside the lane's
        # own worktree can never be trusted as the host trust root.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "wt"
            (worktree / "nested").mkdir(parents=True)
            path = worktree / "nested" / "record.json"
            path.write_text(json.dumps(_valid_record(worktree, root)))
            with self.assertRaises(GateError):
                lane_env_from_record(path, expected_worktree=worktree)

    def test_rejects_control_character_in_a_seam_value(self) -> None:
        # A newline in a record field would inject an extra host env variable when
        # a launcher serializes the env line by line.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "wt"
            worktree.mkdir()
            record = _valid_record(worktree, root)
            record["control_repo"] = "/ctl\nPATH=/attacker"
            path = root / "issue13.json"
            path.write_text(json.dumps(record))
            with self.assertRaises(GateError):
                lane_env_from_record(path, expected_worktree=worktree)


class TargetLaneProvisionTests(unittest.TestCase):
    # gh#13: a TARGET repo lane's worktree belongs to the target git repo (no
    # octo-lite tooling), and octo_control_repo names the separate octo-lite
    # tooling repo. The record's control_repo (== OCTO_CONTROL_REPO, from which the
    # loop resolves role_resolver.py) must be the octo-lite tooling repo, while the
    # worktree/resolver_root is the target worktree and repo_slug is the target's.
    # This is what makes a target lane loop-RUNNABLE, not merely provisioned.
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.control_repo = base / "target"
        self.worktree_root = base / "worktrees"
        self.head = self._init_target_repo(self.control_repo)
        self.lane = "tur-x"
        self.branch = "tur-x-shaping"
        self.worktree = self.worktree_root / self.lane
        # ROOT is a real octo-lite repo (roles.toml + roles/ + installer): the
        # octo-lite tooling repo a target lane resolves its roles from.
        self.octo_control_repo = ROOT

    def _init_target_repo(self, repo: Path) -> str:
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", REMOTE], check=True)
        # A target repo: AGENTS.md + CLAUDE.md but NO roles.toml and NO installer.
        (repo / "AGENTS.md").write_text("# Target\n")
        (repo / "CLAUDE.md").write_text("# Target\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        return _git(repo, "rev-parse", "HEAD")

    def provision(self, **overrides):
        values = dict(
            control_repo=self.control_repo, octo_control_repo=self.octo_control_repo,
            worktree_root=self.worktree_root, worktree=self.worktree, lane=self.lane,
            branch=self.branch, head=self.head, repo_slug=REPO_SLUG,
            install_check=lambda repo: "clean", now=lambda: "2026-07-23T00:00:00+00:00",
        )
        values.update(overrides)
        return provision_lane_worktree(**values)

    def test_fresh_provision_points_octo_control_repo_at_the_tooling_repo(self) -> None:
        result = self.provision()
        # OCTO_CONTROL_REPO (record.control_repo) is the octo-lite tooling repo...
        self.assertEqual(str(self.octo_control_repo.resolve()), result.record["control_repo"])
        # ...worktree_repo is the target git-owner (used by cleanup ownership)...
        self.assertEqual(str(self.control_repo.resolve()), result.record["worktree_repo"])
        # ...while the worktree, resolver_root, and slug are the target's.
        self.assertEqual(str(self.worktree), result.record["worktree"])
        self.assertEqual(str(self.worktree), result.record["resolver_root"])
        self.assertEqual(REPO_SLUG, result.record["repo_slug"])
        validate_provision_record(result.record)
        # The frozen env a target lane launches with resolves tooling from octo-lite
        # and cwd from the target worktree: loop-runnable, not target-code-executing.
        _, env = lane_invocation_env(result)
        self.assertEqual(str(self.octo_control_repo.resolve()), env["OCTO_CONTROL_REPO"])
        self.assertEqual(str(self.worktree), env["OCTO_WORKTREE"])

    def test_adopt_existing_target_repo_points_octo_control_repo_at_tooling(self) -> None:
        first = self.provision()
        Path(first.record_path).unlink()
        result = self.provision(adopt_existing=True, head=None)
        self.assertTrue(Path(result.record_path).is_file())
        self.assertEqual(str(self.octo_control_repo.resolve()), result.record["control_repo"])
        self.assertEqual(str(self.worktree), result.record["resolver_root"])
        validate_provision_record(result.record)

    def test_cleanup_recognizes_target_lane_ownership_via_worktree_repo(self) -> None:
        # Cleanup must prove ownership against the target git-owner (worktree_repo),
        # even though the record's control_repo is the octo-lite tooling repo, so a
        # clean aborted target worktree is not leaked.
        from octo_lite.launch import _owning_provision_record

        result = self.provision()
        self.assertEqual(Path(result.record_path), _owning_provision_record(self.worktree))

    def test_target_worktree_without_octo_control_repo_fails_closed(self) -> None:
        # Omitting octo_control_repo defaults it to the target control_repo, which
        # carries no roles.toml, so registry verification fails closed rather than
        # silently producing a record that cannot resolve roles.
        with self.assertRaises(GateError):
            self.provision(octo_control_repo=None)

    def test_default_install_check_reports_clean_when_control_repo_has_no_installer(self) -> None:
        self.assertEqual("clean", default_install_check(self.control_repo))

    def test_default_install_check_never_executes_a_target_repos_installer(self) -> None:
        # Safety: a target control repo (no roles.toml) that happens to carry an
        # executable scripts/install-octo-lite must NOT be executed; report clean.
        scripts = self.control_repo / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        booby = scripts / "install-octo-lite"
        booby.write_text("#!/bin/sh\ntouch " + str(self.control_repo / "EXECUTED") + "\nexit 7\n")
        booby.chmod(0o755)
        self.assertEqual("clean", default_install_check(self.control_repo))
        self.assertFalse((self.control_repo / "EXECUTED").exists())


if __name__ == "__main__":
    unittest.main()
