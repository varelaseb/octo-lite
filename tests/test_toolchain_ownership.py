"""Installer ownership seams and the delivery mapping."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"


class ToolchainOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ann33-ownership-")
        self.root = Path(self.tmp.name)
        self.peer = self.root / "spec-chat"
        for name in ("shape-spec", "review-spec"):
            source = self.peer / "skill" / name
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        self.profile = self.root / "profile"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _install(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["SPEC_CHAT_ROOT"] = str(self.peer)
        return subprocess.run(
            [str(INSTALLER), "--prefix", str(self.profile)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_installer_yields_live_peer_link_and_prunes_dangling_link(self) -> None:
        peer_source = self.root / "peer-skill"
        peer_source.mkdir()
        (peer_source / "SKILL.md").write_text("peer\n", encoding="utf-8")
        peer_target = self.profile / ".claude" / "skills" / "commit"
        peer_target.parent.mkdir(parents=True)
        peer_target.symlink_to(peer_source)

        result = self._install()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(peer_source.resolve(), peer_target.resolve())
        self.assertIn("owned by another repo", result.stdout)

        dangling = self.profile / ".codex" / "skills" / "commit"
        dangling.unlink()
        dangling.symlink_to(self.root / "gone")
        result = self._install()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((ROOT / "skills" / "commit").resolve(), dangling.resolve())


    def test_missing_required_skill_blocks_installer_check(self) -> None:
        result = self._install()
        self.assertEqual(0, result.returncode, result.stderr)
        target = self.profile / ".claude" / "skills" / "commit"
        target.unlink()

        check = subprocess.run(
            [str(INSTALLER), "--check", "--prefix", str(self.profile)],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "SPEC_CHAT_ROOT": str(self.peer)},
        )
        self.assertNotEqual(0, check.returncode)

if __name__ == "__main__":
    unittest.main()
