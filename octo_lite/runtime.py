from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Callable, Mapping


class GateError(RuntimeError):
    pass


FAILURE_CATEGORIES = (
    "input or contract",
    "environment",
    "provider or session",
    "implementation or validation",
    "external dependency",
)

TRACE_KINDS = {
    "bootstrap",
    "pass_completion",
    "verdict",
    "retry",
    "transition",
    "control_message",
    "merge",
    "deployment",
}

TRACE_FORBIDDEN_KEYS = {
    "prompt",
    "raw_prompt",
    "response",
    "raw_response",
    "log",
    "transcript",
    "secret",
    "evidence_body",
    "product_data",
}

TRACE_ATTRIBUTE_KEYS = {
    "role",
    "issue",
    "pr",
    "head",
    "cycle",
    "category",
    "attempt",
    "model",
    "provider",
    "gate",
    "from_state",
    "to_state",
    "message_id",
    "result",
    "owner",
    "execution_location",
    "worktree",
    "duration_ms",
}


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def _render_full_receipt(receipt: Mapping[str, object]) -> str:
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


def _toml_document(values: Mapping[str, object]) -> str:
    return "".join(f"{key} = {_toml_value(value)}\n" for key, value in values.items())


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


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def normalize_launch_access(values: Mapping[str, object]) -> dict:
    loopback = values.get("operator_loopback_access") is True
    normalized = {
        "execution_location": str(values.get("execution_location") or "unknown"),
        "operator_loopback_access": loopback,
        "review_delivery": str(
            values.get("review_delivery")
            or ("loopback_allowed" if loopback else "reachable_url_required")
        ),
    }
    if not loopback and normalized["review_delivery"] == "loopback_allowed":
        raise GateError("loopback delivery requires explicit operator access")
    return normalized


def exact_fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def launch_revision(receipt: Mapping[str, object]) -> str:
    payload = {key: value for key, value in receipt.items() if key not in {"ready", "launch_revision", "bootstrap"}}
    return exact_fingerprint(payload)


def initialize_stream(
    path: Path,
    *,
    stream_id: str,
    parent_session: str,
    child_session: str,
    child_role: str,
    caller: str,
    brief: str,
    issue: str | None = None,
) -> dict:
    if caller != parent_session:
        raise GateError("only parent may create stream brief")
    if not all(value.strip() for value in (stream_id, parent_session, child_session, child_role, brief)):
        raise GateError("stream identity, role, and brief required")
    if path.exists():
        raise GateError("stream already exists")
    path.mkdir(parents=True)
    state = {
        "schema_version": 1,
        "stream_id": stream_id,
        "parent_session": parent_session,
        "child_session": child_session,
        "child_role": child_role,
        "brief_revision": 1,
        "status_revision": 0,
    }
    # gh#28 leg1 (delivery-lifecycle linear-transition-issue-binding,
    # operator-control stream-issue-binding): the host-owned registry entry
    # records the exact delivered issue alongside its owner, distinct from a
    # descriptive stream name, so the verified transition binds authority to this
    # registry-recorded issue rather than requiring stream_id == issue. This is
    # the SOLE registry writer (operator-control stream-registry-sole); no second
    # writer stamps this field. Sourced from the already launch-bound issue.
    if issue is not None:
        if not issue.strip():
            raise GateError("stream issue binding must be a nonempty identifier")
        state["issue"] = issue
    _atomic_write(path / "brief.md", brief)
    _atomic_write(path / "stream.toml", _toml_document(state))
    return state


def update_stream_brief(path: Path, *, caller: str, expected_revision: int, brief: str) -> dict:
    if not brief.strip():
        raise GateError("brief required")
    manifest = path / "stream.toml"
    lock_path = path / "stream.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read_toml(manifest)
        if state.get("parent_session") != caller:
            raise GateError("only parent may update stream brief")
        if state.get("brief_revision") != expected_revision:
            raise GateError("brief revision mismatch")
        state["brief_revision"] = expected_revision + 1
        _atomic_write(path / "brief.md", brief)
        _atomic_write(manifest, _toml_document(state))
        return state


def write_stream_status(
    path: Path,
    *,
    caller: str,
    expected_revision: int,
    outcome: str,
    gate: str,
    blocker: str,
    next_operator_action: str,
) -> dict:
    values = (outcome, gate, blocker, next_operator_action)
    if not all(value.strip() for value in values):
        raise GateError("complete compact status required")
    manifest = path / "stream.toml"
    lock_path = path / "stream.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read_toml(manifest)
        if state.get("child_session") != caller:
            raise GateError("only child may update stream status")
        if state.get("status_revision") != expected_revision:
            raise GateError("status revision mismatch")
        state["status_revision"] = expected_revision + 1
        status = (
            f"Outcome: {outcome}\n"
            f"Gate: {gate}\n"
            f"Blocker: {blocker}\n"
            f"Next operator action: {next_operator_action}\n"
        )
        _atomic_write(path / "status.md", status)
        _atomic_write(manifest, _toml_document(state))
        return state


def verdict_body(
    review_type: str,
    verdict: str,
    head: str,
    bound_inputs: list[str],
    findings: list[str],
    receipt: str,
    conversation_log_references: list[str] | None = None,
    conversation_cutoff: str = "",
) -> str:
    # GH-65 item 3a: qa is a first-class published verdict type. It mirrors code's
    # per-type invariants: only the shaping verdict carries conversation-log
    # references and a cutoff; code and qa carry neither.
    if review_type not in {"shaping", "code", "qa"}:
        raise GateError("invalid review type")
    if verdict not in {"clear", "blocking"}:
        raise GateError("invalid verdict")
    if not head or not receipt:
        raise GateError("head and receipt required")
    references = list(conversation_log_references or [])
    if review_type == "shaping":
        if not references:
            raise GateError("shaping verdict requires conversation log references")
        if not conversation_cutoff:
            raise GateError("shaping verdict requires a conversation cutoff")
    else:
        if references:
            raise GateError(f"{review_type} verdict does not carry conversation log references")
        if conversation_cutoff:
            raise GateError(f"{review_type} verdict does not carry a conversation cutoff")
    values = {
        "schema_version": 1,
        "review_type": review_type,
        "verdict": verdict,
        "head": head,
        "bound_inputs": bound_inputs,
        "findings": findings,
        "reviewer_receipt": receipt,
        "conversation_log_references": references,
        "conversation_cutoff": conversation_cutoff,
    }
    lines = []
    for key, value in values.items():
        if isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = _toml_value(value)
        lines.append(f"{key} = {rendered}")
    return (
        f"<!-- octo-lite-verdict:{review_type} -->\n"
        "```toml\n"
        + "\n".join(lines)
        + "\n```"
    )


def declare_successor_ready(
    path: Path,
    *,
    caller: str,
    session_id: str,
    handoff_revision: int,
    handoff: Path | str,
) -> dict:
    """The dedicated Fable successor's own readiness record.

    Readiness is meaningless without the brief it reconciled, so the record
    BINDS the exact handoff artifact bytes the successor read (operator-control
    handoff-reconcile, activation-handoff-brief). The atomic transfer admits
    only a readiness record carrying that binding, so a readiness file no
    verified activation wrote transfers nothing.

    Codex-thread routing is NOT declarable here: a Codex successor becomes ready
    only by explicitly activating, the sole path that read-verifies the
    workspace and reconciles durable context (operator-control
    activation-handoff-brief, activation-workspace, activation-no-new-auth).
    """
    if caller != session_id:
        raise GateError("only the successor may declare its own readiness")
    state = _readiness_state(session_id, handoff_revision, handoff)
    _atomic_write(path, _toml_document(state))
    return state


def _readiness_state(session_id: str, handoff_revision: int, handoff: Path | str) -> dict:
    if handoff_revision < 1:
        raise GateError("handoff revision must be positive")
    artifact = Path(handoff)
    if not artifact.is_file():
        raise GateError("successor readiness requires the handoff artifact it reconciled")
    return {
        "schema_version": 1,
        "session_id": session_id,
        "handoff_revision": handoff_revision,
        "handoff_artifact": str(artifact.resolve()),
        "handoff_digest": exact_fingerprint(artifact.read_text()),
    }


def _declare_codex_successor_ready(
    path: Path,
    *,
    thread_id: str,
    handoff_revision: int,
    handoff: Path | str,
    workspace: str,
    context: Mapping[str, str],
) -> dict:
    """The Codex successor readiness activation itself writes.

    It carries the activation's own proof: the verified workspace and the exact
    digest-bound durable context this activation reconciled. The atomic transfer
    admits a Codex successor only with that proof, so a record minted without
    activating commits no ownership (operator-control activation-workspace,
    activation-authoritative-context, activation-no-new-auth).
    """
    if not workspace.strip():
        raise GateError("codex successor readiness requires one verified herdr workspace")
    state = _readiness_state(thread_id, handoff_revision, handoff)
    state["owner_mode"] = CODEX_OWNER_MODE
    state["herdr_workspace"] = workspace.strip()
    state["context_sources"] = list(CODEX_CONTEXT_SOURCES)
    state["context_references"] = [context[source] for source in CODEX_CONTEXT_SOURCES]
    _atomic_write(path, _toml_document(state))
    return state


CODEX_OWNER_MODE = "codex-thread"

# The dedicated persistent Fable owner record carries no owner mode; the closed
# set of owner modes octo-lite recognizes is exactly these two.
FABLE_OWNER_MODE = ""
KNOWN_OWNER_MODES = (FABLE_OWNER_MODE, CODEX_OWNER_MODE)

# The canonical live Herdr agent_status values (operator-control
# message-eligibility-gate). A resident session reports one of these; stopped,
# unknown, absent, and every unrecognized value are not a live session.
LIVE_AGENT_STATUSES = ("working", "idle", "blocked", "done")

# The authoritative durable operating context an activated or takeover-committed
# Codex owner re-reads before its first owner mutation (operator-control
# activation-authoritative-context). Prose and raw conversation are never in it.
CODEX_CONTEXT_SOURCES = (
    "owner_record",
    "control_records",
    "transfer_artifact",
    "source_tracked_work",
    "linear_issue_state",
    "github_pull_request_state",
    "canonical_specs_and_adrs",
    "child_stream_status",
    "workspace_and_runtime_configuration",
)

# The complete existing meta-operator capability set (operator-control
# activation-complete-capability). Initial activation and either lawful transfer
# bind the same set; takeover creates no reduced Codex-only runtime.
CODEX_META_OPERATOR_CAPABILITIES = (
    "herdr_messaging_and_acknowledgment",
    "issue_and_epic_orchestration",
    "resolver_bound_role_spawning",
    "stream_and_owner_controls",
    "lifecycle_helpers",
    "durable_source_reconciliation",
    "human_gated_acceptance",
    "human_gated_preproduction",
    "human_gated_traffic_shift",
)


def _swap_owner(
    path: Path,
    *,
    expected_owner_session_id: str,
    expected_owner_route: str,
    expected_prior_revision: int,
    new_owner_session_id: str,
    new_owner_route: str,
    handoff_revision: int,
    control_dir: str,
    new_owner_mode: str | None = None,
    new_workspace: str = "",
    extra: Mapping[str, object] | None = None,
) -> dict:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _read_toml(path)
        if current.get("owner_session_id") != expected_owner_session_id:
            raise GateError("owner identity mismatch")
        if current.get("owner_route") != expected_owner_route:
            raise GateError("owner route mismatch")
        if current.get("control_dir") != control_dir:
            raise GateError("control directory mismatch")
        if int(current.get("handoff_revision", -1)) != expected_prior_revision:
            raise GateError("handoff revision mismatch")
        if handoff_revision <= expected_prior_revision:
            raise GateError("handoff revision must increase")
        updated = {
            "schema_version": 1,
            "owner_session_id": new_owner_session_id,
            "owner_route": new_owner_route,
        }
        # Mode-specific routing belongs to the SUCCESSOR, never to the record it
        # replaces (operator-control handoff-owner, handoff-routing): a dedicated
        # Fable successor keeps its routable Herdr owner route and inherits no
        # Codex mode or workspace, while a declared Codex successor must reuse the
        # exact verified workspace (ADR 0005 decision-workspace-routing).
        if new_owner_mode == CODEX_OWNER_MODE:
            prior_workspace = str(current.get("herdr_workspace") or "")
            workspace = new_workspace.strip() or prior_workspace
            if not workspace:
                raise GateError("codex successor requires one verified herdr workspace")
            if prior_workspace and workspace != prior_workspace:
                raise GateError("codex owner workspace is immutable across transfer")
            updated["owner_mode"] = CODEX_OWNER_MODE
            updated["herdr_workspace"] = workspace
        elif new_owner_mode:
            raise GateError(f"unknown successor owner mode: {new_owner_mode}")
        updated["handoff_revision"] = handoff_revision
        updated["control_dir"] = control_dir
        updated.update(extra or {})
        _atomic_write(path, _toml_document(updated))
        return updated


def transfer_owner(
    path: Path,
    expected_owner_session_id: str,
    expected_owner_route: str,
    expected_prior_revision: int,
    new_owner_session_id: str,
    new_owner_route: str,
    handoff_revision: int,
    control_dir: str,
    *,
    caller: str,
    handoff: Path,
    successor_readiness_path: Path,
    new_owner_mode: str | None = None,
    new_workspace: str = "",
) -> dict:
    if caller != expected_owner_session_id:
        raise GateError("caller is not current expected owner")
    # The derived immutable handoff artifact is the transfer's provenance root:
    # it is checked FIRST, and the readiness record is then admitted only if it
    # binds those exact artifact bytes (operator-control handoff-artifact,
    # handoff-reconcile). A readiness file no verified activation wrote carries
    # no binding and transfers nothing.
    if not _is_owner_handoff(handoff, control_dir, handoff_revision):
        raise GateError("immutable handoff revision missing")
    readiness = _read_toml(successor_readiness_path)
    if readiness.get("session_id") != new_owner_session_id or readiness.get("handoff_revision") != handoff_revision:
        raise GateError("successor readiness receipt mismatch")
    if str(readiness.get("handoff_artifact") or "") != str(handoff.resolve()) or str(
        readiness.get("handoff_digest") or ""
    ) != exact_fingerprint(handoff.read_text()):
        raise GateError("successor readiness is not bound to this handoff artifact")
    # The successor's own readiness record carries its verified routing, so the
    # workspace committed here is the one the successor read, never a
    # substitute supplied at transfer time (operator-control
    # activation-workspace, ADR 0005 decision-workspace-routing).
    declared_mode = str(readiness.get("owner_mode") or "")
    if declared_mode != (new_owner_mode or ""):
        raise GateError("successor readiness owner mode mismatch")
    if declared_mode == CODEX_OWNER_MODE:
        if str(readiness.get("herdr_workspace") or "") != new_workspace.strip():
            raise GateError("successor readiness workspace mismatch")
        # A Codex successor is admitted only with its activation's own proof:
        # the complete durable context that activation reconciled, each entry
        # binding exact bytes. A readiness record minted without activating
        # carries none, so it transfers nothing (operator-control
        # activation-handoff-brief, activation-authoritative-context).
        references = readiness.get("context_references")
        if list(readiness.get("context_sources") or []) != list(CODEX_CONTEXT_SOURCES) or not isinstance(
            references, list
        ) or len(references) != len(CODEX_CONTEXT_SOURCES) or not all(
            _is_digest_reference(str(reference).strip()) for reference in references
        ):
            raise GateError("codex successor readiness is not activation-reconciled")
    return _swap_owner(
        path,
        expected_owner_session_id=expected_owner_session_id,
        expected_owner_route=expected_owner_route,
        expected_prior_revision=expected_prior_revision,
        new_owner_session_id=new_owner_session_id,
        new_owner_route=new_owner_route,
        handoff_revision=handoff_revision,
        control_dir=control_dir,
        new_owner_mode=new_owner_mode,
        new_workspace=new_workspace,
    )


def _is_owner_handoff(handoff: Path, control_dir: str, revision: int) -> bool:
    """The one immutable handoff artifact a revision can have:
    <control_dir>/handoffs/<zero-padded-revision>.md (operator-control
    handoff-artifact).

    The location is DERIVED from the owner record in force, never accepted from
    the caller, so a file that merely carries the revision name somewhere else
    is not the outgoing owner's artifact and creates neither readiness nor a
    transfer. There is no fallback: with no recorded control directory, or with
    the artifact anywhere but that directory's own handoffs tree, the answer is
    no.
    """
    control = control_dir.strip()
    if not control:
        return False
    if not handoff.is_file() or handoff.name != f"{revision:04d}.md":
        return False
    return handoff.resolve().parent == (Path(control) / "handoffs").resolve()


def _is_digest_reference(value: str) -> bool:
    identity, separator, digest = value.rpartition("#")
    return bool(identity) and bool(separator) and len(digest) == 64 and all(
        character in "0123456789abcdef" for character in digest
    )


def _reconciled_context(reconcile: Callable[[Mapping[str, object]], Mapping[str, str]], owner: Mapping[str, object]) -> dict:
    """One live read of every authoritative durable source, bound to exact
    digests (operator-control activation-authoritative-context,
    activation-same-thread-resume; role-runtime launch-codex-activation-complete).

    Reporting a static source list is not reconciliation: authority is reported
    only with the exact references this pass actually read.
    """
    captured = dict(reconcile(owner) or {})
    missing = [
        source for source in CODEX_CONTEXT_SOURCES
        if not _is_digest_reference(str(captured.get(source) or "").strip())
    ]
    if missing:
        raise GateError(f"durable context reconciliation incomplete: {', '.join(missing)}")
    return {source: str(captured[source]).strip() for source in CODEX_CONTEXT_SOURCES}


def _codex_result(outcome: str, owner: Mapping[str, object], context: Mapping[str, str]) -> dict:
    return {
        "outcome": outcome,
        "owner": dict(owner),
        "context_sources": list(CODEX_CONTEXT_SOURCES),
        "context_references": [context[source] for source in CODEX_CONTEXT_SOURCES],
        "capabilities": list(CODEX_META_OPERATOR_CAPABILITIES),
    }


def activate_codex_thread(
    path: Path,
    *,
    thread_id: str,
    workspace: str,
    control_dir: str,
    reconcile: Callable[[Mapping[str, object]], Mapping[str, str]],
    handoff: str = "",
) -> dict:
    """Bind meta-operator authority to the exact current Codex app thread
    (operator-control codex-thread-activation).

    Creates the existing owner record only when absent, treats the same thread as
    an idempotent resume with no write at all, reports the pending successor path
    when the exact next-revision handoff artifact exists, and refuses every other
    case without touching the existing record. A handoff brief is context only:
    it never substitutes for the lawful owner transition.
    """
    if not thread_id.strip():
        raise GateError("codex thread activation requires the exact host thread identity")
    if not workspace.strip():
        raise GateError("codex thread activation requires one verified herdr workspace")
    if not control_dir.strip():
        raise GateError("codex thread activation requires a control directory")

    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _read_toml(path)
        if current:
            if current.get("owner_mode") != CODEX_OWNER_MODE or current.get("owner_session_id") != thread_id:
                # A dedicated Fable owner, or any other session, keeps sole
                # authority. The exact next-revision immutable handoff artifact
                # opens only the successor-reconciliation and readiness path
                # (operator-control activation-different-owner); a brief that is
                # not that artifact grants nothing, and neither writes anything.
                revision = int(current.get("handoff_revision", 0)) + 1
                artifact = Path(handoff.strip()) if handoff.strip() else None
                if artifact and _is_owner_handoff(artifact, str(current.get("control_dir") or ""), revision):
                    # The successor reconciles the brief against live sources and
                    # then records its own readiness, binding the exact thread,
                    # revision, mode, and verified workspace the later atomic
                    # transfer must match (operator-control
                    # activation-handoff-brief, activation-workspace).
                    context = _reconciled_context(reconcile, current)
                    candidate = Path(control_dir)
                    candidate.mkdir(parents=True, exist_ok=True)
                    readiness_path = candidate / "successor-ready.toml"
                    _declare_codex_successor_ready(
                        readiness_path,
                        thread_id=thread_id,
                        handoff_revision=revision,
                        handoff=artifact,
                        workspace=workspace,
                        context=context,
                    )
                    pending = _codex_result("pending", current, context)
                    pending["handoff_revision"] = revision
                    pending["successor_session_id"] = thread_id
                    pending["successor_readiness"] = str(readiness_path)
                    return pending
                raise GateError(
                    "another session owns operator authority; use the existing handoff, "
                    "manual takeover, or a direct human forced takeover"
                )
            if current.get("herdr_workspace") != workspace:
                raise GateError("codex owner workspace is immutable across resume")
            # Reopening revalidates durable state before any owner mutation
            # (role-runtime launch-codex-activation-revalidate): an owner record
            # whose recorded control directory no longer reads back is stale, so
            # the session stays ordinary instead of resuming authority.
            if not Path(str(current.get("control_dir") or "")).is_dir():
                raise GateError("codex owner control directory unreadable; session stays ordinary")
            return _codex_result("resumed", current, _reconciled_context(reconcile, current))

        # Reconciliation runs BEFORE the owner record exists, so no live reader
        # can ever observe an authority record this pass has not earned, and a
        # failed activation leaves no owner record and no control state at all
        # (operator-control activation-failure-ordinary; role-runtime
        # launch-codex-activation-failure). The record reconciled is the exact
        # pending record committed a moment later: the control directory is
        # materialized first because the live control tree is one authoritative
        # source, and a directory this pass created is removed again on any
        # failure.
        control = Path(control_dir)
        created = not control.exists()
        owner = {
            "schema_version": 1,
            "owner_session_id": thread_id,
            "owner_route": thread_id,
            "owner_mode": CODEX_OWNER_MODE,
            "herdr_workspace": workspace,
            "handoff_revision": 0,
            "control_dir": control_dir,
        }
        try:
            control.mkdir(parents=True, exist_ok=True)
            if not control.is_dir():
                raise GateError("codex control directory readback mismatch")
            context = _reconciled_context(reconcile, owner)
            _atomic_write(path, _toml_document(owner))
            readback = _read_toml(path)
            if readback != owner:
                raise GateError("codex owner readback mismatch")
        except BaseException:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            if created:
                shutil.rmtree(control, ignore_errors=True)
            raise
        return _codex_result("activated", readback, context)


def force_takeover_codex_thread(
    path: Path,
    *,
    thread_id: str,
    workspace: str,
    reason: str,
    context: Mapping[str, str],
    verify_active_fable: Callable[[Mapping[str, object]], Mapping[str, object]],
    retire_fable: Callable[[Mapping[str, object]], Mapping[str, object]],
    now: Callable[[], str],
    reconcile: Callable[[Mapping[str, object]], Mapping[str, str]],
) -> dict:
    """One direct-human forced takeover from a verified active dedicated Fable
    owner into the exact current Codex thread (operator-control
    codex-forced-takeover).

    Ordered phases: candidate validation, context capture, Fable retirement,
    immutable receipt, atomic owner commit. Any unproven phase leaves the Codex
    thread ordinary and the prior owner record byte-identical.
    """
    if not thread_id.strip():
        raise GateError("forced takeover requires the exact host thread identity")
    if not workspace.strip():
        raise GateError("forced takeover requires one verified herdr workspace")
    if not reason.strip():
        raise GateError("forced takeover requires a direct human instruction with a nonempty reason")

    # Phase 1: candidate validation. Only a structured, verified ACTIVE dedicated
    # Fable owner is eligible; another Codex owner and a missing, dead, stopped,
    # unreadable, or ambiguous owner keep the existing handoff or manual law.
    prior = _read_toml(path)
    if not prior:
        raise GateError("forced takeover requires an existing dedicated Fable owner record")
    # Admission is a CLOSED set: the dedicated Fable owner record carries no
    # owner mode at all. Another Codex owner is ineligible, and an unrecognized
    # mode is not a dedicated Fable either, so it fails closed instead of being
    # read as one (operator-control takeover-live-fable-only).
    prior_mode = str(prior.get("owner_mode") or "").strip()
    if prior_mode not in KNOWN_OWNER_MODES:
        raise GateError(f"forced takeover admits only a known owner mode: {prior_mode}")
    if prior_mode == CODEX_OWNER_MODE:
        raise GateError("forced takeover admits only a dedicated Fable owner")
    for key in ("owner_session_id", "owner_route", "control_dir"):
        if not str(prior.get(key) or "").strip():
            raise GateError("forced takeover requires an unambiguous prior owner record")
    liveness = dict(verify_active_fable(prior))
    if liveness.get("session_running") is not True:
        raise GateError("forced takeover admits only a verified active Fable session")

    # Phase 2: context capture. Every authoritative durable source must be
    # referenced before fencing, and every reference must bind the exact bytes it
    # names as <identity>#<sha256> (operator-control takeover-context-capture).
    # A bare path, a prose summary, and an absent or unreadable placeholder are
    # all unproven, so they refuse instead of standing in for read evidence.
    missing = [
        source for source in CODEX_CONTEXT_SOURCES
        if not _is_digest_reference(str(context.get(source) or "").strip())
    ]
    if missing:
        raise GateError(f"forced takeover context incomplete: {', '.join(missing)}")
    captured = {source: str(context[source]).strip() for source in CODEX_CONTEXT_SOURCES}
    context_digest = exact_fingerprint(captured)

    # Live reconciliation runs BEFORE any fence, receipt, or owner commit: an
    # unreadable live source leaves the Fable owner byte-identical, its session
    # untouched, and this thread ordinary (operator-control
    # activation-failure-ordinary, takeover-failure).
    _reconciled_context(reconcile, prior)

    # Phase 3: fencing. The exact Fable session and its heartbeat timer are
    # retired and verified before any owner write.
    fence = dict(retire_fable(prior))
    if fence.get("session_running") is not False or fence.get("timer_present") is not False:
        raise GateError("forced takeover requires verified Fable session and timer retirement")

    # Phase 4: immutable receipt, written before the sole authority commit so a
    # later transfer failure surfaces as a blocked existing owner.
    prior_revision = int(prior.get("handoff_revision", 0))
    revision = prior_revision + 1
    control = Path(str(prior["control_dir"]))
    receipt_path = control / "takeovers" / f"{revision:04d}.toml"
    if receipt_path.exists():
        raise GateError(f"takeover receipt already exists: {receipt_path}")
    receipt = {
        "schema_version": 1,
        "prior_owner_session_id": str(prior["owner_session_id"]),
        "prior_owner_route": str(prior["owner_route"]),
        "new_owner_session_id": thread_id,
        "new_owner_mode": CODEX_OWNER_MODE,
        "herdr_workspace": workspace,
        "reason": reason.strip(),
        "requested_at": now(),
        "context_digest": context_digest,
        "context_sources": list(CODEX_CONTEXT_SOURCES),
        "context_references": [captured[source] for source in CODEX_CONTEXT_SOURCES],
        "fence_session_running": False,
        "fence_timer_present": False,
        "verification_outcome": "verified",
    }
    _atomic_write(receipt_path, _toml_document(receipt))
    receipt_digest = exact_fingerprint(receipt_path.read_text())

    # Phase 5: the sole authority commit. One locked exact compare of the prior
    # Fable identity, route, control directory, and revision, then one atomic
    # rename naming the exact Codex thread and its receipt.
    owner = _swap_owner(
        path,
        expected_owner_session_id=str(prior["owner_session_id"]),
        expected_owner_route=str(prior["owner_route"]),
        expected_prior_revision=prior_revision,
        new_owner_session_id=thread_id,
        new_owner_route=thread_id,
        handoff_revision=revision,
        control_dir=str(prior["control_dir"]),
        new_owner_mode=CODEX_OWNER_MODE,
        new_workspace=workspace,
        extra={
            "takeover_receipt": str(receipt_path),
            "takeover_receipt_digest": receipt_digest,
        },
    )

    # Phase 6: continue. The committed record is read back from disk and the
    # complete durable context is reconciled again before the new owner may act
    # (operator-control takeover-success).
    committed = _read_toml(path)
    if committed != owner:
        raise GateError("codex owner readback mismatch after takeover commit")
    return _codex_result("takeover", committed, _reconciled_context(reconcile, committed))


def transition_linear(
    issue: str,
    expected_state: str,
    target_state: str,
    progress_path: Path,
    read: Callable[[], Mapping[str, object]],
    mutate: Callable[[str], None],
    update_status: Callable[[Mapping[str, object]], None],
    notify_parent: Callable[[Mapping[str, object]], None],
) -> dict:
    lock_path = progress_path.with_suffix(progress_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        progress = _read_toml(progress_path)
        if progress:
            bound = (progress.get("issue"), progress.get("expected_state"), progress.get("target_state"))
            if bound != (issue, expected_state, target_state):
                raise GateError("transition progress belongs to another operation")
        else:
            progress = {
                "schema_version": 1,
                "issue": issue,
                "expected_state": expected_state,
                "target_state": target_state,
                "mutation_done": False,
                "status_done": False,
                "notify_done": False,
            }

        current = dict(read())
        if current.get("identifier") != issue:
            raise GateError("Linear identity mismatch")

        if not progress["mutation_done"]:
            state = current.get("state")
            if state == expected_state:
                mutate(target_state)
                current = dict(read())
            elif state != target_state:
                raise GateError(f"expected {expected_state}, found {state}")
            if current.get("state") != target_state:
                raise GateError("Linear readback mismatch")
            progress["mutation_done"] = True
            progress["issue_fingerprint"] = exact_fingerprint(current)
            _atomic_write(progress_path, _toml_document(progress))
        elif current.get("state") != target_state:
            raise GateError("completed mutation no longer matches target state")

        if not progress["status_done"]:
            update_status(current)
            progress["status_done"] = True
            _atomic_write(progress_path, _toml_document(progress))

        if not progress["notify_done"]:
            notify_parent(current)
            progress["notify_done"] = True
            _atomic_write(progress_path, _toml_document(progress))

        return progress


def bind_pass_result(receipt_path: Path, role: str, result: Mapping[str, object]) -> str:
    receipt = _read_toml(receipt_path)
    if receipt.get("ready") is not True or receipt.get("bootstrap", {}).get("verified") is not True:
        raise GateError("receipt bootstrap not verified")
    if receipt.get("role", {}).get("name") != role:
        raise GateError("result role mismatch")
    payload = {key: value for key, value in result.items() if key != "result_binding"}
    binding = exact_fingerprint(payload)
    receipt["result"] = {"bound": True, "binding": binding}
    _atomic_write(receipt_path, _render_full_receipt(receipt))
    return binding


def record_acceptance(
    path: Path,
    owner_file: Path,
    *,
    caller: str,
    issue: str,
    pr: str,
    head: str,
    verdict_reference: str,
    decision: str,
) -> dict:
    owner = _read_toml(owner_file)
    if owner.get("owner_session_id") != caller:
        raise GateError("caller is not current operator owner")
    if decision not in {"accept", "reject"}:
        raise GateError("decision must be accept or reject")
    if not all(str(value).strip() for value in (issue, pr, head, verdict_reference)):
        raise GateError("issue, pr, head, and verdict reference required")
    record = {
        "schema_version": 1,
        "issue": issue,
        "pr": pr,
        "head": head,
        "verdict_reference": verdict_reference,
        "decision": decision,
        "decided_by": caller,
    }
    _atomic_write(path, _toml_document(record))
    return record


def record_failure(
    attempt: int,
    original_error: str,
    category: str,
    useful_work: str,
    owner: str,
    next_action: str,
) -> dict:
    if attempt < 1:
        raise GateError("attempt must be positive")
    if category not in FAILURE_CATEGORIES:
        raise GateError("invalid failure category")
    if not original_error.strip():
        raise GateError("original error required")
    return {
        "schema_version": 1,
        "attempt": attempt,
        "original_error": original_error,
        "category": category,
        "useful_work": useful_work,
        "owner": owner,
        "next_action": next_action,
    }


def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _validate_trace(event: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "session_id",
        "trace_id",
        "observation_id",
        "kind",
        "status",
        "time",
        "attributes",
        "artifacts",
    }
    missing = required - set(event)
    if missing:
        raise GateError(f"trace fields missing: {', '.join(sorted(missing))}")
    extra = set(event) - required
    if extra:
        raise GateError(f"trace fields unsupported: {', '.join(sorted(extra))}")
    if event.get("schema_version") != 1:
        raise GateError("unsupported trace schema")
    if event.get("kind") not in TRACE_KINDS:
        raise GateError("invalid trace kind")
    forbidden = TRACE_FORBIDDEN_KEYS.intersection(key.lower() for key in _walk_keys(event))
    if forbidden:
        raise GateError(f"forbidden trace content: {', '.join(sorted(forbidden))}")
    if not isinstance(event.get("attributes"), dict) or not isinstance(event.get("artifacts"), list):
        raise GateError("trace attributes and artifacts have wrong shape")
    unknown_attributes = set(event["attributes"]) - TRACE_ATTRIBUTE_KEYS
    if unknown_attributes:
        raise GateError(f"trace attributes unsupported: {', '.join(sorted(unknown_attributes))}")
    if any(not isinstance(value, (str, int, bool)) for value in event["attributes"].values()):
        raise GateError("trace attributes must be scalar")
    if any(not isinstance(value, str) or not value for value in event["artifacts"]):
        raise GateError("trace artifacts must be nonempty references")


def _trace_degraded(status_path: Path) -> None:
    try:
        existing = status_path.read_text() if status_path.exists() else ""
        warning = "trace degraded: append failed; workflow continues\n"
        if warning not in existing:
            _atomic_write(status_path, existing + warning)
    except OSError:
        pass


def append_trace(trace_path: Path, status_path: Path, event: Mapping[str, object]) -> bool:
    _validate_trace(event)
    lock_path = trace_path.with_suffix(trace_path.suffix + ".lock")
    try:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        return True
    except OSError:
        _trace_degraded(status_path)
        return False


def safe_cleanup(
    worktree: Path,
    *,
    worktree_root: Path,
    control_repo: Path,
    handoff: Path,
    expected_head: str,
    remote_ref: str,
    remote_head: Callable[[Path, str], str] | None = None,
    remove: Callable[[Path], None],
) -> None:
    if not handoff.is_file():
        raise GateError("durable handoff missing")
    target = worktree.resolve()
    allowed = worktree_root.resolve()
    if os.path.commonpath((allowed, target)) != str(allowed) or target == allowed:
        raise GateError("cleanup path escapes worktree root")
    top = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if Path(top).resolve() != target:
        raise GateError("cleanup path is not the worktree root")
    worktree_common_raw = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    control_common_raw = subprocess.run(
        ["git", "-C", str(control_repo), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    worktree_common = Path(worktree_common_raw)
    control_common = Path(control_common_raw)
    worktree_common = (target / worktree_common).resolve() if not worktree_common.is_absolute() else worktree_common.resolve()
    control_root = control_repo.resolve()
    control_common = (control_root / control_common).resolve() if not control_common.is_absolute() else control_common.resolve()
    if worktree_common != control_common:
        raise GateError("worktree belongs to another control repo")
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != expected_head:
        raise GateError("worktree HEAD mismatch")
    if not remote_ref.startswith("refs/heads/"):
        raise GateError("remote branch ref required")
    if remote_head is None:
        remote = subprocess.run(
            ["git", "-C", str(control_repo), "ls-remote", "--exit-code", "origin", remote_ref],
            capture_output=True,
            text=True,
        )
        pushed = remote.stdout.split(maxsplit=1)[0] if remote.returncode == 0 and remote.stdout.strip() else ""
    else:
        pushed = remote_head(control_repo, remote_ref)
    if pushed != head:
        raise GateError("remote push proof missing")
    result = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise GateError("dirty worktree requires inspection")
    remove(worktree)


def admit_workspace(
    worktree: Path,
    worktree_root: Path,
    *,
    disk_free_bytes: int,
    minimum_free_bytes: int,
    conflicts: list[str],
    provider_overloaded: bool,
) -> Path:
    root = worktree_root.resolve()
    target = worktree.resolve()
    if os.path.commonpath((root, target)) != str(root) or target == root:
        raise GateError("worktree escapes allowed root")
    if disk_free_bytes < minimum_free_bytes:
        raise GateError("insufficient disk for fresh worktree")
    if conflicts:
        raise GateError(f"resource conflict: {', '.join(conflicts)}")
    if provider_overloaded:
        raise GateError("provider overload active")
    return target


def herdr_label(
    *,
    kind: str,
    issue: int | None = None,
    pr: int | None = None,
    outcome: str | None = None,
    direct: bool = False,
) -> str:
    if kind == "operator":
        if any((issue, pr, outcome, direct)):
            raise GateError("operator label has no suffix")
        return "🧠 operator"
    if kind not in {"epic", "issue"}:
        raise GateError("only persistent operator and orchestrator tabs have labels")
    if issue is None or not outcome:
        raise GateError("orchestrator label needs issue and outcome")
    identity = f"{issue}/{pr}" if pr is not None else str(issue)
    epic = "◆" if kind == "epic" else ""
    mic = "🎤 " if direct else ""
    return f"{mic}{epic}{identity} · {outcome}"
