from __future__ import annotations

import fcntl
import hashlib
import json
import os
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
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


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


def initialize_stream(
    path: Path,
    *,
    stream_id: str,
    parent_session: str,
    child_session: str,
    caller: str,
    brief: str,
) -> dict:
    if caller != parent_session:
        raise GateError("only parent may create stream brief")
    if not all(value.strip() for value in (stream_id, parent_session, child_session, brief)):
        raise GateError("stream identity and brief required")
    if path.exists():
        raise GateError("stream already exists")
    path.mkdir(parents=True)
    state = {
        "schema_version": 1,
        "stream_id": stream_id,
        "parent_session": parent_session,
        "child_session": child_session,
        "brief_revision": 1,
        "status_revision": 0,
    }
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
) -> str:
    if review_type not in {"shaping", "code"}:
        raise GateError("invalid review type")
    if verdict not in {"clear", "blocking"}:
        raise GateError("invalid verdict")
    if not head or not receipt:
        raise GateError("head and receipt required")
    values = {
        "schema_version": 1,
        "review_type": review_type,
        "verdict": verdict,
        "head": head,
        "bound_inputs": bound_inputs,
        "findings": findings,
        "reviewer_receipt": receipt,
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


def transfer_owner(
    path: Path,
    expected_owner: str,
    new_owner: str,
    handoff_revision: int,
    control_dir: str,
    *,
    caller: str,
    handoff: Path,
    successor_ready: bool,
) -> dict:
    if caller != expected_owner:
        raise GateError("caller is not current expected owner")
    if not successor_ready:
        raise GateError("successor readiness required")
    if not handoff.is_file() or handoff.name != f"{handoff_revision:04d}.md":
        raise GateError("immutable handoff revision missing")
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _read_toml(path)
        if current.get("owner_session") != expected_owner:
            raise GateError("owner mismatch")
        if current.get("control_dir") != control_dir:
            raise GateError("control directory mismatch")
        if handoff_revision <= int(current.get("handoff_revision", 0)):
            raise GateError("handoff revision must increase")
        updated = {
            "schema_version": 1,
            "owner_session": new_owner,
            "handoff_revision": handoff_revision,
            "control_dir": control_dir,
        }
        _atomic_write(path, _toml_document(updated))
        return updated


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
    handoff: Path,
    expected_head: str,
    remote_ref: str,
    remove: Callable[[Path], None],
) -> None:
    if not handoff.is_file():
        raise GateError("durable handoff missing")
    top = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if Path(top).resolve() != worktree.resolve():
        raise GateError("cleanup path is not the worktree root")
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != expected_head:
        raise GateError("worktree HEAD mismatch")
    remote = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--verify", remote_ref],
        capture_output=True,
        text=True,
    )
    if remote.returncode != 0 or remote.stdout.strip() != head:
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
