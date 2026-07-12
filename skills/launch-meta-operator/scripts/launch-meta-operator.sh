#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: launch-meta-operator.sh [options]

Options:
  --runtime codex|claude   Child runtime (default: claude — Fable only; codex is an explicit operator override)
  --cwd PATH               Starting directory (default: current directory)
  --workspace ID           Herdr workspace (default: current/focused workspace)
  --name NAME              Unique Herdr agent name
  --label TEXT             Herdr tab label (default: Meta Operator)
  --objective TEXT         Explicit starting objective, if already known
  --handoff TEXT           Compact caller context and granted authority
  --state-root PATH        Durable state root
  --focus | --no-focus     Focus the new tab after launch (default: focus)
  --dry-run                Validate and print the launch plan without starting
  -h, --help               Show this help
EOF
}

runtime="claude"
start_cwd="$PWD"
workspace="${HERDR_WORKSPACE_ID:-}"
name=""
label="Meta Operator"
objective=""
handoff=""
state_root="${XDG_STATE_HOME:-$HOME/.local/state}/octo-lite/meta-operators"
focus="true"
dry_run="false"

while (($#)); do
  case "$1" in
    --runtime)
      runtime="${2:?--runtime requires a value}"
      shift 2
      ;;
    --cwd)
      start_cwd="${2:?--cwd requires a value}"
      shift 2
      ;;
    --workspace)
      workspace="${2:?--workspace requires a value}"
      shift 2
      ;;
    --name)
      name="${2:?--name requires a value}"
      shift 2
      ;;
    --label)
      label="${2:?--label requires a value}"
      shift 2
      ;;
    --objective)
      objective="${2:?--objective requires a value}"
      shift 2
      ;;
    --handoff)
      handoff="${2:?--handoff requires a value}"
      shift 2
      ;;
    --state-root)
      state_root="${2:?--state-root requires a value}"
      shift 2
      ;;
    --focus)
      focus="true"
      shift
      ;;
    --no-focus)
      focus="false"
      shift
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$runtime" in
  codex|claude) ;;
  *)
    echo "Unsupported runtime: $runtime" >&2
    exit 2
    ;;
esac

for dependency in herdr jq "$runtime"; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    echo "Required command not found: $dependency" >&2
    exit 1
  fi
done

if [[ ! -d "$start_cwd" ]]; then
  echo "Starting directory does not exist: $start_cwd" >&2
  exit 1
fi
start_cwd="$(cd "$start_cwd" && pwd -P)"

status_output="$(herdr status)"
if ! grep -q 'compatible: yes' <<<"$status_output"; then
  echo "Herdr server is unavailable or incompatible." >&2
  echo "$status_output" >&2
  exit 1
fi

if [[ -z "$workspace" ]]; then
  workspace_json="$(herdr workspace list)"
  workspace="$(jq -r '.result.workspaces[] | select(.focused == true) | .workspace_id' <<<"$workspace_json" | head -n 1)"
  if [[ -z "$workspace" ]]; then
    workspace="$(jq -r '.result.workspaces[0].workspace_id // empty' <<<"$workspace_json")"
  fi
fi
if [[ -z "$workspace" ]]; then
  echo "No Herdr workspace is available." >&2
  exit 1
fi
herdr workspace get "$workspace" >/dev/null

if [[ -z "$name" ]]; then
  name="meta-operator-$(date -u +%Y%m%d-%H%M%S)"
fi
if [[ ! "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Invalid name '$name'; use letters, digits, dot, underscore, or hyphen." >&2
  exit 2
fi

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
template="$skill_dir/assets/meta-operator-prompt.md"
if [[ ! -f "$template" ]]; then
  echo "Prompt template not found: $template" >&2
  exit 1
fi

state_dir="$state_root/$name"
control_file="$state_dir/control.md"
starting_objective="${objective:-Not supplied; infer a hypothesis from live state and ask the user to confirm it.}"
caller_handoff="${handoff:-No additional caller handoff was supplied.}"
if [[ "$runtime" == "codex" ]]; then
  runtime_mode="yolo"
else
  runtime_mode="auto"
fi

prompt="$(<"$template")"
prompt="${prompt//\{\{OPERATOR_NAME\}\}/$name}"
prompt="${prompt//\{\{RUNTIME\}\}/$runtime}"
prompt="${prompt//\{\{RUNTIME_MODE\}\}/$runtime_mode}"
prompt="${prompt//\{\{WORKSPACE\}\}/$workspace}"
prompt="${prompt//\{\{STARTING_CWD\}\}/$start_cwd}"
prompt="${prompt//\{\{CONTROL_FILE\}\}/$control_file}"
prompt="${prompt//\{\{STARTING_OBJECTIVE\}\}/$starting_objective}"
prompt="${prompt//\{\{CALLER_HANDOFF\}\}/$caller_handoff}"

if [[ "$dry_run" == "true" ]]; then
  jq -n \
    --arg name "$name" \
    --arg runtime "$runtime" \
    --arg runtime_mode "$runtime_mode" \
    --arg cwd "$start_cwd" \
    --arg workspace "$workspace" \
    --arg state_dir "$state_dir" \
    --arg label "$label" \
    '{dry_run:true,name:$name,runtime:$runtime,runtime_mode:$runtime_mode,cwd:$cwd,workspace:$workspace,state_dir:$state_dir,label:$label}'
  exit 0
fi

if [[ -e "$state_dir" ]]; then
  echo "State directory already exists: $state_dir" >&2
  exit 1
fi

umask 077
mkdir -p "$state_dir"
cp "$template" "$state_dir/prompt-template.md"
printf '%s\n' "$prompt" >"$state_dir/launch-prompt.md"
cat >"$control_file" <<EOF
# Meta-Operator Control State

- Name: $name
- Runtime: $runtime
- Runtime mode: $runtime_mode
- Status: bootstrapping
- Launched: $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Herdr workspace: $workspace
- Starting directory: $start_cwd
- Objective: unconfirmed
- Done condition: unconfirmed

## Active Work

Inventory pending.

## Decisions and Authority

Awaiting user confirmation after read-only inventory.

## Risks and Questions

Inventory pending.

## Next Expected Transition

Inspect live Herdr state and present an objective hypothesis to the user.
EOF

case "$runtime" in
  codex)
    child_command=(codex --yolo -C "$start_cwd" "$prompt")
    ;;
  claude)
    child_command=(claude --model fable --effort xhigh --permission-mode auto -n "$name" "$prompt")
    ;;
esac

start_output="$(herdr agent start "$name" --cwd "$start_cwd" --workspace "$workspace" --no-focus -- "${child_command[@]}")"
pane_id="$(jq -r '.result.agent.pane_id // empty' <<<"$start_output")"
if [[ -z "$pane_id" ]]; then
  echo "Herdr did not return a pane id." >&2
  echo "$start_output" >&2
  exit 1
fi

move_args=(herdr pane move "$pane_id" --new-tab --workspace "$workspace" --label "$label")
if [[ "$focus" == "true" ]]; then
  move_args+=(--focus)
else
  move_args+=(--no-focus)
fi
if ! move_output="$("${move_args[@]}")"; then
  echo "Agent started in pane $pane_id, but moving it to a new tab failed." >&2
  exit 1
fi

tab_id="$(jq -r '.result.move_result.created_tab.tab_id // .result.move_result.pane.tab_id // empty' <<<"$move_output")"
cat >>"$control_file" <<EOF

## Launch Identity

- Herdr pane: $pane_id
- Herdr tab: ${tab_id:-unknown}
EOF

jq -n \
  --arg name "$name" \
  --arg runtime "$runtime" \
  --arg runtime_mode "$runtime_mode" \
  --arg pane_id "$pane_id" \
  --arg tab_id "$tab_id" \
  --arg workspace "$workspace" \
  --arg control_file "$control_file" \
  '{launched:true,name:$name,runtime:$runtime,runtime_mode:$runtime_mode,pane_id:$pane_id,tab_id:$tab_id,workspace:$workspace,control_file:$control_file}'
