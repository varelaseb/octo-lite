#!/usr/bin/env python3
"""Resolve canonical octo-lite roles and generate lossless launch adapters."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from octo_lite.runtime import launch_revision as _launch_revision  # noqa: E402


UNICODE_DASHES = ("\u2013", "\u2014")
ROLE_FIELDS = {
    "contract",
    "provider",
    "model",
    "effort",
    "mode",
    "session",
    "execution",
    "service_tier",
    "tools",
    "required_skills",
    "conditional_skills",
}
OPTIONAL_ROLE_FIELDS = {"subagent_access", "provenance", "alt_runtimes"}
PERSISTENT_EXECUTION_ROLES = {"meta-operator", "orchestrator"}
SUBAGENT_ACCESS_VALUES = {"standard", "read-restricted"}
PROVENANCE_VALUES = {"relay-verbatim-rollout"}


class ConditionalSkill(NamedTuple):
    skill: str
    when: str


class Role(NamedTuple):
    name: str
    contract: str
    provider: str
    model: str
    effort: str
    mode: str
    session: str
    execution: str
    subagent_access: str | None
    provenance: str | None
    service_tier: str
    tools: tuple[str, ...]
    required_skills: tuple[str, ...]
    conditional_skills: tuple[ConditionalSkill, ...]
    alt_runtimes: tuple[tuple[str, str], ...] = ()


class Registry(NamedTuple):
    root: Path
    roles: dict[str, Role]
    concise: bool
    forbid_unicode_dashes: bool
    raw_adapter_spawn: bool
    mapping_revision: str


class ResolvedRole(NamedTuple):
    registry: Registry
    role: Role
    contract_text: str
    contract_blob: str
    skills: tuple[str, ...]
    capabilities: tuple[str, ...]


def _strings(value: Any, field: str, role: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{role}.{field} must be a string array")
    if not allow_empty and not value:
        raise ValueError(f"{role}.{field} must not be empty")
    if len(set(value)) != len(value):
        raise ValueError(f"{role}.{field} contains duplicates")
    return tuple(value)


def _git_blob(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", "--no-filters", str(path)],
        cwd=path.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if result.returncode == 0 and value:
        return value
    content = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def _inside(root: Path, relative: str, prefix: str) -> Path:
    if Path(relative).is_absolute():
        raise ValueError(f"path must be relative: {relative}")
    candidate = (root / relative).resolve()
    allowed = (root / prefix).resolve()
    if candidate == allowed or allowed not in candidate.parents:
        raise ValueError(f"path escapes {prefix}/: {relative}")
    return candidate


def _description(contract: str) -> str:
    lines = contract.splitlines()
    try:
        start = lines.index("## Purpose") + 1
    except ValueError as exc:
        raise ValueError("contract missing Purpose section") from exc
    for line in lines[start:]:
        if line.strip():
            return line.strip()
    raise ValueError("contract Purpose is empty")


def load_registry(root: Path | str) -> Registry:
    root = Path(root).resolve()
    mapping = root / "roles.toml"
    data = tomllib.loads(mapping.read_text())
    if data.get("schema_version") != 1:
        raise ValueError("roles.toml schema_version must be 1")
    policy = data.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("roles.toml missing policy")
    concise = policy.get("concise") is True
    forbid_dashes = policy.get("forbid_unicode_dashes") is True
    raw_spawn = policy.get("raw_adapter_spawn") is True
    if not concise or not forbid_dashes or raw_spawn:
        raise ValueError("roles.toml must require concise text, forbid unicode dashes, and prohibit raw adapter spawn")
    raw_roles = data.get("roles")
    if not isinstance(raw_roles, dict) or not raw_roles:
        raise ValueError("roles.toml missing roles")

    roles: dict[str, Role] = {}
    for name, raw in raw_roles.items():
        if not isinstance(raw, dict):
            raise ValueError(f"role {name} must be a table")
        unknown = set(raw) - ROLE_FIELDS - OPTIONAL_ROLE_FIELDS
        missing = ROLE_FIELDS - set(raw)
        if unknown or missing:
            raise ValueError(f"role {name} fields invalid: missing={sorted(missing)} unknown={sorted(unknown)}")
        values = {field: raw[field] for field in ROLE_FIELDS - {"tools", "required_skills", "conditional_skills"}}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise ValueError(f"role {name} has empty machine field")
        if raw["provider"] not in {"anthropic", "openai"}:
            raise ValueError(f"role {name} provider unsupported")
        if raw["effort"] not in {"low", "medium", "high", "xhigh", "ultra"}:
            raise ValueError(f"role {name} effort unsupported")
        if raw["mode"] not in {"auto", "never"}:
            raise ValueError(f"role {name} mode unsupported")
        if raw["session"] not in {"persistent", "fresh"}:
            raise ValueError(f"role {name} session unsupported")
        if raw["execution"] not in {"workflow-subagent", "persistent"}:
            raise ValueError(f"role {name} execution unsupported")
        if raw["execution"] == "persistent" and name not in PERSISTENT_EXECUTION_ROLES:
            raise ValueError(f"role {name} execution persistent restricted to meta-operator and orchestrator")
        subagent_access = raw.get("subagent_access")
        provenance = raw.get("provenance")
        if raw["execution"] == "persistent":
            if subagent_access is not None:
                raise ValueError(f"role {name} subagent_access only on workflow-subagent roles")
            if provenance is not None:
                raise ValueError(f"role {name} provenance only on workflow-subagent roles")
        else:
            if subagent_access is None:
                raise ValueError(f"role {name} subagent_access required for workflow-subagent roles")
        if subagent_access is not None and subagent_access not in SUBAGENT_ACCESS_VALUES:
            raise ValueError(f"role {name} subagent_access unsupported")
        if provenance is not None and provenance not in PROVENANCE_VALUES:
            raise ValueError(f"role {name} provenance unsupported")
        if raw["service_tier"] not in {"default", "fast"}:
            raise ValueError(f"role {name} service_tier unsupported")

        # Operator-selectable alternate runtimes (model, effort) an orchestrator may
        # be spawned on at operator choice; the default model/effort remain the pin.
        alt_runtimes: list[tuple[str, str]] = []
        raw_alts = raw.get("alt_runtimes")
        if raw_alts is not None:
            if not isinstance(raw_alts, list):
                raise ValueError(f"role {name}.alt_runtimes must be an array of tables")
            for item in raw_alts:
                if not isinstance(item, dict) or set(item) != {"model", "effort"}:
                    raise ValueError(f"role {name} has invalid alt_runtime (expected model, effort)")
                alt_model, alt_effort = item["model"], item["effort"]
                if not isinstance(alt_model, str) or not alt_model:
                    raise ValueError(f"role {name} alt_runtime model must be a nonempty string")
                if alt_effort not in {"low", "medium", "high", "xhigh", "ultra"}:
                    raise ValueError(f"role {name} alt_runtime effort unsupported")
                if (alt_model, alt_effort) == (raw["model"], raw["effort"]):
                    raise ValueError(f"role {name} alt_runtime duplicates the default runtime")
                alt_runtimes.append((alt_model, alt_effort))

        conditional: list[ConditionalSkill] = []
        seen_conditions: set[tuple[str, str]] = set()
        if not isinstance(raw["conditional_skills"], list):
            raise ValueError(f"role {name}.conditional_skills must be an array of tables")
        for item in raw["conditional_skills"]:
            if not isinstance(item, dict) or set(item) != {"skill", "when"}:
                raise ValueError(f"role {name} has invalid conditional skill")
            pair = (item["skill"], item["when"])
            if any(not isinstance(value, str) or not value for value in pair) or pair in seen_conditions:
                raise ValueError(f"role {name} has invalid or duplicate conditional skill")
            seen_conditions.add(pair)
            conditional.append(ConditionalSkill(*pair))

        contract_path = _inside(root, raw["contract"], "roles")
        if not contract_path.is_file():
            raise ValueError(f"role {name} contract missing: {raw['contract']}")
        contract = contract_path.read_text()
        if forbid_dashes and any(dash in contract for dash in UNICODE_DASHES):
            raise ValueError(f"role {name} contract contains unicode dash")
        if "Be extremely concise. Sacrifice grammar for concision. No em dashes or en dashes. Ever." not in contract:
            raise ValueError(f"role {name} contract missing concise text rule")
        _description(contract)

        role = Role(
            name=name,
            contract=raw["contract"],
            provider=raw["provider"],
            model=raw["model"],
            effort=raw["effort"],
            mode=raw["mode"],
            session=raw["session"],
            execution=raw["execution"],
            subagent_access=subagent_access,
            provenance=provenance,
            service_tier=raw["service_tier"],
            tools=_strings(raw["tools"], "tools", name, allow_empty=False),
            required_skills=_strings(raw["required_skills"], "required_skills", name),
            conditional_skills=tuple(conditional),
            alt_runtimes=tuple(alt_runtimes),
        )
        role_skills = set(role.required_skills)
        for item in role.conditional_skills:
            if item.skill in role_skills:
                raise ValueError(f"role {name} skill is both required and conditional: {item.skill}")
            role_skills.add(item.skill)
        roles[name] = role

    return Registry(root, roles, concise, forbid_dashes, raw_spawn, _git_blob(mapping))


def _skill_blob(root: Path, skill: str) -> str:
    # Managed skills (skillfile install target agents/skills, ADR 0002) shadow
    # locally authored skills/ skills of the same name.
    for base in ("agents/skills", "skills"):
        path = _inside(root, f"{base}/{skill}/SKILL.md", base)
        if path.is_file():
            return _git_blob(path)
    raise ValueError(f"skill contract missing: {skill}")


def resolve_role(registry: Registry, role_name: str, capabilities: set[str] | None = None) -> ResolvedRole:
    try:
        role = registry.roles[role_name]
    except KeyError as exc:
        raise ValueError(f"unknown role: {role_name}") from exc
    matched = capabilities or set()
    skills = list(role.required_skills)
    skills.extend(item.skill for item in role.conditional_skills if item.when in matched)
    contract_path = registry.root / role.contract
    return ResolvedRole(
        registry=registry,
        role=role,
        contract_text=contract_path.read_text(),
        contract_blob=_git_blob(contract_path),
        skills=tuple(skills),
        capabilities=tuple(sorted(matched)),
    )


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: tuple[str, ...] | list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def render_claude_adapter(resolved: ResolvedRole) -> str:
    role = resolved.role
    conditional = [f"{item.skill}:{item.when}" for item in role.conditional_skills]
    runtime_extra = [f"execution: {role.execution}"]
    if role.subagent_access is not None:
        runtime_extra.append(f"subagentAccess: {role.subagent_access}")
    if role.provenance is not None:
        runtime_extra.append(f"provenance: {role.provenance}")
    header = [
        "---",
        f"name: {role.name}",
        f"description: {_toml_string(_description(resolved.contract_text))}",
        "generated: true",
        "raw_spawn: prohibited",
        f"provider: {role.provider}",
        f"model: {_toml_string(role.model)}",
        f"effort: {role.effort}",
        f"permissionMode: {role.mode}",
        f"session: {role.session}",
        *runtime_extra,
        f"serviceTier: {role.service_tier}",
        f"tools: {json.dumps(role.tools)}",
        f"requiredSkills: {json.dumps(role.required_skills)}",
        f"conditionalSkills: {json.dumps(conditional)}",
        f"contractPath: {role.contract}",
        f"contractBlob: {resolved.contract_blob}",
        f"mappingRevision: {resolved.registry.mapping_revision}",
        "---",
        "<!-- Generated by workflows/lib/role_resolver.py. Resolve before launch. Never edit or spawn raw. -->",
        "",
    ]
    return "\n".join(header) + resolved.contract_text.rstrip() + "\n"


def generate_adapters(root: Path | str, registry: Registry | None = None) -> list[Path]:
    root = Path(root).resolve()
    registry = registry or load_registry(root)
    agents = root / "agents"
    agents.mkdir(exist_ok=True)
    written: list[Path] = []
    for name in sorted(registry.roles):
        resolved = resolve_role(registry, name)
        path = agents / f"{name}.md"
        path.write_text(render_claude_adapter(resolved))
        written.append(path)
    return written


def check_adapters(root: Path | str, registry: Registry | None = None) -> list[str]:
    root = Path(root).resolve()
    registry = registry or load_registry(root)
    expected: dict[Path, str] = {}
    for name in sorted(registry.roles):
        resolved = resolve_role(registry, name)
        expected[root / "agents" / f"{name}.md"] = render_claude_adapter(resolved)
    errors: list[str] = []
    for path, content in expected.items():
        if not path.is_file():
            errors.append(f"missing generated adapter: {path.relative_to(root)}")
        elif path.read_text() != content:
            errors.append(f"stale generated adapter: {path.relative_to(root)}")
    actual = set((root / "agents").glob("*.md")) | set((root / "agents").glob("*.toml"))
    for path in sorted(actual - set(expected)):
        errors.append(f"obsolete adapter: {path.relative_to(root)}")
    return errors


def _git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def build_launch_receipt(
    root: Path | str,
    resolved: ResolvedRole,
    *,
    spawn_id: str,
    parent: str,
    reply_route: str,
    repo: Path | str,
    worktree: Path | str,
    execution_location: str,
    operator_loopback: bool,
    review_delivery: str,
    issue: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    repo = Path(repo).resolve()
    # Operator runtime choice at spawn: model+effort default to the role's pinned
    # runtime, or may select one of the role's sanctioned alt_runtimes (e.g. a Fable
    # orchestrator). An override that is neither the default nor a declared alternate
    # fails closed.
    if model is not None or effort is not None:
        if model is None or effort is None:
            raise ValueError("model and effort must be provided together")
        allowed = {(resolved.role.model, resolved.role.effort), *resolved.role.alt_runtimes}
        if (model, effort) not in allowed:
            raise ValueError(
                f"runtime {model}/{effort} not sanctioned for role {resolved.role.name}"
            )
    effective_model = model if model is not None else resolved.role.model
    effective_effort = effort if effort is not None else resolved.role.effort
    worktree = Path(worktree).resolve()
    if not spawn_id or not parent or not reply_route:
        raise ValueError("spawn_id, parent, and reply_route are required")
    if execution_location not in {"local", "remote"}:
        raise ValueError("execution_location must be local or remote")
    instructions = worktree / "AGENTS.md"
    if not instructions.is_file():
        raise ValueError(f"target instructions missing: {instructions}")
    git_root = Path(_git_output(worktree, "rev-parse", "--show-toplevel")).resolve()
    if git_root != worktree:
        raise ValueError(f"worktree must be git root: {worktree}")
    if Path(_git_output(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError(f"repo must be git root: {repo}")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "spawn_id": spawn_id,
        "parent": parent,
        "reply_route": reply_route,
        "ready": True,
        "role": {
            "name": resolved.role.name,
            "root": str(root),
            "contract_path": resolved.role.contract,
            "contract_blob": resolved.contract_blob,
            "mapping_revision": resolved.registry.mapping_revision,
        },
        "runtime": {
            "provider": resolved.role.provider,
            "model": effective_model,
            "effort": effective_effort,
            "mode": resolved.role.mode,
            "session": resolved.role.session,
            "service_tier": resolved.role.service_tier,
            "tools": list(resolved.role.tools),
        },
        "skills": {
            "resolved": list(resolved.skills),
            "matched_capabilities": list(resolved.capabilities),
            "paths": [f"skills/{skill}/SKILL.md" for skill in resolved.skills],
            "blobs": [_skill_blob(root, skill) for skill in resolved.skills],
        },
        "workspace": {
            "repo": str(repo),
            "worktree": str(worktree),
            "starting_head": _git_output(worktree, "rev-parse", "HEAD"),
            "instructions_path": "AGENTS.md",
            "instructions_blob": _git_blob(instructions),
        },
        "access": {
            "execution_location": execution_location,
            "operator_loopback": operator_loopback,
            "review_delivery": review_delivery,
        },
        "bootstrap": {"verified": False, "provider_session_id": ""},
    }
    # launch-receipt-issue-binding: an issue orchestrator's persistent receipt
    # additionally binds its exact issue identifier so the Shaped-transition gate
    # that requires the caller receipt name that exact issue admits it. A
    # meta-operator or epic orchestrator receipt binds no issue and omits it.
    if issue is not None:
        if not issue.strip():
            raise ValueError("issue identifier must be nonempty when provided")
        receipt["issue"] = {"identifier": issue}
    receipt["launch_revision"] = _launch_revision(receipt)
    return receipt


def render_receipt(receipt: dict[str, Any]) -> str:
    lines = [
        f"schema_version = {receipt['schema_version']}",
        f"spawn_id = {_toml_string(receipt['spawn_id'])}",
        f"parent = {_toml_string(receipt['parent'])}",
        f"reply_route = {_toml_string(receipt['reply_route'])}",
        f"ready = {str(receipt['ready']).lower()}",
        f"launch_revision = {_toml_string(receipt['launch_revision'])}",
    ]
    sections = ["role", "runtime", "skills", "workspace"]
    if "issue" in receipt:
        sections.append("issue")
    sections.extend(["access", "bootstrap"])
    for section in sections:
        lines.extend(["", f"[{section}]"])
        for key, value in receipt[section].items():
            if isinstance(value, bool):
                rendered = str(value).lower()
            elif isinstance(value, list):
                rendered = _toml_array(value)
            else:
                rendered = _toml_string(str(value))
            lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def render_contract_section(resolved: ResolvedRole) -> str:
    """Render the canonical contract text as a valid TOML [contract] table.

    The relay carries this text verbatim as the codex exec prompt, and every consumer that
    loads the resolve stdout as TOML still parses cleanly. The text is emitted as a multiline
    basic string with backslash and quote sequences escaped so the value round-trips exactly.
    """
    text = resolved.contract_text
    escaped = text.replace("\\", "\\\\").replace('"""', '""\\"')
    body = escaped if escaped.startswith("\n") else "\n" + escaped
    if not body.endswith("\n"):
        body += "\n"
    return "".join(
        [
            "\n[contract]\n",
            f"blob = {_toml_string(resolved.contract_blob)}\n",
            f"path = {_toml_string(resolved.role.contract)}\n",
            f'text = """{body}"""\n',
        ]
    )


def dry_run_child(resolved: ResolvedRole, receipt: dict[str, Any]) -> dict[str, Any]:
    """Cross a real child-process boundary and return its launch acknowledgment."""
    child = r'''
import hashlib
import json
import sys

payload = json.load(sys.stdin)
receipt = payload["receipt"]
contract = payload["contract"].encode()
blob = hashlib.sha1(b"blob " + str(len(contract)).encode() + b"\0" + contract).hexdigest()
if blob != receipt["role"]["contract_blob"]:
    raise SystemExit("contract blob mismatch")
json.dump({
    "spawn_id": receipt["spawn_id"],
    "role": receipt["role"]["name"],
    "contract_blob": blob,
    "mapping_revision": receipt["role"]["mapping_revision"],
    "provider": receipt["runtime"]["provider"],
    "model": receipt["runtime"]["model"],
    "effort": receipt["runtime"]["effort"],
    "mode": receipt["runtime"]["mode"],
    "session": receipt["runtime"]["session"],
    "service_tier": receipt["runtime"]["service_tier"],
    "skills": receipt["skills"]["resolved"],
    "skill_blobs": receipt["skills"]["blobs"],
    "repo": receipt["workspace"]["repo"],
    "worktree": receipt["workspace"]["worktree"],
    "instructions_blob": receipt["workspace"]["instructions_blob"],
    "starting_head": receipt["workspace"]["starting_head"],
    "execution_location": receipt["access"]["execution_location"],
    "operator_loopback": receipt["access"]["operator_loopback"],
    "review_delivery": receipt["access"]["review_delivery"],
}, sys.stdout, sort_keys=True)
'''
    result = subprocess.run(
        [sys.executable, "-c", child],
        input=json.dumps({"contract": resolved.contract_text, "receipt": receipt}),
        text=True,
        capture_output=True,
        check=True,
    )
    acknowledgment = json.loads(result.stdout)
    verify_bootstrap_ack(receipt, acknowledgment)
    return acknowledgment


def verify_bootstrap_ack(receipt: dict[str, Any], acknowledgment: dict[str, Any]) -> None:
    expected = {
        "spawn_id": receipt["spawn_id"],
        "role": receipt["role"]["name"],
        "contract_blob": receipt["role"]["contract_blob"],
        "mapping_revision": receipt["role"]["mapping_revision"],
        "provider": receipt["runtime"]["provider"],
        "model": receipt["runtime"]["model"],
        "effort": receipt["runtime"]["effort"],
        "mode": receipt["runtime"]["mode"],
        "session": receipt["runtime"]["session"],
        "service_tier": receipt["runtime"]["service_tier"],
        "skills": receipt["skills"]["resolved"],
        "skill_blobs": receipt["skills"]["blobs"],
        "repo": receipt["workspace"]["repo"],
        "worktree": receipt["workspace"]["worktree"],
        "instructions_blob": receipt["workspace"]["instructions_blob"],
        "starting_head": receipt["workspace"]["starting_head"],
        "execution_location": receipt["access"]["execution_location"],
        "operator_loopback": receipt["access"]["operator_loopback"],
        "review_delivery": receipt["access"]["review_delivery"],
    }
    mismatches = [key for key, value in expected.items() if acknowledgment.get(key) != value]
    if mismatches:
        raise ValueError(f"bootstrap acknowledgment mismatch: {', '.join(mismatches)}")


def _root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_root_from_script())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate")
    sub.add_parser("check")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("role")
    resolve.add_argument("--capability", action="append", default=[])
    resolve.add_argument("--spawn-id", required=True)
    resolve.add_argument("--parent", required=True)
    resolve.add_argument("--reply-route", required=True)
    resolve.add_argument("--repo", type=Path, required=True)
    resolve.add_argument("--worktree", type=Path, required=True)
    resolve.add_argument("--execution-location", choices=("local", "remote"), required=True)
    resolve.add_argument("--operator-loopback", choices=("true", "false"), default="false")
    resolve.add_argument("--review-delivery", required=True)
    # launch-receipt-issue-binding: the launcher binds the exact issue identifier
    # onto an issue-orchestrator persistent receipt so the octo-control
    # Shaped-transition gate that requires receipt[issue][identifier] admits it.
    # Absent for meta-operator and epic-orchestrator receipts, which bind no issue.
    resolve.add_argument("--issue")
    # Operator runtime choice at spawn (e.g. a Fable orchestrator): must be the
    # role's default runtime or one of its sanctioned alt_runtimes.
    resolve.add_argument("--model")
    resolve.add_argument("--effort")
    # TUR-447 cycle1 pass2 P0 (role-runtime role-openai-relay): a relay resolver run opts in to
    # the canonical contract text so the relay carries it as the codex exec prompt. Off by
    # default so a durable launch-receipt consumer (the persistent launch path writes this
    # stdout to receipt.toml and fingerprints it) sees the exact receipt with no extra section.
    resolve.add_argument("--emit-contract", action="store_true")
    args = parser.parse_args(argv)
    registry = load_registry(args.root)
    if args.command == "generate":
        for path in generate_adapters(args.root, registry):
            print(path.relative_to(args.root))
        return 0
    if args.command == "check":
        errors = check_adapters(args.root, registry)
        for error in errors:
            print(error, file=sys.stderr)
        return 1 if errors else 0
    resolved = resolve_role(registry, args.role, set(args.capability))
    receipt = build_launch_receipt(
        args.root,
        resolved,
        spawn_id=args.spawn_id,
        parent=args.parent,
        reply_route=args.reply_route,
        repo=args.repo,
        worktree=args.worktree,
        execution_location=args.execution_location,
        operator_loopback=args.operator_loopback == "true",
        review_delivery=args.review_delivery,
        issue=args.issue,
        model=args.model,
        effort=args.effort,
    )
    print(render_receipt(receipt), end="")
    # TUR-447 cycle1 pass2 P0 (role-runtime role-openai-relay, role-no-prompt-copy): with
    # --emit-contract, print the canonical role contract text VERBATIM after the receipt as a
    # VALID TOML [contract] table so a relay subagent carries the exact contract as the codex
    # exec prompt without a copied workflow literal, and the whole stdout stays parseable TOML.
    # The blob field binds the printed text's identity. Omitted by default so the durable launch
    # receipt written by the persistent launch path stays fingerprint-stable.
    if args.emit_contract:
        print(render_contract_section(resolved), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
