"""Reds for the two remaining TUR-641 v16 live-boundary contract items.

Seam one: the owner-locked transfer to a Codex successor
(operator-control activation-binding-transfer). Positive activated-transfer
proof inside the one owner-lock hold requires a LIVE transfer-time Herdr
workspace lookup returning the exact bound workspace. A failed lookup and a
lookup answering a different workspace each refuse the whole transfer, leaving
the prior owner record byte-identical and no binding written, and
scripts/octo-control owner-transfer is the caller that performs that live
lookup.

Seam two: the forced takeover's post-fence failure surface (operator-control
takeover-receipt-residue). An owner write that fails after fencing leaves a
loudly-surfaced blocked-owner state that NAMES the unreferenced receipt path,
mutates nothing else, and no agent-callable path retries, reads, or reclaims
that receipt.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workflows" / "lib"))

from octo_lite import runtime  # noqa: E402
from tests.test_codex_thread_operator_binding import (  # noqa: E402
    FABLE_ROUTE,
    FABLE_SESSION,
    FAKE_HERDR,
    THREAD,
    WORKSPACE,
    OCTO_CONTROL,
    TakeoverCliHarness,
    digest_context,
    fable_owner,
    write_executable,
)

CODEX_MODE = runtime.CODEX_OWNER_MODE


class TransferWorkspaceLookupTest(unittest.TestCase):
    """Seam: scripts/octo-control owner-transfer to a declared Codex successor."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.call_log = self.base / "calls.log"
        write_executable(self.bin / "herdr", FAKE_HERDR)

        self.control = self.base / "control"
        (self.control / "handoffs").mkdir(parents=True)
        self.handoff = self.control / "handoffs" / "0001.md"
        self.handoff.write_text("compact brief\n")
        self.candidate_control = self.base / "codex-control"
        self.owner = self.base / "operator-owner.toml"
        fable_owner(self.owner, self.control)

        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "OCTO_HERDR": str(self.bin / "herdr"),
            "CALL_LOG": str(self.call_log),
            "WORKSPACE_JSON": json.dumps({"result": {"workspace": {"id": WORKSPACE}}}),
        }

        result = runtime.activate_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            handoff=str(self.handoff),
            reconcile=lambda owner: digest_context(),
        )
        self.readiness = Path(result["successor_readiness"])

    def binding_path(self) -> Path:
        return self.control / "handoffs" / "0001.binding.toml"

    def transfer(self, **env_extra):
        args = Namespace(
            owner_file=str(self.owner),
            expected_owner=FABLE_SESSION,
            expected_route=FABLE_ROUTE,
            expected_revision=0,
            caller=FABLE_SESSION,
            new_owner=THREAD,
            new_route=THREAD,
            revision=1,
            control_dir=str(self.control),
            handoff=str(self.handoff),
            successor_readiness=str(self.readiness),
            new_owner_mode=CODEX_MODE,
            new_workspace=WORKSPACE,
            repo=str(self.base),
        )
        env = dict(self.env)
        env.update(env_extra)
        # This seam is the live workspace lookup, so the durable-source reader is
        # the same test double the activation above reconciled with; the real
        # reader is exercised in test_codex_thread_operator_reference_reconciliation.
        with unittest.mock.patch.dict(os.environ, env), unittest.mock.patch.object(
            OCTO_CONTROL, "_codex_live_context", lambda **kwargs: digest_context()
        ):
            return OCTO_CONTROL.command_owner(args)

    def calls(self) -> str:
        return self.call_log.read_text() if self.call_log.exists() else ""

    def test_a_failed_transfer_time_lookup_refuses_the_whole_transfer(self) -> None:
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(WORKSPACE_STATUS="1")
        # An unreadable lookup is not an answer: nothing commits, and the prior
        # owner record stays byte-identical.
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse(self.binding_path().exists())

    def test_a_lookup_answering_a_different_workspace_refuses(self) -> None:
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(
                WORKSPACE_JSON=json.dumps({"result": {"workspace": {"id": "w-other"}}})
            )
        # Exit status alone is not verification: the lookup must return the exact
        # workspace the transfer binds.
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse(self.binding_path().exists())

    def test_a_matching_live_lookup_commits_the_transfer(self) -> None:
        committed = self.transfer()
        self.assertEqual(committed["owner_session_id"], THREAD)
        self.assertEqual(committed["herdr_workspace"], WORKSPACE)
        self.assertTrue(self.binding_path().is_file())
        # The proof is a LIVE transfer-time read, so the boundary is actually
        # crossed on the positive path too.
        self.assertIn(f"herdr workspace get {WORKSPACE}", self.calls())


class TakeoverReceiptResidueTest(TakeoverCliHarness):
    """Seam: octo-control codex-activate --force-takeover post-fence failure."""

    def test_a_post_fence_owner_write_failure_names_the_unreferenced_receipt(self) -> None:
        receipt_path = self.prior_control / "takeovers" / "0001.toml"
        before = self.owner_path.read_bytes()
        original = runtime._atomic_write

        def fail_owner_write(path: Path, content: str) -> None:
            # The owner write is the single durable commit point: breaking it
            # AFTER fencing is the exact blocked state the residue law governs.
            if Path(path) == self.owner_path:
                raise OSError("owner record write failed")
            original(path, content)

        with unittest.mock.patch.object(runtime, "_atomic_write", fail_owner_write):
            with self.assertRaises(runtime.GateError) as raised:
                self.takeover()

        # The surface is loud and names the exact unreferenced receipt path.
        self.assertIn(str(receipt_path), str(raised.exception))
        self.assertTrue(receipt_path.is_file())
        residue = receipt_path.read_bytes()
        # Nothing else is mutated: the prior owner record is byte-identical and
        # no owner ever referenced the receipt.
        self.assertEqual(self.owner_path.read_bytes(), before)

        # No agent-callable path retries, reads, or reclaims the residue: the
        # stopped prior owner is ineligible for another forced takeover, so the
        # only remaining seam refuses and leaves the receipt untouched.
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertEqual(receipt_path.read_bytes(), residue)
        self.assertEqual(self.owner_path.read_bytes(), before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
