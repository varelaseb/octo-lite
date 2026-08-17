"""Regression reds for the TUR-641 cold code-review findings.

Three seams the committed contract names and the delivered code still leaves
open: forced-takeover commit atomicity across the FINAL reconciliation
(operator-control takeover-failure, takeover-atomic), the canonical
meta-operator contract sources an activation must load from their installed
sources before authority can act (role-runtime
launch-codex-activation-contract, launch-codex-activation-complete), and the
full persistent dedicated-Fable launch receipt that alone proves an eligible
forced-takeover candidate (operator-control takeover-live-fable-only).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
import unittest
import unittest.mock
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workflows" / "lib"))

from octo_lite import runtime  # noqa: E402
from role_resolver import load_registry, resolve_role  # noqa: E402
from tests.test_codex_thread_operator_binding import (  # noqa: E402
    FABLE_ROUTE,
    FABLE_SESSION,
    OCTO_CONTROL,
    THREAD,
    WORKSPACE,
    TakeoverCliHarness,
    digest_context,
    fable_owner,
)

# The canonical contract sources an activation must load from their installed
# sources before authority can act (role-runtime
# launch-codex-activation-contract).
CONTRACT_SOURCES = (
    "installed_profile",
    "target_instructions",
    "meta_operator_contract",
    "meta_operator_skills",
)

REGISTRY = load_registry(ROOT)
FABLE_ROLE = REGISTRY.roles["meta-operator"]
FABLE_RESOLVED = resolve_role(REGISTRY, "meta-operator", {"operator-launch"})


def canonical_fable_receipt(path: Path, session_id: str, repo: Path, **sections) -> None:
    """The persistent receipt a real dedicated Fable meta-operator launch writes.

    Built from the canonical role mapping itself, so the only proof of an
    eligible forced-takeover candidate is a receipt that matches the exact
    canonical Fable runtime (operator-control takeover-live-fable-only;
    role-runtime role-receipt, launch-receipt-persistent).
    """
    values = {
        "schema_version": 1,
        "spawn_id": "11111111-1111-1111-1111-111111111111",
        "parent": "operator",
        "reply_route": "operator",
        "ready": True,
        "role": {
            "name": "meta-operator",
            "root": str(ROOT),
            "contract_path": FABLE_ROLE.contract,
            "contract_blob": FABLE_RESOLVED.contract_blob,
            "mapping_revision": REGISTRY.mapping_revision,
        },
        "runtime": {
            "provider": FABLE_ROLE.provider,
            "model": FABLE_ROLE.model,
            "effort": FABLE_ROLE.effort,
            "mode": FABLE_ROLE.mode,
            "session": FABLE_ROLE.session,
            "service_tier": FABLE_ROLE.service_tier,
            "tools": list(FABLE_ROLE.tools),
        },
        "skills": {
            "resolved": list(FABLE_RESOLVED.skills),
            "matched_capabilities": list(FABLE_RESOLVED.capabilities),
            "paths": [f"skills/{skill}/SKILL.md" for skill in FABLE_RESOLVED.skills],
            "blobs": ["0" * 40 for _ in FABLE_RESOLVED.skills],
        },
        "workspace": {
            "repo": str(repo),
            "worktree": str(repo),
            "starting_head": "0" * 40,
            "instructions_path": "AGENTS.md",
            "instructions_blob": "0" * 40,
        },
        "access": {
            "execution_location": "local",
            "operator_loopback": True,
            "review_delivery": "loopback_allowed",
        },
    }
    for section, overrides in sections.items():
        if overrides is None:
            values.pop(section, None)
            continue
        if isinstance(values.get(section), dict) and isinstance(overrides, dict):
            values[section] = {**values[section], **overrides}
            for key, item in list(overrides.items()):
                if item is None:
                    values[section].pop(key, None)
        else:
            values[section] = overrides
    # The receipt self-binds: a post-launch edit that is not recomputed fails
    # closed already, so every case here recomputes and still must be judged on
    # the receipt SHAPE and runtime it declares.
    values["launch_revision"] = runtime.launch_revision(values)
    values["bootstrap"] = {"verified": True, "provider_session_id": session_id}
    path.write_text(runtime._render_full_receipt(values))


class TakeoverCommitAtomicityTest(unittest.TestCase):
    """Seam: every phase of the forced takeover, INCLUDING the final durable
    reconciliation the new owner must have before it may act, is proven before
    the one atomic authority commit. An unprovable final read leaves the Codex
    thread ordinary and the prior Fable ownership record byte-identical
    (operator-control takeover-failure, takeover-atomic, takeover-no-split)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.control = self.base / "control"
        self.control.mkdir()
        self.owner = self.base / "operator-owner.toml"
        fable_owner(self.owner, self.control)
        self.reads: list[dict] = []

    def takeover(self, reconcile):
        return runtime.force_takeover_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            reason="operator directed control transfer",
            context=digest_context(),
            verify_active_fable=lambda owner: {"session_running": True},
            retire_fable=lambda owner: {"session_running": False, "timer_present": False},
            now=lambda: "2026-08-17T01:00:00Z",
            reconcile=reconcile,
        )

    def test_a_failed_final_reconciliation_commits_no_owner_and_no_receipt(self) -> None:
        def reconcile(owner):
            self.reads.append(dict(owner))
            if len(self.reads) > 1:
                raise runtime.GateError("live source unreadable")
            return digest_context()

        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover(reconcile)
        self.assertGreaterEqual(
            len(self.reads), 2, "the takeover must reconcile again before it commits authority"
        )
        self.assertEqual(
            self.owner.read_bytes(),
            before,
            "an unprovable final reconciliation must leave the prior Fable owner byte-identical",
        )
        self.assertFalse(
            (self.control / "takeovers").exists(),
            "a takeover that never commits authority writes no immutable receipt",
        )

    def test_a_proven_takeover_still_commits_one_owner_and_one_receipt(self) -> None:
        result = self.takeover(lambda owner: digest_context())
        self.assertEqual(result["outcome"], "takeover")
        owner = runtime._read_toml(self.owner)
        self.assertEqual(owner["owner_session_id"], THREAD)
        self.assertEqual(
            sorted(path.name for path in (self.control / "takeovers").iterdir()), ["0001.toml"]
        )


class ActivationContractSourceTest(TakeoverCliHarness):
    """Seam: before authority can act, the activated thread loads the canonical
    profile, target instructions, roles/meta-operator.md, and the required
    meta-operator skills from their INSTALLED sources, binding each to exact
    bytes and copying none of that prose into the control directory
    (role-runtime launch-codex-activation-contract,
    launch-codex-activation-complete, launch-codex-activation-failure)."""

    def activate(self, *, owner_file=None, env_extra=None):
        args = Namespace(
            owner_file=str(owner_file or self.base / "fresh-owner.toml"),
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            repo=str(self.repo),
            handoff="",
            force_takeover=False,
            reason=None,
            context_ref=[],
        )
        env = dict(self.env)
        env["AGENT_JSON"] = json.dumps({"result": {"agent": self.agent}})
        env["CODEX_THREAD_ID"] = THREAD
        env["CODEX_HOME"] = str(self.codex_home())
        env.update(env_extra or {})
        with unittest.mock.patch.dict(os.environ, env):
            return OCTO_CONTROL.command_codex_activate(args)

    def contract(self, result) -> dict:
        self.assertEqual(result.get("contract_sources"), list(CONTRACT_SOURCES))
        return dict(zip(result["contract_sources"], result["contract_references"]))

    def assert_binds_installed_sources(self, references) -> None:
        for source, reference in references.items():
            identity, separator, digest = reference.rpartition("#")
            self.assertTrue(separator and identity, f"{source} binds no exact bytes")
            self.assertEqual(len(digest), 64, f"{source} binds no exact bytes")
        self.assertIn(
            str(self.codex_home() / "AGENTS.md"), references["installed_profile"]
        )
        self.assertIn(str(self.repo / "AGENTS.md"), references["target_instructions"])
        self.assertIn("roles/meta-operator.md", references["meta_operator_contract"])
        for skill in FABLE_ROLE.required_skills:
            self.assertIn(skill, references["meta_operator_skills"])

    def test_activation_binds_the_canonical_contract_sources(self) -> None:
        result = self.activate()
        self.assertEqual(result["outcome"], "activated")
        self.assert_binds_installed_sources(self.contract(result))

    def test_forced_takeover_binds_the_same_canonical_contract_sources(self) -> None:
        # Takeover creates no reduced Codex-only runtime: it binds the same
        # canonical meta-operator surface as an initial activation.
        self.assert_binds_installed_sources(self.contract(self.takeover()))

    def test_an_unreadable_canonical_source_leaves_the_session_ordinary(self) -> None:
        owner_file = self.base / "fresh-owner.toml"
        (self.codex_home() / "AGENTS.md").unlink()
        with self.assertRaises(runtime.GateError):
            self.activate(owner_file=owner_file)
        self.assertFalse(owner_file.exists())

        (self.codex_home() / "AGENTS.md").write_text("installed profile\n")
        (self.repo / "AGENTS.md").unlink()
        with self.assertRaises(runtime.GateError):
            self.activate(owner_file=owner_file)
        self.assertFalse(owner_file.exists())

    def test_no_canonical_prose_is_copied_into_the_control_directory(self) -> None:
        self.activate()
        copied = [
            path
            for path in self.candidate_control.rglob("*")
            if path.is_file() and path.read_text(errors="ignore").strip() == "installed profile"
        ]
        self.assertEqual(copied, [])


class DedicatedFableReceiptProofTest(TakeoverCliHarness):
    """Seam: forced takeover admits only an owner record that resolves to one
    STRUCTURED, VERIFIED active dedicated Fable, so the whole persistent launch
    receipt and the exact canonical Fable runtime are the proof; a receipt that
    is not a complete canonical dedicated-Fable launch is not a dedicated Fable
    (operator-control takeover-live-fable-only, takeover-failure)."""

    def receipt_path(self) -> Path:
        return self.prior_control / "receipt.toml"

    def assert_refused(self, **sections) -> None:
        canonical_fable_receipt(self.receipt_path(), FABLE_SESSION, self.repo, **sections)
        before = self.owner_path.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertNotIn("agent stop", self.calls())
        self.assertEqual(self.owner_path.read_bytes(), before)
        self.assertFalse((self.prior_control / "takeovers").exists())

    def test_a_complete_canonical_fable_receipt_is_proof(self) -> None:
        canonical_fable_receipt(self.receipt_path(), FABLE_SESSION, self.repo)
        result = self.takeover()
        self.assertEqual(result["outcome"], "takeover")
        self.assertEqual(result["owner"]["owner_session_id"], THREAD)

    def test_an_uncanonical_fable_runtime_is_not_proof(self) -> None:
        for override in (
            {"provider": "openai"},
            {"model": "claude-opus-5"},
            {"effort": "low"},
            {"session": "worker"},
            {"mode": "manual"},
            {"service_tier": None},
            {"tools": []},
        ):
            with self.subTest(runtime_override=override):
                self.assert_refused(runtime=override)

    def test_an_incomplete_persistent_receipt_is_not_proof(self) -> None:
        for name, sections in (
            ("no skills", {"skills": None}),
            ("no resolved skills", {"skills": {"resolved": [], "paths": [], "blobs": []}}),
            ("unmapped skill", {"skills": {"resolved": ["python"], "paths": ["skills/python/SKILL.md"], "blobs": ["0" * 40]}}),
            ("no access", {"access": None}),
            ("no workspace", {"workspace": None}),
            ("not ready", {"ready": False}),
            ("no spawn identity", {"spawn_id": ""}),
            ("uncanonical contract path", {"role": {"contract_path": "roles/orchestrator.md"}}),
        ):
            with self.subTest(case=name):
                self.assert_refused(**sections)


if __name__ == "__main__":
    unittest.main()
