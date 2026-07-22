#!/usr/bin/env bash
set -euo pipefail

# Live meta-operator handoff launcher (operator-control operator-handoff:
# handoff-launcher-live, handoff-launcher-pre-derive,
# handoff-launcher-single-live-command, handoff-launcher-owner-identity-preexisting,
# handoff-launcher-dead-owner-guidance). This is the SEPARATE live path; the
# initial launch (revision zero owner create) stays in launch-meta-operator.sh.
# It requires an existing owner record, spawns ONE successor that coexists with
# the current owner under the same invariant control directory, writes NO owner
# record itself, installs NO timer, and never probes owner liveness.

usage() {
  echo "usage: handoff-meta-operator.sh --workspace ID --handoff DOC [--cwd PATH] [--name NAME] [--execution-location local|remote] [--operator-loopback true|false] [--review-delivery MODE] [--dry-run]"
}

workspace=""
cwd="$PWD"
name="operator-$(date -u +%Y%m%d-%H%M%S)"
handoff=""
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
control_cli="$root/scripts/octo-control"
[[ -f "$resolver" && -x "$spawn" && -x "$control_cli" ]] || exit 66

owner="$state_root/operator-owner.toml"

# Dry-run: resolve the successor receipt to stdout and exit, making NO durable
# mutation (no owner write, no operators/<name>/, no spawn, no timer).
if [[ "$dry_run" == true ]]; then
  dry_spawn_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
  python3 "$resolver" resolve meta-operator \
    --capability operator-launch \
    --spawn-id "$dry_spawn_id" --parent operator --reply-route operator \
    --repo "$cwd" --worktree "$cwd" \
    --execution-location "$execution_location" \
    --operator-loopback "$operator_loopback" \
    --review-delivery "$review_delivery"
  exit 0
fi

# Live handoff REQUIRES an existing owner record. A missing owner record means
# this is not a live handoff; the initial path is launch-meta-operator.sh. This
# launcher never weakens the initial launcher's own already-exists guard.
[[ -f "$owner" ]] || { echo "handoff-meta-operator: no owner record; initial launch uses launch-meta-operator.sh" >&2; exit 65; }

# Read the current owner identity, route, revision, and INVARIANT control dir.
read_owner() {
  python3 - "$owner" "$1" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    owner = tomllib.load(handle)
value = owner.get(sys.argv[2])
if value is None:
    raise SystemExit(2)
print(value)
PY
}
cur_owner_sid="$(read_owner owner_session_id)" || { echo "handoff-meta-operator: owner record missing owner_session_id" >&2; exit 65; }
cur_route="$(read_owner owner_route)" || { echo "handoff-meta-operator: owner record missing owner_route" >&2; exit 65; }
cur_revision="$(read_owner handoff_revision)" || { echo "handoff-meta-operator: owner record missing handoff_revision" >&2; exit 65; }
control_dir="$(read_owner control_dir)" || { echo "handoff-meta-operator: owner record missing control_dir" >&2; exit 65; }
new_revision=$((cur_revision + 1))

# The next-revision handoff artifact must exist AND its basename must be the
# zero-padded R+1 AND its parent dir must be control_dir/handoffs. This rejects a
# correct basename in the wrong dir and a wrong basename in the right dir.
[[ -n "$handoff" ]] || { echo "handoff-meta-operator: --handoff DOC required" >&2; exit 64; }
[[ -f "$handoff" ]] || { echo "handoff-meta-operator: handoff doc missing: $handoff" >&2; exit 66; }
handoff_abs="$(cd "$(dirname "$handoff")" && pwd -P)/$(basename "$handoff")"
expected_base="$(printf '%04d.md' "$new_revision")"
expected_parent="$(cd "$control_dir/handoffs" 2>/dev/null && pwd -P || true)"
[[ "$(basename "$handoff_abs")" == "$expected_base" ]] || { echo "handoff-meta-operator: handoff basename must be $expected_base (next revision)" >&2; exit 65; }
[[ -n "$expected_parent" && "$(dirname "$handoff_abs")" == "$expected_parent" ]] || { echo "handoff-meta-operator: handoff must live under $control_dir/handoffs" >&2; exit 65; }

# Successor session artifacts live under the successor's OWN operator directory,
# never the invariant control dir.
succ_control="$state_root/operators/$name"
succ_brief="$succ_control/brief.md"
succ_status="$succ_control/status.md"
succ_receipt="$succ_control/receipt.toml"
succ_ready="$succ_control/successor-ready.toml"

[[ ! -e "$succ_control" ]] || { echo "handoff-meta-operator: successor control already exists: $succ_control" >&2; exit 65; }
umask 077
mkdir -p "$succ_control/handoffs"
printf '# Successor operator brief\n\nHandoff doc: %s\nRevision: %s -> %s\nControl dir (invariant): %s\nAuthority: reconcile at source, then declare readiness.\n' \
  "$handoff_abs" "$cur_revision" "$new_revision" "$control_dir" >"$succ_brief"
printf 'Outcome: reconcile pending\nGate: successor-ready\nBlocker: none\nNext operator action: reconcile handoff at source and declare successor-ready\n' >"$succ_status"

spawn_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
python3 "$resolver" resolve meta-operator \
  --capability operator-launch \
  --spawn-id "$spawn_id" --parent operator --reply-route operator \
  --repo "$cwd" --worktree "$cwd" \
  --execution-location "$execution_location" \
  --operator-loopback "$operator_loopback" \
  --review-delivery "$review_delivery" >"$succ_receipt"

# The successor coexists with the current owner. Its spawn prompt instructs it to
# read the handoff, reconcile at source, run the pre-derived successor-ready
# command, then signal the current owner; the current owner runs owner-transfer.
prompt="Bootstrap already verified. Live operator handoff. Load and acknowledge $succ_receipt, the canonical meta-operator role, target instructions, and $succ_brief. Read the handoff $handoff_abs and reconcile it against source systems. Then run the pre-derived successor-ready command (declares $succ_ready at revision $new_revision) and signal the current owner ready. The current owner runs the owner-transfer command to commit authority."
spawn_output="$("$spawn" --workspace "$workspace" --name "$name" --label "🧠 operator" --cwd "$cwd" --role meta-operator --receipt "$succ_receipt" -- \
  claude --rc --agent meta-operator --model claude-fable-5 --effort xhigh --permission-mode auto -n "$name" "$prompt")"
echo "$spawn_output"
succ_sid="$(grep -oE 'provider_session_id=[^ ]+' <<<"$spawn_output" | cut -d= -f2)"
[[ -n "$succ_sid" ]] || { echo "handoff-meta-operator: missing verified successor provider session id" >&2; exit 1; }

# Pre-derive and print the two exact runnable commands. Each is a bare runnable
# line (first token is the octo-control CLI). The successor runs the
# successor-ready command after reconciling; the CURRENT owner runs the
# owner-transfer command after the successor is ready. The launcher writes no
# owner record; owner-transfer is the sole authority commit.
echo "octo-control successor-ready --path $succ_ready --caller $succ_sid --session-id $succ_sid --handoff-revision $new_revision"
echo "octo-control owner-transfer --owner-file $owner --expected-owner $cur_owner_sid --expected-route $cur_route --expected-revision $cur_revision --caller $cur_owner_sid --new-owner $succ_sid --new-route $name --revision $new_revision --control-dir $control_dir --handoff $handoff_abs --successor-readiness $succ_ready"
# ruling-76 term A boundary notice (one line): the printed owner-transfer is the
# normal owner-run handoff-atomic step, run ONLY as the live current owner.
echo "boundary: Run owner-transfer ONLY as the live current owner; a dead or ambiguous owner is recovered solely by manual operator takeover outside role authority on operator instruction (ADR-0001)."

echo "name=$name succ_control=$succ_control succ_sid=$succ_sid revision=$new_revision control_dir=$control_dir"
