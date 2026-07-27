"""Stream-envelope builder (ADR 0003 drop-loop-trust-root; spec
launch-stream-envelope-builder, launch-stream-envelope-sources,
loop-runs-on-cwd-and-branch). Builds the loop's bound-inputs envelope as a plain
JSON-serializable dict so a Workflow-native invocation NEVER hands a raw `--stream
<name>` flag to the JSON-parsing loop entry. Every field has exactly one declared
source; a missing source fails closed before any envelope is returned.

The loop runs inside its provisioned worktree and reads no frozen launch
environment: the local repo path, the worktree, its branch, the repo slug, and the
starting head come from the running loop's own process working directory and git,
NOT an OCTO_* env seam. This module never reimplements the loop's own
assertReadyEnvelope validation logic (workflows/lib/gates.mjs), it only SOURCES the
fields that logic requires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from octo_lite.launch import LaneProvision
from octo_lite.runtime import GateError

# From the running loop's own process working directory and git
# (launch-stream-envelope-sources, loop-runs-on-cwd-and-branch): the local repo path
# used for git operations, the worktree, its worktree root, the repo slug, the branch,
# and the starting head, since the loop runs inside its provisioned worktree and reads
# no frozen launch environment.
CWD_GIT_FIELDS = (
    "worktree",
    "worktree_root",
    "repo_slug",
    "starting_head",
    "branch",
)

# From stream and brief data (launch-stream-envelope-sources).
STREAM_FIELDS = (
    "issue",
    "pr",
    "pr_base",
    "topology_revision",
    "conversation_log_references",
    "conversation_cutoff",
    "acceptance_criteria",
)

# From live reads at the shaping head (launch-stream-envelope-sources); pr_head is the
# FRESH PR head confirmation, cross-checked against the git-read starting head rather
# than trusted verbatim.
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
    cwd_git: Mapping[str, str],
    stream: Mapping[str, Any],
    live_reads: Mapping[str, Any],
    contract_hash: str,
    shaping_journal: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the parsed-JSON bound-inputs envelope the loop expects as its structured
    args (never a raw `--stream <name>` flag). The worktree, its root, the repo slug,
    the branch, and the starting head are SOURCED from the running loop's process
    working directory and git (loop-runs-on-cwd-and-branch); every required field is
    sourced exactly once; a missing source fails closed before any envelope is
    returned (launch-stream-envelope-sources)."""
    worktree = _require(cwd_git, "worktree", "cwd/git worktree path")
    worktree_root = _require(cwd_git, "worktree_root", "cwd/git worktree root")
    repo_slug = _require(cwd_git, "repo_slug", "git origin repo slug")
    starting_head = _require(cwd_git, "starting_head", "git HEAD (starting head)")
    branch = _require(cwd_git, "branch", "git branch")
    if not contract_hash:
        raise GateError("stream envelope missing source: contract_hash (resolved worker-role contract blob)")

    envelope: dict[str, Any] = {
        "repo": str(worktree),
        "worktree": str(worktree),
        "worktree_root": str(worktree_root),
        "repo_slug": str(repo_slug),
        "branch": str(branch),
        "shaping_head": str(starting_head),
        "contract_hash": str(contract_hash),
    }

    for field in STREAM_FIELDS:
        envelope[field] = _require(stream, field, f"stream.{field}")

    for field in LIVE_READ_FIELDS:
        envelope[field] = _require(live_reads, field, f"live_reads.{field}")

    # The fresh PR head confirmation is a LIVE read (launch-stream-envelope-sources),
    # never trusted verbatim: it must independently agree with the git-read starting
    # head before the envelope binds pr_head to that starting head.
    fresh_pr_head = envelope.pop("pr_head")
    if fresh_pr_head != starting_head:
        raise GateError("stream envelope fresh PR head confirmation mismatch")
    envelope["pr_head"] = str(starting_head)

    for field in SHAPING_JOURNAL_FIELDS:
        envelope[field] = _require(shaping_journal, field, f"shaping_journal.{field}")

    # Fail closed before the envelope is returned, mirroring the loop's own
    # assertReadyEnvelope semantics (workflows/lib/gates.mjs).
    for field in ("spec_blobs", "acceptance_criteria", "shaping_verdict_inputs", "conversation_log_references"):
        if not isinstance(envelope[field], list) or not envelope[field]:
            raise GateError(f"stream envelope requires a nonempty {field.replace('_', ' ')}")
    if envelope["shaping_verdict"] != "clear":
        raise GateError("stream envelope shaping verdict not clear")
    if envelope["shaping_verdict_head"] != envelope["shaping_head"]:
        raise GateError("stream envelope shaping verdict head mismatch")

    return envelope


def launch_stream_lane(
    stream_name: str,
    *,
    provision: LaneProvision,
    cwd_git: Mapping[str, str],
    stream: Mapping[str, Any],
    live_reads: Mapping[str, Any],
    contract_hash: str,
    shaping_journal: Mapping[str, Any],
    runner: Callable[[Path, Mapping[str, Any]], Any],
) -> Any:
    """Production entrypoint (spec launch-stream-envelope-builder,
    loop-runs-on-cwd-and-branch): given a stream NAME as pure identity, build the ready
    envelope from its real sources and start the loop through the injected runner, so
    the runner always receives the PARSED JSON envelope as a dict, never the stream
    name itself and never a raw `--stream <name>` string. The worktree, branch, repo
    slug, and starting head are SOURCED from the running loop's cwd + git (cwd_git),
    not a frozen launch environment; the loop runs inside the provisioned worktree, so
    the cwd is that worktree."""
    if not isinstance(stream_name, str) or not stream_name.strip():
        raise GateError("stream name required")
    envelope = build_stream_envelope(
        cwd_git=cwd_git, stream=stream, live_reads=live_reads,
        contract_hash=contract_hash, shaping_journal=shaping_journal,
    )
    cwd = Path(provision.record["worktree"])
    return runner(cwd, envelope)
