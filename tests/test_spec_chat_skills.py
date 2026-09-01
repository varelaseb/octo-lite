from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "skills/spec-chat-review"
PREFLIGHT = REVIEW / "scripts/preflight.py"
WATCH = REVIEW / "scripts/watch.sh"
DETACHED = REVIEW / "scripts/codex-review.sh"


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

    def test_detached_review_refuses_a_live_interactive_lease(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec = root / "example.spec.html"
            spec.write_text("<p>Works.</p>\n")
            review = Path(str(spec) + ".review")
            human = review / "human"
            human.mkdir(parents=True)
            (review / "agent").mkdir()
            (human / "001-comment-a.json").write_text("{}")
            (human / "002-handoff-h.json").write_text("{}")
            (review / "state.json").write_text(
                json.dumps(
                    {
                        "ownerKind": "interactive",
                        "pid": os.getpid(),
                        "leaseUntil": int(time.time()) + 300,
                        "heartbeatAt": "now",
                    }
                )
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_codex = fake_bin / "codex"
            fake_codex.write_text("#!/bin/sh\nexit 99\n")
            fake_codex.chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")
            result = subprocess.run(
                [str(DETACHED), "--once", str(spec)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(75, result.returncode, result.stderr)
            self.assertIn("interactive owner holds", result.stderr)


if __name__ == "__main__":
    unittest.main()
