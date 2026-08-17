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
  echo "usage: activate-codex-thread-operator.sh --workspace ID [--cwd PATH] [--handoff PATH] [--force-takeover --reason TEXT] [--context-ref KEY=VALUE]..."
}

workspace=""
cwd="$PWD"
handoff=""
reason=""
force=false
context_refs=()
state_root="${XDG_STATE_HOME:-$HOME/.local/state}/octo-lite"

while (($#)); do
  case "$1" in
    --workspace) workspace="${2:?}"; shift 2 ;;
    --cwd) cwd="${2:?}"; shift 2 ;;
    --handoff) handoff="${2:?}"; shift 2 ;;
    --force-takeover) force=true; shift ;;
    --reason) reason="${2:?}"; shift 2 ;;
    --context-ref) context_refs+=(--context-ref "${2:?}"); shift 2 ;;
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
# identity proof reads).
codex_home="${CODEX_HOME:-$HOME/.codex}"
session_matches="$(find "$codex_home/sessions" -type f -name "rollout-*-$thread_id.jsonl" -print -quit 2>/dev/null || true)"
[[ -n "$session_matches" ]] || { echo "activate-codex-thread-operator: no local Codex session for $thread_id" >&2; exit 66; }

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
root="$(cd "$skill_dir/../.." && pwd -P)"
control_cli="$root/scripts/octo-control"
[[ -x "$control_cli" ]] || exit 66

# Read-only workspace verification BEFORE any authority write. The Codex app
# thread is not a Herdr pane, so this verified workspace is the only route
# canonical orchestrator spawns can use.
herdr workspace get "$workspace" >/dev/null || {
  echo "activate-codex-thread-operator: herdr workspace $workspace not verified" >&2
  exit 66
}

owner="$state_root/operator-owner.toml"
control="$state_root/operators/codex-$thread_id"

args=(codex-activate --owner-file "$owner" --workspace "$workspace" --control-dir "$control" --repo "$cwd")
[[ -n "$handoff" ]] && args+=(--handoff "$handoff")
if [[ "$force" == true ]]; then
  args+=(--force-takeover --reason "$reason")
  args+=("${context_refs[@]+"${context_refs[@]}"}")
fi

"$control_cli" "${args[@]}"
