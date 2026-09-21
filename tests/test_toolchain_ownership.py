"""ANN-33 ownership, role-resolution, and shaping-review conformance seams."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"
CHECK = ROOT / "scripts" / "check-octo-lite-conformance"
FIXTURE = ROOT / "fixtures" / "conformance" / "octo-lite" / "fixture.json"
SHAPING_CLEAR = ROOT / "fixtures" / "conformance" / "octo-lite" / "shaping-review-clear.json"
SHAPING_BLOCKING = ROOT / "fixtures" / "conformance" / "octo-lite" / "shaping-review-blocking.json"


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

    def _check(self, shaping: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
        return_value = subprocess.run(
            [
                str(CHECK),
                "--profile-root",
                str(self.profile),
                "--shaping-review",
                str(shaping),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return return_value, json.loads(return_value.stdout)

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

    def test_conformance_receipt_binds_revision_profile_paths_and_mapping(self) -> None:
        result = self._install()
        self.assertEqual(0, result.returncode, result.stderr)

        result, receipt = self._check(SHAPING_CLEAR)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("clear", receipt["overall_status"])
        self.assertRegex(receipt["octo_lite_revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(str(self.profile.resolve()), receipt["profile_root"])
        self.assertEqual("clear", receipt["role_resolution"]["status"])
        self.assertEqual("shaping-reviewer", receipt["provider_mapping"]["role"])
        self.assertEqual(
            ["repo-read", "linear-read", "github-read", "session-log-read"],
            receipt["provider_mapping"]["tools"],
        )
        self.assertEqual("clear", receipt["shaping_review"]["verdict"])
        self.assertTrue(receipt["resolved_paths"])

    def test_wrong_shaping_binding_blocks_conformance(self) -> None:
        result = self._install()
        self.assertEqual(0, result.returncode, result.stderr)

        shaping = self.root / "shaping-review-wrong-binding.json"
        payload = json.loads(SHAPING_CLEAR.read_text(encoding="utf-8"))
        payload["binding"]["head"] = "unrelated-head"
        shaping.write_text(json.dumps(payload), encoding="utf-8")

        result, receipt = self._check(shaping)

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("blocking", receipt["overall_status"])
        self.assertTrue(any("binding mismatch for head" in item["message"] for item in receipt["errors"]))

    def test_missing_required_skill_blocks_installer_check_and_conformance(self) -> None:
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

        result, receipt = self._check(SHAPING_CLEAR)

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("blocking", receipt["overall_status"])
        self.assertTrue(any(str(target) in item["message"] for item in receipt["errors"]))

    def test_copied_peer_skill_blocks_role_resolution(self) -> None:
        result = self._install()
        self.assertEqual(0, result.returncode, result.stderr)
        target = self.profile / ".claude" / "skills" / "spec-chat-shape"
        target.unlink()
        target.symlink_to(ROOT / "skills" / "commit")

        result, receipt = self._check(SHAPING_CLEAR)

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("blocking", receipt["overall_status"])
        self.assertTrue(any("copied peer skill" in item["message"] for item in receipt["errors"]))

    def test_missing_cli_role_link_blocks_conformance(self) -> None:
        for cli in (".claude", ".codex"):
            with self.subTest(cli=cli):
                result = self._install()
                self.assertEqual(0, result.returncode, result.stderr)
                target = self.profile / cli / "agents" / "orchestrator.md"
                target.unlink()

                result, receipt = self._check(SHAPING_CLEAR)

                self.assertNotEqual(0, result.returncode)
                self.assertEqual("blocking", receipt["overall_status"])
                self.assertEqual("blocking", receipt["role_resolution"]["status"])
                self.assertTrue(any(str(target) in item["message"] for item in receipt["errors"]))

    def test_blocking_shaping_review_blocks_conformance(self) -> None:
        result = self._install()
        self.assertEqual(0, result.returncode, result.stderr)

        result, receipt = self._check(SHAPING_BLOCKING)

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("blocking", receipt["overall_status"])
        self.assertEqual("blocking", receipt["shaping_review"]["verdict"])
        self.assertTrue(any("returned blocking" in item["message"] for item in receipt["errors"]))

    def test_delivery_skill_keeps_the_exact_pre_fleet_mapping(self) -> None:
        text = (ROOT / "skills" / "implement-spec" / "SKILL.md").read_text(encoding="utf-8")
        for expected in (
            "role: shaping-reviewer",
            "provider: openai",
            "engine: codex",
            "model: gpt-5.6-sol",
            "effort: xhigh",
            "service_tier: fast",
            "tools: repo-read, linear-read, github-read, session-log-read",
            "herdr-spawn ... --role shaping-reviewer -- codex -m gpt-5.6-sol -c model_reasoning_effort=xhigh -c service_tier=fast",
        ):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
