#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: launch-meta-operator.sh --workspace ID [--cwd PATH] [--name NAME] [--objective TEXT] [--handoff TEXT] [--execution-location local|remote] [--operator-loopback true|false] [--review-delivery MODE] [--dry-run]"
}

workspace=""
cwd="$PWD"
name="operator-$(date -u +%Y%m%d-%H%M%S)"
objective="unconfirmed"
handoff="none"
execution_location="${OCTO_EXECUTION_LOCATION:-remote}"
operator_loopback="${OCTO_OPERATOR_LOOPBACK:-false}"
review_delivery="${OCTO_REVIEW_DELIVERY:-reachable_url_required}"
state_root="${XDG_STATE_HOME:-$HOME/.local/state}/octo-lite"
dry_run=false

while (($#)); do
  case "$1" in
    --workspace) workspace="${2:?}"; shift 2 ;;
    --cwd) cwd="${2:?}"; shift 2 ;;
    --name) name="${2:?}"; shift 2 ;;
    --objective) objective="${2:?}"; shift 2 ;;
    --handoff) handoff="${2:?}"; shift 2 ;;
    --execution-location) execution_location="${2:?}"; shift 2 ;;
    --operator-loopback) operator_loopback="${2:?}"; shift 2 ;;
    --review-delivery) review_delivery="${2:?}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 64 ;;
  esac
done

[[ -n "$workspace" ]] || { usage >&2; exit 64; }
[[ "$execution_location" == local || "$execution_location" == remote ]] || exit 64
[[ "$operator_loopback" == true || "$operator_loopback" == false ]] || exit 64
[[ -d "$cwd" ]] || exit 66
cwd="$(cd "$cwd" && pwd -P)"

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
root="$(cd "$skill_dir/../.." && pwd -P)"
resolver="$root/workflows/lib/role_resolver.py"
spawn="$root/skills/herdr-comms/assets/herdr-spawn"
timer="$root/scripts/operator-timer"
[[ -f "$resolver" && -x "$spawn" && -x "$timer" ]] || exit 66

control="$state_root/operators/$name"
brief="$control/brief.md"
status="$control/status.md"
receipt="$control/receipt.toml"
owner="$state_root/operator-owner.toml"

if [[ "$dry_run" == true ]]; then
  python3 "$resolver" resolve meta-operator \
    --capability operator-launch \
    --spawn-id "$name" --parent operator --reply-route operator \
    --repo "$cwd" --worktree "$cwd" \
    --execution-location "$execution_location" \
    --operator-loopback "$operator_loopback" \
    --review-delivery "$review_delivery"
  exit 0
fi

[[ ! -e "$control" && ! -e "$owner" ]] || { echo "operator control already exists" >&2; exit 65; }
umask 077
mkdir -p "$control/handoffs"
printf '# Operator brief\n\nObjective: %s\nCaller handoff: %s\nAuthority: confirm after read-only inventory.\n' "$objective" "$handoff" >"$brief"
printf 'Outcome: inventory pending\nGate: bootstrap\nBlocker: none\nNext operator action: confirm objective and authority\n' >"$status"
spawn_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
python3 "$resolver" resolve meta-operator \
  --capability operator-launch \
  --spawn-id "$spawn_id" --parent operator --reply-route operator \
  --repo "$cwd" --worktree "$cwd" \
  --execution-location "$execution_location" \
  --operator-loopback "$operator_loopback" \
  --review-delivery "$review_delivery" >"$receipt"
# herdr-spawn verifies BOOTSTRAP_ACK itself before this prompt ever runs; it is a
# post-bootstrap mutation instruction only, never a bootstrap-ack instruction.
prompt="Bootstrap already verified. Load and acknowledge $receipt, the canonical meta-operator role, target instructions, and $brief. Verify cwd and access facts. Write current state to $status. Begin read-only inventory."
"$spawn" --workspace "$workspace" --name "$name" --label "🧠 operator" --cwd "$cwd" --role meta-operator --receipt "$receipt" -- \
  claude --agent meta-operator --model claude-fable-5 --effort xhigh --permission-mode auto -n "$name" "$prompt"

owner_tmp="$owner.$$.tmp"
printf 'schema_version = 1\nowner_session = "%s"\nhandoff_revision = 0\ncontrol_dir = "%s"\n' "$spawn_id" "$control" >"$owner_tmp"
mv "$owner_tmp" "$owner"
"$timer" install --name "$name" --control-dir "$control" --owner-file "$owner" --repo "$cwd"

echo "name=$name control=$control owner=$owner"
