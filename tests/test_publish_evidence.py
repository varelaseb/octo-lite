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
- Operator-visibility rendered-card verify: render-card.sh
"""


def _expected(issue="TUR-1"):
    return {
        "issue": issue,
        "pr": 29,
        "head": "a" * 40,
        "verdict": "clear",
        "story_ids": ["S1", "S2"],
        "criterion_coverage": "AC1-AC7",
    }


def _rendered(issue="TUR-1", **overrides):
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
    RENDERED operator card for the exact fields, failing loud on any gap."""

    def _scaffold(self, base: Path, *, agents_text=COMPLETE_AGENTS, issue="TUR-1", write_durable=True):
        target = base / "target"
        target.mkdir()
        (target / "AGENTS.md").write_text(agents_text)
        durable = base / "durable"
        (durable / "qa-verdicts").mkdir(parents=True)
        (durable / issue).mkdir(parents=True)  # served-evidence source dir
        (durable / issue / "index.html").write_text("<html>card</html>")
        if write_durable:
            (durable / "qa-verdicts" / f"{issue}.json").write_text(
                json.dumps({"issue": issue, "verdict": "clear"})
            )
        return target, durable

    # --- AC4 (red4): served-evidence symlink ---

    def test_missing_served_link_fails_loud_and_helper_creates_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            served_root = target / "served"
            link = served_root / "TUR-1"
            self.assertFalse(link.exists())  # missing before publish

            result = publish_evidence(
                issue="TUR-1", agents_path=target / "AGENTS.md",
                durable_home=durable, target_root=target, expected=_expected(),
                run_verify=lambda **kw: _rendered(),
            )
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
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=lambda **kw: _rendered(),
                )
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

            publish_evidence(
                issue="TUR-1", agents_path=target / "AGENTS.md",
                durable_home=durable, target_root=target, expected=_expected(),
                run_verify=lambda **kw: _rendered(),
            )
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
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=lambda **kw: _rendered(),
                )
            self.assertIn("durable verdict card missing", str(caught.exception).lower())

    # --- AC6 (red6): rendered-card readback ---

    def test_unreadable_rendered_card_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)

            def bad_verify(**kw):
                return "not a card"  # unreadable

            with self.assertRaises(GateError) as caught:
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=bad_verify,
                )
            self.assertIn("unreadable", str(caught.exception).lower())

    def test_rendered_card_field_mismatch_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            with self.assertRaises(GateError) as caught:
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=lambda **kw: _rendered(head="b" * 40),  # HEAD mismatch
                )
            self.assertIn("mismatch", str(caught.exception).lower())

    def test_rendered_card_missing_field_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            incomplete = _rendered()
            del incomplete["criterion_coverage"]
            with self.assertRaises(GateError) as caught:
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=lambda **kw: incomplete,
                )
            self.assertIn("missing fields", str(caught.exception).lower())

    def test_complete_and_readable_card_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            result = publish_evidence(
                issue="TUR-1", agents_path=target / "AGENTS.md",
                durable_home=durable, target_root=target, expected=_expected(),
                run_verify=lambda **kw: _rendered(),
            )
            self.assertTrue(result["ready"])
            for field in ("issue", "pr", "head", "verdict", "story_ids", "criterion_coverage"):
                self.assertIn(field, result["rendered"])

    # --- adv1: durable/index card cross-check (caller-vs-caller loophole) ---

    def test_caller_verdict_mismatch_with_durable_card_fails_loud(self) -> None:
        # adv1: the durable qa-verdicts card says verdict=blocking, the caller
        # passes verdict=clear, and a naive echo-style render command returns the
        # caller's clear back. The old readback (caller expected vs render output)
        # is caller-vs-caller and reports ready:true while the operator-read index
        # card actually says blocking. The helper must cross-check the durable
        # source card and fail LOUD on the caller/durable verdict mismatch.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base, write_durable=False)
            durable_card = durable / "qa-verdicts" / "TUR-1.json"
            durable_card.write_text(json.dumps({
                "issue": "TUR-1",
                "pr": 29,
                "head": "a" * 40,
                "verdict": "blocking",
                "story_ids": ["S1", "S2"],
                "criterion_coverage": "AC1-AC7",
            }))

            def echo_render(**kw):
                # A target render command that merely echoes the caller's expected
                # fields, reducing the render readback to caller-vs-caller.
                return _expected()  # verdict=clear, matching the caller

            with self.assertRaises(GateError) as caught:
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=echo_render,
                )
            message = str(caught.exception).lower()
            self.assertIn("durable", message)
            self.assertIn("verdict", message)

    def test_caller_field_matches_durable_card_is_ready(self) -> None:
        # The complementary green: caller-supplied verified fields agreeing with
        # the durable/index card publishes ready.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base, write_durable=False)
            durable_card = durable / "qa-verdicts" / "TUR-1.json"
            durable_card.write_text(json.dumps({
                "issue": "TUR-1",
                "pr": 29,
                "head": "a" * 40,
                "verdict": "clear",
                "story_ids": ["S1", "S2"],
                "criterion_coverage": "AC1-AC7",
            }))
            result = publish_evidence(
                issue="TUR-1", agents_path=target / "AGENTS.md",
                durable_home=durable, target_root=target, expected=_expected(),
                run_verify=lambda **kw: _rendered(),
            )
            self.assertTrue(result["ready"])

    def test_index_card_diverging_from_durable_source_fails_loud(self) -> None:
        # adv1: the operator-read INDEX card the helper wrote must equal the
        # DURABLE source it was sourced from. If they diverge (split-brain) the
        # publish fails loud rather than reporting ready on a stale index.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base, write_durable=False)
            durable_card = durable / "qa-verdicts" / "TUR-1.json"
            durable_card.write_text(json.dumps(_expected()))

            def tamper_render(**kw):
                # After the helper wrote the index from the durable source, tamper
                # the operator-read index card so it diverges from durable.
                index_card = target / "gallery" / "qa-verdicts" / "TUR-1.json"
                index_card.write_text(json.dumps({"issue": "TUR-1", "verdict": "blocking"}))
                return _rendered()

            with self.assertRaises(GateError) as caught:
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=tamper_render,
                )
            self.assertIn("index card", str(caught.exception).lower())

    # --- AC7 (red7): target surface config required, no hard-coded path ---

    def test_incomplete_surface_declaration_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # Declare served root + verdict index but OMIT the rendered-card verify.
            incomplete_agents = (
                "# Target\n\n"
                "- Operator-visibility served root: served\n"
                "- Operator-visibility verdict index: gallery/qa-verdicts\n"
            )
            target, durable = self._scaffold(base, agents_text=incomplete_agents)
            with self.assertRaises(GateError) as caught:
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=lambda **kw: _rendered(),
                )
            self.assertIn("incompletely declared", str(caught.exception).lower())
            self.assertIn("rendered-card verify", str(caught.exception).lower())

    def test_todo_placeholder_surface_declaration_fails_loud(self) -> None:
        # adv3: the target-init template ships the three signals with `TODO: ...`
        # placeholder values. A freshly-copied-but-unfilled AGENTS.md must fail
        # LOUD at the surface-declaration gate, not silently pass read and only
        # break later at the filesystem/render step.
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
            "- Operator-visibility verdict index: gallery/qa-verdicts\n"
            "- Operator-visibility rendered-card verify: TODO: command emitting the card\n"
        )
        with self.assertRaises(GateError) as caught:
            read_surface_declaration(agents)
        self.assertIn("incompletely declared", str(caught.exception).lower())
        self.assertIn("rendered-card verify", str(caught.exception).lower())

    def test_missing_agents_file_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target, durable = self._scaffold(base)
            (target / "AGENTS.md").unlink()
            with self.assertRaises(GateError) as caught:
                publish_evidence(
                    issue="TUR-1", agents_path=target / "AGENTS.md",
                    durable_home=durable, target_root=target, expected=_expected(),
                    run_verify=lambda **kw: _rendered(),
                )
            self.assertIn("agents.md missing", str(caught.exception).lower())

    def test_surface_declaration_reads_all_three_target_declared_fields(self) -> None:
        declaration = read_surface_declaration(COMPLETE_AGENTS)
        self.assertEqual("served", declaration["served_root"])
        self.assertEqual("gallery/qa-verdicts", declaration["verdict_index"])
        self.assertEqual("render-card.sh", declaration["rendered_verify"])

    def test_target_init_template_declares_all_three_surface_signals(self) -> None:
        # AC7 (qa-publication-surface-target): the target-init AGENTS.md template
        # the shaper copies declares all three operator-visibility surface signals,
        # so a freshly initialized target cannot ship without the surface contract.
        from octo_lite import publish as pub
        template = (
            Path(__file__).resolve().parents[1]
            / "skills/octo-lite-issue-shaper/assets/repo-agents.md"
        ).read_text()
        for signal in (
            pub.SURFACE_SERVED_ROOT_SIGNAL,
            pub.SURFACE_VERDICT_INDEX_SIGNAL,
            pub.SURFACE_RENDERED_VERIFY_SIGNAL,
        ):
            self.assertIn(signal, template)

    def test_no_hard_coded_uploads_path_in_publish_module(self) -> None:
        # qa-publication-surface-target: octo-lite owns mechanism only; the
        # concrete surface is target-declared. No Turbo/codex-uploads path is
        # baked into the helper.
        source = (Path(__file__).resolve().parents[1] / "octo_lite" / "publish.py").read_text()
        self.assertNotIn("codex-uploads", source)
        self.assertNotIn("/root/", source)


if __name__ == "__main__":
    unittest.main()
