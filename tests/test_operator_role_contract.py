"""
Operator role contract tests for GitHub issue #25.

Spec-derived TDD: each assertion maps to a ruling and an AC.
Run BEFORE prose edits to see RED, then AFTER to see GREEN.

AC-B is DEFERRED: reconcile sweep-line after #23 lands (no assertion here).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
META_OPERATOR = ROOT / "roles/meta-operator.md"
ORCHESTRATOR = ROOT / "roles/orchestrator.md"
LAUNCH_SKILL = ROOT / "skills/launch-meta-operator/SKILL.md"


def _text(path: Path) -> str:
    return path.read_text()


def _lower(path: Path) -> str:
    return path.read_text().lower()


class OperatorJobStatementTests(unittest.TestCase):
    """AC-A: ruling 1 -- job statement and twofold primary goal."""

    def test_meta_operator_states_job_find_needs_surface_unblock(self) -> None:
        # The operator job must be stated: find agent needs, surface, unblock.
        text = _lower(META_OPERATOR)
        self.assertIn("find", text)
        self.assertIn("surface", text)
        self.assertIn("unblock", text)

    def test_meta_operator_states_twofold_primary_goal_no_session_stranded(self) -> None:
        # Primary goal (a): no session left stranded unseen.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "strand" in text or "stranded" in text,
            "meta-operator.md must mention strand/stranded (no session stranded unseen)"
        )
        self.assertIn("unseen", text)

    def test_meta_operator_states_twofold_primary_goal_branch_merge_strategy(self) -> None:
        # Primary goal (b): branch/merge strategy across streams (conflicts, shared goals, gating).
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "branch" in text and "merge" in text,
            "meta-operator.md must state branch/merge strategy across streams"
        )
        self.assertIn("conflict", text)


class AttentionModelTests(unittest.TestCase):
    """AC-C: rulings 2+4 -- dialogue-based attention, retire focus/label model."""

    def test_meta_operator_attention_derives_from_dialogue_not_focus(self) -> None:
        # Ruling 4: attention = actual operator<->session dialogue, NOT pane/tab focus.
        text = _lower(META_OPERATOR)
        self.assertIn("dialogue", text)
        self.assertTrue(
            "pane" in text or "focus" in text or "tab" in text,
            "meta-operator.md must name the retired focus signal to contrast it"
        )

    def test_meta_operator_suppresses_surfacing_for_hand_driven_session(self) -> None:
        # Ruling 2: suppress surfacing/nag/interrupt while operator hand-drives a session.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "hand-driven" in text or "hand driven" in text or "hand-drive" in text or "driving" in text,
            "meta-operator.md must mention suppressing surfacing for a hand-driven session"
        )

    def test_meta_operator_on_leaving_dialogue_resume_or_surface(self) -> None:
        # Ruling 2: on operator leaving that dialogue, either let orchestrator resume
        # autonomously or surface its open needs.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "resume" in text or "autonomous" in text,
            "meta-operator.md must state: on leaving dialogue, let orchestrator resume or surface needs"
        )
        self.assertIn("open needs", text)

    def test_meta_operator_dialogue_attention_model_stated(self) -> None:
        # AC-C: the new dialogue-based attention model must be explicitly stated.
        # The prose must contrast dialogue vs focus/pane attention.
        text = _lower(META_OPERATOR)
        # Dialogue-based model is now stated.
        self.assertIn("dialogue", text)
        # NOT pane/tab focus -- the contrast must be stated.
        self.assertTrue(
            "not pane" in text or "not tab" in text or "not focus" in text or "not window" in text
            or "not pane/tab" in text,
            "meta-operator.md must explicitly contrast dialogue vs focus/pane/tab"
        )


class StrandAndDeliveryMonitoringTests(unittest.TestCase):
    """AC-D: rulings 5,6,7,10,11 -- strand, delivery-cadence, one-layer-down, escalation."""

    def test_meta_operator_monitors_orchestrators_one_layer_down(self) -> None:
        # Ruling 10: monitor ORCHESTRATORS only (one layer down), keyed on delivery.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "one layer" in text or "layer down" in text,
            "meta-operator.md must state monitoring is one layer down (orchestrators only)"
        )

    def test_meta_operator_states_strand_belief_vs_observable(self) -> None:
        # Ruling 6: strand = belief-vs-observable contradiction.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "belief" in text and "observable" in text,
            "meta-operator.md must state strand = belief vs observable contradiction"
        )

    def test_meta_operator_pokes_stale_orchestrator_to_investigate(self) -> None:
        # Ruling 10: orchestrator that has not delivered in hours is POKED to investigate.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "poke" in text or "poked" in text or "investigate" in text,
            "meta-operator.md must state: stale orchestrator is poked to investigate"
        )
        self.assertTrue(
            "hour" in text or "cadence" in text,
            "meta-operator.md must mention delivery cadence (hours threshold)"
        )

    def test_meta_operator_relaunches_dead_orchestrator(self) -> None:
        # Ruling 10: dead/unresponsive orchestrator is relaunched fresh.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "relaunch" in text or "relaunched" in text or "dead" in text,
            "meta-operator.md must state: dead orchestrator is relaunched fresh"
        )

    def test_meta_operator_surface_modal_phone_non_blocking(self) -> None:
        # Ruling 5: default surface = modal + phone notification, non-blocking.
        text = _lower(META_OPERATOR)
        self.assertIn("modal", text)
        self.assertIn("phone", text)
        self.assertIn("non-blocking", text)

    def test_meta_operator_escalation_trigger_post_dialogue_silence(self) -> None:
        # Ruling 7: escalation trigger = post-dialogue operator silence, lean, tuned by experiment.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "silence" in text or "post-dialogue" in text,
            "meta-operator.md must state escalation trigger is post-dialogue operator silence"
        )
        self.assertIn("lean", text)

    def test_orchestrator_rechecks_workers_on_poke(self) -> None:
        # Ruling 10 / AC-D: on operator poke, orchestrator re-checks its own workers.
        text = _lower(ORCHESTRATOR)
        self.assertTrue(
            "poke" in text or "investigate" in text,
            "orchestrator.md must state: on operator poke, re-check own workers"
        )

    def test_orchestrator_worker_liveness_is_orchestrators_job(self) -> None:
        # AC-D: worker-level liveness is the orchestrator's job (belief-vs-observable).
        text = _lower(ORCHESTRATOR)
        self.assertTrue(
            "belief" in text or "observable" in text or "liveness" in text,
            "orchestrator.md must state worker-level liveness / belief-vs-observable is its job"
        )


class AcceptanceLedgerTests(unittest.TestCase):
    """AC-E: acceptance-ledger recording as a bound step in the merge routine."""

    def test_meta_operator_merge_records_acceptance_ledger_artifact(self) -> None:
        # The merge routine must state it records acceptance-<id>.toml.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "acceptance-" in text or "acceptance ledger" in text,
            "meta-operator.md must state acceptance-<id>.toml ledger artifact is recorded"
        )

    def test_meta_operator_merge_references_spec_anchor(self) -> None:
        # Must reference spec anchor supervision-carve-out-instruction-gated.
        text = _lower(META_OPERATOR)
        self.assertIn("supervision-carve-out-instruction-gated", text)

    def test_meta_operator_merge_records_under_streams_dir(self) -> None:
        # Must state the control/streams dir.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "streams" in text or "control dir" in text or "control_dir" in text,
            "meta-operator.md must mention streams dir for acceptance ledger"
        )


class IntakeConfirmationTests(unittest.TestCase):
    """AC-F: intake-confirmation before dispatch."""

    def test_meta_operator_echoes_intake_for_confirmation(self) -> None:
        # Voice/paraphrased intake is echoed back as grounded target/scope.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "echo" in text or "echoed" in text,
            "meta-operator.md must state intake is echoed back"
        )

    def test_meta_operator_confirms_before_dispatch(self) -> None:
        # Confirmed before a lane is dispatched.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "confirm" in text or "confirmed" in text,
            "meta-operator.md must state confirmation before lane dispatch"
        )
        self.assertTrue(
            "dispatch" in text or "lane" in text,
            "meta-operator.md must mention dispatch / lane in intake confirmation context"
        )

    def test_meta_operator_intake_grounds_target_scope(self) -> None:
        # Must mention grounded target/scope.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "grounded" in text or "target" in text and "scope" in text,
            "meta-operator.md must state intake is echoed as grounded target/scope"
        )


class TransportDoctrineTests(unittest.TestCase):
    """AC-G: role-level transport doctrine."""

    def test_meta_operator_drains_outbox_each_wake(self) -> None:
        # Drain the outbox each wake.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "outbox" in text or "drain" in text,
            "meta-operator.md must state: drain the outbox each wake"
        )

    def test_meta_operator_delivery_is_ack_confirmed_not_exit_code(self) -> None:
        # Delivery is ack/observed-state confirmed, never the exit code.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "exit code" in text or "ack" in text or "observed-state" in text or "observed state" in text,
            "meta-operator.md must state delivery is ack/observed-state confirmed, not exit code"
        )

    def test_meta_operator_stalled_mandate_surfaced_not_assumed(self) -> None:
        # A stalled mandate is surfaced not assumed delivered.
        text = _lower(META_OPERATOR)
        self.assertTrue(
            "stalled" in text or "stall" in text,
            "meta-operator.md must state: stalled mandate is surfaced, not assumed delivered"
        )

    def test_meta_operator_transport_references_herdr_comms(self) -> None:
        # Must reference herdr-comms.
        text = _lower(META_OPERATOR)
        self.assertIn("herdr-comms", text)


class LaunchSkillAccuracyTests(unittest.TestCase):
    """AC-H: launch-meta-operator/SKILL.md path accuracy and tool-neutral sweep wording."""

    def test_launch_skill_references_real_script_path(self) -> None:
        # Must reference skills/launch-meta-operator/scripts/ paths.
        text = _text(LAUNCH_SKILL)
        self.assertIn("skills/launch-meta-operator/scripts/", text)

    def test_launch_skill_no_bare_scripts_prefix_for_launcher(self) -> None:
        # Must NOT use bare "scripts/launch-meta-operator.sh" (wrong path).
        text = _text(LAUNCH_SKILL)
        # Acceptable: any line that has the full path; unacceptable: bare scripts/ prefix only
        # We check that every launcher reference includes the full path.
        bare_refs = [
            line.strip() for line in text.splitlines()
            if re.search(r'\bscripts/launch-meta-operator\.sh\b', line)
            and 'skills/launch-meta-operator/scripts/' not in line
        ]
        self.assertEqual(
            [], bare_refs,
            f"launch-meta-operator.sh referenced with bare scripts/ prefix (wrong path): {bare_refs}"
        )

    def test_launch_skill_no_bare_handoff_script_prefix(self) -> None:
        # Must NOT use bare "scripts/handoff-meta-operator.sh" (wrong path).
        text = _text(LAUNCH_SKILL)
        bare_refs = [
            line.strip() for line in text.splitlines()
            if re.search(r'\bscripts/handoff-meta-operator\.sh\b', line)
            and 'skills/launch-meta-operator/scripts/' not in line
        ]
        self.assertEqual(
            [], bare_refs,
            f"handoff-meta-operator.sh referenced with bare scripts/ prefix (wrong path): {bare_refs}"
        )

    def test_launch_skill_sweep_wording_is_tool_neutral(self) -> None:
        # Pending #23: sweep-tool wording must be tool-neutral (e.g. "operator heartbeat sweep")
        # not hard-coding "operator-sweep" as the tool name.
        text = _text(LAUNCH_SKILL)
        # The phrase "runs operator-sweep directly" must be gone.
        self.assertNotIn("runs operator-sweep directly", text)
        # Must mention the sweep in a tool-neutral way.
        self.assertTrue(
            "heartbeat" in text.lower() or "heartbeat sweep" in text.lower() or "operator heartbeat" in text.lower(),
            "launch-meta-operator/SKILL.md must use tool-neutral sweep wording (e.g. 'operator heartbeat sweep')"
        )

    def test_launch_skill_no_hardcoded_operator_sweep_tool_name_in_timer_section(self) -> None:
        # The timer section must not hard-code "operator-sweep" as what the timer runs.
        text = _text(LAUNCH_SKILL)
        # Check specific sentence that is known to be wrong.
        self.assertNotIn("installs one lifecycle-bound host timer that runs `operator-sweep` directly", text)


# AC-B DEFERRED: no test for sweep-line reconcile; sequenced after #23 lands.
# (deferred: the contract Rule "On sweep, run operator-sweep" reconciles after #23 lands)


if __name__ == "__main__":
    unittest.main()
