"""Regression red for the TUR-641 cold code-review finding P1.

One seam: the forced-takeover active-Fable proof must verify the WHOLE
resolver-built launch receipt against the canonical resolver mapping itself,
not merely its shape. A receipt whose contract blob, roles.toml revision, skill
blobs, or workspace instructions blob are merely blob-SHAPED, or whose skill and
capability set omits part of what the resolver grants the meta-operator role, is
not a dedicated Fable and must never license session retirement or a forced
ownership transfer (operator-control takeover-live-fable-only,
takeover-failure; role-runtime role-receipt).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workflows" / "lib"))

from octo_lite import runtime  # noqa: E402
from role_resolver import _skill_blob  # noqa: E402
from tests.test_codex_thread_operator_binding import (  # noqa: E402
    FABLE_RESOLVED,
    FABLE_SESSION,
    TakeoverCliHarness,
)
from tests.test_codex_thread_operator_contract import canonical_fable_receipt  # noqa: E402

FABRICATED = "0" * 40


class CanonicalReceiptBlobProofTest(TakeoverCliHarness):
    """Seam: every blob a dedicated-Fable receipt carries is checked against the
    canonical resolver mapping, and the resolver-granted skill and capability set
    is required whole; a fabricated or omitted entry refuses the takeover and
    leaves the prior owner bytes intact."""

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

    def test_the_canonical_resolver_built_receipt_is_still_proof(self) -> None:
        canonical_fable_receipt(self.receipt_path(), FABLE_SESSION, self.repo)
        self.assertEqual(self.takeover()["outcome"], "takeover")

    def test_a_fabricated_role_blob_is_not_proof(self) -> None:
        for field in ("contract_blob", "mapping_revision"):
            with self.subTest(field=field):
                self.assert_refused(role={field: FABRICATED})

    def test_a_fabricated_skill_blob_is_not_proof(self) -> None:
        self.assert_refused(skills={"blobs": [FABRICATED for _ in FABLE_RESOLVED.skills]})

    def test_a_fabricated_instructions_blob_is_not_proof(self) -> None:
        self.assert_refused(workspace={"instructions_blob": FABRICATED})

    def test_a_receipt_omitting_a_granted_capability_is_not_proof(self) -> None:
        # A meta-operator launched without launch-meta-operator holds no
        # operator-launch authority, so it is not the dedicated Fable owner a
        # forced takeover may retire.
        kept = [skill for skill in FABLE_RESOLVED.skills if skill != "launch-meta-operator"]
        self.assertTrue(kept and len(kept) < len(FABLE_RESOLVED.skills))
        self.assert_refused(
            skills={
                "resolved": kept,
                "matched_capabilities": [],
                "paths": [f"skills/{skill}/SKILL.md" for skill in kept],
                "blobs": [_skill_blob(ROOT, skill) for skill in kept],
            }
        )


if __name__ == "__main__":
    unittest.main()
