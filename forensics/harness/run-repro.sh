#!/usr/bin/env bash
# gh#31 reproduction harness: proves the herdr transport confirmation is
# unsound in BOTH directions, using a stub herdr that decouples REAL delivery
# from the confirmation signal the wrapper reads. No live state touched:
# a private XDG_STATE_HOME under a temp dir.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ASSETS="$(cd "$HERE/../../skills/herdr-comms/assets" && pwd)"
export PATH="$HERE:$PATH"   # stub herdr wins

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export XDG_STATE_HOME="$TMP/state"
export HOME="$TMP/home"     # keep any HOME-derived path off the real tree
mkdir -p "$XDG_STATE_HOME" "$HOME"

export HARNESS_SEQ_FILE="$TMP/seq"
export HARNESS_SINK="$TMP/delivered"   # real submissions land here
: >"$HARNESS_SINK"

pass=0; fail=0
ok()   { echo "  PASS: $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $1"; fail=$((fail+1)); }

sink_count() { grep -c "$1" "$HARNESS_SINK" 2>/dev/null || true; }
msg_state() { python3 -c "import tomllib,glob,sys;
fs=sorted(glob.glob('$XDG_STATE_HOME/octo-lite/messages/*.toml'));
d=tomllib.load(open(fs[-1],'rb'));
print(d.get('status',''),d.get('delivery_path',''),d.get('transport_attempts',0))" 2>/dev/null
}
inbox_items() { find "$XDG_STATE_HOME/octo-lite/inbox" -type f 2>/dev/null | grep -Ec '[0-9]{8}T' || true; }

reset() { rm -rf "$XDG_STATE_HOME/octo-lite"; : >"$HARNESS_SINK"; echo 100 >"$HARNESS_SEQ_FILE"; }

echo "=============================================================="
echo "SCENARIO 1  RC2 FALSE NEGATIVE: busy target, message SUBMITTED,"
echo "            global seq unchanged -> wrapper reports UNCONFIRMED"
echo "            though delivered; retry re-delivers => DUPLICATE."
echo "=============================================================="
reset
export HARNESS_STATUS=working HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=timeout
out="$("$ASSETS/herdr-say" --kind info busyagent "hello busy" 2>&1)"; rc=$?
echo "  say rc=$rc :: $out"
read -r st dp at <<<"$(msg_state)"
echo "  state: status=$st path=$dp attempts=$at ; delivered_copies=$(sink_count 'hello busy') ; inbox_items=$(inbox_items)"
[[ $rc -eq 75 ]] && ok "say exits 75 (unconfirmed)" || bad "expected rc 75"
[[ "$(sink_count 'hello busy')" -ge 1 ]] && ok "message WAS actually delivered (stub sink)" || bad "not delivered"
[[ "$st" == "pending" && "$dp" == "deferred" ]] && ok "stays pending+deferred (will retry a delivered msg)" || bad "unexpected state $st/$dp"
[[ "$(inbox_items)" -ge 1 ]] && ok "inbox item RETAINED -> drain WILL re-fire" || bad "item not retained"
# drain re-fire = second real delivery = duplicate
"$ASSETS/herdr-drain" busyagent >/dev/null 2>&1
echo "  after drain: delivered_copies=$(sink_count 'hello busy') attempts=$(msg_state | awk '{print $3}')"
[[ "$(sink_count 'hello busy')" -ge 2 ]] && ok "DUPLICATE proven: same body delivered >=2x" || bad "no duplicate"

echo
echo "=============================================================="
echo "SCENARIO 2  RC3 FALSE POSITIVE: busy target, message NOT"
echo "            submitted (stuck in composer), but global seq flips"
echo "            for an UNRELATED reason -> wrapper reports CONFIRMED"
echo "            direct, removes the item. Message lost; operator must"
echo "            hand-submit. (matches live specimen 203323: path=direct"
echo "            attempts=1 yet stuck unsubmitted.)"
echo "=============================================================="
reset
export HARNESS_STATUS=working HARNESS_SUBMIT=no HARNESS_SEQ_DELTA=1 HARNESS_OUTCOME=timeout
out="$("$ASSETS/herdr-say" --kind info busyagent "phantom confirmed" 2>&1)"; rc=$?
echo "  say rc=$rc :: $out"
read -r st dp at <<<"$(msg_state)"
echo "  state: status=$st path=$dp attempts=$at ; delivered_copies=$(sink_count 'phantom confirmed') ; inbox_items=$(inbox_items)"
[[ $rc -eq 0 ]] && ok "say exits 0 (claims delivered)" || bad "expected rc 0"
[[ "$dp" == "direct" ]] && ok "delivery_path=direct (FALSE confirmation)" || bad "path not direct: $dp"
[[ "$(sink_count 'phantom confirmed')" -eq 0 ]] && ok "message was NEVER actually submitted" || bad "unexpectedly delivered"
[[ "$(inbox_items)" -eq 0 ]] && ok "inbox item REMOVED -> NO retry, message lost" || bad "item still present"

echo
echo "=============================================================="
echo "SCENARIO 3  RC1 DEAD MATCHER: target settles to idle and the"
echo "            message is delivered, but wrapper still reports"
echo "            UNCONFIRMED because it greps \"state\" while herdr"
echo "            0.7.5 emits \"agent_status\"."
echo "=============================================================="
reset
# settle to idle, delivered, but seq does NOT advance so ONLY the matched-state
# path could confirm. It can't, because the field name is agent_status.
export HARNESS_STATUS=idle HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=settled
out="$("$ASSETS/herdr-say" --kind info idleagent "settled but missed" 2>&1)"; rc=$?
echo "  say rc=$rc :: $out"
read -r st dp at <<<"$(msg_state)"
echo "  state: status=$st path=$dp ; delivered_copies=$(sink_count 'settled but missed')"
[[ $rc -eq 75 ]] && ok "say exits 75 despite a settled idle delivery (matcher blind)" || bad "expected rc 75"
[[ "$(sink_count 'settled but missed')" -ge 1 ]] && ok "message WAS delivered + target settled idle" || bad "not delivered"
# demonstrate the fix-shaped matcher WOULD have matched agent_status:
if HARNESS_STATUS=idle HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=0 HARNESS_OUTCOME=settled \
   herdr agent prompt w0:pX body --wait --timeout 15000 2>&1 \
   | grep -qE '"agent_status"[[:space:]]*:[[:space:]]*"(idle|done|blocked)"'; then
  ok "herdr output DOES carry agent_status:idle (a correct matcher would confirm)"
else
  bad "agent_status not present"
fi

echo
echo "=============================================================="
echo "SCENARIO 4  CONTROL: idle target, delivered, seq advances ->"
echo "            wrapper correctly confirms (harness fidelity check)."
echo "=============================================================="
reset
export HARNESS_STATUS=idle HARNESS_SUBMIT=yes HARNESS_SEQ_DELTA=1 HARNESS_OUTCOME=settled
out="$("$ASSETS/herdr-say" --kind info idleagent "clean success" 2>&1)"; rc=$?
echo "  say rc=$rc :: $out"
read -r st dp at <<<"$(msg_state)"
echo "  state: status=$st path=$dp ; delivered_copies=$(sink_count 'clean success')"
[[ $rc -eq 0 && "$st" == "completed" && "$dp" == "direct" ]] && ok "confirmed+completed as expected" || bad "control failed $rc $st $dp"

echo
echo "=============================================================="
echo "RESULT: pass=$pass fail=$fail"
echo "=============================================================="
[[ $fail -eq 0 ]]
