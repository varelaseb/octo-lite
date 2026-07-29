#!/usr/bin/env bash
# gh#31 POST-FIX contract (TDD). Asserts the corrected submission-correlated
# confirmation. RED against original scripts, GREEN after the fix.
#
# Fix contract:
#  - FIRE only into a NON-WORKING target (agent_status idle|done). A working/
#    blocked/unknown target DEFERS (no fire, no attempt burn, item retained).
#    -> kills RC3 false-positive and the RC2 fire-then-dup, because we never
#       fire a send we cannot confirm.
#  - CONFIRM per-message on THIS prompt's own outcome (no global seq):
#      agent_prompt_stalled -> UNCONFIRMED (submit swallowed, retry)
#      settled agent_status idle|done|blocked -> CONFIRMED
#      timeout (turn started from a non-working start) -> CONFIRMED
#  - ack/complete contract and message TOML schema UNCHANGED.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ASSETS="$(cd "$HERE/../../skills/herdr-comms/assets" && pwd)"
export PATH="$HERE:$PATH"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export XDG_STATE_HOME="$TMP/state"; export HOME="$TMP/home"
mkdir -p "$XDG_STATE_HOME" "$HOME"
export HARNESS_SEQ_FILE="$TMP/seq"; export HARNESS_SINK="$TMP/delivered"
: >"$HARNESS_SINK"

pass=0; fail=0
ok()  { echo "  PASS: $1"; pass=$((pass+1)); }
bad() { echo "  FAIL: $1"; fail=$((fail+1)); }
sink_count() { grep -c "$1" "$HARNESS_SINK" 2>/dev/null || true; }
msg_state() { python3 -c "import tomllib,glob;
fs=sorted(glob.glob('$XDG_STATE_HOME/octo-lite/messages/*.toml'));
d=tomllib.load(open(fs[-1],'rb'));
print(d.get('status',''),d.get('delivery_path',''),d.get('transport_attempts',0))" 2>/dev/null; }
inbox_items() { find "$XDG_STATE_HOME/octo-lite/inbox" -type f 2>/dev/null | grep -Ec '[0-9]{8}T' || true; }
reset() { rm -rf "$XDG_STATE_HOME/octo-lite"; : >"$HARNESS_SINK"; echo 100 >"$HARNESS_SEQ_FILE"; }

echo "F1  idle target, submit settles -> CONFIRMED"
reset; export HARNESS_STATUS=idle HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=settled
out="$("$ASSETS/herdr-say" --kind info idleagent "f1 body" 2>&1)"; rc=$?
read -r st dp at <<<"$(msg_state)"; echo "  rc=$rc state=$st/$dp/$at delivered=$(sink_count 'f1 body')"
[[ $rc -eq 0 && "$st" == completed && "$dp" == direct ]] && ok "confirmed+completed" || bad "F1 rc=$rc $st/$dp"
[[ "$(sink_count 'f1 body')" -eq 1 ]] && ok "delivered exactly once" || bad "F1 delivery"

echo "F2  idle target, turn starts but times out (not settled) -> CONFIRMED"
reset; export HARNESS_STATUS=idle HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=timeout
out="$("$ASSETS/herdr-say" --kind info idleagent "f2 body" 2>&1)"; rc=$?
read -r st dp at <<<"$(msg_state)"; echo "  rc=$rc state=$st/$dp/$at delivered=$(sink_count 'f2 body')"
[[ $rc -eq 0 && "$dp" == direct ]] && ok "confirmed via timeout (turn started)" || bad "F2 rc=$rc $st/$dp"
[[ "$(sink_count 'f2 body')" -eq 1 ]] && ok "delivered exactly once (no dup)" || bad "F2 delivery"

echo "F3  idle target, submit SWALLOWED (stalled) -> UNCONFIRMED, retryable, never false-confirm"
reset; export HARNESS_STATUS=idle HARNESS_SUBMIT=no HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=stalled
out="$("$ASSETS/herdr-say" --kind info idleagent "f3 body" 2>&1)"; rc=$?
read -r st dp at <<<"$(msg_state)"; echo "  rc=$rc state=$st/$dp/$at delivered=$(sink_count 'f3 body') items=$(inbox_items)"
[[ $rc -eq 75 ]] && ok "unconfirmed (rc75)" || bad "F3 rc=$rc"
[[ "$st" == pending && "$dp" == deferred ]] && ok "stays pending+deferred" || bad "F3 $st/$dp"
[[ "$(inbox_items)" -ge 1 ]] && ok "item retained for retry" || bad "F3 item"
[[ "$(sink_count 'f3 body')" -eq 0 ]] && ok "never delivered, never false-confirmed" || bad "F3 phantom delivery"

echo "F4  WORKING target -> DEFER (no fire), then idle drain delivers ONCE (no dup, no loss)"
reset; export HARNESS_STATUS=working HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=timeout
out="$("$ASSETS/herdr-say" --kind info busyagent "f4 body" 2>&1)"; rc=$?
read -r st dp at <<<"$(msg_state)"; echo "  say(working) rc=$rc state=$st/$dp/$at delivered=$(sink_count 'f4 body') items=$(inbox_items)"
[[ "$(sink_count 'f4 body')" -eq 0 ]] && ok "did NOT fire into working target" || bad "F4 fired into busy"
[[ "$st" == pending && "$dp" == deferred ]] && ok "held pending+deferred" || bad "F4 $st/$dp"
[[ "$at" -eq 0 ]] && ok "no attempt burned on defer" || bad "F4 attempts=$at"
[[ "$(inbox_items)" -ge 1 ]] && ok "item retained" || bad "F4 item lost"
# drain while still working -> still defers
export HARNESS_STATUS=working; "$ASSETS/herdr-drain" busyagent >/dev/null 2>&1
[[ "$(sink_count 'f4 body')" -eq 0 ]] && ok "drain also defers while busy" || bad "F4 drain fired busy"
# target goes idle -> drain delivers exactly once
export HARNESS_STATUS=idle HARNESS_SUBMIT=yes HARNESS_OUTCOME=settled
"$ASSETS/herdr-drain" busyagent >/dev/null 2>&1
read -r st dp at <<<"$(msg_state)"; echo "  drain(idle) state=$st/$dp/$at delivered=$(sink_count 'f4 body')"
[[ "$(sink_count 'f4 body')" -eq 1 ]] && ok "delivered EXACTLY once when idle (no dup)" || bad "F4 dup/loss: $(sink_count 'f4 body')"
[[ "$st" == completed && "$dp" == direct ]] && ok "completed cleanly" || bad "F4 final $st/$dp"

echo "F5  anti-RC3: WORKING + unrelated seq churn -> NEVER false-confirm direct"
reset; export HARNESS_STATUS=working HARNESS_SUBMIT=no HARNESS_SEQ_DELTA=5 HARNESS_OUTCOME=timeout
out="$("$ASSETS/herdr-say" --kind info busyagent "f5 body" 2>&1)"; rc=$?
read -r st dp at <<<"$(msg_state)"; echo "  rc=$rc state=$st/$dp/$at delivered=$(sink_count 'f5 body') items=$(inbox_items)"
[[ "$dp" != direct ]] && ok "not falsely confirmed direct despite seq churn" || bad "F5 FALSE POSITIVE"
[[ "$(sink_count 'f5 body')" -eq 0 ]] && ok "not delivered (would be stuck), item kept" || bad "F5"
[[ "$(inbox_items)" -ge 1 ]] && ok "item retained (not lost)" || bad "F5 item lost"

echo "F6  anti-RC1: settled confirmation reads agent_status, not a phantom 'state' field"
reset; export HARNESS_STATUS=idle HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=settled
out="$("$ASSETS/herdr-say" --kind info idleagent "f6 body" 2>&1)"; rc=$?
[[ $rc -eq 0 ]] && ok "settled idle confirms via agent_status (RC1 matcher fixed)" || bad "F6 rc=$rc"

echo "======================  pass=$pass fail=$fail  ======================"
[[ $fail -eq 0 ]]
