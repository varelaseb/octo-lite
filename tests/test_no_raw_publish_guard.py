from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/guard-no-raw-publish"


class NoRawPublishGuardTests(unittest.TestCase):
    """AC3 (delivery-lifecycle qa-publication-no-raw-guard): the sole-path and
    single-writer guarantees are mechanically checked. A guard rejects any skill,
    workflow, or role text that directs a raw Linear state change or a direct
    write to the operator-read surface outside the verified helpers; a clean tree
    passes; the verified wrapped mutate in octo-control is exempt."""

    def test_clean_repo_tree_passes(self) -> None:
        # The real repo tree carries no raw publish path outside the verified
        # helpers, so the guard passes; the octo-control wrapped mutate is exempt.
        result = subprocess.run([str(GUARD)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def _seed_repo(self, base: Path) -> Path:
        # Minimal repo surface the guard scans: real octo-control (carries the
        # exempt wrapped mutate) plus the scanned dirs.
        (base / "scripts").mkdir(parents=True)
        shutil.copy(ROOT / "scripts/octo-control", base / "scripts/octo-control")
        for name in ("skills", "workflows", "roles"):
            (base / name).mkdir()
        return base

    def test_seeded_raw_linear_state_change_in_a_skill_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = self._seed_repo(Path(td))
            skill = base / "skills" / "bad-skill.md"
            skill.write_text(
                "# Bad skill\n\nMove the issue:\n\n    linear issue update TUR-1 --state 'Awaiting Accept'\n"
            )
            result = subprocess.run([str(GUARD), "--root", str(base)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("raw Linear state change", result.stderr)
            self.assertIn("bad-skill.md", result.stderr)

    def test_seeded_raw_surface_write_in_a_workflow_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = self._seed_repo(Path(td))
            wf = base / "workflows" / "bad-workflow.md"
            wf.write_text(
                "# Bad workflow\n\nPublish evidence by hand:\n\n"
                "    ln -s qa-artifacts/TUR-1 /root/codex-uploads/TUR-1\n"
            )
            result = subprocess.run([str(GUARD), "--root", str(base)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("direct operator-surface write", result.stderr)
            self.assertIn("bad-workflow.md", result.stderr)

    def test_seeded_positional_state_raw_linear_update_fails(self) -> None:
        # adv2: `linear issue update TUR-1 Done` uses a POSITIONAL state (no
        # --state flag). The old detector required --state on the same line, so
        # this evaded. The guard must trip on `linear issue update` itself.
        with tempfile.TemporaryDirectory() as td:
            base = self._seed_repo(Path(td))
            skill = base / "skills" / "positional-skill.md"
            skill.write_text(
                "# Bad skill\n\nMove it:\n\n    linear issue update TUR-1 Done\n"
            )
            result = subprocess.run([str(GUARD), "--root", str(base)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("positional-skill.md", result.stderr)

    def test_seeded_line_continuation_state_raw_linear_update_fails(self) -> None:
        # adv2: `--state` on a shell line-continuation after `linear issue update
        # ... \` split the tokens across physical lines, evading a per-physical-
        # line detector. The guard must join logical (continued) lines first.
        with tempfile.TemporaryDirectory() as td:
            base = self._seed_repo(Path(td))
            wf = base / "workflows" / "continued-workflow.md"
            wf.write_text(
                "# Bad workflow\n\nMove it:\n\n"
                "    linear issue update TUR-1 \\\n"
                "        --state 'Awaiting Accept'\n"
            )
            result = subprocess.run([str(GUARD), "--root", str(base)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("continued-workflow.md", result.stderr)

    def test_seeded_clean_tree_with_helper_passes(self) -> None:
        # A seeded tree with the real octo-control (exempt wrapped mutate) and no
        # raw paths in the scanned dirs passes, proving the allowlist works.
        with tempfile.TemporaryDirectory() as td:
            base = self._seed_repo(Path(td))
            (base / "roles" / "ok-role.md").write_text(
                "# Role\n\nUse the verified octo-control linear-transition helper.\n"
            )
            result = subprocess.run([str(GUARD), "--root", str(base)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
