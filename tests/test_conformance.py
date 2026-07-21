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

    def test_workflow_spawns_workers_natively_through_admission_and_ack_echo_gates(self) -> None:
        # Decision 109 (role-runtime launch-correctness-path, role-worker-migration):
        # the Workflow spawns every worker pass natively through agent(); the retired
        # launcher's completed pass_result consumption path must not return, and raw
        # adapter files (agents/*.md) are never spawn inputs.
        text = (ROOT / "workflows/octo-loop-qa.js").read_text()
        for role in ("implementer", "code-reviewer", "qa-capture", "qa-reviewer"):
            self.assertIn(f"'{role}'", text)
        for stale in ("octo-lite-implementer", "octo-lite-reviewer", "octo-lite-code-reviewer"):
            self.assertNotIn(stale, text)
        self.assertIn("await agent(", text)
        for retired in ("pass_result", "assertPassReceipt", "assertBoundPassResult", "octo-launch"):
            self.assertNotIn(retired, text)
        self.assertNotIn("agents/", text)
        # The shared spawn path admits the role before agent() runs and verifies the
        # schema-forced ack echo before any mutation-phase advance, in that order.
        spawn = text[text.index("async function spawnWorker"):text.index("if (mode ===")]
        self.assertLess(spawn.index("assertAdmission("), spawn.index("await agent("))
        self.assertLess(spawn.index("await agent("), spawn.index("assertWorkerAckEcho("))

    def test_workflow_loop_fires_shaped_to_todo_before_any_delivery_spawn(self) -> None:
        # delivery-lifecycle delivery-entry-gate and linear-loop-fire-transition: at
        # Shaped the loop itself performs the one mechanical Shaped -> Todo fire through
        # octo-control linear-transition and verifies the Todo readback before spawning
        # any delivery worker; a delivery spawn attempted at Shaped without that prior
        # fire is rejected, and Shaped never moves directly to In Progress.
        text = (ROOT / "workflows/octo-loop-qa.js").read_text()
        self.assertIn("octo-control linear-transition", text)
        self.assertIn("--expected Shaped --target Todo", text)
        self.assertNotIn("--target In Progress", text)
        implement = text[text.index("if (mode === 'implement')"):text.index("if (mode === 'code-review')")]
        self.assertIn("=== 'Shaped'", implement)
        self.assertLess(implement.index("loopFire("), implement.index("spawnWorker('implementer'"))
        self.assertIn("delivery spawn at Shaped rejected", text)
        # The single ruling-15 orchestrator-performed manual Shaped -> Todo for TUR-447
        # is the one recorded non-recurring exception, held in a comment, never in code.
        self.assertIn("ruling-15", text)
        self.assertIn("TUR-447", text)

    def test_loop_skill_directs_journal_based_gating_with_no_worker_receipt(self) -> None:
        # Deterministic wiring check only (prompt-tdd-deterministic): the installed
        # loop skill directs journal-plus-ack-echo gating and keeps the retired
        # launcher binding surfaces retired.
        text = " ".join((ROOT / "skills/octo-lite-loop/SKILL.md").read_text().split())
        self.assertIn("workflow journal plus a schema-forced acknowledgment echo", text)
        self.assertIn("no worker TOML receipt", text)
        self.assertIn("No worker TOML receipt exists to pass anywhere", text)
        self.assertNotIn("recomputes the result binding", text)

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

    def test_root_instruction_law_has_no_stale_codex_toml_adapter_claim(self) -> None:
        text = (ROOT / "AGENTS.md").read_text()
        self.assertNotIn("Codex TOML", text)
        self.assertIn("no generated Codex custom-agent", text)
        self.assertIn("codex exec", text)

    def test_generic_spec_does_not_define_target_deployment_state_mapping(self) -> None:
        text = (ROOT / "spec/domains/operating-model.spec.html").read_text()
        self.assertIn("linear-deployment-target-owned", text)
        self.assertIn("target-owned Linear state mapping", text)
        for leak in ("zero percent live traffic", "deployed to staging and therefore"):
            self.assertNotIn(leak, text)


if __name__ == "__main__":
    unittest.main()
