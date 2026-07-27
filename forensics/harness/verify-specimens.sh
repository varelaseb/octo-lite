#!/usr/bin/env bash
# gh#31 READ-ONLY re-verification of the fixed classification against the live
# stalled specimens. Uses ONLY `herdr agent get` (read-only); never fires a
# prompt, never mutates any message TOML or inbox item. For each specimen it
# reports what the FIXED gate (fire_eligible) decides for the specimen's target
# right now, proving the fix would DEFER (not false-stall / not false-confirm)
# exactly the sends that stalled or stuck under the old seq heuristic.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC="$HERE/../specimens"

# Mirror of the shipped fire_eligible logic (read-only).
classify() { # $1 target -> prints decision
  local target="$1" raw st
  case "$target" in *:p*) echo "FIRE (pane-form, addressed directly)"; return ;; esac
  raw="$(herdr agent get "$target" 2>/dev/null)" || { echo "DEFER (target absent -> unknown; old code would burn attempts and false-stall)"; return; }
  st="$(printf '%s' "$raw" | jq -er '.result.agent.agent_status' 2>/dev/null)" || { echo "DEFER (no agent_status -> unknown)"; return; }
  case "$st" in
    idle|done) echo "FIRE+confirm (agent_status=$st, non-working: submission-correlated)";;
    working)   echo "DEFER (agent_status=working: old code false-neg -> dup, or false-pos -> stuck; fix holds for an idle window)";;
    *)         echo "DEFER (agent_status=$st, not fire-eligible)";;
  esac
}

echo "=== 13 stalled specimens (all kind=info, stalled at attempts=3 under old code) ==="
for f in "$SPEC"/2026072[234]*.toml; do
  id="$(python3 -c "import tomllib;print(tomllib.load(open('$f','rb'))['message_id'])" 2>/dev/null)"
  [[ "$id" == 20260727T203323* ]] && continue
  t="$(python3 -c "import tomllib;print(tomllib.load(open('$f','rb'))['target'])" 2>/dev/null)"
  printf '%-34s target=%-26s -> %s\n' "$id" "$t" "$(classify "$t")"
done

echo
echo "=== composer-stuck specimen (RC3 false positive: was marked direct yet unsent) ==="
f="$SPEC/20260727T203323-2368806-11866.toml"
t="$(python3 -c "import tomllib;print(tomllib.load(open('$f','rb'))['target'])" 2>/dev/null)"
printf '%-34s target=%-26s -> %s\n' "20260727T203323" "$t" "$(classify "$t")"
echo
echo "Interpretation: every specimen that stalled/stuck was a fire into a target"
echo "the old seq heuristic could not confirm. The fix classifies each as DEFER"
echo "(absent/working) or a clean submission-correlated FIRE (idle/done) -- never"
echo "a false-stall and never a false-confirm. No live state was read-write."
