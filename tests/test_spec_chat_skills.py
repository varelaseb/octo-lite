from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

# spec-chat is a peer repository, not a vendored dependency: its skills are
# linked straight from a clone so a pull there is live with no pin to bump.
SPEC_CHAT = Path(os.environ.get("SPEC_CHAT_ROOT", "/root/spec-chat"))
REVIEW = SPEC_CHAT / "skill/review-spec"
SHAPE = SPEC_CHAT / "skill/shape-spec"
PREFLIGHT = REVIEW / "scripts/preflight.py"
WATCH = REVIEW / "scripts/watch.sh"


def _spec_chat_available() -> bool:
    try:
        return SPEC_CHAT.is_dir()
    except OSError:
        return False


SPEC_CHAT_AVAILABLE = _spec_chat_available()


class SpecChatSkillTests(unittest.TestCase):
    def test_spec_chat_is_a_peer_repository_not_a_vendored_pin(self) -> None:
        manifest = (ROOT / "Skillfile").read_text()
        lock = json.loads((ROOT / "Skillfile.lock").read_text())
        for name in ("spec-chat-review", "spec-chat-shape"):
            with self.subTest(name=name):
                self.assertNotIn(name, manifest, "spec-chat must not be pinned")
                self.assertFalse(
                    (ROOT / "agents/skills" / name).exists(),
                    "spec-chat must not be vendored into agents/skills",
                )
        self.assertFalse(
            [k for k in lock if "spec-chat" in k], "lockfile still pins spec-chat"
        )

    def test_the_installer_links_spec_chat_from_a_clone(self) -> None:
        installer = (ROOT / "scripts/install-octo-lite").read_text()
        self.assertIn("SPEC_CHAT_ROOT", installer)
        self.assertIn("skill/${pair%%:*}", installer)

    @unittest.skipUnless(SPEC_CHAT_AVAILABLE, f"no spec-chat clone at {SPEC_CHAT}")
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

    @unittest.skipUnless(SPEC_CHAT_AVAILABLE, f"no spec-chat clone at {SPEC_CHAT}")
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

    @unittest.skipUnless(SPEC_CHAT_AVAILABLE, f"no spec-chat clone at {SPEC_CHAT}")
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
                env={**os.environ, "SPEC_CHAT_WATCH_OWNER": "turn-yielded"},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(names[:2], result.stdout.splitlines())

    @unittest.skipUnless(SPEC_CHAT_AVAILABLE, f"no spec-chat clone at {SPEC_CHAT}")
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
                env={**os.environ, "SPEC_CHAT_WATCH_OWNER": "turn-yielded"},
            )
            self.assertEqual(3, result.returncode, result.stderr)

if __name__ == "__main__":
    unittest.main()
