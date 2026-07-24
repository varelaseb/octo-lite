from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from octo_lite.launch import GateError, default_install_check, provision_lane_worktree
from workflows.lib.role_resolver import load_registry, resolve_role

ROOT = Path(__file__).resolve().parents[1]
REPO_SLUG = "acme/widgets"
REMOTE = f"https://github.com/{REPO_SLUG}.git"


def _init_control_repo(repo: Path, *, remote: str = REMOTE, include_claude: bool = True) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
    shutil.copy(ROOT / "roles.toml", repo / "roles.toml")
    shutil.copytree(ROOT / "roles", repo / "roles")
    (repo / "AGENTS.md").write_text("# Target\n")
    if include_claude:
        (repo / "CLAUDE.md").write_text("# Target\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()


class WorkspaceWiringTests(unittest.TestCase):
    # gh#8 AC7 wiring liveness (spec launch-provision-wiring-liveness), operator
    # flagged first-class.

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.control_repo = self.base / "control"
        self.worktree_root = self.base / "worktrees"
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

    # RED-7
    def test_provisioned_worktree_resolves_core_roles(self) -> None:
        self.provision()
        registry = load_registry(self.worktree)
        self.assertEqual(self.worktree.resolve(), registry.root)
        for role in ("orchestrator", "implementer"):
            resolved = resolve_role(registry, role)
            self.assertEqual(role, resolved.role.name)

    # RED-7b
    def test_provisioned_worktree_own_instructions(self) -> None:
        self.provision()
        self.assertTrue((self.worktree / "AGENTS.md").is_file())
        self.assertTrue((self.worktree / "CLAUDE.md").is_file())

        no_claude_repo = self.base / "control-no-claude"
        head = _init_control_repo(no_claude_repo, include_claude=False)
        with self.assertRaises(GateError):
            provision_lane_worktree(
                control_repo=no_claude_repo,
                worktree_root=self.base / "worktrees-no-claude",
                worktree=self.base / "worktrees-no-claude" / "lane-x",
                lane="lane-x",
                branch="octo-lite/lane-x",
                head=head,
                repo_slug=REPO_SLUG,
                install_check=lambda repo: "clean",
                now=lambda: "2026-07-21T00:00:00+00:00",
            )

    # RED-8: install_check state is recorded truthfully, never falsely repaired,
    # and a genuine drift emits an owner-routing signal.
    def test_provision_records_install_check_state(self) -> None:
        clean_result = self.provision(install_check=lambda repo: "clean")
        self.assertEqual("clean", clean_result.record["install_check"])
        self.assertIsNone(clean_result.install_check_owner_route)

        drifted_worktree = self.worktree_root / "lane-2"
        drifted_result = provision_lane_worktree(
            control_repo=self.control_repo,
            worktree_root=self.worktree_root,
            worktree=drifted_worktree,
            lane="lane-2",
            branch="octo-lite/lane-2",
            head=self.head,
            repo_slug=REPO_SLUG,
            install_check=lambda repo: "drifted",
            now=lambda: "2026-07-21T00:00:00+00:00",
        )
        self.assertEqual("drifted", drifted_result.record["install_check"])
        self.assertIsNotNone(drifted_result.install_check_owner_route)
        self.assertEqual("installed-surface-owner", drifted_result.install_check_owner_route)

    def test_provision_uses_real_installer_check_and_never_false_repairs_a_seeded_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "prefix"
            installer = ROOT / "scripts" / "install-octo-lite"
            subprocess.run(
                [str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True,
            )
            target = prefix / ".codex" / "AGENTS.md"
            target.unlink()
            foreign = prefix / "elsewhere.md"
            foreign.write_text("foreign\n")
            target.symlink_to(foreign)
            before = target.readlink()

            result = self.provision(
                install_check=lambda repo: default_install_check(ROOT, prefix=prefix),
            )
            self.assertEqual("drifted", result.record["install_check"])
            self.assertIsNotNone(result.install_check_owner_route)
            self.assertEqual(before, target.readlink())
            self.assertEqual("foreign\n", foreign.read_text())


if __name__ == "__main__":
    unittest.main()
