from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from octo_lite.runtime import GateError
from octo_lite.publish import publish_evidence, read_surface_declaration


COMPLETE_AGENTS = """# Target AGENTS.md

## Operator-visibility surface

- Operator-visibility served root: served
- Operator-visibility verdict index: gallery/qa-verdicts
"""


def _durable_card(issue="TUR-1", **overrides):
    card = {
        "issue": issue,
        "pr": 29,
        "head": "a" * 40,
        "verdict": "clear",
        "story_ids": ["S1", "S2"],
        "criterion_coverage": "AC1-AC7",
    }
    card.update(overrides)
    return card


class PublishEvidenceTests(unittest.TestCase):
    """AC4-AC7: the SOLE writer of an issue's operator-visibility surface, reading
    the target-declared surface from AGENTS.md, creating+verifying the served
    link, writing the verdict card from the ONE durable home, and reading back the
    WRITTEN operator-read index card for the exact fields, failing loud on any
    gap."""

    def _scaffold(
        self, base: Path, *, agents_text=COMPLETE_AGENTS, issue="TUR-1",
        write_durable=True, durable_card=None,
    ):
        target = base / "target"
        target.mkdir()
        (target / "AGENTS.md").write_text(agents_text)
        durable = base / "durable"
        (durable / "qa-verdicts").mkdir(parents=True)
        (durable / issue).mkdir(parents=True)  # served-evidence source dir
        (durable / issue / "index.html").write_text("<html>card</html>")
        if write_durable:
            card = durable_card if durable_card is not None else _durable_card(issue)
            (durable / "qa-verdicts" / f"{issue}.json").write_text(json.dumps(card))
        return target, durable

    def _publish(self, target, durable, issue="TUR-1"):
        return publish_evidence(
            issue=issue, agents_path=target / "AGENTS.md",
            durable_home=durable, target_root=target,
        )

    # --- AC4 (red4): served-evidence symlink ---

    def test_missing_served_link_fails_loud_and_helper_creates_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            served_root = target / "served"
            link = served_root / "TUR-1"
            self.assertFalse(link.exists())  # missing before publish

            result = self._publish(target, durable)
            self.assertTrue(link.is_symlink())
            self.assertTrue(link.resolve().exists())
            self.assertEqual(str(link), result["served_link"])
            self.assertTrue(result["ready"])

    def test_missing_served_evidence_source_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            # Remove the served-evidence source dir so the link would dangle.
            import shutil
            shutil.rmtree(durable / "TUR-1")
            with self.assertRaises(GateError) as caught:
                self._publish(target, durable)
            self.assertIn("served-evidence source", str(caught.exception).lower())

    # --- AC5 (red5): verdict card single-writer / single durable store ---

    def test_verdict_only_in_durable_home_then_helper_writes_operator_read_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            index_card = target / "gallery" / "qa-verdicts" / "TUR-1.json"
            durable_card = durable / "qa-verdicts" / "TUR-1.json"
            # Before publish: the card exists ONLY in the durable home; the
            # operator-read index location is empty.
            self.assertTrue(durable_card.is_file())
            self.assertFalse(index_card.exists())

            self._publish(target, durable)
            # After publish: the operator-read index carries the card, sourced from
            # the durable home; exactly ONE durable store exists.
            self.assertTrue(index_card.is_file())
            self.assertEqual(json.loads(durable_card.read_text()), json.loads(index_card.read_text()))
            durable_stores = list((durable).glob("qa-verdicts/*.json"))
            self.assertEqual(1, len(durable_stores))

    def test_missing_durable_verdict_card_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base, write_durable=False)
            with self.assertRaises(GateError) as caught:
                self._publish(target, durable)
            self.assertIn("durable verdict card missing", str(caught.exception).lower())

    # --- AC6 (red6): written-card readback ---

    def test_written_index_card_missing_required_field_is_not_ready(self) -> None:
        # The durable card (single source) lacks a required field, so the WRITTEN
        # operator-read index card lacks it too; readback must fail loud.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            incomplete = _durable_card()
            del incomplete["criterion_coverage"]
            target, durable = self._scaffold(base, durable_card=incomplete)
            with self.assertRaises(GateError) as caught:
                self._publish(target, durable)
            self.assertIn("missing fields", str(caught.exception).lower())

    def test_written_index_card_issue_mismatch_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base, durable_card=_durable_card(issue="OTHER-9"))
            with self.assertRaises(GateError) as caught:
                self._publish(target, durable)
            self.assertIn("issue mismatch", str(caught.exception).lower())

    def test_happy_path_writes_readable_index_card_with_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            result = self._publish(target, durable)
            self.assertTrue(result["ready"])
            index_card = Path(result["verdict_index_card"])
            # The written operator-read card is readable JSON carrying all 6 fields.
            written = json.loads(index_card.read_text())
            for field in ("issue", "pr", "head", "verdict", "story_ids", "criterion_coverage"):
                self.assertIn(field, written)
                self.assertIn(field, result["readback"])
            self.assertEqual("TUR-1", written["issue"])

    # --- AC7 (red7): target surface config required, no hard-coded path ---

    def test_incomplete_surface_declaration_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # Declare served root but OMIT the verdict index.
            incomplete_agents = (
                "# Target\n\n"
                "- Operator-visibility served root: served\n"
            )
            target, durable = self._scaffold(base, agents_text=incomplete_agents)
            with self.assertRaises(GateError) as caught:
                self._publish(target, durable)
            self.assertIn("incompletely declared", str(caught.exception).lower())
            self.assertIn("verdict index", str(caught.exception).lower())

    def test_todo_placeholder_surface_declaration_fails_loud(self) -> None:
        # adv3: the target-init template ships the surface signals with `TODO: ...`
        # placeholder values. A freshly-copied-but-unfilled AGENTS.md must fail
        # LOUD at the surface-declaration gate, not silently pass read and only
        # break later at the filesystem step.
        placeholder_agents = (
            Path(__file__).resolve().parents[1]
            / "skills/octo-lite-issue-shaper/assets/repo-agents.md"
        ).read_text()
        with self.assertRaises(GateError) as caught:
            read_surface_declaration(placeholder_agents)
        self.assertIn("incompletely declared", str(caught.exception).lower())

    def test_todo_placeholder_single_signal_fails_loud(self) -> None:
        # A single unfilled TODO placeholder value is rejected as not-declared.
        agents = (
            "# Target\n\n"
            "- Operator-visibility served root: served\n"
            "- Operator-visibility verdict index: TODO: operator-read verdict-index dir\n"
        )
        with self.assertRaises(GateError) as caught:
            read_surface_declaration(agents)
        self.assertIn("incompletely declared", str(caught.exception).lower())
        self.assertIn("verdict index", str(caught.exception).lower())

    def test_missing_agents_file_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            (target / "AGENTS.md").unlink()
            with self.assertRaises(GateError) as caught:
                self._publish(target, durable)
            self.assertIn("agents.md missing", str(caught.exception).lower())

    def test_surface_declaration_reads_both_target_declared_fields(self) -> None:
        declaration = read_surface_declaration(COMPLETE_AGENTS)
        self.assertEqual("served", declaration["served_root"])
        self.assertEqual("gallery/qa-verdicts", declaration["verdict_index"])
        self.assertNotIn("rendered_verify", declaration)

    def test_target_init_template_declares_both_surface_signals(self) -> None:
        # AC7 (qa-publication-surface-target): the target-init AGENTS.md template
        # the shaper copies declares both operator-visibility surface signals, so a
        # freshly initialized target cannot ship without the surface contract.
        from octo_lite import publish as pub
        template = (
            Path(__file__).resolve().parents[1]
            / "skills/octo-lite-issue-shaper/assets/repo-agents.md"
        ).read_text()
        for signal in (
            pub.SURFACE_SERVED_ROOT_SIGNAL,
            pub.SURFACE_VERDICT_INDEX_SIGNAL,
        ):
            self.assertIn(signal, template)
        # The retired rendered-card verify signal must be gone from the template.
        self.assertNotIn("rendered-card verify", template)

    def test_no_hard_coded_uploads_path_in_publish_module(self) -> None:
        # qa-publication-surface-target: octo-lite owns mechanism only; the
        # concrete surface is target-declared. No Turbo/codex-uploads path is
        # baked into the helper.
        source = (Path(__file__).resolve().parents[1] / "octo_lite" / "publish.py").read_text()
        self.assertNotIn("codex-uploads", source)
        self.assertNotIn("/root/", source)


if __name__ == "__main__":
    unittest.main()
