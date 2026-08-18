#!/usr/bin/env bash
set -euo pipefail

# Current Codex thread meta-operator activation (operator-control
# codex-thread-activation, codex-forced-takeover; role-runtime
# launch-codex-thread-activation; ADR 0005).
#
# This is a host-session AUTHORITY BINDING, not a provider launch: it resolves no
# role, writes no launch receipt, spawns no session, and installs no timer,
# daemon, polling service, background resume, surrogate, or duplicate inbox.
# There is NO thread-ID argument; the exact current thread comes only from the
# host CODEX_THREAD_ID and is proven against Codex's own local session record.

usage() {
  echo "usage: activate-codex-thread-operator.sh --workspace ID [--cwd PATH] [--handoff PATH] [--force-takeover --reason TEXT]"
}

workspace=""
cwd="$PWD"
handoff=""
reason=""
force=false
state_root="${XDG_STATE_HOME:-$HOME/.local/state}/octo-lite"

while (($#)); do
  case "$1" in
    --workspace) workspace="${2:?}"; shift 2 ;;
    --cwd) cwd="${2:?}"; shift 2 ;;
    --handoff) handoff="${2:?}"; shift 2 ;;
    --force-takeover) force=true; shift ;;
    --reason) reason="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    # Every other option, including any thread-ID override, is rejected.
    *) usage >&2; exit 64 ;;
  esac
done

[[ -n "$workspace" ]] || { usage >&2; exit 64; }
[[ -d "$cwd" ]] || exit 66
cwd="$(cd "$cwd" && pwd -P)"

# Exact current thread identity: host-provided only, never caller-supplied.
thread_id="${CODEX_THREAD_ID:-}"
[[ -n "$thread_id" ]] || { echo "activate-codex-thread-operator: host CODEX_THREAD_ID required" >&2; exit 64; }

# Prove the corresponding local Codex session exists, using Codex's own rollout
# record under CODEX_HOME/sessions (the same authoritative source the relay
# identity proof reads). A matching FILENAME is not identity: the session's own
# session_meta record must name the same ID
# (role-runtime launch-codex-activation-host-identity).
codex_home="${CODEX_HOME:-$HOME/.codex}"
session_proven=false
while IFS= read -r rollout; do
  meta_id="$(head -n 1 "$rollout" | jq -r 'select(.type == "session_meta") | .payload.id // .payload.session_id // empty' 2>/dev/null || true)"
  if [[ "$meta_id" == "$thread_id" ]]; then
    session_proven=true
    break
  fi
done < <(find "$codex_home/sessions" -type f -name "rollout-*-$thread_id.jsonl" 2>/dev/null || true)
[[ "$session_proven" == true ]] || { echo "activate-codex-thread-operator: no local Codex session for $thread_id" >&2; exit 66; }

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
root="$(cd "$skill_dir/../.." && pwd -P)"
control_cli="$root/scripts/octo-control"
[[ -x "$control_cli" ]] || exit 66

# Read-only workspace verification BEFORE any authority write. The Codex app
# thread is not a Herdr pane, so this verified workspace is the only route
# canonical orchestrator spawns can use. Exit status alone is not verification:
# the lookup must return the exact requested workspace ID
# (role-runtime launch-codex-activation-workspace).
workspace_json="$(herdr workspace get "$workspace" 2>/dev/null)" || {
  echo "activate-codex-thread-operator: herdr workspace $workspace not verified" >&2
  exit 66
}
resolved_workspace="$(jq -r '.result.workspace.id // empty' <<<"$workspace_json" 2>/dev/null || true)"
[[ "$resolved_workspace" == "$workspace" ]] || {
  echo "activate-codex-thread-operator: herdr workspace $workspace not verified" >&2
  exit 66
}

owner="$state_root/operator-owner.toml"
control="$state_root/operators/codex-$thread_id"

# The canonical contract load runs inside octo-control codex-activate, the one
# authority entry point every activation and forced takeover passes through: it
# reads the installed profile, this target's AGENTS.md, roles/meta-operator.md,
# and the resolver-mapped meta-operator skills, binds each to exact bytes, and
# refuses before any owner write when one is unreadable
# (role-runtime launch-codex-activation-contract).
args=(codex-activate --owner-file "$owner" --workspace "$workspace" --control-dir "$control" --repo "$cwd")
[[ -n "$handoff" ]] && args+=(--handoff "$handoff")
if [[ "$force" == true ]]; then
  args+=(--force-takeover --reason "$reason")
fi

"$control_cli" "${args[@]}"
