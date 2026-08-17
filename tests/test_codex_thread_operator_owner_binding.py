"""Red for the TUR-641 v16 owner-authored transfer-provenance record.

Seam: the atomic owner transfer to a Codex successor is one owner-locked act
that also authors the transfer provenance. Inside the single owner-lock hold the
current owner reclaims any void residue at the derived binding path without
reading it, exclusively creates one immutable owner-authored binding record
cross-binding the exact activated successor thread, workspace, readiness record,
and handoff artifact, and commits an owner record referencing that exact binding
path and digest, which is the only thing that gives a binding any authority
(operator-control activation-owner-binding, activation-owner-binding-fields,
activation-binding-order, activation-binding-transfer,
activation-binding-owner-modes, activation-binding-command; ADR 0005
decision-transfer-provenance, decision-failure-atomic).

No activation or successor path ever writes the binding record, there is no
separate creation command, nothing overwrites a binding, and the unchanged
dedicated-Fable successor path requires none.
"""

from __future__ import annotations

import sys
import tempfile
import tomllib
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
    codex_owner,
    digest_context,
    fable_owner,
)

CODEX_MODE = runtime.CODEX_OWNER_MODE

BINDING_FIELDS = (
    "schema_version",
    "revision",
    "successor_session",
    "herdr_workspace",
    "readiness_digest",
    "handoff_digest",
    "authored_by_session",
    "authored_at_utc",
)


class OwnerAuthoredBindingTest(unittest.TestCase):
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

    # The one derived location the owner authors, a sibling of the immutable
    # handoff artifact and of the activation's readiness record it cross-binds.
    def binding_path(self) -> Path:
        return self.control / "handoffs" / "0001.binding.toml"

    def activate(self, *, thread_id: str = THREAD) -> Path:
        result = runtime.activate_codex_thread(
            self.owner,
            thread_id=thread_id,
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            handoff=str(self.handoff),
            reconcile=lambda owner: digest_context(),
        )
        return Path(result["successor_readiness"])

    def transfer(self, readiness: Path, *, caller: str = FABLE_SESSION):
        return runtime.transfer_owner(
            self.owner,
            FABLE_SESSION,
            FABLE_ROUTE,
            0,
            THREAD,
            THREAD,
            1,
            str(self.control),
            caller=caller,
            handoff=self.handoff,
            successor_readiness_path=readiness,
            new_owner_mode=CODEX_MODE,
            new_workspace=WORKSPACE,
            # The live transfer-time routing boundary the owner-locked act crosses.
            workspace_lookup=lambda workspace: {"id": workspace},
        )

    def test_the_committed_transfer_carries_an_owner_authored_binding(self) -> None:
        readiness = self.activate()
        committed = self.transfer(readiness)

        binding_path = self.binding_path()
        self.assertTrue(binding_path.is_file(), "the owner authors the binding record")
        document = binding_path.read_text()
        binding = tomllib.loads(document)
        # Exactly the canonical flat field set, nothing more and nothing less.
        self.assertEqual(tuple(binding), BINDING_FIELDS)
        self.assertEqual(binding["schema_version"], 1)
        self.assertEqual(binding["revision"], 1)
        self.assertEqual(binding["successor_session"], THREAD)
        self.assertEqual(binding["herdr_workspace"], WORKSPACE)
        # Nonrecursive digest domain: the binding digests the readiness record
        # and the handoff artifact, and nothing digests the binding.
        self.assertEqual(
            binding["readiness_digest"], runtime.exact_fingerprint(readiness.read_text())
        )
        self.assertEqual(
            binding["handoff_digest"], runtime.exact_fingerprint(self.handoff.read_text())
        )
        self.assertEqual(binding["authored_by_session"], FABLE_SESSION)
        self.assertRegex(binding["authored_at_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        # The committed owner record is what makes the binding authoritative: it
        # names that exact path and digest, so no other file has any authority.
        self.assertEqual(Path(str(committed["successor_binding"])), binding_path)
        self.assertEqual(
            committed["successor_binding_digest"], runtime.exact_fingerprint(document)
        )
        self.assertEqual(tomllib.loads(self.owner.read_text()), committed)

    def test_no_activation_or_successor_path_writes_the_binding(self) -> None:
        self.activate()
        self.assertFalse(
            self.binding_path().exists(),
            "only the owner-locked transfer act authors the binding record",
        )

    def test_void_residue_at_the_binding_path_is_reclaimed_unread(self) -> None:
        readiness = self.activate()
        residue = self.binding_path()
        residue.write_text(
            runtime._toml_document(
                {
                    "schema_version": 1,
                    "revision": 1,
                    "successor_session": OTHER_THREAD,
                    "herdr_workspace": WORKSPACE,
                    "readiness_digest": runtime.exact_fingerprint(readiness.read_text()),
                    "handoff_digest": runtime.exact_fingerprint(self.handoff.read_text()),
                    "authored_by_session": OTHER_THREAD,
                    "authored_at_utc": "2000-01-01T00:00:00Z",
                }
            )
        )

        committed = self.transfer(readiness)
        binding = tomllib.loads(residue.read_text())
        # Hand-written bytes never influence the transfer: the hold reclaims the
        # residue unread and creates its own record, so a crashed or cleaned-up
        # earlier attempt poisons no retry.
        self.assertEqual(binding["successor_session"], THREAD)
        self.assertEqual(binding["authored_by_session"], FABLE_SESSION)
        self.assertEqual(
            committed["successor_binding_digest"],
            runtime.exact_fingerprint(residue.read_text()),
        )

    def test_a_refused_transfer_leaves_no_binding_and_the_prior_owner_intact(self) -> None:
        readiness = self.activate()
        before = self.owner.read_bytes()
        # A non-owner caller is not the owner-locked transfer act, so it authors
        # nothing at all.
        with self.assertRaises(runtime.GateError):
            self.transfer(readiness, caller=THREAD)
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse(self.binding_path().exists())

        # A mismatched readiness record refuses inside the act, before any write.
        forged = self.base / "forged-ready.toml"
        forged.write_text(readiness.read_text())
        with self.assertRaises(runtime.GateError):
            self.transfer(forged)
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse(self.binding_path().exists())

    def test_a_codex_thread_owner_authors_the_same_binding(self) -> None:
        # activation-binding-owner-modes: every current owner mode authors the
        # binding identically before transferring to a Codex successor.
        codex_owner(self.owner, self.control)
        readiness = self.activate(thread_id=OTHER_THREAD)
        committed = runtime.transfer_owner(
            self.owner,
            THREAD,
            THREAD,
            0,
            OTHER_THREAD,
            OTHER_THREAD,
            1,
            str(self.control),
            caller=THREAD,
            handoff=self.handoff,
            successor_readiness_path=readiness,
            new_owner_mode=CODEX_MODE,
            new_workspace=WORKSPACE,
            # The live transfer-time routing boundary the owner-locked act crosses.
            workspace_lookup=lambda workspace: {"id": workspace},
        )
        binding = tomllib.loads(self.binding_path().read_text())
        self.assertEqual(binding["successor_session"], OTHER_THREAD)
        self.assertEqual(binding["authored_by_session"], THREAD)
        self.assertEqual(
            committed["successor_binding_digest"],
            runtime.exact_fingerprint(self.binding_path().read_text()),
        )

    def test_a_dedicated_fable_successor_needs_no_binding(self) -> None:
        # The dedicated-Fable successor path is unchanged by the binding law.
        readiness = self.control / "handoffs" / "0001.ready.toml"
        runtime.declare_successor_ready(
            readiness,
            caller="fable-session-2",
            session_id="fable-session-2",
            handoff_revision=1,
            handoff=self.handoff,
        )
        committed = runtime.transfer_owner(
            self.owner,
            FABLE_SESSION,
            FABLE_ROUTE,
            0,
            "fable-session-2",
            "operator-fable-2",
            1,
            str(self.control),
            caller=FABLE_SESSION,
            handoff=self.handoff,
            successor_readiness_path=readiness,
        )
        self.assertNotIn("successor_binding", committed)
        self.assertFalse(self.binding_path().exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
