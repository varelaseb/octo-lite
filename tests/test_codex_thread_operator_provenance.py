"""Regression reds for the TUR-641 cycle-4 blocking code-review findings.

Three seams the committed contract already names and the delivered code still
leaves open: no owner record exists before reconciliation succeeds and a failed
activation leaves no control state at all, successor readiness is accepted only
when the verified activation bound it to the outgoing owner's immutable handoff
artifact, and the handoff artifact location is DERIVED from the owner record in
force with no foreign-directory fallback.
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
    FABLE_SESSION,
    THREAD,
    WORKSPACE,
    digest_context,
    fable_owner,
)

CODEX_MODE = runtime.CODEX_OWNER_MODE


def refuse(owner):
    # One live source is unreadable, so this pass has no authoritative context.
    raise runtime.GateError("live source unreadable")


class PreCommitReconciliationOrderTest(unittest.TestCase):
    """Seam: reconciliation runs BEFORE the owner record exists on disk, and an
    unreconciled activation leaves neither an owner record nor a control
    directory (operator-control activation-failure-ordinary; role-runtime
    launch-codex-activation-failure)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.owner = self.base / "operator-owner.toml"
        self.control = self.base / "control"
        self.observed: list[bool] = []

    def activate(self, reconcile):
        return runtime.activate_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            control_dir=str(self.control),
            reconcile=reconcile,
        )

    def watch(self, owner):
        # What the live reader can see at the exact moment it runs.
        self.observed.append(self.owner.exists())
        return digest_context()

    def test_reconciliation_never_observes_an_uncommitted_owner_record(self) -> None:
        def watch_then_refuse(owner):
            self.watch(owner)
            raise runtime.GateError("live source unreadable")

        with self.assertRaises(runtime.GateError):
            self.activate(watch_then_refuse)
        self.assertEqual(
            self.observed,
            [False],
            "reconciliation must run before any owner-record write",
        )
        self.assertFalse(self.owner.exists())

    def test_unreconciled_activation_leaves_no_control_directory(self) -> None:
        with self.assertRaises(runtime.GateError):
            self.activate(refuse)
        self.assertFalse(self.owner.exists())
        self.assertFalse(
            self.control.exists(),
            "a failed activation must leave no control state behind",
        )

    def test_a_preexisting_control_tree_survives_an_unreconciled_activation(self) -> None:
        self.control.mkdir()
        (self.control / "status.md").write_text("prior status\n")
        with self.assertRaises(runtime.GateError):
            self.activate(refuse)
        self.assertFalse(self.owner.exists())
        self.assertEqual((self.control / "status.md").read_text(), "prior status\n")

    def test_reconciled_activation_still_commits_the_exact_reconciled_record(self) -> None:
        seen: list[dict] = []

        def reconcile(owner):
            seen.append(dict(owner))
            self.observed.append(self.owner.exists())
            return digest_context()

        result = self.activate(reconcile)
        self.assertEqual(result["outcome"], "activated")
        self.assertEqual(self.observed, [False])
        self.assertTrue(self.control.is_dir())
        self.assertEqual(
            seen,
            [result["owner"]],
            "the record reconciled must be the exact record committed",
        )


class ReadinessProvenanceTest(unittest.TestCase):
    """Seam: the atomic owner transfer accepts only the successor readiness a
    verified activation wrote against the outgoing owner's immutable handoff
    artifact (operator-control activation-handoff-brief, handoff-artifact,
    activation-no-new-auth)."""

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
        self.prior = fable_owner(self.owner, self.control)

    def genuine_readiness(self) -> Path:
        pending = runtime.activate_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            handoff=str(self.handoff),
            reconcile=lambda owner: digest_context(),
        )
        self.assertEqual(pending["outcome"], "pending")
        return Path(pending["successor_readiness"])

    def transfer(self, readiness: Path):
        return runtime.transfer_owner(
            self.owner,
            FABLE_SESSION,
            FABLE_ROUTE,
            0,
            THREAD,
            THREAD,
            1,
            str(self.control),
            caller=FABLE_SESSION,
            handoff=self.handoff,
            successor_readiness_path=readiness,
            new_owner_mode=CODEX_MODE,
            new_workspace=WORKSPACE,
            # The live transfer-time routing boundary the owner-locked act crosses.
            workspace_lookup=lambda workspace: {"id": workspace},
            # The in-hold live re-reconciliation of the readiness references.
            reconcile=lambda owner: digest_context(),
        )

    def test_transfer_refuses_a_forged_successor_readiness_record(self) -> None:
        genuine = self.genuine_readiness()
        forged = self.base / "forged-ready.toml"
        forged.write_text(
            runtime._toml_document(
                {
                    "schema_version": 1,
                    "session_id": THREAD,
                    "handoff_revision": 1,
                    "owner_mode": CODEX_MODE,
                    "herdr_workspace": WORKSPACE,
                }
            )
        )
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(forged)
        self.assertEqual(
            self.owner.read_bytes(),
            before,
            "a readiness record no verified activation wrote transfers nothing",
        )

        committed = self.transfer(genuine)
        self.assertEqual(committed["owner_session_id"], THREAD)
        self.assertEqual(committed["herdr_workspace"], WORKSPACE)

    def test_transfer_refuses_readiness_no_activation_reconciled(self) -> None:
        # Cycle-5 finding P1: the public readiness path mints every field the
        # transfer validates, including the exact artifact binding, while
        # skipping activation entirely, so it never read-verifies the workspace
        # and never reconciles durable context. Only explicit activation makes a
        # Codex successor ready (operator-control activation-handoff-brief,
        # activation-workspace, activation-no-new-auth).
        unactivated = self.base / "unactivated-ready.toml"
        unactivated.write_text(
            runtime._toml_document(
                {
                    "schema_version": 1,
                    "session_id": THREAD,
                    "handoff_revision": 1,
                    "handoff_artifact": str(self.handoff.resolve()),
                    "handoff_digest": runtime.exact_fingerprint(self.handoff.read_text()),
                    "owner_mode": CODEX_MODE,
                    "herdr_workspace": WORKSPACE,
                }
            )
        )
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(unactivated)
        self.assertEqual(
            self.owner.read_bytes(),
            before,
            "readiness no activation reconciled commits no Codex ownership",
        )

        committed = self.transfer(self.genuine_readiness())
        self.assertEqual(committed["owner_session_id"], THREAD)
        self.assertEqual(committed["herdr_workspace"], WORKSPACE)

    def test_transfer_refuses_readiness_bound_to_other_handoff_bytes(self) -> None:
        genuine = self.genuine_readiness()
        # The brief the successor reconciled is not the brief presented at
        # transfer time: same derived location, different bytes.
        self.handoff.write_text("rewritten brief\n")
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(genuine)
        self.assertEqual(self.owner.read_bytes(), before)


class DerivedHandoffLocationTest(unittest.TestCase):
    """Seam: the immutable handoff artifact location is derived from the owner
    record in force and never falls back to a foreign directory
    (operator-control handoff-artifact, activation-different-owner)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        self.control.mkdir()
        self.foreign = self.base / "foreign" / "handoffs" / "0001.md"
        self.foreign.parent.mkdir(parents=True)
        self.foreign.write_text("foreign brief\n")
        self.owner = self.base / "operator-owner.toml"
        self.prior = fable_owner(self.owner, self.control)
        self.readiness = self.base / "ready.toml"
        self.readiness.write_text(
            runtime._toml_document(
                {"schema_version": 1, "session_id": "successor", "handoff_revision": 1}
            )
        )

    def test_transfer_refuses_a_foreign_handoff_when_the_owner_tree_has_none(self) -> None:
        self.assertFalse((self.control / "handoffs").exists())
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            runtime.transfer_owner(
                self.owner,
                FABLE_SESSION,
                FABLE_ROUTE,
                0,
                "successor",
                "operator-next",
                1,
                str(self.control),
                caller=FABLE_SESSION,
                handoff=self.foreign,
                successor_readiness_path=self.readiness,
            )
        self.assertEqual(
            self.owner.read_bytes(),
            before,
            "an absent owner handoffs directory admits no foreign artifact",
        )

    def test_an_unrecorded_control_directory_derives_no_handoff_artifact(self) -> None:
        self.assertFalse(runtime._is_owner_handoff(self.foreign, "", 1))
        self.assertFalse(runtime._is_owner_handoff(self.foreign, "   ", 1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
