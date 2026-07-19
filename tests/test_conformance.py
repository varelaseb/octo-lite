from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_TEXT = (ROOT / "profile", ROOT / "roles", ROOT / "skills", ROOT / "workflows")


class CutoverConformanceTests(unittest.TestCase):
    def test_every_skill_has_compact_style_contract(self) -> None:
        skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertTrue(skills)
        for path in skills:
            text = path.read_text()
            self.assertIn("Be extremely concise. Sacrifice grammar for the sake of concision.", text, path.name)
            self.assertIn("No em-dashes or en-dashes. Ever.", text, path.name)

    def test_herdr_comms_skill_states_ack_only_delivery_wiring(self) -> None:
        text = (ROOT / "skills/herdr-comms/SKILL.md").read_text()
        self.assertIn("leaving the message pending", text)
        self.assertIn("Queued and pending are not acknowledged or", text)
        self.assertIn("never re-pastes text", text)

    def test_qa_evidence_capture_skill_states_screenshot_default_wiring(self) -> None:
        text = (ROOT / "skills/qa-evidence-capture/SKILL.md").read_text()
        self.assertIn("Screenshots are the default proof", text)
        self.assertIn("Video only when", text)
        self.assertIn("Backend-only work skips browser capture", text)

    def test_active_instructions_have_no_unicode_dashes_or_target_leaks(self) -> None:
        forbidden = ("Turbo-Outreach", "TopicFinder", "codex-uploads", "Notion")
        for root in ACTIVE_TEXT:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".md", ".toml", ".yaml", ".js", ".mjs"}:
                    continue
                text = path.read_text()
                self.assertNotIn("\u2013", text, str(path))
                self.assertNotIn("\u2014", text, str(path))
                for token in forbidden:
                    self.assertNotIn(token, text, str(path))

    def test_issue_shaper_is_progressive_not_a_monolith(self) -> None:
        lines = (ROOT / "skills/octo-lite-issue-shaper/SKILL.md").read_text().splitlines()
        self.assertLessEqual(len(lines), 160)

    def test_workflow_gates_generated_role_names_and_never_calls_agent(self) -> None:
        text = (ROOT / "workflows/octo-loop-qa.js").read_text()
        for role in ("implementer", "code-reviewer", "qa-capture", "qa-reviewer"):
            self.assertIn(f"'{role}'", text)
        for stale in ("octo-lite-implementer", "octo-lite-reviewer", "octo-lite-code-reviewer"):
            self.assertNotIn(stale, text)
        # octo-launch launch is the sole LLM execution; this Workflow only gates its
        # already-completed, receipt-bound pass_result. It must never spawn a second worker.
        self.assertNotIn("agent(", text)
        self.assertIn("assertBoundPassResult", text)

    def test_install_is_symlink_only_and_checkable(self) -> None:
        installer = ROOT / "scripts/install-octo-lite"
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td)
            subprocess.run([str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True)
            subprocess.run([str(installer), "--prefix", str(prefix), "--check"], check=True)
            self.assertTrue((prefix / ".codex/AGENTS.md").is_symlink())
            self.assertTrue((prefix / ".claude/CLAUDE.md").is_symlink())
            self.assertTrue((prefix / ".claude/workflows/octo-loop-qa.js").is_symlink())
            self.assertEqual((ROOT / "roles").resolve(), (prefix / ".claude/octo-lite/roles").resolve())
            self.assertEqual((ROOT / "skills/tdd").resolve(), (prefix / ".codex/skills/tdd").resolve())

    LEGACY_LINKS = (
        ".codex/octo-lite-role-skills.json",
        ".claude/agents/octo-lite-implementer.md",
        ".claude/agents/octo-lite-reviewer.md",
        ".codex/agents/octo-lite-implementer.toml",
        ".codex/agents/octo-lite-reviewer.toml",
    )

    def test_install_migrates_known_dangling_or_repo_owned_legacy_links(self) -> None:
        installer = ROOT / "scripts/install-octo-lite"
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td)
            dangling = prefix / self.LEGACY_LINKS[0]
            dangling.parent.mkdir(parents=True, exist_ok=True)
            dangling.symlink_to(ROOT / "role-skills.json")
            for relative in self.LEGACY_LINKS[1:]:
                target = prefix / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(ROOT / "README.md")

            subprocess.run([str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True)
            for relative in self.LEGACY_LINKS:
                path = prefix / relative
                self.assertFalse(path.is_symlink() or path.exists(), relative)

            subprocess.run([str(installer), "--prefix", str(prefix), "--check"], check=True, capture_output=True, text=True)

    def test_install_check_rejects_a_leftover_legacy_link(self) -> None:
        installer = ROOT / "scripts/install-octo-lite"
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td)
            subprocess.run([str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True)
            leftover = prefix / self.LEGACY_LINKS[0]
            leftover.parent.mkdir(parents=True, exist_ok=True)
            leftover.symlink_to(ROOT / "README.md")
            result = subprocess.run(
                [str(installer), "--prefix", str(prefix), "--check"], capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("legacy", result.stderr.lower())

    def test_install_leaves_an_unrelated_non_symlink_file_at_a_legacy_path_untouched(self) -> None:
        installer = ROOT / "scripts/install-octo-lite"
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td)
            unrelated = prefix / self.LEGACY_LINKS[0]
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_text("not ours\n")
            subprocess.run([str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True)
            self.assertTrue(unrelated.is_file())
            self.assertFalse(unrelated.is_symlink())
            self.assertEqual("not ours\n", unrelated.read_text())

    CODEX_AGENT_LEGACY_LINKS = tuple(
        f".codex/agents/{role}.toml"
        for role in (
            "meta-operator", "orchestrator", "shaping-reviewer", "implementer",
            "code-reviewer", "qa-capture", "qa-reviewer", "reconciler",
        )
    )

    def test_install_migrates_dangling_codex_role_adapter_links_for_all_eight_roles(self) -> None:
        # Codex custom agents are removed: agents/<role>.toml no longer exists, so
        # every previously installed per-role Codex adapter link is now dangling.
        # Install must migrate each of the eight exact former names and never touch
        # an unrelated file that happens to sit at one of those paths.
        installer = ROOT / "scripts/install-octo-lite"
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td)
            for relative in self.CODEX_AGENT_LEGACY_LINKS:
                target = prefix / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                # agents/<role>.toml no longer exists at all, so a real prior
                # install's link at this exact name is now dangling.
                target.symlink_to(ROOT / "agents" / Path(relative).name)

            unrelated = prefix / ".codex/agents/unrelated-role.toml"
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_text("not ours\n")

            subprocess.run([str(installer), "--prefix", str(prefix)], check=True, capture_output=True, text=True)
            for relative in self.CODEX_AGENT_LEGACY_LINKS:
                path = prefix / relative
                self.assertFalse(path.is_symlink() or path.exists(), relative)
            self.assertTrue(unrelated.is_file())
            self.assertFalse(unrelated.is_symlink())
            self.assertEqual("not ours\n", unrelated.read_text())

            subprocess.run([str(installer), "--prefix", str(prefix), "--check"], check=True, capture_output=True, text=True)

    def test_repo_claude_entrypoint_is_relative_symlink(self) -> None:
        entry = ROOT / "CLAUDE.md"
        self.assertTrue(entry.is_symlink())
        self.assertEqual(Path("AGENTS.md"), entry.readlink())

    def test_generic_spec_does_not_define_target_deployment_state_mapping(self) -> None:
        text = (ROOT / "spec/domains/operating-model.spec.html").read_text()
        self.assertIn("linear-deployment-target-owned", text)
        self.assertIn("target-owned Linear state mapping", text)
        for leak in ("zero percent live traffic", "deployed to staging and therefore"):
            self.assertNotIn(leak, text)


if __name__ == "__main__":
    unittest.main()
