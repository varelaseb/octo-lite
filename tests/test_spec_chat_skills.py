from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "skills/spec-chat-review"
PREFLIGHT = REVIEW / "scripts/preflight.py"
WATCH = REVIEW / "scripts/watch.sh"


class SpecChatSkillTests(unittest.TestCase):
    def test_preflight_migrates_the_runtime_referenced_by_the_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            spec_dir = repo / "spec"
            spec_dir.mkdir(parents=True)
            spec = spec_dir / "example.spec.html"
            spec.write_text(
                '<script defer src="./.viz/runtime.js"></script>\n'
                '<section data-anchor="x"><p>Works.</p></section>\n'
            )
            result = subprocess.run(
                ["python3", str(PREFLIGHT), str(repo), str(spec)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((spec_dir / ".viz/runtime.js").is_file())
            self.assertFalse((repo / "docs/specs/.viz/runtime.js").exists())

    def test_preflight_rejects_a_noncanonical_runtime_filename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            spec_dir = repo / "spec"
            spec_dir.mkdir(parents=True)
            spec = spec_dir / "example.spec.html"
            spec.write_text(
                '<script defer src="./app-runtime.js"></script>\n'
                '<section data-anchor="x"><p>Works.</p></section>\n'
            )
            result = subprocess.run(
                ["python3", str(PREFLIGHT), str(repo), str(spec)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, result.returncode)
            self.assertFalse((spec_dir / "runtime.js").exists())

    def test_single_page_watch_stops_at_the_newest_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            review = Path(td) / "example.spec.html.review"
            human = review / "human"
            human.mkdir(parents=True)
            (review / "agent").mkdir()
            names = [
                "001-comment-a.json",
                "002-handoff-h.json",
                "003-comment-not-handed-off.json",
            ]
            for name in names:
                (human / name).write_text("{}")
            cursor = review / ".cursor-test"
            result = subprocess.run(
                [str(WATCH), str(review), str(cursor), "1", "1"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(names[:2], result.stdout.splitlines())

    def test_single_page_watch_times_out_while_draft_is_unhanded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            review = Path(td) / "example.spec.html.review"
            human = review / "human"
            human.mkdir(parents=True)
            (review / "agent").mkdir()
            (human / "001-comment-a.json").write_text("{}")
            cursor = review / ".cursor-test"
            result = subprocess.run(
                [str(WATCH), str(review), str(cursor), "1", "1"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            self.assertEqual(3, result.returncode, result.stderr)

if __name__ == "__main__":
    unittest.main()
