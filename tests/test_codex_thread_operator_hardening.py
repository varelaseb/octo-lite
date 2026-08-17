"""Reshape-addendum reds for TUR-641 cycle-3.

Four seams the committed contract already names and the delivered code still
leaves open: reconciliation ordered BEFORE any owner-record commit, a CLOSED
live-Fable admission set, the ADR 0005 delivery surfaces, and handoff-artifact
provenance for successor readiness.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from octo_lite import runtime  # noqa: E402
from tests.test_codex_thread_operator_binding import (  # noqa: E402
    FABLE_ROUTE,
    THREAD,
    WORKSPACE,
    TakeoverCliHarness,
    digest_context,
    fable_owner,
)

CODEX_MODE = runtime.CODEX_OWNER_MODE


def refuse(owner):
    # One live source is unreadable, so this pass has no authoritative context.
    raise runtime.GateError("live source unreadable")


class PreCommitReconciliationTest(unittest.TestCase):
    """Seam: reconciliation runs BEFORE any owner-record commit, so a failed
    live read leaves no owner record and the session ordinary
    (operator-control activation-failure-ordinary, takeover-failure;
    role-runtime launch-codex-activation-failure)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.owner = self.base / "operator-owner.toml"
        self.control = self.base / "control"

    def test_activation_reconcile_failure_leaves_no_owner_record(self) -> None:
        with self.assertRaises(runtime.GateError):
            runtime.activate_codex_thread(
                self.owner,
                thread_id=THREAD,
                workspace=WORKSPACE,
                control_dir=str(self.control),
                reconcile=refuse,
            )
        self.assertFalse(
            self.owner.exists(),
            "an unreconciled activation must leave no owner record at all",
        )

    def test_takeover_reconcile_failure_leaves_the_prior_owner_byte_identical(self) -> None:
        self.control.mkdir()
        fable_owner(self.owner, self.control)
        before = self.owner.read_bytes()
        retired: list[str] = []

        with self.assertRaises(runtime.GateError):
            runtime.force_takeover_codex_thread(
                self.owner,
                thread_id=THREAD,
                workspace=WORKSPACE,
                reason="operator directed control transfer",
                context=digest_context(),
                verify_active_fable=lambda owner: {"session_running": True},
                retire_fable=lambda owner: retired.append(owner["owner_route"]) or {
                    "session_running": False,
                    "timer_present": False,
                },
                now=lambda: "2026-08-17T01:00:00Z",
                reconcile=refuse,
            )
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertEqual(retired, [], "an unreconciled takeover must not fence the Fable")
        self.assertFalse((self.control / "takeovers").exists())


class ClosedFableAdmissionTest(unittest.TestCase):
    """Seam: forced takeover admits only the dedicated Fable owner shape; an
    unrecognized owner mode is not a dedicated Fable
    (operator-control takeover-live-fable-only)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        self.control.mkdir()
        self.owner = self.base / "operator-owner.toml"
        self.retired: list[str] = []

    def takeover(self):
        return runtime.force_takeover_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            reason="operator directed control transfer",
            context=digest_context(),
            verify_active_fable=lambda owner: {"session_running": True},
            retire_fable=lambda owner: self.retired.append(owner["owner_route"]) or {
                "session_running": False,
                "timer_present": False,
            },
            now=lambda: "2026-08-17T01:00:00Z",
            reconcile=lambda owner: digest_context(),
        )

    def test_unknown_owner_mode_is_not_a_dedicated_fable(self) -> None:
        for mode in ("surrogate", "fable-bridge", "codex", "unknown"):
            with self.subTest(mode=mode):
                values = fable_owner(self.owner, self.control)
                self.owner.write_text(runtime._toml_document({**values, "owner_mode": mode}))
                before = self.owner.read_bytes()
                with self.assertRaises(runtime.GateError):
                    self.takeover()
                self.assertEqual(self.owner.read_bytes(), before)
                self.assertEqual(self.retired, [])

    def test_the_dedicated_fable_owner_shape_still_admits_takeover(self) -> None:
        fable_owner(self.owner, self.control)
        self.assertEqual(self.takeover()["outcome"], "takeover")


class LiveAgentStatusAdmissionTest(TakeoverCliHarness):
    """Seam: octo-control resolves an active Fable only from the four canonical
    live agent_status values; every other value fails closed
    (operator-control takeover-live-fable-only, message-eligibility-gate)."""

    def reset_owner(self) -> bytes:
        self.prior = fable_owner(self.owner_path, self.prior_control)
        takeovers = self.prior_control / "takeovers"
        for receipt in takeovers.glob("*.toml"):
            receipt.unlink()
        if self.call_log.exists():
            self.call_log.unlink()
        if self.stopped.exists():
            self.stopped.unlink()
        return self.owner_path.read_bytes()

    def test_uncanonical_agent_status_is_never_a_live_fable(self) -> None:
        for status in ("unknown", "zombie", "starting", "STOPPED", "Idle"):
            with self.subTest(status=status):
                before = self.reset_owner()
                self.agent = {"name": FABLE_ROUTE, "agent_status": status}
                with self.assertRaises(runtime.GateError):
                    self.takeover()
                self.assertNotIn("agent stop", self.calls())
                self.assertEqual(self.owner_path.read_bytes(), before)

    def test_every_canonical_live_status_admits_takeover(self) -> None:
        for status in ("working", "idle", "blocked", "done"):
            with self.subTest(status=status):
                self.reset_owner()
                self.agent = {"name": FABLE_ROUTE, "agent_status": status}
                result = self.takeover()
                self.assertEqual(result["outcome"], "takeover")
                self.assertIn("agent stop", self.calls())


class HandoffProvenanceTest(unittest.TestCase):
    """Seam: successor readiness comes only from the outgoing owner's own
    immutable handoff artifact, so an arbitrary file named like a revision
    creates no readiness and commits no transfer
    (operator-control handoff-artifact, activation-handoff-brief)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        (self.control / "handoffs").mkdir(parents=True)
        self.candidate_control = self.base / "codex-control"
        self.owner = self.base / "operator-owner.toml"
        self.prior = fable_owner(self.owner, self.control)
        self.handoff = self.control / "handoffs" / "0001.md"
        self.handoff.write_text("compact brief\n")
        self.foreign = self.base / "elsewhere" / "0001.md"
        self.foreign.parent.mkdir()
        self.foreign.write_text("compact brief\n")

    def activate(self, handoff: Path):
        return runtime.activate_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            handoff=str(handoff),
            reconcile=lambda owner: digest_context(),
        )

    def transfer(self, readiness: Path, handoff: Path):
        return runtime.transfer_owner(
            self.owner,
            self.prior["owner_session_id"],
            self.prior["owner_route"],
            0,
            THREAD,
            THREAD,
            1,
            str(self.control),
            caller=self.prior["owner_session_id"],
            handoff=handoff,
            successor_readiness_path=readiness,
            new_owner_mode=CODEX_MODE,
            new_workspace=WORKSPACE,
        )

    def test_a_foreign_revision_named_file_creates_no_readiness(self) -> None:
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.activate(self.foreign)
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse((self.candidate_control / "successor-ready.toml").exists())

    def test_transfer_refuses_a_handoff_outside_the_owner_control_tree(self) -> None:
        readiness = Path(self.activate(self.handoff)["successor_readiness"])
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(readiness, self.foreign)
        self.assertEqual(self.owner.read_bytes(), before)

        committed = self.transfer(readiness, self.handoff)
        self.assertEqual(committed["owner_session_id"], THREAD)
        self.assertEqual(committed["herdr_workspace"], WORKSPACE)


class Adr0005DeliverySurfaceTest(unittest.TestCase):
    """Seam: the ADR 0005 expected delivery surfaces
    (adr/0005 links-delivery-surfaces): the existing role human gate, installed
    profile guidance, and README usage."""

    def test_role_prose_carries_the_direct_human_forced_takeover_gate(self) -> None:
        prose = (ROOT / "roles/meta-operator.md").read_text().lower()
        self.assertIn("forced takeover", prose)
        self.assertIn("direct human instruction", prose)

    def test_installed_profile_guidance_names_current_thread_activation(self) -> None:
        profile = (ROOT / "profile/AGENTS.md").read_text()
        self.assertIn("Codex thread", profile)
        self.assertIn("forced takeover", profile)

    def test_readme_documents_activation_and_forced_takeover_usage(self) -> None:
        readme = (ROOT / "README.md").read_text()
        self.assertIn("activate-codex-thread-operator.sh", readme)
        self.assertIn("--force-takeover", readme)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
