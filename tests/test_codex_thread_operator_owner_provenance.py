"""Regression reds for the TUR-641 cycle-6 blocking code-review findings.

Two seams the committed contract already names and the delivered code still
leaves open.

Target 1: the atomic owner transfer trusts a caller-supplied readiness path after
checking only field equality and digest SHAPE, so a fully shaped hand-written
readiness TOML transfers authority to a thread that never activated. Codex
successor readiness must instead be bound to the activation itself: the record
lives at the one location DERIVED from the owner record in force, only the
activation holding the owner lock writes it, and no other candidate can displace
it (operator-control activation-handoff-brief, activation-distinct-thread,
handoff-artifact, activation-no-new-auth).

Target 2: the forced-takeover active-Fable proof resolves the owner receipt only
under the invariant control directory, while a lawful Fable handoff stores the
successor's receipt under the state root's own operators/<route> directory and
preserves that control directory. The proof therefore verifies a stale location
and never the CURRENT owner's receipt (operator-control
takeover-live-fable-only, handoff-launcher-pre-derive).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workflows" / "lib"))

from octo_lite import runtime  # noqa: E402
from tests.test_codex_thread_operator_binding import (  # noqa: E402
    FABLE_ROUTE,
    FABLE_SESSION,
    OTHER_THREAD,
    THREAD,
    WORKSPACE,
    TakeoverCliHarness,
    digest_context,
    fable_owner,
)
from tests.test_codex_thread_operator_contract import canonical_fable_receipt  # noqa: E402

CODEX_MODE = runtime.CODEX_OWNER_MODE

SUCCESSOR_SESSION = "fable-session-2"
SUCCESSOR_ROUTE = "operator-fable-2"


class ActivationBoundReadinessTest(unittest.TestCase):
    """Seam: Codex successor readiness is the activation's own record at the one
    derived location, so a hand-written readiness file transfers nothing and no
    second candidate can displace the record a verified activation wrote
    (operator-control activation-handoff-brief, activation-distinct-thread,
    handoff-artifact)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        (self.control / "handoffs").mkdir(parents=True)
        self.handoff = self.control / "handoffs" / "0001.md"
        self.handoff.write_text("compact brief\n")
        self.candidate_control = self.base / "codex-control"
        self.owner = self.base / "operator-owner.toml"
        fable_owner(self.owner, self.control)

    def activate(self, *, thread_id: str = THREAD):
        return runtime.activate_codex_thread(
            self.owner,
            thread_id=thread_id,
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            handoff=str(self.handoff),
            reconcile=lambda owner: digest_context(),
        )

    def derived_readiness(self) -> Path:
        # Derived exactly like the immutable handoff artifact it answers: from the
        # owner record in force plus the next revision, never from the candidate.
        return self.control / "handoffs" / "0001.ready.toml"

    def transfer(self, readiness: Path, *, thread_id: str = THREAD):
        return runtime.transfer_owner(
            self.owner,
            FABLE_SESSION,
            FABLE_ROUTE,
            0,
            thread_id,
            thread_id,
            1,
            str(self.control),
            caller=FABLE_SESSION,
            handoff=self.handoff,
            successor_readiness_path=readiness,
            new_owner_mode=CODEX_MODE,
            new_workspace=WORKSPACE,
        )

    def forge(self, path: Path, *, thread_id: str = THREAD) -> Path:
        # Every field the transfer validates, fully shaped: the exact thread, the
        # exact revision, the outgoing owner's own handoff artifact with its real
        # digest, the declared mode, the verified workspace, the complete source
        # list, and one digest-bound reference per source. No activation ever ran.
        context = digest_context()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            runtime._toml_document(
                {
                    "schema_version": 1,
                    "session_id": thread_id,
                    "handoff_revision": 1,
                    "handoff_artifact": str(self.handoff.resolve()),
                    "handoff_digest": runtime.exact_fingerprint(self.handoff.read_text()),
                    "owner_mode": CODEX_MODE,
                    "herdr_workspace": WORKSPACE,
                    "context_sources": list(runtime.CODEX_CONTEXT_SOURCES),
                    "context_references": [
                        context[source] for source in runtime.CODEX_CONTEXT_SOURCES
                    ],
                }
            )
        )
        return path

    def test_activation_writes_readiness_at_the_derived_location(self) -> None:
        pending = self.activate()
        self.assertEqual(pending["outcome"], "pending")
        self.assertEqual(Path(pending["successor_readiness"]), self.derived_readiness())
        self.assertTrue(self.derived_readiness().is_file())

    def test_transfer_refuses_a_hand_written_readiness_file(self) -> None:
        forged = self.forge(self.base / "forged-ready.toml")
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(forged)
        self.assertEqual(
            self.owner.read_bytes(),
            before,
            "a readiness file no activation wrote transfers no authority",
        )

        committed = self.transfer(Path(self.activate()["successor_readiness"]))
        self.assertEqual(committed["owner_session_id"], THREAD)
        self.assertEqual(committed["herdr_workspace"], WORKSPACE)

    def test_a_second_candidate_cannot_displace_the_activated_readiness(self) -> None:
        readiness = Path(self.activate()["successor_readiness"])
        bytes_before = readiness.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.activate(thread_id=OTHER_THREAD)
        self.assertEqual(
            readiness.read_bytes(),
            bytes_before,
            "the revision slot belongs to the thread that activated",
        )

        # The distinct thread inherits nothing: it cannot transfer authority to
        # itself with the other candidate's readiness, nor by writing its own.
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(readiness, thread_id=OTHER_THREAD)
        self.assertEqual(self.owner.read_bytes(), before)

    def test_the_same_thread_may_reactivate_and_refresh_its_readiness(self) -> None:
        first = Path(self.activate()["successor_readiness"])
        self.handoff.write_text("revised brief\n")
        second = Path(self.activate()["successor_readiness"])
        self.assertEqual(first, second)
        committed = self.transfer(second)
        self.assertEqual(committed["owner_session_id"], THREAD)


class CurrentOwnerReceiptLocationTest(TakeoverCliHarness):
    """Seam: the forced-takeover active-Fable proof resolves the CURRENT owner's
    receipt, including the lawful-handoff location a Fable successor's receipt
    lives in, and fails closed when the resolved receipt does not name the live
    owner session (operator-control takeover-live-fable-only, takeover-failure)."""

    def handed_off_owner(self, *, receipt_session: str) -> None:
        """The owner record a lawful Fable-to-Fable handoff leaves behind.

        The successor holds authority with its own session and route, the control
        directory stays invariant, and the successor's persistent launch receipt
        lives under the state root's own operators/<route> directory.
        """
        self.owner_path.write_text(
            runtime._toml_document(
                {
                    "schema_version": 1,
                    "owner_session_id": SUCCESSOR_SESSION,
                    "owner_route": SUCCESSOR_ROUTE,
                    "handoff_revision": 1,
                    "control_dir": str(self.prior_control),
                }
            )
        )
        successor_control = self.owner_path.parent / "operators" / SUCCESSOR_ROUTE
        successor_control.mkdir(parents=True, exist_ok=True)
        canonical_fable_receipt(successor_control / "receipt.toml", receipt_session, self.repo)
        # The invariant control directory still carries the ORIGINAL owner's
        # receipt, which names a session that no longer owns anything.
        self.agent = {"name": SUCCESSOR_ROUTE, "agent_status": "idle"}

    def test_the_current_owner_receipt_under_the_handoff_location_is_proof(self) -> None:
        self.handed_off_owner(receipt_session=SUCCESSOR_SESSION)
        result = self.takeover()
        self.assertEqual(result["outcome"], "takeover")
        self.assertIn("agent stop", self.calls())
        self.assertEqual(result["owner"]["owner_session_id"], THREAD)

    def test_a_receipt_naming_another_session_is_not_the_current_owner(self) -> None:
        self.handed_off_owner(receipt_session=FABLE_SESSION)
        before = self.owner_path.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertNotIn("agent stop", self.calls())
        self.assertEqual(self.owner_path.read_bytes(), before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
