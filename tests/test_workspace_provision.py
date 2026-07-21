from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from octo_lite.launch import (
    GateError,
    _prepare_worktree,
    default_install_check,
    lane_invocation_env,
    provision_lane_worktree,
    run_lane_loop,
    validate_provision_record,
    verify_lane_worktree_reality,
)

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
            "schema_version", "source", "lane", "control_repo", "worktree", "worktree_root",
            "repo_slug", "branch", "starting_head", "resolver_root", "install_check", "provisioned_at",
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


if __name__ == "__main__":
    unittest.main()
