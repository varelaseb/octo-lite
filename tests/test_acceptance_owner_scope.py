from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AcceptanceOwnerScopeTests(unittest.TestCase):
    def test_profile_binds_merge_to_current_human_instruction(self) -> None:
        text = (ROOT / "profile/AGENTS.md").read_text()
        self.assertIn("instruction to merge a named PR accepts that exact head", text)
        self.assertIn("active owning agent receiving that instruction", text)
        self.assertIn("Required failed checks remain blockers", text)

    def test_github_skill_does_not_import_meta_operator_ownership(self) -> None:
        text = (ROOT / "skills/octo-lite-github/SKILL.md").read_text()
        self.assertIn("active owning agent's mechanical execution", text)
        self.assertIn("human statement assigning the current lane ownership is sufficient", text)
        self.assertIn("Required failed checks remain blockers", text)

    def test_implement_spec_handles_acceptance_callback(self) -> None:
        text = (ROOT / "skills/implement-spec/SKILL.md").read_text()
        self.assertIn("## Human acceptance callback", text)
        self.assertIn("record acceptance, execute the merge", text)

    def test_merge_completes_worklane_without_follow_up_from_qa_gaps(self) -> None:
        for path in ("profile/AGENTS.md", "skills/implement-spec/SKILL.md",
                     "skills/octo-lite-github/SKILL.md", "agents/orchestrator.md"):
            text = " ".join((ROOT / path).read_text().split())
            self.assertIn("Done", text, path)
            self.assertIn("never infer, create, reopen, or drive follow-up", text, path)
        spec = (ROOT / "spec/domains/octo-lite.spec.html").read_text()
        self.assertIn('id="delivery-linear"', spec)


if __name__ == "__main__":
    unittest.main()
