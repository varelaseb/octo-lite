from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from octo_lite.runtime import (
    GateError,
    admit_workspace,
    exact_fingerprint,
    launch_revision as _receipt_launch_revision,
    normalize_launch_access,
)
from workflows.lib.role_resolver import build_launch_receipt, load_registry, resolve_role


ReadLinear = Callable[[str], Mapping[str, Any]]
ReadPullRequest = Callable[[str, int], Mapping[str, Any]]


def _run(*argv: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def read_linear(issue: str) -> dict[str, Any]:
    raw = json.loads(_run("linear", "issue", "view", issue, "--json", "--no-download"))
    state = raw.get("state")
    normalized = dict(raw)
    normalized["state"] = state.get("name") if isinstance(state, dict) else state
    return normalized


def read_pull_request(repo: str, number: int) -> dict[str, Any]:
    return json.loads(
        _run(
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,url,headRefOid,headRefName,baseRefName,comments,"
            "state,reviewDecision,statusCheckRollup",
        )
    )


def _required(envelope: Mapping[str, Any], name: str) -> Any:
    value = envelope.get(name)
    if value is None or value == "":
        raise GateError(f"{name} required")
    return value


def _validate_envelope_shape(envelope: Mapping[str, Any]) -> None:
    for name in (
        "issue",
        "repo",
        "pr",
        "branch",
        "purpose",
        "starting_head",
        "shaping_head",
        "spec_revision",
        "linear_revision",
        "linear_fingerprint",
        "linear_state",
        "pr_head",
        "pr_base",
        "topology_revision",
        "conversation_cutoff",
        "pass_instruction",
    ):
        _required(envelope, name)
    references = envelope.get("conversation_log_references")
    if not isinstance(references, list) or not references or any(not isinstance(item, str) or not item for item in references):
        raise GateError("conversation log references required")
    if envelope["purpose"] not in {"shaping-review", "delivery"}:
        raise GateError("purpose must be shaping-review or delivery")
    if envelope["pr_head"] != envelope["starting_head"]:
        raise GateError("PR HEAD mismatch")
    if envelope["purpose"] == "shaping-review":
        if envelope["linear_state"] not in {"Ideas", "Todo", "Shaped", "In Progress"}:
            raise GateError("Linear state invalid for shaping review")
        if envelope["shaping_head"] != envelope["starting_head"]:
            raise GateError("shaping review must start at current HEAD")
    else:
        if envelope["linear_state"] not in {"Shaped", "Todo", "In Progress"}:
            raise GateError("Linear state must be Shaped, Todo, or In Progress")
        for name in ("shaping_verdict", "shaping_verdict_head", "shaping_reviewer_receipt"):
            _required(envelope, name)
        if envelope["shaping_verdict"] != "clear":
            raise GateError("shaping verdict not clear")
        if envelope["shaping_verdict_head"] != envelope["shaping_head"]:
            raise GateError("shaping verdict HEAD mismatch")
    for name, allow_empty in (
        ("spec_blobs", False),
        ("adr_blobs", True),
        ("acceptance_criteria", False),
    ):
        value = envelope.get(name)
        if not isinstance(value, list) or (not allow_empty and not value):
            raise GateError(f"{name.replace('_', ' ')} required")
    if envelope["purpose"] == "delivery":
        inputs = envelope.get("shaping_verdict_inputs")
        if not isinstance(inputs, list) or not inputs:
            raise GateError("shaping verdict inputs required")
    claims = envelope.get("resource_claims")
    if not isinstance(claims, Mapping) or set(claims) != {
        "branch", "fixtures", "ports", "pids", "artifact_roots",
    }:
        raise GateError("complete resource claims required")
    if not isinstance(claims["branch"], str) or not claims["branch"]:
        raise GateError("resource branch required")
    for name in ("fixtures", "artifact_roots"):
        if not isinstance(claims[name], list) or any(not isinstance(item, str) or not item for item in claims[name]):
            raise GateError(f"resource {name} invalid")
    for name in ("ports", "pids"):
        if not isinstance(claims[name], list) or any(not isinstance(item, int) or item < 1 for item in claims[name]):
            raise GateError(f"resource {name} invalid")
    if not isinstance(envelope.get("resource_conflicts"), list):
        raise GateError("resource conflicts required")
    if not isinstance(envelope.get("provider_overloaded"), bool):
        raise GateError("provider overload fact required")
    if not isinstance(envelope.get("minimum_free_bytes"), int) or envelope["minimum_free_bytes"] < 1:
        raise GateError("minimum free bytes required")


def _issue_revision(issue: Mapping[str, Any]) -> str:
    value = issue.get("updatedAt") or issue.get("updated_at") or issue.get("revision")
    return str(value or exact_fingerprint(issue))


def _pull_number(value: Any) -> int:
    if isinstance(value, int):
        return value
    match = re.search(r"/(\d+)(?:/)?$", str(value))
    if not match:
        raise GateError("PR number unreadable")
    return int(match.group(1))


def _remote_repo_identity(remote: str) -> str:
    if "://" in remote:
        path = urlparse(remote).path
    elif ":" in remote:
        path = remote.split(":", 1)[1]
    else:
        path = remote
    parts = [part for part in path.removesuffix(".git").strip("/").split("/") if part]
    if len(parts) < 2:
        raise GateError("repo identity unreadable from origin")
    return "/".join(parts[-2:])


def _parse_verdict(comments: Any) -> dict[str, Any]:
    if not isinstance(comments, list):
        raise GateError("shaping verdict comments missing")
    marker = "<!-- octo-lite-verdict:shaping -->"
    for comment in comments:
        body = comment.get("body", "") if isinstance(comment, dict) else ""
        if marker not in body:
            continue
        match = re.search(r"```toml\s*(.*?)\s*```", body, re.DOTALL)
        if not match:
            raise GateError("shaping verdict unreadable")
        try:
            return tomllib.loads(match.group(1))
        except tomllib.TOMLDecodeError as error:
            raise GateError("shaping verdict unreadable") from error
    raise GateError("shaping verdict missing")


def _git(repo: Path, *args: str) -> str:
    return _run("git", "-C", str(repo), *args)


def _verify_blobs(repo: Path, head: str, bindings: list[str], label: str) -> None:
    for binding in bindings:
        if not isinstance(binding, str) or ":" not in binding:
            raise GateError(f"{label} blob binding unreadable")
        relative, expected = binding.rsplit(":", 1)
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise GateError(f"{label} path escapes repo")
        try:
            actual = _git(repo, "rev-parse", f"{head}:{path.as_posix()}")
        except subprocess.CalledProcessError as error:
            raise GateError(f"{label} blob missing: {relative}") from error
        if actual != expected:
            raise GateError(f"{label} blob mismatch: {relative}")


def _verify_snapshot_source(snapshot_path: Path, snapshot_digest: str, allowed_root: Path) -> bytes:
    """Independently prove the caller's claimed snapshot_digest by reading and
    hashing the exact snapshot_path bytes, rather than trusting the caller's own
    claim. Rejects a missing, symlinked, escaping, unreadable, or hash-mismatched
    source before any worktree or provider launch. Returns the verified bytes so
    the gateway can persist them to the final receipt-bound location."""
    if snapshot_path.is_symlink():
        raise GateError("snapshot source must be a regular file")
    allowed = allowed_root.resolve()
    resolved = snapshot_path.resolve()
    if os.path.commonpath((allowed, resolved)) != str(allowed) or resolved == allowed:
        raise GateError("snapshot path escapes allowed root")
    if not resolved.is_file():
        raise GateError("snapshot source missing")
    try:
        content = resolved.read_bytes()
    except OSError as error:
        raise GateError("snapshot source unreadable") from error
    actual = hashlib.sha256(content).hexdigest()
    if actual != str(snapshot_digest):
        raise GateError("snapshot digest mismatch")
    return content


def _verify_sources(
    repo: Path,
    envelope: Mapping[str, Any],
    linear: Mapping[str, Any],
    pull: Mapping[str, Any],
) -> None:
    if linear.get("identifier") != envelope["issue"]:
        raise GateError("Linear identity mismatch")
    if linear.get("state") != envelope["linear_state"]:
        raise GateError("Linear state mismatch")
    if _issue_revision(linear) != str(envelope["linear_revision"]):
        raise GateError("Linear revision mismatch")
    if exact_fingerprint(linear) != envelope["linear_fingerprint"]:
        raise GateError("Linear fingerprint mismatch")

    if pull.get("headRefOid") != envelope["starting_head"]:
        raise GateError("PR HEAD mismatch")
    if pull.get("baseRefName") != envelope["pr_base"]:
        raise GateError("PR base mismatch")
    if pull.get("headRefName") != envelope["branch"]:
        raise GateError("PR branch mismatch")
    if str(pull.get("url")) != str(envelope["pr"]):
        raise GateError("PR identity mismatch")
    if str(envelope["resource_claims"]["branch"]) != str(envelope["branch"]):
        raise GateError("resource branch mismatch")

    if envelope["purpose"] == "delivery":
        verdict = _parse_verdict(pull.get("comments"))
        expected_verdict = {
            "review_type": "shaping",
            "verdict": "clear",
            "head": envelope["shaping_head"],
            "bound_inputs": envelope["shaping_verdict_inputs"],
            "reviewer_receipt": envelope["shaping_reviewer_receipt"],
            # A nonempty reference or cutoff alone is not proof: it must be the exact
            # one this envelope declares, or a stale or substituted verdict from an
            # unrelated or earlier session could otherwise pass preflight.
            "conversation_log_references": envelope["conversation_log_references"],
            "conversation_cutoff": envelope["conversation_cutoff"],
        }
        mismatches = [name for name, value in expected_verdict.items() if verdict.get(name) != value]
        if mismatches:
            raise GateError(f"shaping verdict mismatch: {', '.join(mismatches)}")

    _verify_blobs(repo, envelope["starting_head"], envelope["spec_blobs"], "spec")
    _verify_blobs(repo, envelope["starting_head"], envelope["adr_blobs"], "ADR")


def _linear_binding(linear: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identifier": linear["identifier"],
        "revision": _issue_revision(linear),
        "fingerprint": exact_fingerprint(linear),
        "state": linear["state"],
    }


def _normalized_status_checks(rollup: Any) -> list[dict[str, str]]:
    if not isinstance(rollup, list):
        return []
    normalized = []
    for entry in rollup:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name") or entry.get("context") or "")
        status = str(entry.get("status") or "")
        outcome = str(entry.get("conclusion") or entry.get("state") or "")
        normalized.append({"name": name, "status": status, "outcome": outcome})
    # Sorting on the full normalized content, not only name, makes duplicate-name
    # entries land in the same order regardless of the API's own return order, so
    # differing outcomes or in-progress states never collapse or reorder the
    # fingerprint for the same actual rollup.
    return sorted(normalized, key=lambda item: (item["name"], item["status"], item["outcome"]))


def _pull_request_binding(pull: Mapping[str, Any], *, repo: str, number: int) -> dict[str, Any]:
    return {
        "repo": repo,
        "number": number,
        "url": str(pull["url"]),
        "branch": str(pull["headRefName"]),
        "base": str(pull["baseRefName"]),
        "head": str(pull["headRefOid"]),
    }


def fetch_stream_binding(
    *,
    linear_issue: str | None,
    pr_repo: str | None,
    pr_number: int | None,
    read_linear: ReadLinear = read_linear,
    read_pr: ReadPullRequest = read_pull_request,
) -> dict[str, Any]:
    """Fetch and bind one stream's declared Linear issue and pull request, the sole
    fact shape shared between a snapshot's declared facts and the reconcile
    gateway's fresh re-verification of those same facts."""
    binding: dict[str, Any] = {}
    if linear_issue:
        linear = dict(read_linear(linear_issue))
        state = linear.get("state")
        if isinstance(state, Mapping):
            linear["state"] = state.get("name")
        binding["linear"] = _linear_binding(linear)
    if pr_repo and pr_number:
        pull = dict(read_pr(pr_repo, pr_number))
        pr_binding = _pull_request_binding(pull, repo=pr_repo, number=pr_number)
        pr_binding["state"] = str(pull.get("state") or "")
        pr_binding["review"] = str(pull.get("reviewDecision") or "")
        pr_binding["status_checks"] = _normalized_status_checks(pull.get("statusCheckRollup"))
        binding["pull_request"] = pr_binding
    return binding


def _worktree_common_dir(path: Path) -> Path:
    value = _git(path, "rev-parse", "--git-common-dir")
    candidate = Path(value)
    return (path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


# Mutable implement/fix passes attach the exact bound PR branch. Review, QA review,
# shaping review, and the reconciler are inherently read-only (no Bash/Edit/Write
# tools) and may use a fresh detached worktree at the exact HEAD instead.
READ_ONLY_WORKTREE_ROLES = frozenset({"shaping-reviewer", "code-reviewer", "qa-reviewer", "reconciler"})


def _verify_review_worktree_unmutated(receipt: Mapping[str, Any], stage: str) -> None:
    """A read-only role's OpenAI resume may run under workspace-write plus network
    access to reach live GitHub or Linear; this independently proves that capability
    was never used to change the review-pass worktree itself."""
    if receipt["role"]["name"] not in READ_ONLY_WORKTREE_ROLES:
        return
    worktree = Path(receipt["workspace"]["worktree"])
    expected_head = str(receipt["workspace"]["starting_head"])
    try:
        actual_head = _git(worktree, "rev-parse", "HEAD")
        dirty = _git(worktree, "status", "--porcelain")
    except subprocess.CalledProcessError as error:
        raise GateError(f"review-pass worktree verification failed after {stage}") from error
    if actual_head != expected_head:
        raise GateError(f"review-pass worktree HEAD mutated after {stage}")
    if dirty:
        raise GateError(f"review-pass worktree status mutated after {stage}")


def _branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _prepare_worktree(
    repo: Path,
    root: Path,
    worktree: Path,
    head: str,
    branch: str,
    *,
    read_only: bool,
    minimum_free_bytes: int,
    conflicts: list[str],
    provider_overloaded: bool,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    admit_workspace(
        worktree,
        root,
        disk_free_bytes=free,
        minimum_free_bytes=minimum_free_bytes,
        conflicts=conflicts,
        provider_overloaded=provider_overloaded,
    )
    if worktree.exists():
        raise GateError("fresh pass requires a new absent worktree path")
    try:
        if read_only:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), head],
                check=True, capture_output=True, text=True,
            )
        elif _branch_exists(repo, branch):
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", str(worktree), branch],
                check=True, capture_output=True, text=True,
            )
        else:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", str(worktree), "-b", branch, head],
                check=True, capture_output=True, text=True,
            )
    except subprocess.CalledProcessError as error:
        raise GateError(f"worktree creation failed: {error.stderr.strip()}") from error
    try:
        top = Path(_git(worktree, "rev-parse", "--show-toplevel")).resolve()
        actual_head = _git(worktree, "rev-parse", "HEAD")
        actual_branch = _git(worktree, "branch", "--show-current")
        dirty = _git(worktree, "status", "--porcelain")
    except subprocess.CalledProcessError as error:
        raise GateError("worktree validation failed") from error
    if top != worktree.resolve():
        raise GateError("worktree must be git root")
    if _worktree_common_dir(worktree) != _worktree_common_dir(repo):
        raise GateError("worktree belongs to another repo")
    if actual_head != head:
        raise GateError("worktree starting HEAD mismatch")
    if dirty:
        raise GateError("fresh worktree is dirty")
    if read_only:
        if actual_branch:
            raise GateError("read-only worktree must be detached")
    elif actual_branch != branch:
        raise GateError("worktree branch mismatch")
    if not (worktree / "AGENTS.md").is_file():
        raise GateError("target AGENTS.md missing")


def _owning_provision_record(worktree: Path) -> Path | None:
    """provision-record-guard (TUR-447 d1, workspace-cleanup-clean-abort,
    launch-provision-record-schema): prove workspace-admit created and owns THIS
    exact worktree before any error-path removal, returning the proving record's
    path (for retirement after a successful removal) or None. Ownership is
    proven only by a host-provision record at a host-known location, the
    OCTO_PROVISION_RECORD seam path or a workspace-admit-written
    .octo-provisions record beside the worktree, that passes the frozen schema
    validation (source host-provisioned-worktree, schema_version 1, via
    validate_provision_record) and whose record.worktree is this worktree.

    TUR-447 cycle-2 P1-2b (provision-instance binding): a pathname match alone
    is NOT ownership. The record must also match the LIVE worktree's identity
    through non-destructive checks: the worktree's git common dir must resolve
    to the record's control_repo, and the worktree's checked-out branch must
    equal the record's branch. A stale record plus a hand-recreated worktree at
    the same conventional path (a different branch, a different repo, or a
    detached HEAD) therefore proves nothing. Anything unreadable, malformed,
    mismatched, or unprovable stays None and the worktree is preserved."""
    resolved = Path(worktree).resolve()
    target = str(resolved)
    candidates: list[Path] = []
    env_path = os.environ.get("OCTO_PROVISION_RECORD", "")
    if env_path:
        candidates.append(Path(env_path))
    for ancestor in resolved.parents:
        records_dir = ancestor / ".octo-provisions"
        if records_dir.is_dir():
            candidates.extend(sorted(records_dir.glob("*.json")))
    for path in candidates:
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        try:
            validate_provision_record(record)
        except GateError:
            continue
        if str(record["worktree"]) != target:
            continue
        try:
            if _worktree_common_dir(resolved) != _worktree_common_dir(Path(str(record["control_repo"]))):
                continue
            actual_branch = _git(resolved, "symbolic-ref", "--short", "HEAD")
        except (OSError, subprocess.CalledProcessError):
            continue
        if actual_branch != str(record["branch"]):
            continue
        return path
    return None


def _provision_record_owns_worktree(worktree: Path) -> bool:
    return _owning_provision_record(worktree) is not None


def cleanup_clean_abort(
    repo: Path, worktree: Path, expected_head: str, *, gateway_provisioned: bool = False
) -> None:
    """workspace-cleanup-clean-abort: a pass failing before its acknowledgment
    echo is verified removes its worktree on the error path only when that
    worktree is pristine, meaning zero dirty lines and HEAD equal to the exact
    expected starting head, so an abandoned clean worktree never blocks the
    next fresh pass at the same path. A dirty or diverged worktree, or one
    that is not a genuine worktree of the exact bound repo, is preserved for
    inspection instead of being force-removed.

    provision-record-guard (TUR-447 d1): removal is additionally gated on proven
    host-provision ownership. The caller either provisioned this exact worktree
    itself in the failing flow (gateway_provisioned=True, the reconcile gateway
    whose prepare creates its worktree at a required-absent path), or a matching
    host-provision record must prove workspace-admit created and owns it. A
    foreign or hand-created worktree with no such matching record is PRESERVED,
    never force-removed, even when clean and at the exact expected head; the
    pristine-only checks below stay as additional guards, never the sole basis.

    TUR-447 cycle-2 P1-2: ownership is bound to the provision INSTANCE, not the
    pathname (_owning_provision_record checks control_repo and branch identity
    against the live worktree), and a successful record-authorized removal
    RETIRES the proving record, so a stale record can never re-authorize
    deleting a later hand-created worktree at the same conventional path."""
    repo = Path(repo)
    worktree = Path(worktree)
    if worktree == repo or not worktree.is_dir():
        return
    record_path: Path | None = None
    if not gateway_provisioned:
        record_path = _owning_provision_record(worktree)
        if record_path is None:
            return
    try:
        if _worktree_common_dir(worktree) != _worktree_common_dir(repo):
            return
        if _git(worktree, "rev-parse", "HEAD") != str(expected_head):
            return
        if _git(worktree, "status", "--porcelain"):
            return
    except subprocess.CalledProcessError:
        return
    try:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", str(worktree)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        return
    # Record retirement (TUR-447 cycle-2 P1-2a): the worktree this record
    # authorized removing is gone, so the record's authority ends with it.
    if record_path is not None:
        try:
            record_path.unlink()
        except OSError:
            pass


# gh#8 host-provisioned isolated worktree (spec launch-provisioning-trust-root,
# workspace-admission-provisions). Provisioning REUSES the existing create+verify
# path in _prepare_worktree (workspace-provision-shares-create-verify) and ADDS the
# origin-slug reality check, the same-lane idempotent-reuse disposition, the
# control-repository-path-itself refusal, and an own-CLAUDE.md wiring check the
# generic worker-pass path never needed.

PROVISION_RECORD_SOURCE = "host-provisioned-worktree"

# launch-provision-record-schema: the RFC3339 date-time profile (structural
# shape only; calendar-date and tz-aware confirmation stay with
# datetime.fromisoformat below). `datetime.fromisoformat` alone is NOT
# sufficient (re-review finding 2): it also accepts non-RFC3339 forms such as
# ISO week dates ("2026-W30-2...") and compact/basic timestamps
# ("20260721T000000+0000"), which this pattern rejects while still accepting
# the Z form and the numeric-offset form. The seconds field is captured
# separately (re-review finding, leap seconds) because RFC3339 section 5.6
# permits the value 60 there, which `datetime.fromisoformat` rejects.
#
# Every numeric component below is explicitly range-bound (re-review finding,
# offset-bounds regression): month 01-12, day 01-31, hour 00-23, minute
# 00-59, second 00-60 (60 = leap second, handled separately below), and the
# offset hour 00-23 / offset minute 00-59. A loose `[+-]\d{2}:\d{2}` offset
# previously let an out-of-range offset such as "+00:60" or "+24:00" match
# the regex, after which `datetime.fromisoformat` silently NORMALIZES the
# out-of-range offset instead of rejecting it, so the structural pattern
# alone must reject those values before fromisoformat ever sees them.
_RFC3339_DATE_TIME_RE = re.compile(
    r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])"
    r"[Tt](?:[01]\d|2[0-3]):[0-5]\d:(?P<seconds>[0-5]\d|60)(\.\d+)?"
    r"([Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)

# launch-provision-record-schema: exactly these keys, no more, no fewer.
PROVISION_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "lane",
        "control_repo",
        "worktree",
        "worktree_root",
        "repo_slug",
        "branch",
        "starting_head",
        "resolver_root",
        "install_check",
        "provisioned_at",
    }
)
PROVISION_RECORD_ABSOLUTE_PATH_KEYS = ("control_repo", "worktree", "worktree_root", "resolver_root")
PROVISION_RECORD_INSTALL_CHECK_VALUES = frozenset({"clean", "drifted"})

# launch-provision-wiring-liveness: a genuine install drift is recorded truthfully
# and ROUTED to the installed-surface owner, never silently repaired in place (the
# installer itself refuses to replace a nonmatching target).
INSTALLED_SURFACE_OWNER = "installed-surface-owner"

# launch-provision-env-seam: the frozen stable seam names, in the frozen order.
LANE_ENV_KEYS = (
    "OCTO_WORKTREE",
    "OCTO_WORKTREE_ROOT",
    "OCTO_CONTROL_REPO",
    "OCTO_REPO_SLUG",
    "OCTO_STARTING_HEAD",
    "OCTO_LANE",
    "OCTO_PROVISION_RECORD",
)


def validate_provision_record(record: Mapping[str, Any]) -> None:
    """launch-provision-record-schema: any extra key, missing key, wrong type, or
    wrong source value fails closed."""
    if not isinstance(record, Mapping):
        raise GateError("provision record must be an object")
    keys = set(record)
    extra = keys - PROVISION_RECORD_KEYS
    missing = PROVISION_RECORD_KEYS - keys
    if extra or missing:
        raise GateError(f"provision record keys invalid: extra={sorted(extra)} missing={sorted(missing)}")
    if not isinstance(record["schema_version"], int) or isinstance(record["schema_version"], bool):
        raise GateError("provision record schema_version must be an integer")
    if record["schema_version"] != 1:
        raise GateError("provision record schema_version must be 1")
    if record["source"] != PROVISION_RECORD_SOURCE:
        raise GateError("provision record source must be host-provisioned-worktree")
    for key in PROVISION_RECORD_KEYS - {"schema_version"}:
        value = record[key]
        if not isinstance(value, str) or not value:
            raise GateError(f"provision record field must be a nonempty string: {key}")
    for key in PROVISION_RECORD_ABSOLUTE_PATH_KEYS:
        if not os.path.isabs(record[key]):
            raise GateError(f"provision record {key} must be an absolute path")
    if record["resolver_root"] != record["worktree"]:
        raise GateError("provision record resolver_root must equal worktree")
    slug_parts = record["repo_slug"].split("/")
    if len(slug_parts) != 2 or not all(slug_parts):
        raise GateError("provision record repo_slug must be an owner/repo slug")
    if record["install_check"] not in PROVISION_RECORD_INSTALL_CHECK_VALUES:
        raise GateError("provision record install_check must be clean or drifted")
    if not re.fullmatch(r"[0-9a-f]{40}", record["starting_head"]):
        raise GateError("provision record starting_head must be a resolved commit sha")
    raw_provisioned_at = record["provisioned_at"]
    match = _RFC3339_DATE_TIME_RE.fullmatch(raw_provisioned_at)
    if not match:
        raise GateError("provision record provisioned_at must be an RFC3339 timestamp")
    normalized = raw_provisioned_at.replace("Z", "+00:00").replace("z", "+00:00")
    if match.group("seconds") == "60":
        # RFC3339 section 5.6 permits a leap-second value (seconds field 60),
        # but `datetime.fromisoformat` raises on second=60, so this case
        # cannot depend on it succeeding. Probe with the seconds field
        # substituted to 59 to confirm the surrounding date/time components
        # and the tz-aware offset are genuinely valid, without accepting the
        # leap second through fromisoformat itself.
        probe = normalized[: match.start("seconds")] + "59" + normalized[match.end("seconds"):]
        try:
            probed = datetime.fromisoformat(probe)
        except ValueError as error:
            raise GateError("provision record provisioned_at must be an RFC3339 timestamp") from error
        if probed.tzinfo is None:
            raise GateError("provision record provisioned_at must be an RFC3339 timestamp")
        return
    try:
        provisioned_at = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise GateError("provision record provisioned_at must be an RFC3339 timestamp") from error
    if provisioned_at.tzinfo is None:
        # A date-only or timezone-less value parses successfully as a naive
        # datetime; RFC3339 requires an explicit offset, so a naive result is
        # rejected here.
        raise GateError("provision record provisioned_at must be an RFC3339 timestamp")


def default_install_check(control_repo: Path, *, prefix: Path | None = None) -> str:
    """launch-provision-wiring-liveness: run the real installer's read-only
    --check and report clean or drifted. Never repairs; the installer itself
    refuses to replace a nonmatching target."""
    installer = Path(control_repo) / "scripts" / "install-octo-lite"
    argv = [str(installer), "--check"]
    if prefix is not None:
        argv += ["--prefix", str(prefix)]
    result = subprocess.run(argv, capture_output=True, text=True)
    return "clean" if result.returncode == 0 else "drifted"


def _find_foreign_lane_record(records_dir: Path, worktree: Path, lane: str, *, exclude: Path) -> str | None:
    """launch-provision-exclusivity: a path already bound to a DIFFERENT lane is
    refused. Returns the foreign lane name, or None if the path is unclaimed or
    claimed by this same lane. A malformed or foreign (non-schema) record found
    during the scan FAILS CLOSED rather than being silently skipped, so it can
    never weaken record-backed exclusivity."""
    if not records_dir.is_dir():
        return None
    target = str(worktree.resolve())
    for path in sorted(records_dir.glob("*.json")):
        if path == exclude:
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise GateError(f"malformed provision record: {path}") from error
        try:
            validate_provision_record(record)
        except GateError as error:
            raise GateError(f"foreign provision record: {path}: {error}") from error
        if record.get("worktree") == target and record.get("lane") != lane:
            return str(record.get("lane"))
    return None


def verify_lane_worktree_reality(
    control_repo: Path, worktree: Path, head: str, branch: str, repo_slug: str
) -> None:
    """launch-provision-verify + workspace-provision-shares-create-verify: verify
    the worktree by reality (top-level, common-dir, HEAD, branch, clean tree),
    plus the ADDED origin-slug reality check and the own-CLAUDE.md wiring check
    (launch-provision-wiring-liveness)."""
    control_repo = Path(control_repo)
    worktree = Path(worktree)
    try:
        top = Path(_git(worktree, "rev-parse", "--show-toplevel")).resolve()
    except subprocess.CalledProcessError as error:
        raise GateError("worktree validation failed") from error
    if top != worktree.resolve():
        raise GateError("worktree must be git root")
    if _worktree_common_dir(worktree) != _worktree_common_dir(control_repo):
        raise GateError("worktree belongs to another repo")
    try:
        actual_head = _git(worktree, "rev-parse", "HEAD")
        actual_branch = _git(worktree, "branch", "--show-current")
        dirty = _git(worktree, "status", "--porcelain")
    except subprocess.CalledProcessError as error:
        raise GateError("worktree validation failed") from error
    if actual_head != head:
        raise GateError("worktree starting HEAD mismatch")
    if actual_branch != branch:
        raise GateError("worktree branch mismatch")
    if dirty:
        raise GateError("fresh worktree is dirty")
    try:
        origin = _git(worktree, "remote", "get-url", "origin")
    except subprocess.CalledProcessError as error:
        raise GateError("worktree origin remote unreadable") from error
    if _remote_repo_identity(origin) != repo_slug:
        raise GateError("worktree origin does not resolve to the expected repo slug")
    if not (worktree / "AGENTS.md").is_file():
        raise GateError("target AGENTS.md missing")
    if not (worktree / "CLAUDE.md").is_file():
        raise GateError("target CLAUDE.md missing")


@dataclass(frozen=True)
class LaneProvision:
    record: dict[str, Any]
    record_path: Path
    install_check_owner_route: str | None


def provision_lane_worktree(
    *,
    control_repo: Path,
    worktree_root: Path,
    worktree: Path,
    lane: str,
    branch: str,
    head: str,
    repo_slug: str,
    minimum_free_bytes: int = 1,
    conflicts: list[str] | None = None,
    provider_overloaded: bool = False,
    install_check: Callable[[Path], str] = default_install_check,
    now: Callable[[], str] | None = None,
) -> LaneProvision:
    """workspace-admission-provisions, launch-provision-exclusivity,
    workspace-provision-idempotent: provision the exclusive per-lane worktree,
    reusing an already-provisioned worktree for the SAME lane at the expected
    repo/branch/head without error, and refusing the control repository path
    itself and any path already bound to a different lane or branch. Emits the
    host-authored provisioning record OUT of the worktree tree
    (launch-provision-record-out-of-tree)."""
    control_repo = Path(control_repo).resolve()
    worktree_root = Path(worktree_root).resolve()
    worktree = Path(worktree).resolve()
    if not lane or not lane.strip():
        raise GateError("lane identity required")
    # Sanitize the lane before it ever controls a filesystem path (code-review
    # finding 1): a lane carrying a path separator, a bare "..", or an
    # absolute-path shape could otherwise escape .octo-provisions/ when the
    # record path is built from it below.
    if "/" in lane or "\\" in lane or lane in {"..", "."} or os.path.isabs(lane):
        raise GateError("lane identity invalid")
    if worktree == control_repo:
        raise GateError("provisioning refuses the control repository path itself")
    try:
        control_top = Path(_git(control_repo, "rev-parse", "--show-toplevel")).resolve()
    except subprocess.CalledProcessError as error:
        raise GateError("control repo must be a git root") from error
    if control_top != control_repo:
        raise GateError("control repo must be a git root")

    # Resolve the starting commit ref to a full PEELED COMMIT sha BEFORE any
    # comparison or recording (code-review finding 4; re-review finding 1): a
    # branch name or abbreviated sha must provision correctly rather than
    # mismatch against the worktree's own resolved HEAD after worktree
    # creation, and an ANNOTATED TAG must be peeled to the commit it points
    # at (plain `rev-parse <ref>` returns the tag OBJECT sha, but
    # `git worktree add` checks out the peeled commit).
    try:
        head = _git(control_repo, "rev-parse", "--verify", f"{head}^{{commit}}")
    except subprocess.CalledProcessError as error:
        raise GateError(f"starting commit unresolvable: {head}") from error

    worktree_root.mkdir(parents=True, exist_ok=True)
    admit_workspace(
        worktree,
        worktree_root,
        disk_free_bytes=shutil.disk_usage(worktree_root).free,
        minimum_free_bytes=minimum_free_bytes,
        conflicts=list(conflicts or []),
        provider_overloaded=provider_overloaded,
    )

    records_dir = worktree_root / ".octo-provisions"
    records_dir.mkdir(parents=True, exist_ok=True)
    lane_record_path = records_dir / f"{lane}.json"
    lock_path = records_dir / f"{lane}.lock"

    # Lane reservation lock (code-review finding 3): reserve+create+record runs
    # under an exclusive fcntl lock keyed to this lane, so concurrent same-lane
    # requests for different paths/branches can never both create worktrees and
    # last-write the single lane record; the second request blocks here until
    # the first has fully finished.
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        foreign_lane = _find_foreign_lane_record(records_dir, worktree, lane, exclude=lane_record_path)
        if foreign_lane is not None:
            raise GateError(f"worktree already bound to a different lane: {foreign_lane}")

        existing_lane_record: dict[str, Any] | None = None
        if lane_record_path.is_file():
            existing_lane_record = json.loads(lane_record_path.read_text())
            validate_provision_record(existing_lane_record)

        if worktree.exists():
            if existing_lane_record is None:
                raise GateError("worktree path exists but is not provisioned for this lane")
            if existing_lane_record["worktree"] != str(worktree):
                raise GateError("lane already provisioned at a different worktree path")
            if existing_lane_record["branch"] != branch:
                raise GateError("lane already provisioned on a different branch")
            # Idempotent reuse: skip worktree creation and fall through to the same
            # reality verification the fresh-create path runs.
        else:
            if existing_lane_record is not None:
                raise GateError("lane record exists but its provisioned worktree is missing")
            _prepare_worktree(
                control_repo,
                worktree_root,
                worktree,
                head,
                branch,
                read_only=False,
                minimum_free_bytes=minimum_free_bytes,
                conflicts=list(conflicts or []),
                provider_overloaded=provider_overloaded,
            )

        verify_lane_worktree_reality(control_repo, worktree, head, branch, repo_slug)

        resolver_root = load_registry(worktree).root
        if resolver_root != worktree:
            raise GateError("role resolver root must be the provisioned worktree")

        check_state = install_check(control_repo)
        if check_state not in PROVISION_RECORD_INSTALL_CHECK_VALUES:
            raise GateError("install check must report clean or drifted")
        owner_route = INSTALLED_SURFACE_OWNER if check_state == "drifted" else None

        provisioned_at = now() if now is not None else datetime.now(timezone.utc).isoformat()
        record = {
            "schema_version": 1,
            "source": PROVISION_RECORD_SOURCE,
            "lane": lane,
            "control_repo": str(control_repo),
            "worktree": str(worktree),
            "worktree_root": str(worktree_root),
            "repo_slug": repo_slug,
            "branch": branch,
            "starting_head": head,
            "resolver_root": str(resolver_root),
            "install_check": check_state,
            "provisioned_at": provisioned_at,
        }
        validate_provision_record(record)

        _atomic_write(lane_record_path, json.dumps(record, indent=2, sort_keys=True) + "\n")

        # launch-provision-record-out-of-tree: the record lives outside the worktree
        # tree, so the verified-clean tree stays clean.
        if _git(worktree, "status", "--porcelain"):
            raise GateError("worktree unexpectedly dirty after provisioning")

        return LaneProvision(record=record, record_path=lane_record_path, install_check_owner_route=owner_route)


def lane_invocation_env(provision: LaneProvision) -> tuple[Path, dict[str, str]]:
    """launch-provision-env-seam: cwd is the provisioned worktree; env carries
    exactly the 7 frozen OCTO_* names, without importing or editing
    octo-loop-qa.js."""
    record = provision.record
    cwd = Path(record["worktree"])
    values = {
        "OCTO_WORKTREE": record["worktree"],
        "OCTO_WORKTREE_ROOT": record["worktree_root"],
        "OCTO_CONTROL_REPO": record["control_repo"],
        "OCTO_REPO_SLUG": record["repo_slug"],
        "OCTO_STARTING_HEAD": record["starting_head"],
        "OCTO_LANE": record["lane"],
        "OCTO_PROVISION_RECORD": str(provision.record_path),
    }
    env = {key: values[key] for key in LANE_ENV_KEYS}
    return cwd, env


def run_lane_loop(
    provision: LaneProvision,
    envelope: Mapping[str, Any],
    *,
    runner: Callable[[Path, Mapping[str, str], Mapping[str, Any]], Any],
) -> Any:
    """launch-provision-identity-supersedes-interim (ruling-62 'runs the loop IN
    it'): actually INVOKE the loop through the injected runner with the seam's
    cwd, env, and the already-built envelope, proving this layer STARTS the loop
    rather than only building params."""
    cwd, env = lane_invocation_env(provision)
    return runner(cwd, env, envelope)


def _child_workspace_check(
    repo: Path, root: Path, worktree: Path, head: str, branch: str | None
) -> dict[str, Any]:
    child = r'''
import json
import os
import subprocess
import sys
from pathlib import Path

expected = json.load(sys.stdin)
cwd = Path.cwd().resolve()
root = Path(expected["root"]).resolve()
repo = Path(expected["repo"]).resolve()
top = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
).stdout.strip()).resolve()
head = subprocess.run(
    ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
).stdout.strip()
branch = subprocess.run(
    ["git", "branch", "--show-current"], check=True, capture_output=True, text=True
).stdout.strip()
common = Path(subprocess.run(
    ["git", "rev-parse", "--git-common-dir"], check=True, capture_output=True, text=True
).stdout.strip())
common = (cwd / common).resolve() if not common.is_absolute() else common.resolve()
repo_common_raw = subprocess.run(
    ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
    check=True, capture_output=True, text=True,
).stdout.strip()
repo_common = Path(repo_common_raw)
repo_common = (repo / repo_common).resolve() if not repo_common.is_absolute() else repo_common.resolve()
if cwd != Path(expected["worktree"]).resolve() or top != cwd:
    raise SystemExit("child worktree identity mismatch")
if os.path.commonpath((root, cwd)) != str(root) or cwd == root:
    raise SystemExit("child worktree containment mismatch")
if common != repo_common or head != expected["head"] or not (cwd / "AGENTS.md").is_file():
    raise SystemExit("child workspace fact mismatch")
expected_branch = expected.get("branch")
if expected_branch is not None and branch != expected_branch:
    raise SystemExit("child worktree branch mismatch")
if expected_branch is None and branch:
    raise SystemExit("child worktree unexpectedly attached to a branch")
json.dump({"worktree": str(cwd), "head": head, "branch": branch, "contained": True}, sys.stdout)
'''
    payload = {
        "repo": str(repo),
        "root": str(root),
        "worktree": str(worktree),
        "head": head,
        "branch": branch,
    }
    try:
        result = subprocess.run(
            [os.environ.get("PYTHON", "python3"), "-c", child],
            cwd=worktree,
            input=json.dumps(payload),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise GateError("child workspace bootstrap check failed") from error
    return json.loads(result.stdout)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list) and all(isinstance(item, (str, int)) for item in value):
        return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
    raise GateError(f"unsupported receipt value: {type(value).__name__}")


def render_receipt(receipt: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for key, value in receipt.items():
        if isinstance(value, Mapping):
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    for section, values in receipt.items():
        if not isinstance(values, Mapping):
            continue
        lines.extend(["", f"[{section}]"])
        lines.extend(f"{key} = {_toml_value(value)}" for key, value in values.items())
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _provider_argv(receipt: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    runtime = receipt["runtime"]
    worktree = receipt["workspace"]["worktree"]
    provider = runtime["provider"]
    session = receipt["spawn_id"]
    if provider == "anthropic":
        try:
            uuid.UUID(session)
        except ValueError as error:
            raise GateError("Anthropic spawn ID must be a UUID") from error
        safe_tools = [tool for tool in runtime["tools"] if tool in {"Read", "Grep", "Glob"}]
        common = [
            "--model", runtime["model"],
            "--effort", runtime["effort"],
            "--permission-mode", runtime["mode"],
        ]
        bootstrap = [
            "claude", "--print", "--output-format", "json", "--session-id", session,
            *common, "--tools", ",".join(safe_tools),
        ]
        mutation = [
            "claude", "--print", "--output-format", "json", "--resume", session,
            *common, "--tools", ",".join(runtime["tools"]),
        ]
    elif provider == "openai":
        config = [
            "-c", f'model_reasoning_effort="{runtime["effort"]}"',
            "-c", f'service_tier="{runtime["service_tier"]}"',
        ]
        bootstrap = [
            "codex", "exec", "--json", "-C", worktree, "-m", runtime["model"],
            *config, "-s", "read-only", "-",
        ]
        # A review pass whose tools include a live GitHub or Linear read needs
        # network for its resumed pass; read-only sandbox never grants network,
        # so that resume explicitly opts into workspace-write plus network access
        # instead. Every other OpenAI resume stays read-only. The installed CLI's
        # resume subcommand rejects the top-level -s flag (exit 2, "unexpected
        # argument '-s'"), so sandbox selection goes through -c config instead;
        # only the exec bootstrap above still accepts -s.
        needs_live_reads = {"linear-read", "github-read"} & set(runtime["tools"])
        resume_sandbox = (
            ["-c", 'sandbox_mode="workspace-write"', "-c", "sandbox_workspace_write.network_access=true"]
            if needs_live_reads else ["-c", 'sandbox_mode="read-only"']
        )
        mutation = [
            "codex", "exec", "resume", "--json", "-m", runtime["model"],
            *config, *resume_sandbox, "{provider_session_id}", "-",
        ]
    else:
        raise GateError("unsupported provider")
    if "--last" in bootstrap + mutation or "--continue" in bootstrap + mutation:
        raise GateError("implicit continuation prohibited")
    return bootstrap, mutation


def _expected_ack(receipt: Mapping[str, Any], provider_session_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "spawn_id": receipt["spawn_id"],
        "provider_session_id": provider_session_id,
        "launch_revision": receipt["launch_revision"],
        "role": receipt["role"]["name"],
        "worktree": receipt["workspace"]["worktree"],
        "starting_head": receipt["workspace"]["starting_head"],
        "ready": True,
        "blocker": "",
    }


def _launch_revision(receipt: Mapping[str, Any]) -> str:
    return _receipt_launch_revision(receipt)


PERSISTENT_RECEIPT_ROLES = frozenset({"meta-operator", "orchestrator"})


def revalidate_launch_receipt(receipt: Mapping[str, Any]) -> None:
    """launch-entrypoint-revalidation: every persistent-session bootstrap
    entrypoint revalidates its receipt against its manifest shape and launch
    revision immediately after receipt readback and before the provider runner
    is invoked, and again before marking the receipt ready or bootstrap-verified.
    launch-receipt-manifest-shapes / launch-receipt-persistent: the only durable
    receipt shape left is the generic persistent one, role meta-operator or
    orchestrator, carrying no pass purpose and none of the retired shaping or
    reconcile tables, so a stale, malformed, role-substituted, or
    purpose-injected persistent receipt starts no provider."""
    manifest_type = str(receipt.get("manifest_type") or "")
    # TUR-447 F4a: the octo-launch worker-pass launcher is retired, so the
    # durable "octo-lite-pass" receipt shape it wrote is no longer an admitted
    # manifest_type (decision-109-workflow-native, launch-receipt-manifest-shapes).
    # Only the generic persistent receipt (empty manifest_type) remains admitted,
    # preserving the persistent-session bootstrap (Unit K).
    if manifest_type != "":
        raise GateError(f"unknown launch receipt manifest type: {manifest_type}")
    role = receipt.get("role")
    name = role.get("name") if isinstance(role, Mapping) else None
    if name not in PERSISTENT_RECEIPT_ROLES:
        raise GateError("persistent receipt requires role meta-operator or orchestrator")
    if "purpose" in receipt or "pass" in receipt:
        raise GateError("persistent receipt carries no pass purpose")
    if "shaping" in receipt:
        raise GateError("persistent receipt carries no retired shaping table")
    if "reconcile" in receipt:
        raise GateError("persistent receipt carries no retired reconcile table")
    if receipt.get("launch_revision") != _launch_revision(receipt):
        raise GateError("launch receipt revision mismatch")


@dataclass(frozen=True)
class PreparedLaunch:
    receipt_path: Path
    bootstrap_argv: list[str]
    mutation_argv: list[str]
    contract_text: str

    def expected_ack(self, provider_session_id: str) -> dict[str, Any]:
        with self.receipt_path.open("rb") as handle:
            return _expected_ack(tomllib.load(handle), provider_session_id)

    def mutation_argv_for(self, provider_session_id: str) -> list[str]:
        return [provider_session_id if item == "{provider_session_id}" else item for item in self.mutation_argv]


def prepared_from_receipt(receipt: Mapping[str, Any], receipt_path: Path, contract_text: str) -> PreparedLaunch:
    bootstrap, mutation = _provider_argv(receipt)
    return PreparedLaunch(receipt_path.resolve(), bootstrap, mutation, contract_text)


def _assert_reconcile_admission(role: str, purpose: str, read_restricted: bool) -> None:
    """Same admission semantics as the workflow gates (launch-purpose-reconcile,
    launch-receipt-manifest-shapes): a reconcile purpose admits only role
    reconciler spawned as a Read-restricted subagent; every other role, purpose,
    or access shape is rejected before any spawn."""
    if purpose != "reconcile":
        raise GateError(f"purpose {purpose} not admitted for the reconcile gateway")
    if role != "reconciler":
        raise GateError(f"role {role} not admitted for reconcile purpose")
    if read_restricted is not True:
        raise GateError("reconcile admits reconciler only as a Read-restricted subagent")


def _reconcile_journal_revision(journal: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in journal.items()
        if key not in {"ready", "launch_revision", "bootstrap", "result"}
    }
    return exact_fingerprint(payload)


def _write_reconcile_journal(journal_path: Path, journal: Mapping[str, Any]) -> None:
    _atomic_write(journal_path, json.dumps(journal, sort_keys=True, indent=1) + "\n")


def load_reconcile_journal(journal_path: Path) -> dict[str, Any]:
    """Read and validate the reconcile journal entry (decision-109-binding,
    launch-receipt-manifest-shapes): a plain JSON file binding role reconciler,
    purpose reconcile with Read-restricted access, the final persisted snapshot
    path plus digest, the expected control HEAD, spec and ADR blobs, and streams.
    The retired octo-lite-reconcile receipt shape is rejected if presented."""
    journal_path = Path(journal_path)
    try:
        text = journal_path.read_text()
    except OSError as error:
        raise GateError("reconcile journal missing") from error
    try:
        journal = json.loads(text)
    except json.JSONDecodeError:
        try:
            legacy = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise GateError("reconcile journal unreadable") from error
        if legacy.get("manifest_type") == "octo-lite-reconcile" or "reconcile" in legacy:
            raise GateError("retired reconcile receipt shape rejected")
        raise GateError("reconcile journal unreadable")
    if not isinstance(journal, dict):
        raise GateError("reconcile journal unreadable")
    if journal.get("manifest_type") == "octo-lite-reconcile":
        raise GateError("retired reconcile receipt shape rejected")
    if journal.get("manifest_shape") != "worker-journal":
        raise GateError("reconcile journal shape invalid")
    _assert_reconcile_admission(
        str(journal.get("role", {}).get("name") or ""),
        str(journal.get("purpose") or ""),
        journal.get("read_restricted"),
    )
    reconcile = journal.get("reconcile")
    if not isinstance(reconcile, dict) or any(
        not reconcile.get(name) for name in ("snapshot_path", "snapshot_digest", "control_head")
    ) or any(
        not isinstance(reconcile.get(name), list)
        for name in ("spec_blobs", "adr_blobs", "streams")
    ):
        raise GateError("reconcile journal bindings incomplete")
    if journal.get("launch_revision") != _reconcile_journal_revision(journal):
        raise GateError("reconcile journal revision mismatch")
    return journal


def _reconcile_expected_ack(journal: Mapping[str, Any], provider_session_id: str) -> dict[str, Any]:
    """role-reconciler-snapshot-receipt-binding: the reconciler's acknowledgment
    echo carries the journal-bound snapshot path and digest, verified against the
    journal entry before any judgment call."""
    expected = _expected_ack(journal, provider_session_id)
    expected["snapshot_path"] = journal["reconcile"]["snapshot_path"]
    expected["snapshot_digest"] = journal["reconcile"]["snapshot_digest"]
    return expected


@dataclass(frozen=True)
class PreparedReconcile:
    journal_path: Path
    bootstrap_argv: list[str]
    mutation_argv: list[str]
    contract_text: str

    def expected_ack(self, provider_session_id: str) -> dict[str, Any]:
        return _reconcile_expected_ack(load_reconcile_journal(self.journal_path), provider_session_id)

    def mutation_argv_for(self, provider_session_id: str) -> list[str]:
        return [provider_session_id if item == "{provider_session_id}" else item for item in self.mutation_argv]


def prepare_reconcile_launch(
    *,
    root: Path,
    spawn_id: str,
    parent: str,
    reply_route: str,
    repo: Path,
    worktree_root: Path,
    worktree: Path,
    journal_path: Path,
    execution_location: str,
    operator_loopback: bool,
    review_delivery: str,
    expected_head: str,
    snapshot_path: Path,
    snapshot_digest: str,
    streams: list[Mapping[str, Any]],
    spec_blobs: list[str],
    adr_blobs: list[str],
    conversation_state_refs: list[str] | None = None,
    minimum_free_bytes: int = 1,
    resource_conflicts: list[str] | None = None,
    provider_overloaded: bool = False,
    read_linear: ReadLinear = read_linear,
    read_pr: ReadPullRequest = read_pull_request,
) -> PreparedReconcile:
    """The sole reconciler launch gateway: same worktree provisioning, containment,
    and gateway checks as prepare_launch, narrowed to the reconciler's aggregate
    multi-stream read-only shape, binding through a journal entry instead of a
    TOML receipt (role-worker-migration, decision-109-workflow-native,
    launch-receipt-manifest-shapes). Every declared stream's Linear and PR facts
    are refetched and compared to the caller's declared bindings before any
    worktree or provider call, so a stale or substituted snapshot input fails
    closed. The current repo HEAD is also compared to the caller's expected_head
    before any of that validation, so a target commit landing between snapshot
    capture and gateway dispatch fails closed even when every declared blob is
    still unchanged."""
    root = root.resolve()
    repo = repo.resolve()
    worktree_root = worktree_root.resolve()
    worktree = worktree.resolve()
    journal_path = journal_path.resolve()
    snapshot_bytes = _verify_snapshot_source(snapshot_path, str(snapshot_digest), worktree_root.parent)
    normalize_launch_access(
        {
            "execution_location": execution_location,
            "operator_loopback_access": operator_loopback,
            "review_delivery": review_delivery,
        }
    )
    if execution_location not in {"local", "remote"}:
        raise GateError("execution_location must be local or remote")
    registry = load_registry(root)
    resolved = resolve_role(registry, "reconciler", set())
    if Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise GateError("repo must be control git root")
    control_head = _git(repo, "rev-parse", "HEAD")
    if control_head != expected_head:
        raise GateError(f"target HEAD changed: expected {expected_head}, found {control_head}")

    verified_streams: list[dict[str, Any]] = []
    for stream in streams:
        name = str(stream["stream"])
        linear_decl = stream.get("linear")
        pr_decl = stream.get("pull_request")
        fresh = fetch_stream_binding(
            linear_issue=str(linear_decl["identifier"]) if linear_decl else None,
            pr_repo=str(pr_decl["repo"]) if pr_decl else None,
            pr_number=int(pr_decl["number"]) if pr_decl else None,
            read_linear=read_linear,
            read_pr=read_pr,
        )
        if linear_decl and fresh.get("linear") != dict(linear_decl):
            raise GateError(f"stale Linear input: {name}")
        if pr_decl and fresh.get("pull_request") != dict(pr_decl):
            raise GateError(f"stale PR input: {name}")
        entry = {"stream": name}
        entry.update(fresh)
        verified_streams.append(entry)

    _verify_blobs(repo, control_head, spec_blobs, "spec")
    _verify_blobs(repo, control_head, adr_blobs, "ADR")

    _prepare_worktree(
        repo,
        worktree_root,
        worktree,
        control_head,
        "",
        read_only=True,
        minimum_free_bytes=minimum_free_bytes,
        conflicts=list(resource_conflicts or []),
        provider_overloaded=provider_overloaded,
    )
    try:
        child_workspace = _child_workspace_check(repo, worktree_root, worktree, control_head, None)

        base = build_launch_receipt(
            root,
            resolved,
            spawn_id=spawn_id,
            parent=parent,
            reply_route=reply_route,
            repo=repo,
            worktree=worktree,
            execution_location=execution_location,
            operator_loopback=operator_loopback,
            review_delivery=review_delivery,
        )
        read_restricted = resolved.role.subagent_access == "read-restricted"
        _assert_reconcile_admission(resolved.role.name, "reconcile", read_restricted)
        workspace = dict(base["workspace"])
        workspace["child_containment_verified"] = child_workspace["contained"]
        persisted_snapshot_path = journal_path.parent / "snapshot.md"
        try:
            _atomic_write(persisted_snapshot_path, snapshot_bytes.decode("utf-8"))
            # The durable binding artifact is the journal entry, never a reconcile
            # receipt.toml (launch-receipt-manifest-shapes, decision-109-binding).
            # It binds the final persisted snapshot path and digest
            # (role-reconciler-snapshot-receipt-binding), the expected control
            # HEAD, the canonical spec and ADR blobs, and the verified streams.
            journal = {
                "schema_version": 1,
                "manifest_shape": "worker-journal",
                "purpose": "reconcile",
                "read_restricted": read_restricted,
                "spawn_id": base["spawn_id"],
                "parent": base["parent"],
                "reply_route": base["reply_route"],
                "role": base["role"],
                "runtime": base["runtime"],
                "skills": base["skills"],
                "workspace": workspace,
                "reconcile": {
                    "snapshot_path": str(persisted_snapshot_path),
                    "snapshot_digest": str(snapshot_digest),
                    "control_head": control_head,
                    "spec_blobs": list(spec_blobs),
                    "adr_blobs": list(adr_blobs),
                    "conversation_state_refs": list(conversation_state_refs or []),
                    "streams": verified_streams,
                },
                "bootstrap": {"verified": False, "provider_session_id": ""},
            }
            journal["launch_revision"] = _reconcile_journal_revision(journal)
            _write_reconcile_journal(journal_path, journal)
            bootstrap, mutation = _provider_argv(journal)
        except BaseException:
            # A caught failure anywhere after the final snapshot is written, most
            # notably a journal persistence failure, must not leave the final
            # snapshot, journal, or sweep directory behind; rmdir only removes the
            # directory this call itself populated, since it no-ops on leftover
            # unrelated content instead of masking that state.
            persisted_snapshot_path.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)
            try:
                journal_path.parent.rmdir()
            except OSError:
                pass
            raise
    except BaseException:
        # workspace-cleanup-clean-abort: this reconcile pass failed after
        # provisioning its worktree but before any acknowledgment echo could be
        # verified, so remove the worktree only while pristine at the exact
        # control head; a dirty or diverged worktree stays for inspection.
        # gateway_provisioned: THIS call created the worktree just above via
        # _prepare_worktree at a required-absent path (provision-record-guard).
        cleanup_clean_abort(repo, worktree, control_head, gateway_provisioned=True)
        raise
    return PreparedReconcile(journal_path, bootstrap, mutation, resolved.contract_text)


def verify_bootstrap(receipt_path: Path, acknowledgment: Mapping[str, Any]) -> dict[str, Any]:
    with receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    # Pre-mutation boundary: revalidate again before any ready or
    # bootstrap-verified mutation (launch-entrypoint-revalidation).
    revalidate_launch_receipt(receipt)
    provider_session_id = acknowledgment.get("provider_session_id")
    if not isinstance(provider_session_id, str) or not provider_session_id:
        raise GateError("bootstrap acknowledgment mismatch: provider_session_id")
    expected = _expected_ack(receipt, provider_session_id)
    mismatches = [name for name, value in expected.items() if acknowledgment.get(name) != value]
    if mismatches:
        raise GateError(f"bootstrap acknowledgment mismatch: {', '.join(mismatches)}")
    receipt["ready"] = True
    receipt["bootstrap"]["verified"] = True
    receipt["bootstrap"]["provider_session_id"] = provider_session_id
    _atomic_write(receipt_path, render_receipt(receipt))
    return dict(acknowledgment)


def bootstrap_prompt(prepared: PreparedLaunch) -> str:
    receipt = prepared.receipt_path
    return (
        f"{prepared.contract_text.rstrip()}\n\n"
        f"Bootstrap only. Read {receipt}. Check every bound source and workspace fact. "
        "Do not mutate. Return BOOTSTRAP_ACK as JSON with schema_version, spawn_id, "
        "launch_revision, role, worktree, starting_head, ready true, and empty blocker. "
        "Include provider_session_id when visible."
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.DOTALL)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        value = None
        for index, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                value = candidate
        if value is None:
            raise GateError("provider output is not JSON")
    if not isinstance(value, dict):
        raise GateError("provider output is not an object")
    return value


def _json_object(text: str) -> dict[str, Any]:
    value = _extract_json_object(text)
    nested = value.get("BOOTSTRAP_ACK")
    return nested if isinstance(nested, dict) else value


def parse_provider_message(provider: str, output: str) -> tuple[str, str]:
    """Return (provider_session_id, raw message text) for one print-mode provider call."""
    if provider == "anthropic":
        try:
            event = json.loads(output)
        except json.JSONDecodeError as error:
            raise GateError("Anthropic output unreadable") from error
        session = event.get("session_id")
        result = event.get("result")
        if not isinstance(session, str) or not isinstance(result, str):
            raise GateError("Anthropic session identity missing")
        return session, result
    if provider == "openai":
        session = ""
        message = ""
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise GateError("OpenAI output unreadable") from error
            if event.get("type") == "thread.started":
                session = str(event.get("thread_id") or "")
            item = event.get("item")
            if event.get("type") == "item.completed" and isinstance(item, dict):
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    message = item["text"]
        if not session or not message:
            raise GateError("OpenAI session identity missing")
        return session, message
    raise GateError("unsupported provider")


def parse_bootstrap_output(provider: str, output: str) -> tuple[str, dict[str, Any]]:
    session, message = parse_provider_message(provider, output)
    return session, _json_object(message)


def parse_pass_output(provider: str, output: str) -> tuple[str, dict[str, Any]]:
    session, message = parse_provider_message(provider, output)
    return session, _extract_json_object(message)


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"))


def _read_codex_rollout_record(session_id: str, codex_home: Path | None = None) -> dict[str, str]:
    """Read the exact effective provider, model, effort, and final assistant message
    Codex itself recorded for this session, from its own rollout file under
    CODEX_HOME/sessions, never from the model's or relay's self-report
    (decision-identity-source, role-openai-fail-closed)."""
    home = Path(codex_home) if codex_home is not None else _codex_home()
    sessions_dir = home / "sessions"
    matches = sorted(sessions_dir.rglob(f"rollout-*-{session_id}.jsonl")) if sessions_dir.is_dir() else []
    if not matches:
        raise GateError(f"codex effective identity unprovable: no rollout session file for {session_id}")
    provider = ""
    model = ""
    effort = ""
    final_message = ""
    for line in matches[-1].read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if event.get("type") == "session_meta":
            provider = str(payload.get("model_provider") or provider)
        elif event.get("type") == "turn_context":
            model = str(payload.get("model") or model)
            effort = str(payload.get("effort") or effort)
        elif event.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
            texts = [
                item["text"]
                for item in payload.get("content") or []
                if isinstance(item, dict) and item.get("type") == "output_text" and isinstance(item.get("text"), str)
            ]
            if texts:
                final_message = "".join(texts)
        elif event.get("type") == "event_msg" and payload.get("type") == "agent_message" and isinstance(payload.get("message"), str):
            final_message = payload["message"]
    if not provider or not model or not effort:
        raise GateError(f"codex effective identity unprovable: rollout session file incomplete for {session_id}")
    return {"provider": provider, "model": model, "effort": effort, "final_message": final_message}


def _read_codex_rollout_identity(session_id: str) -> dict[str, str]:
    """Read the exact effective provider, model, and effort Codex itself recorded
    for this session, from its own rollout file, never from the model's self-report."""
    record = _read_codex_rollout_record(session_id)
    return {"provider": record["provider"], "model": record["model"], "effort": record["effort"]}


def verify_relay_verbatim(
    claimed_session_id: str,
    claimed_payload: str,
    claimed_sha256: str,
    expected_model: str,
    expected_effort: str,
    codex_home: Path | None = None,
) -> dict[str, str]:
    """Independent relay-verbatim proof (role-openai-relay, role-openai-fail-closed).

    Resolves the relay-claimed session id to codex's OWN rollout record under
    CODEX_HOME/sessions (decision-identity-source), proves effective provider,
    model, and effort from that record, extracts the final assistant message
    from the record itself, and rejects any mismatch with the relay-returned
    payload. Relay-supplied artifacts are never consulted; an absent rollout
    record fails closed. Returns the proven record."""
    record = _read_codex_rollout_record(claimed_session_id, codex_home)
    if record["provider"] != "openai":
        raise GateError(f"relay verbatim rejected: provider substitution: {record['provider']}")
    mismatches = [
        name
        for name, expected in (("model", expected_model), ("effort", expected_effort))
        if record[name] != expected
    ]
    if mismatches:
        raise GateError(f"relay verbatim rejected: effective identity mismatch: {', '.join(mismatches)}")
    final_message = record["final_message"]
    if not final_message:
        raise GateError(f"relay verbatim rejected: no final assistant message in rollout record for {claimed_session_id}")
    record_sha256 = hashlib.sha256(final_message.encode()).hexdigest()
    if record_sha256 != claimed_sha256 or record_sha256 != hashlib.sha256(claimed_payload.encode()).hexdigest():
        raise GateError("relay verbatim rejected: payload mismatch with rollout record")
    return record


def verify_codex_effective_identity(receipt: Mapping[str, Any], session_id: str) -> None:
    runtime = receipt["runtime"]
    actual = _read_codex_rollout_identity(session_id)
    expected = {"provider": runtime["provider"], "model": runtime["model"], "effort": runtime["effort"]}
    mismatches = [key for key in expected if actual[key] != expected[key]]
    if mismatches:
        raise GateError(f"codex effective identity mismatch: {', '.join(mismatches)}")


def _reverify_argv(prepared: PreparedLaunch, provider: str, recorded_session: str) -> list[str]:
    """launch-bootstrap-reverify-idempotent (TUR-447 d2): resume the exact
    recorded provider session for a re-verify pass instead of creating a fresh
    session the provider refuses as a duplicate. Anthropic keeps the bootstrap
    call's restricted safe-tool surface and swaps the fresh --session-id create
    for --resume of the recorded session; OpenAI uses the standard resume argv
    bound to the recorded thread."""
    if provider == "anthropic":
        argv = list(prepared.bootstrap_argv)
        index = argv.index("--session-id")
        argv[index] = "--resume"
        argv[index + 1] = recorded_session
        return argv
    return prepared.mutation_argv_for(recorded_session)


def run_bootstrap(
    prepared: PreparedLaunch,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Run the read-only bootstrap phase and verify BOOTSTRAP_ACK. Returns the verified provider session ID.

    launch-bootstrap-reverify-idempotent (TUR-447 d2): a receipt already marked
    bootstrap-verified with a recorded provider session is accepted idempotently
    on the re-verify path. It re-confirms the SAME recorded session by resume,
    under the full receipt revalidation and the same acknowledgment-fact checks,
    instead of being forced through a fresh --session-id create the provider
    refuses as a duplicate session; nothing about revalidation or the ack and
    session re-checks is weakened.

    TUR-447 cycle-2 P1-1a: a receipt claiming bootstrap verified=true with a
    MISSING or BLANK provider_session_id is INCONSISTENT (the partially-written
    shape a crashed prior run leaves behind). It is rejected fail-closed BEFORE
    any provider invocation, never misclassified as FRESH into a fresh-session
    attempt the provider refuses as a duplicate, and its previously-verified
    worktree is never touched."""
    with prepared.receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    # Pre-provider boundary: revalidate manifest shape and launch revision
    # immediately after receipt readback, before any provider process starts
    # (launch-entrypoint-revalidation).
    revalidate_launch_receipt(receipt)
    worktree = receipt["workspace"]["worktree"]
    provider = receipt["runtime"]["provider"]
    bootstrap_state = receipt.get("bootstrap") or {}
    recorded_session = str(bootstrap_state.get("provider_session_id") or "").strip()
    prior_verified = bootstrap_state.get("verified") is True
    if prior_verified and not recorded_session:
        raise GateError(
            "inconsistent bootstrap state: verified without provider_session_id"
        )
    reverify = prior_verified
    argv = _reverify_argv(prepared, provider, recorded_session) if reverify else prepared.bootstrap_argv
    try:
        bootstrap = runner(
            argv,
            cwd=worktree,
            input=bootstrap_prompt(prepared),
            capture_output=True,
            text=True,
            check=False,
        )
        if bootstrap.returncode != 0:
            raise GateError(f"bootstrap provider failed: {bootstrap.stderr.strip()}")
        session, acknowledgment = parse_bootstrap_output(provider, bootstrap.stdout)
        if reverify and session != recorded_session:
            raise GateError("bootstrap re-verify session mismatch")
        claimed_session = acknowledgment.get("provider_session_id")
        if claimed_session not in {None, "", session}:
            raise GateError("bootstrap acknowledgment mismatch: provider_session_id")
        acknowledgment["provider_session_id"] = session
        if provider == "openai":
            verify_codex_effective_identity(receipt, session)
        _verify_review_worktree_unmutated(receipt, "bootstrap")
        verify_bootstrap(prepared.receipt_path, acknowledgment)
    except BaseException:
        # workspace-cleanup-clean-abort: everything above runs before the
        # acknowledgment echo is verified, so a fresh-bootstrap failure removes
        # the worktree only when it is still pristine at the exact starting head
        # AND host-provision ownership is proven (provision-record-guard); a
        # foreign or hand-created worktree is preserved. Any failure on a
        # receipt claiming PRIOR VERIFICATION (verified=true, TUR-447 cycle-2
        # P1-1b) happens against a previously-verified workspace, so it never
        # removes the session's worktree at all; the worktree is preserved for
        # inspection (launch-bootstrap-reverify-idempotent).
        if not prior_verified:
            cleanup_clean_abort(
                Path(receipt["workspace"]["repo"]),
                Path(worktree),
                str(receipt["workspace"]["starting_head"]),
            )
        raise
    return session


def bootstrap_from_receipt(
    receipt_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Bootstrap-verify an already-prepared receipt, reading its role contract from the working tree
    and checking it still matches the exact blob the receipt was built from (no prior commit required)."""
    with receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    # Pre-provider boundary: revalidate immediately after receipt readback so
    # an invalid persistent receipt never reaches the contract-blob subprocess
    # or the provider runner (launch-entrypoint-revalidation).
    revalidate_launch_receipt(receipt)
    role_root = Path(receipt["role"]["root"])
    contract_path = role_root / receipt["role"]["contract_path"]
    actual_blob = _run("git", "hash-object", "--no-filters", str(contract_path), cwd=role_root)
    if actual_blob != receipt["role"]["contract_blob"]:
        raise GateError("role contract blob mismatch")
    contract_text = contract_path.read_text()
    prepared = prepared_from_receipt(receipt, receipt_path, contract_text)
    return run_bootstrap(prepared, runner=runner)


def run_mutation(
    prepared: PreparedLaunch,
    session: str,
    prompt: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    """Sole entry point for any mutation call against an already bootstrap-verified
    session. Fails closed unless the response's own session ID exactly matches the
    resumed session, so a spoofed or mismatched identity can never be accepted."""
    with prepared.receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    worktree = receipt["workspace"]["worktree"]
    mutation = runner(
        prepared.mutation_argv_for(session),
        cwd=worktree,
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
    )
    if mutation.returncode != 0:
        raise GateError(f"provider pass failed with exit {mutation.returncode}")
    mutation_session, message = parse_provider_message(receipt["runtime"]["provider"], mutation.stdout)
    if mutation_session != session:
        raise GateError("provider pass session mismatch")
    _verify_review_worktree_unmutated(receipt, "resumed pass")
    return mutation_session, message


def _cleanup_reconcile_worktree(journal_path: Path) -> None:
    """workspace-cleanup-reconcile: remove a completed, read-only reconcile
    worktree only after its result is bound and the journal entry is durably
    persisted, proven by re-reading the journal from disk; a missing,
    retired-shape, or unbound journal fails closed and preserves the worktree.
    Same pristine-only removal law as cleanup_clean_abort: a worktree that is
    not a genuine detached worktree of the exact bound control repo, has moved
    off its starting HEAD, or is dirty is preserved for inspection instead of
    being force-removed."""
    journal = load_reconcile_journal(journal_path)
    if journal.get("result", {}).get("bound") is not True:
        raise GateError("reconcile cleanup requires a journal-bound result")
    workspace = journal["workspace"]
    # gateway_provisioned: the reconcile gateway itself created this worktree at
    # a required-absent path and bound it into the durable journal entry
    # (provision-record-guard).
    cleanup_clean_abort(
        Path(workspace["repo"]),
        Path(workspace["worktree"]),
        str(workspace["starting_head"]),
        gateway_provisioned=True,
    )


def _reconcile_bootstrap_prompt(prepared: PreparedReconcile) -> str:
    return (
        f"{prepared.contract_text.rstrip()}\n\n"
        f"Bootstrap only. Read the reconcile journal entry {prepared.journal_path}. "
        "Check every journal-bound source and workspace fact, including the bound "
        "snapshot_path bytes against snapshot_digest. Do not mutate. Return "
        "BOOTSTRAP_ACK as JSON with schema_version, spawn_id, launch_revision, role, "
        "worktree, starting_head, snapshot_path, snapshot_digest, ready true, and "
        "empty blocker. Include provider_session_id when visible."
    )


def run_reconcile_launch(
    prepared: PreparedReconcile,
    prompt: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Sole entry point a reconcile caller uses: bootstrap-verify the journal-bound
    Read-restricted reconciler, verify its acknowledgment echo of the journal-bound
    snapshot path and digest before any judgment, run one read-only judgment pass
    with the exact resumed session, bind the result into the durably persisted
    journal entry, then clean up keyed on that entry. No caller composes the
    bootstrap and mutation phases directly."""
    journal = load_reconcile_journal(prepared.journal_path)
    worktree = journal["workspace"]["worktree"]
    provider = journal["runtime"]["provider"]
    try:
        bootstrap = runner(
            prepared.bootstrap_argv,
            cwd=worktree,
            input=_reconcile_bootstrap_prompt(prepared),
            capture_output=True,
            text=True,
            check=False,
        )
        if bootstrap.returncode != 0:
            raise GateError(f"bootstrap provider failed: {bootstrap.stderr.strip()}")
        session, acknowledgment = parse_bootstrap_output(provider, bootstrap.stdout)
        claimed_session = acknowledgment.get("provider_session_id")
        if claimed_session not in {None, "", session}:
            raise GateError("bootstrap acknowledgment mismatch: provider_session_id")
        acknowledgment["provider_session_id"] = session
        expected = _reconcile_expected_ack(journal, session)
        mismatches = [name for name, value in expected.items() if acknowledgment.get(name) != value]
        if mismatches:
            raise GateError(f"bootstrap acknowledgment mismatch: {', '.join(mismatches)}")
        _verify_review_worktree_unmutated(journal, "bootstrap")
        journal["bootstrap"] = {"verified": True, "provider_session_id": session}
        _write_reconcile_journal(prepared.journal_path, journal)
    except BaseException:
        # workspace-cleanup-clean-abort: everything above runs before the
        # acknowledgment echo is verified, so a failure here removes the
        # worktree only when it is still pristine at the exact starting head
        # and preserves a dirty or diverged one for inspection.
        # gateway_provisioned: the reconcile gateway created this journal-bound
        # worktree at a required-absent path (provision-record-guard).
        cleanup_clean_abort(
            Path(journal["workspace"]["repo"]),
            Path(worktree),
            str(journal["workspace"]["starting_head"]),
            gateway_provisioned=True,
        )
        raise
    mutation = runner(
        prepared.mutation_argv_for(session),
        cwd=worktree,
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
    )
    if mutation.returncode != 0:
        raise GateError(f"provider pass failed with exit {mutation.returncode}")
    mutation_session, message = parse_provider_message(provider, mutation.stdout)
    if mutation_session != session:
        raise GateError("provider pass session mismatch")
    _verify_review_worktree_unmutated(journal, "resumed pass")
    # Bind the result into the durably persisted journal entry; a journal that
    # vanished or was substituted since bootstrap fails closed here, preserving
    # the worktree for inspection.
    bound = load_reconcile_journal(prepared.journal_path)
    if bound.get("bootstrap", {}).get("verified") is not True:
        raise GateError("reconcile journal bootstrap not verified")
    bound["result"] = {"bound": True, "binding": exact_fingerprint({"message": message})}
    _write_reconcile_journal(prepared.journal_path, bound)
    _cleanup_reconcile_worktree(prepared.journal_path)
    return message


# TUR-447 F4b-A Unit I: the reconciler-as-Workflow-subagent entry point
# (role-worker-migration, role-claude-native, decision-109-workflow-native). The
# reconciler migrates to a Read-restricted Claude Workflow subagent that the owning
# session spawns through the loop's agent() mechanism, not the provider-argv subprocess
# path (prepare_reconcile_launch / run_reconcile_launch, which the live 2-minute systemd
# sweep still drives). This entry point is ADDITIVE: those provider-argv functions stay
# alive, importable, and behavior-unchanged; sweep-operator-gate migrates operator-sweep
# to this path in a separate step.
#
# The durable binding artifact remains the reconcile journal entry, never a reconcile
# receipt.toml (launch-receipt-manifest-shapes, decision-109-binding). This entry point
# reuses the exact validated journal binding that prepare_reconcile_launch produces, so it
# inherits every prior behavior proof verbatim: snapshot integrity (a missing, substituted,
# corrupt, or digest-mismatched snapshot fails before any journal or worktree,
# role-reconciler-snapshot-integrity), PR-fact fingerprinting (normalized PR head, base,
# state, review, and status-check rollup bind into the journal streams,
# role-reconciler-pr-facts), the HEAD race check, and the canonical spec/ADR sweep. It
# writes NO reconcile TOML receipt, and its reconcile worktree cleanup keys on the durable
# journal entry (workspace-cleanup-reconcile). The retired octo-lite-reconcile receipt
# shape is rejected wherever presented (via load_reconcile_journal).
@dataclass(frozen=True)
class PreparedReconcileWorkflow:
    """The Workflow-native reconciler binding for a loop agent() spawn. It carries the
    durable journal path and the resolved contract text; it carries NO provider argv,
    because the loop's agent() mechanism spawns the Read-restricted subagent, not a
    subprocess relay."""

    journal_path: Path
    contract_text: str

    def expected_ack(self, provider_session_id: str) -> dict[str, Any]:
        return _reconcile_expected_ack(load_reconcile_journal(self.journal_path), provider_session_id)


def bind_reconcile_workflow_journal(**kwargs: Any) -> PreparedReconcileWorkflow:
    """Bind the reconcile journal entry BEFORE the Workflow subagent spawns, keyed to the
    final persisted snapshot.md with matching bytes and digest
    (role-reconciler-snapshot-receipt-binding). Same aggregate multi-stream validation and
    journal shape as the provider-argv gateway, reused verbatim so every behavior proof
    holds, but returned as the Workflow-native prepared shape for a loop agent() spawn. No
    reconcile TOML receipt is written; the retired octo-lite-reconcile receipt shape is
    rejected. Accepts the same keyword inputs as prepare_reconcile_launch."""
    prepared = prepare_reconcile_launch(**kwargs)
    return PreparedReconcileWorkflow(prepared.journal_path, prepared.contract_text)


def verify_reconcile_workflow_ack(journal_path: Path, acknowledgment: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the Read-restricted reconciler subagent's read-only acknowledgment echo
    against the durable journal binding before any judgment is bound
    (role-reconciler-bootstrap-snapshot-proof, launch-gates-workflow-layer). The echo must
    carry the journal-bound snapshot path and digest; the subagent opened the exact
    journal-bound snapshot file, hashed its bytes, and echoes the actual digest, so a
    missing or digest-mismatched snapshot fails closed here. The retired octo-lite-reconcile
    receipt shape is rejected on readback. Marks the journal bootstrap verified so the
    downstream result binding proves the same journal survived unchanged."""
    journal = load_reconcile_journal(journal_path)
    # A native Claude Workflow subagent has no provider session id; its identity echo is
    # the journalled spawn_id, exactly as every delivery-worker ack echoes bound inputs
    # rather than a provider session (decision-109-binding). A caller that does echo a
    # provider_session_id must echo the journalled spawn_id.
    claimed = acknowledgment.get("provider_session_id")
    session = journal["spawn_id"]
    if isinstance(claimed, str) and claimed and claimed != session:
        raise GateError("reconcile ack mismatch: provider_session_id")
    echo = dict(acknowledgment)
    echo["provider_session_id"] = session
    expected = _reconcile_expected_ack(journal, session)
    mismatches = [name for name, value in expected.items() if echo.get(name) != value]
    if mismatches:
        raise GateError(f"reconcile ack mismatch: {', '.join(mismatches)}")
    journal["bootstrap"] = {"verified": True, "provider_session_id": session}
    _write_reconcile_journal(journal_path, journal)
    return echo


# role-reconciler-authority, role-reconciler-escalation: the exhaustive set of
# classifications the reconciler may bind. Anything else is not a valid deterministic
# verdict and never binds. needs_fable is the sole escalation label.
RECONCILE_CLASSIFICATIONS = (
    "changed",
    "missing",
    "stale",
    "contradictory",
    "unchanged",
    "needs_fable",
)


def bind_reconcile_workflow_result(journal_path: Path, classification: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the reconciler subagent's read-only classification into the durably persisted
    journal entry, then clean up keyed on that entry (workspace-cleanup-reconcile). The
    reconciler classifies deltas as changed, missing, stale, contradictory, or unchanged and
    never mutates a source (role-reconciler-input, role-reconciler-authority); missing,
    unparseable, or semantically ambiguous input escalates with needs_fable so Fable judges
    the case (role-reconciler-escalation).

    TUR-447 cycle1 pass3 reconcile binding (role-reconciler-snapshot-receipt-binding,
    role-reconciler-snapshot-integrity): the classification is BOUND to the verified,
    journal-bound snapshot proof, never accepted blind. It must carry the reconciler's
    re-echoed acknowledgment, which is re-verified against the durable journal binding here
    (so a missing, discarded, or digest-mismatched ack fails closed and the ack is never
    dropped); its classification must be an exhaustive-enum member; the snapshot digest it
    reports must equal the journal-bound digest; and its needs_fable flag must be consistent
    with the classification. A journal that vanished or was substituted since bootstrap, or
    that presents the retired receipt shape, fails closed and preserves the worktree."""
    bound = load_reconcile_journal(journal_path)
    if bound.get("bootstrap", {}).get("verified") is not True:
        raise GateError("reconcile journal bootstrap not verified")
    # The reconciler's re-echoed ack is ENFORCED, not discarded: re-verify it against the
    # durable journal binding. A missing ack, or one whose journal-bound snapshot path/digest
    # or bound identity disagrees, raises here before anything binds.
    acknowledgment = classification.get("ack")
    if not isinstance(acknowledgment, Mapping) or not acknowledgment:
        raise GateError("reconcile result ack missing")
    verified_echo = verify_reconcile_workflow_ack(journal_path, acknowledgment)
    # The classification's own reported snapshot digest must equal the journal-bound digest,
    # so a classification produced against a different (or no) snapshot never binds.
    journal_digest = str(bound["reconcile"]["snapshot_digest"])
    if str(classification.get("snapshot_digest")) != journal_digest:
        raise GateError("reconcile result snapshot_digest mismatch")
    if str(verified_echo.get("snapshot_digest")) != journal_digest:
        raise GateError("reconcile result ack snapshot_digest mismatch")
    needs_fable = bool(classification.get("needs_fable"))
    label = str(classification.get("classification") or "")
    if label not in RECONCILE_CLASSIFICATIONS:
        raise GateError(f"reconcile classification not a valid verdict: {label or '(empty)'}")
    # needs_fable is the escalation label and only that label: the flag and the classification
    # agree or the verdict is inconsistent.
    if (label == "needs_fable") != needs_fable:
        raise GateError("reconcile needs_fable flag inconsistent with classification")
    deltas = list(classification.get("deltas") or [])
    result = {
        "bound": True,
        "classification": label,
        "needs_fable": needs_fable,
        "deltas": deltas,
        "binding": exact_fingerprint({"classification": label, "needs_fable": needs_fable, "deltas": deltas}),
    }
    bound["result"] = result
    _write_reconcile_journal(journal_path, bound)
    _cleanup_reconcile_worktree(journal_path)
    return result
