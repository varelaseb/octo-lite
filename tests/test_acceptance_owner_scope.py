from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AcceptanceOwnerScopeTests(unittest.TestCase):
    def test_profile_binds_merge_to_current_human_instruction(self) -> None:
        text = (ROOT / "profile/AGENTS.md").read_text()
        self.assertIn("instruction to merge a named PR accepts that exact head", text)
        self.assertIn("active owning agent receiving that instruction", text)
        self.assertIn("does not consult\n  `operator-owner.toml`", text)
        self.assertIn("Required failed checks remain blockers", text)

    def test_github_skill_does_not_import_meta_operator_ownership(self) -> None:
        text = (ROOT / "skills/octo-lite-github/SKILL.md").read_text()
        self.assertIn("active owning agent's mechanical execution", text)
        self.assertIn("human statement assigning the current lane ownership is sufficient", text)
        self.assertIn("Do not consult\n  `operator-owner.toml`", text)
        self.assertIn("Required failed checks remain blockers", text)

    def test_implement_spec_handles_acceptance_callback(self) -> None:
        text = (ROOT / "skills/implement-spec/SKILL.md").read_text()
        self.assertIn("## Human acceptance callback", text)
        self.assertIn("record acceptance, execute the merge", text)
        self.assertIn("Do not consult `operator-owner.toml`", text)

    def test_canonical_specs_scope_the_pointer_to_meta_operator_control(self) -> None:
        delivery = (ROOT / "spec/domains/delivery-lifecycle.spec.html").read_text()
        operator = (ROOT / "spec/domains/operator-control.spec.html").read_text()
        self.assertIn('id="linear-acceptance-owner-pointer"', delivery)
        self.assertIn("Ordinary PR acceptance and merge never read or mutate", delivery)
        self.assertIn('id="handoff-owner-scope"', operator)
        self.assertIn("never an acceptance or merge authority gate", operator)
        self.assertIn('id="stream-mutation-not-merge"', operator)


if __name__ == "__main__":
    unittest.main()
