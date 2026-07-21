"""D6 stream-envelope builder (gh#8 ruling-65, spec launch-stream-envelope-builder,
launch-stream-envelope-sources). Builds the loop's bound-inputs envelope as a plain
JSON-serializable dict so a Workflow-native invocation NEVER hands a raw `--stream
<name>` flag to the JSON-parsing loop entry (TUR-488). Every field has exactly one
declared source (provisioning env, stream/brief data, live reads, or the
shaping-review journal); a missing source fails closed before any envelope is
returned. This module never reimplements the loop's own assertReadyEnvelope
validation logic (workflows/lib/gates.mjs), it only SOURCES the fields that logic
requires.
"""

from __future__ import annotations

from typing import Any, Mapping

from octo_lite.runtime import GateError

# launch-provision-env-seam: the frozen OCTO_* names the host sets on the loop's
# working environment. Only a subset feeds the envelope directly
# (launch-stream-envelope-sources); OCTO_CONTROL_REPO, OCTO_LANE, and
# OCTO_PROVISION_RECORD are provisioning identity, not envelope fields.
_ENV_WORKTREE = "OCTO_WORKTREE"
_ENV_WORKTREE_ROOT = "OCTO_WORKTREE_ROOT"
_ENV_REPO_SLUG = "OCTO_REPO_SLUG"
_ENV_STARTING_HEAD = "OCTO_STARTING_HEAD"

# From stream and brief data (launch-stream-envelope-sources).
STREAM_FIELDS = (
    "issue",
    "pr",
    "pr_base",
    "branch",
    "topology_revision",
    "conversation_log_references",
    "conversation_cutoff",
    "acceptance_criteria",
)

# From live reads at the shaping head (launch-stream-envelope-sources); pr_head is
# the FRESH PR head confirmation, cross-checked against the provisioning env's
# OCTO_STARTING_HEAD rather than trusted verbatim.
LIVE_READ_FIELDS = (
    "spec_revision",
    "spec_blobs",
    "adr_blobs",
    "pr_head",
    "linear_revision",
    "linear_fingerprint",
    "linear_state",
)

# From the shaping-review journal (launch-stream-envelope-sources).
SHAPING_JOURNAL_FIELDS = (
    "shaping_verdict",
    "shaping_verdict_head",
    "shaping_reviewer_receipt",
    "shaping_verdict_inputs",
)


def _require(mapping: Mapping[str, Any], key: str, label: str) -> Any:
    if not isinstance(mapping, Mapping) or key not in mapping:
        raise GateError(f"stream envelope missing source: {label}")
    value = mapping[key]
    if value is None or value == "":
        raise GateError(f"stream envelope missing source: {label}")
    return value


def build_stream_envelope(
    *,
    env: Mapping[str, str],
    stream: Mapping[str, Any],
    live_reads: Mapping[str, Any],
    contract_hash: str,
    shaping_journal: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the parsed-JSON bound-inputs envelope the loop expects as its
    structured args (never a raw `--stream <name>` flag). Every required field is
    sourced exactly once; a missing source fails closed before any envelope
    is returned (launch-stream-envelope-sources)."""
    worktree = _require(env, _ENV_WORKTREE, "OCTO_WORKTREE (repo / worktree path)")
    worktree_root = _require(env, _ENV_WORKTREE_ROOT, "OCTO_WORKTREE_ROOT")
    repo_slug = _require(env, _ENV_REPO_SLUG, "OCTO_REPO_SLUG")
    starting_head = _require(env, _ENV_STARTING_HEAD, "OCTO_STARTING_HEAD")
    if not contract_hash:
        raise GateError("stream envelope missing source: contract_hash (resolved worker-role contract blob)")

    envelope: dict[str, Any] = {
        "repo": str(worktree),
        "worktree": str(worktree),
        "worktree_root": str(worktree_root),
        "repo_slug": str(repo_slug),
        "shaping_head": str(starting_head),
        "contract_hash": str(contract_hash),
    }

    for field in STREAM_FIELDS:
        envelope[field] = _require(stream, field, f"stream.{field}")

    for field in LIVE_READ_FIELDS:
        envelope[field] = _require(live_reads, field, f"live_reads.{field}")

    # The fresh PR head confirmation is a LIVE read (launch-stream-envelope-sources),
    # never trusted verbatim: it must independently agree with the provisioning
    # env's starting head before the envelope binds pr_head to that starting head.
    fresh_pr_head = envelope.pop("pr_head")
    if fresh_pr_head != starting_head:
        raise GateError("stream envelope fresh PR head confirmation mismatch")
    envelope["pr_head"] = str(starting_head)

    for field in SHAPING_JOURNAL_FIELDS:
        envelope[field] = _require(shaping_journal, field, f"shaping_journal.{field}")

    return envelope
