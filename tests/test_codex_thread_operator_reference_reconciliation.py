"""Regression reds for the TUR-641 cycle-7 blocking code-review finding.

Seam: the owner-locked transfer accepts a hand-written readiness record at the
exact derived slot whenever it merely REPEATS the owner-supplied successor
identity, because the durable context references it carries are only checked for
digest SHAPE. A forger who names the thread the owner is about to transfer to can
therefore fabricate or replay every context reference and still commit ownership,
so the readiness record proves no activation ever reconciled anything.

The in-hold validation validates every binding field against LIVE state
(operator-control activation-binding-command, activation-owner-binding,
activation-handoff-brief, activation-authoritative-context). So inside the one
owner-lock hold, before the exclusive binding create and the owner rename, the
transfer RE-RECONCILES the readiness record's context references against their
named sources: every reference must recompute from the actual current source
bytes, and any fabricated digest, stale digest, unreadable source, or deviation
from the derived Codex source set refuses with the prior owner record
byte-identical and no binding written.

The residual the human ruling accepts: a forger who reproduces every real current
source digest AND is explicitly named by the owner is indistinguishable from the
activated successor. The owner stays the trust anchor for the successor identity;
this seam only removes the case where no live source was ever read.
"""

from __future__ import annotations

import json
import os
import subprocess
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
    FAKE_GH,
    FAKE_HERDR,
    OCTO_CONTROL,
    THREAD,
    WORKSPACE,
    digest_context,
    fable_owner,
    write_executable,
)

CODEX_MODE = runtime.CODEX_OWNER_MODE
SOURCES = runtime.CODEX_CONTEXT_SOURCES
ABSENT = object()


def forged_readiness(path: Path, handoff: Path, references: list[str], sources: list[str]) -> Path:
    """A hand-written readiness record at the exact DERIVED slot carrying the
    owner-named successor identity, the outgoing owner's own handoff artifact with
    its real digest, the declared mode, and the verified workspace: every field
    the transfer validates, written by no activation at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        runtime._toml_document(
            {
                "schema_version": 1,
                "session_id": THREAD,
                "handoff_revision": 1,
                "handoff_artifact": str(handoff.resolve()),
                "handoff_digest": runtime.exact_fingerprint(handoff.read_text()),
                "owner_mode": CODEX_MODE,
                "herdr_workspace": WORKSPACE,
                "context_sources": list(sources),
                "context_references": list(references),
            }
        )
    )
    return path


class LiveReferenceReconciliationTest(unittest.TestCase):
    """One dedicated Fable owner, one immutable handoff artifact, and one live
    durable-source reader the activation and the transfer both reconcile
    against."""

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
        # The live durable sources, read by the ONE reader both the activation and
        # the owner-locked transfer use. A test mutates this to move a live source.
        self.live = dict(digest_context())

    def reconcile(self, owner) -> dict:
        return dict(self.live)

    def derived_readiness(self) -> Path:
        return self.control / "handoffs" / "0001.ready.toml"

    def binding_path(self) -> Path:
        return self.control / "handoffs" / "0001.binding.toml"

    def activate(self) -> Path:
        result = runtime.activate_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            handoff=str(self.handoff),
            reconcile=self.reconcile,
        )
        return Path(result["successor_readiness"])

    def transfer(self, readiness: Path, *, reconcile=ABSENT):
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
            workspace_lookup=lambda workspace: {"id": workspace},
            reconcile=self.reconcile if reconcile is ABSENT else reconcile,
        )

    def assert_refused(self, readiness: Path, **kwargs) -> None:
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(readiness, **kwargs)
        self.assertEqual(
            self.owner.read_bytes(),
            before,
            "an unreconciled readiness record commits no ownership",
        )
        self.assertFalse(self.binding_path().exists())

    def test_a_matching_identity_forgery_with_fabricated_references_refuses(self) -> None:
        # The owner names session THREAD. The forged record names the same session
        # at the same derived slot with correctly SHAPED but fabricated context
        # references: no live source was ever read, so nothing recomputes.
        forged = forged_readiness(
            self.derived_readiness(),
            self.handoff,
            [f"{source}:reference#{runtime.exact_fingerprint('forged')}" for source in SOURCES],
            list(SOURCES),
        )
        self.assert_refused(forged)

    def test_references_that_no_longer_recompute_refuse(self) -> None:
        # A record whose references were true once is not live evidence: the
        # in-hold reconciliation reads the sources NOW, so a moved source refuses.
        readiness = self.activate()
        self.live["canonical_specs_and_adrs"] = (
            f"canonical_specs_and_adrs:reference#{runtime.exact_fingerprint('moved')}"
        )
        self.assert_refused(readiness)

    def test_a_reference_set_deviating_from_the_derived_sources_refuses(self) -> None:
        # The derived Codex source set is closed: a missing source and an extra one
        # are both deviations, whatever digests they carry.
        missing = forged_readiness(
            self.derived_readiness(),
            self.handoff,
            [self.live[source] for source in SOURCES[:-1]],
            list(SOURCES[:-1]),
        )
        self.assert_refused(missing)

        extra = forged_readiness(
            self.derived_readiness(),
            self.handoff,
            [self.live[source] for source in SOURCES]
            + [f"invented:reference#{runtime.exact_fingerprint('invented')}"],
            list(SOURCES) + ["invented"],
        )
        self.assert_refused(extra)

    def test_an_unreadable_live_source_refuses(self) -> None:
        readiness = self.activate()

        def unreadable(owner):
            raise runtime.GateError("context source unreadable")

        self.assert_refused(readiness, reconcile=unreadable)

    def test_a_transfer_with_no_live_reconciliation_refuses(self) -> None:
        # Reconciliation is not optional on the Codex path: with no live reader the
        # references cannot be recomputed at all, so the transfer fails closed.
        readiness = self.activate()
        self.assert_refused(readiness, reconcile=None)

    def test_activation_produced_readiness_commits(self) -> None:
        # The positive path: references written by a real activation recompute
        # against the same live sources, so the transfer commits and the
        # owner-authored binding is written under the same hold.
        readiness = self.activate()
        committed = self.transfer(readiness)
        self.assertEqual(committed["owner_session_id"], THREAD)
        self.assertEqual(committed["successor_binding"], str(self.binding_path()))
        self.assertTrue(self.binding_path().is_file())


class DerivedLiveContextTransferTest(unittest.TestCase):
    """The same seam against the REAL durable-source reader through
    scripts/octo-control owner-transfer.

    The transfer reconciles with the same helper the activation used, so a forged
    or stale readiness record refuses while an activation-produced one still
    recomputes: the readiness and binding records the act itself derives are never
    inside the digest domain they bind (operator-control activation-binding-order).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.call_log = self.base / "calls.log"
        write_executable(self.bin / "herdr", FAKE_HERDR)
        write_executable(self.bin / "gh", FAKE_GH)

        self.repo = self.base / "repo"
        (self.repo / "spec").mkdir(parents=True)
        (self.repo / "spec" / "index.spec.html").write_text("<html></html>\n")
        (self.repo / "AGENTS.md").write_text("target instructions\n")
        for command in (
            ["git", "-C", str(self.repo), "init", "-q"],
            ["git", "-C", str(self.repo), "remote", "add", "origin",
             "https://github.com/example/repo.git"],
            ["git", "-C", str(self.repo), "add", "-A"],
            ["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "seed"],
        ):
            subprocess.run(command, check=True, capture_output=True)

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

    def derived_readiness(self) -> Path:
        return self.control / "handoffs" / "0001.ready.toml"

    def binding_path(self) -> Path:
        return self.control / "handoffs" / "0001.binding.toml"

    def live_context(self, owner) -> dict:
        return OCTO_CONTROL._codex_live_context(
            repo=self.repo,
            owner_path=self.owner,
            control=Path(str(owner.get("control_dir") or self.control)),
            workspace=WORKSPACE,
            pending_owner=owner,
        )

    def activate(self) -> Path:
        return Path(
            runtime.activate_codex_thread(
                self.owner,
                thread_id=THREAD,
                workspace=WORKSPACE,
                control_dir=str(self.candidate_control),
                handoff=str(self.handoff),
                reconcile=self.live_context,
            )["successor_readiness"]
        )

    def transfer(self, readiness: Path):
        return OCTO_CONTROL.command_owner(
            Namespace(
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
                successor_readiness=str(readiness),
                new_owner_mode=CODEX_MODE,
                new_workspace=WORKSPACE,
                repo=str(self.repo),
            )
        )

    def test_a_matching_identity_forgery_refuses_against_live_sources(self) -> None:
        forged = forged_readiness(
            self.derived_readiness(),
            self.handoff,
            [f"{source}:reference#{runtime.exact_fingerprint('forged')}" for source in SOURCES],
            list(SOURCES),
        )
        before = self.owner.read_bytes()
        with unittest.mock.patch.dict(os.environ, self.env):
            with self.assertRaises(runtime.GateError):
                self.transfer(forged)
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse(self.binding_path().exists())

    def test_a_reference_that_no_longer_recomputes_refuses(self) -> None:
        with unittest.mock.patch.dict(os.environ, self.env):
            readiness = self.activate()
            # One authoritative source moves between the activation and the
            # transfer: the recorded reference is a past read, not live evidence.
            (self.repo / "spec" / "index.spec.html").write_text("<html>moved</html>\n")
            before = self.owner.read_bytes()
            with self.assertRaises(runtime.GateError):
                self.transfer(readiness)
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse(self.binding_path().exists())

    def test_an_activation_produced_readiness_still_recomputes_at_transfer(self) -> None:
        with unittest.mock.patch.dict(os.environ, self.env):
            readiness = self.activate()
            committed = self.transfer(readiness)
        self.assertEqual(committed["owner_session_id"], THREAD)
        self.assertTrue(self.binding_path().is_file())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
