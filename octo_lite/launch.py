from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from octo_lite.runtime import (
    GateError,
    admit_workspace,
    bind_pass_result,
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
            "number,url,headRefOid,headRefName,baseRefName,comments",
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
        if envelope["linear_state"] not in {"Ideas", "Todo", "Shaped"}:
            raise GateError("Linear state invalid for shaping review")
        if envelope["shaping_head"] != envelope["starting_head"]:
            raise GateError("shaping review must start at current HEAD")
    else:
        if envelope["linear_state"] not in {"Shaped", "Todo"}:
            raise GateError("Linear state must be Shaped or Todo")
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


def _worktree_common_dir(path: Path) -> Path:
    value = _git(path, "rev-parse", "--git-common-dir")
    candidate = Path(value)
    return (path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


# Mutable implement/fix passes attach the exact bound PR branch. Review, QA review,
# and shaping review are inherently read-only (no Bash/Edit/Write tools) and may use
# a fresh detached worktree at the exact HEAD instead.
READ_ONLY_WORKTREE_ROLES = frozenset({"shaping-reviewer", "code-reviewer", "qa-reviewer"})


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
        mutation = [
            "codex", "exec", "resume", "--json", "-m", runtime["model"],
            *config, "{provider_session_id}", "-",
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


def prepare_launch(
    *,
    root: Path,
    envelope: Mapping[str, Any],
    role_name: str,
    capabilities: set[str],
    spawn_id: str,
    parent: str,
    reply_route: str,
    repo: Path,
    worktree_root: Path,
    worktree: Path,
    receipt_path: Path,
    execution_location: str,
    operator_loopback: bool,
    review_delivery: str,
    read_linear: ReadLinear = read_linear,
    read_pr: ReadPullRequest = read_pull_request,
) -> PreparedLaunch:
    root = root.resolve()
    repo = repo.resolve()
    worktree_root = worktree_root.resolve()
    worktree = worktree.resolve()
    _validate_envelope_shape(envelope)
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
    resolved = resolve_role(registry, role_name, capabilities)
    if Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise GateError("repo must be control git root")
    origin = _git(repo, "remote", "get-url", "origin")
    if _remote_repo_identity(origin).lower() != str(envelope["repo"]).lower():
        raise GateError("repo identity mismatch")

    linear = dict(read_linear(str(envelope["issue"])))
    state = linear.get("state")
    if isinstance(state, Mapping):
        linear["state"] = state.get("name")
    number = _pull_number(envelope["pr"])
    pull = dict(read_pr(str(envelope["repo"]), number))
    _verify_sources(repo, envelope, linear, pull)
    read_only = role_name in READ_ONLY_WORKTREE_ROLES
    branch = str(envelope["branch"])
    _prepare_worktree(
        repo,
        worktree_root,
        worktree,
        str(envelope["starting_head"]),
        branch,
        read_only=read_only,
        minimum_free_bytes=int(envelope["minimum_free_bytes"]),
        conflicts=list(envelope["resource_conflicts"]),
        provider_overloaded=bool(envelope["provider_overloaded"]),
    )
    child_workspace = _child_workspace_check(
        repo,
        worktree_root,
        worktree,
        str(envelope["starting_head"]),
        None if read_only else branch,
    )

    receipt = build_launch_receipt(
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
    receipt["ready"] = False
    receipt["manifest_type"] = "octo-lite-pass"
    receipt["purpose"] = str(envelope["purpose"])
    receipt["workspace"]["remote"] = origin
    receipt["workspace"]["child_containment_verified"] = child_workspace["contained"]
    receipt["issue"] = {
        "identifier": linear["identifier"],
        "revision": _issue_revision(linear),
        "fingerprint": exact_fingerprint(linear),
        "state": linear["state"],
    }
    receipt["spec"] = {
        "revision": str(envelope["spec_revision"]),
        "blobs": list(envelope["spec_blobs"]),
        "adr_blobs": list(envelope["adr_blobs"]),
        "conversation_cutoff": str(envelope["conversation_cutoff"]),
        "conversation_log_references": list(envelope["conversation_log_references"]),
    }
    receipt["pull_request"] = {
        "repo": str(envelope["repo"]),
        "number": number,
        "url": str(pull["url"]),
        "branch": str(pull["headRefName"]),
        "base": str(pull["baseRefName"]),
        "head": str(pull["headRefOid"]),
        "shaping_head": str(envelope["shaping_head"]),
    }
    receipt["topology"] = {"revision": int(envelope["topology_revision"])}
    receipt["resources"] = dict(envelope["resource_claims"])
    is_delivery = envelope["purpose"] == "delivery"
    receipt["prior_gates"] = {
        "shaping_verdict": "clear" if is_delivery else "none",
        "shaping_verdict_head": str(envelope["shaping_verdict_head"]) if is_delivery else "",
        "shaping_verdict_inputs": list(envelope["shaping_verdict_inputs"]) if is_delivery else [],
        "shaping_reviewer_receipt": str(envelope["shaping_reviewer_receipt"]) if is_delivery else "",
        "acceptance_criteria": list(envelope["acceptance_criteria"]),
    }
    receipt["bootstrap"] = {"verified": False, "provider_session_id": ""}
    receipt["pass"] = {
        "instruction": str(envelope["pass_instruction"]),
        "context_json": json.dumps(dict(envelope.get("pass_context") or {}), sort_keys=True, ensure_ascii=False),
    }
    receipt["launch_revision"] = _launch_revision(receipt)
    _atomic_write(receipt_path, render_receipt(receipt))
    bootstrap, mutation = _provider_argv(receipt)
    return PreparedLaunch(receipt_path.resolve(), bootstrap, mutation, resolved.contract_text)


def verify_bootstrap(receipt_path: Path, acknowledgment: Mapping[str, Any]) -> dict[str, Any]:
    with receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    if receipt.get("launch_revision") != _launch_revision(receipt):
        raise GateError("launch receipt revision mismatch")
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


def mutation_prompt(prepared: PreparedLaunch) -> str:
    with prepared.receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    if receipt.get("ready") is not True or receipt.get("bootstrap", {}).get("verified") is not True:
        raise GateError("verified BOOTSTRAP_ACK required before mutation")
    skills = ", ".join(receipt["skills"]["resolved"])
    pass_block = receipt.get("pass") or {}
    instruction = str(pass_block.get("instruction") or "")
    context = str(pass_block.get("context_json") or "{}")
    return (
        f"Bootstrap verified. Execute one {receipt['role']['name']} pass from {prepared.receipt_path}. "
        f"Load resolved skills: {skills}. Use pinned sources. {instruction} "
        f"Pass context: {context}. Return only the exact JSON result object. No prose, no code fences."
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


def _read_codex_rollout_identity(session_id: str) -> dict[str, str]:
    """Read the exact effective provider, model, and effort Codex itself recorded
    for this session, from its own rollout file, never from the model's self-report."""
    sessions_dir = _codex_home() / "sessions"
    matches = sorted(sessions_dir.rglob(f"rollout-*-{session_id}.jsonl")) if sessions_dir.is_dir() else []
    if not matches:
        raise GateError(f"codex effective identity unprovable: no rollout session file for {session_id}")
    provider = ""
    model = ""
    effort = ""
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
    if not provider or not model or not effort:
        raise GateError(f"codex effective identity unprovable: rollout session file incomplete for {session_id}")
    return {"provider": provider, "model": model, "effort": effort}


def verify_codex_effective_identity(receipt: Mapping[str, Any], session_id: str) -> None:
    runtime = receipt["runtime"]
    actual = _read_codex_rollout_identity(session_id)
    expected = {"provider": runtime["provider"], "model": runtime["model"], "effort": runtime["effort"]}
    mismatches = [key for key in expected if actual[key] != expected[key]]
    if mismatches:
        raise GateError(f"codex effective identity mismatch: {', '.join(mismatches)}")


def run_bootstrap(
    prepared: PreparedLaunch,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Run the read-only bootstrap phase and verify BOOTSTRAP_ACK. Returns the verified provider session ID."""
    with prepared.receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    worktree = receipt["workspace"]["worktree"]
    bootstrap = runner(
        prepared.bootstrap_argv,
        cwd=worktree,
        input=bootstrap_prompt(prepared),
        capture_output=True,
        text=True,
        check=False,
    )
    if bootstrap.returncode != 0:
        raise GateError(f"bootstrap provider failed: {bootstrap.stderr.strip()}")
    provider = receipt["runtime"]["provider"]
    session, acknowledgment = parse_bootstrap_output(provider, bootstrap.stdout)
    claimed_session = acknowledgment.get("provider_session_id")
    if claimed_session not in {None, "", session}:
        raise GateError("bootstrap acknowledgment mismatch: provider_session_id")
    acknowledgment["provider_session_id"] = session
    if provider == "openai":
        verify_codex_effective_identity(receipt, session)
    verify_bootstrap(prepared.receipt_path, acknowledgment)
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
    return mutation_session, message


def run_launch(
    prepared: PreparedLaunch,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    session = run_bootstrap(prepared, runner=runner)
    with prepared.receipt_path.open("rb") as handle:
        receipt = tomllib.load(handle)
    _, message = run_mutation(prepared, session, mutation_prompt(prepared), runner=runner)
    role = receipt["role"]["name"]
    result = _extract_json_object(message)
    result.pop("result_binding", None)
    binding = bind_pass_result(prepared.receipt_path, role, result)
    result["result_binding"] = binding
    result.setdefault("receipt", receipt["spawn_id"])
    result.setdefault("launch_revision", receipt["launch_revision"])
    return result
