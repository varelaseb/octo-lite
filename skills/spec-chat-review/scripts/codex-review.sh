#!/bin/sh
# Codex attachment for the spec-chat review loop.
# Codex spends ~40k+ tokens per drain cycle, so the watch runs OUTSIDE the
# Codex session (free) and invokes `codex exec` only when a batch actually
# arrives. Resumes the recorded review thread when review/state.json has one;
# after a cold exec it captures the new thread id so later batches can resume.
# A directory target is the default: one process discovers and serially drains
# every reviewable *.html spool below it. A file target remains available for
# deliberate single-page narrowing.
# usage: codex-review.sh [--once] REVIEW_ROOT_OR_HTML_PATH
set -eu

ONCE=0
if [ "${1:-}" = "--once" ]; then
  ONCE=1
  shift
fi
[ "$#" -eq 1 ] || {
  echo "usage: codex-review.sh [--once] REVIEW_ROOT_OR_HTML_PATH" >&2
  exit 2
}

TARGET=$1
SKILL_DIR=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
CURSOR_NAME=.cursor-codex

if [ -d "$TARGET" ]; then
  MODE=tree
  ROOT=$(CDPATH= cd "$TARGET" && pwd)
  echo "codex-review: watching every reviewable HTML page below $ROOT"
elif [ -f "$TARGET" ]; then
  MODE=single
  SPEC_DIR=$(CDPATH= cd "$(dirname "$TARGET")" && pwd)
  SPEC="$SPEC_DIR/$(basename "$TARGET")"
  REVIEW="$SPEC.review"
  CURSOR="$REVIEW/$CURSOR_NAME"
  mkdir -p "$REVIEW/human" "$REVIEW/agent"
  [ -f "$CURSOR" ] || : > "$CURSOR"
  echo "codex-review: watching only $REVIEW"
else
  echo "codex-review: no such review root or HTML file: $TARGET" >&2
  exit 2
fi

command -v codex >/dev/null 2>&1 || {
  echo "codex-review: codex CLI not found" >&2
  exit 2
}
command -v jq >/dev/null 2>&1 || {
  echo "codex-review: jq is required for session and ownership state" >&2
  exit 2
}

echo "codex-review: detached mode; this will not wake or stream activity into the authoring chat" >&2

LEASE_SECONDS=${SPEC_CHAT_LEASE_SECONDS:-3600}
LEASE_ACTIVE=0

claim_lease() {
  exec 9>"$REVIEW/.state.lock"
  if ! flock -n 9; then
    echo "codex-review: another detached owner holds $REVIEW" >&2
    return 75
  fi
  NOW=$(date +%s)
  OWNER=""
  OWNER_PID=""
  LEASE_UNTIL=0
  if [ -s "$STATE" ] && jq empty "$STATE" >/dev/null 2>&1; then
    OWNER=$(jq -r '.ownerKind // empty' "$STATE")
    OWNER_PID=$(jq -r '.pid // empty' "$STATE")
    LEASE_UNTIL=$(jq -r '.leaseUntil // 0' "$STATE")
  fi
  if [ "$OWNER" = interactive ] && [ "$LEASE_UNTIL" -gt "$NOW" ] \
    && [ -n "$OWNER_PID" ] && kill -0 "$OWNER_PID" 2>/dev/null; then
    echo "codex-review: interactive owner holds $REVIEW until $LEASE_UNTIL" >&2
    flock -u 9
    return 75
  fi
  STATE_TMP="$STATE.tmp.$$"
  HEARTBEAT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  NEXT_LEASE=$((NOW + LEASE_SECONDS))
  if [ -s "$STATE" ] && jq empty "$STATE" >/dev/null 2>&1; then
    jq --argjson pid "$$" --argjson lease "$NEXT_LEASE" --arg heartbeat "$HEARTBEAT" \
      '. + {ownerKind:"detached", pid:$pid, leaseUntil:$lease, heartbeatAt:$heartbeat}' \
      "$STATE" > "$STATE_TMP"
  else
    jq -n --argjson pid "$$" --argjson lease "$NEXT_LEASE" --arg heartbeat "$HEARTBEAT" \
      '{ownerKind:"detached", pid:$pid, leaseUntil:$lease, heartbeatAt:$heartbeat}' > "$STATE_TMP"
  fi
  mv "$STATE_TMP" "$STATE"
  LEASE_ACTIVE=1
}

release_lease() {
  [ "$LEASE_ACTIVE" -eq 1 ] || return 0
  STATE_TMP="$STATE.tmp.$$"
  if [ -s "$STATE" ] && jq empty "$STATE" >/dev/null 2>&1; then
    jq 'del(.ownerKind, .pid, .leaseUntil, .heartbeatAt)' "$STATE" > "$STATE_TMP"
    mv "$STATE_TMP" "$STATE"
  fi
  LEASE_ACTIVE=0
  flock -u 9
}

trap 'release_lease' EXIT HUP INT TERM

record_session() {
  RECORDED_SID=$1
  [ -n "$RECORDED_SID" ] || return 0
  STATE_TMP="$STATE.tmp.$$"
  UPDATED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  THREAD_NAME=$(basename "$SPEC")
  if [ -s "$STATE" ] && jq empty "$STATE" >/dev/null 2>&1; then
    jq --arg sid "$RECORDED_SID" --arg thread "$THREAD_NAME" --arg updated "$UPDATED_AT" \
      '. + {sessionId:$sid, threadName:$thread, updatedAt:$updated}' \
      "$STATE" > "$STATE_TMP"
  else
    jq -n --arg sid "$RECORDED_SID" --arg thread "$THREAD_NAME" --arg updated "$UPDATED_AT" \
      '{sessionId:$sid, threadName:$thread, updatedAt:$updated}' > "$STATE_TMP"
  fi
  mv "$STATE_TMP" "$STATE"
  echo "codex-review: recorded session $RECORDED_SID for $SPEC"
}

while :; do
  set +e
  if [ "$MODE" = tree ]; then
    READY=$("$SKILL_DIR/scripts/watch-specs.sh" "$ROOT" "$CURSOR_NAME" 3600 3)
    RC=$?
  else
    READY=$("$SKILL_DIR/scripts/watch.sh" "$REVIEW" "$CURSOR" 3600 3)
    RC=$?
  fi
  set -e
  [ "$RC" -eq 3 ] && continue          # quiet timeout, re-park for free
  [ "$RC" -eq 0 ] || exit "$RC"
  [ -z "$READY" ] && continue

  if [ "$MODE" = tree ]; then
    SPEC=$(printf '%s\n' "$READY" | cut -f1 | sed -n '1p')
    NEW=$(printf '%s\n' "$READY" | cut -f2-)
    REVIEW="$SPEC.review"
    CURSOR="$REVIEW/$CURSOR_NAME"
  else
    NEW=$READY
  fi
  STATE="$REVIEW/state.json"
  claim_lease || exit $?
  SID=""
  if [ -f "$STATE" ]; then
    SID=$(jq -r '.sessionId // empty' "$STATE" 2>/dev/null || true)
  fi

  PROMPT="A hand-off batch arrived on $SPEC. Follow $SKILL_DIR/SKILL.md exactly: read the new human events under $REVIEW/human, apply each comment to the spec in the dialect, reply per comment with $SKILL_DIR/scripts/emit-reply.sh, append exactly the watcher-reported filenames below to $CURSOR (never regenerate with ls), and externalize agreements to $REVIEW/context.md. Do ONE drain cycle then stop.

Watcher-reported filenames:
$NEW"
  # --skip-git-repo-check: specs may live outside a git repo (or in a
  # gitignored area); workspace-write sandbox still bounds writes.
  # </dev/null: don't let codex block waiting on the wrapper's stdin.
  if [ -n "$SID" ]; then
    echo "codex-review: resuming session $SID for $SPEC"
    codex exec -s workspace-write --skip-git-repo-check resume "$SID" "$PROMPT" </dev/null
  else
    RUN_JSON=$(mktemp "${TMPDIR:-/tmp}/spec-chat-codex.XXXXXX")
    echo "codex-review: cold dispatch for $SPEC"
    set +e
    codex exec --json -s workspace-write --skip-git-repo-check "$PROMPT" </dev/null > "$RUN_JSON"
    RC=$?
    set -e
    jq -r 'select(.type == "item.completed" and .item.type == "agent_message") | .item.text' "$RUN_JSON"
    jq -r 'select(.type == "item.completed" and .item.type == "error") | .item.message' "$RUN_JSON" >&2
    if [ "$RC" -ne 0 ]; then
      echo "codex-review: cold dispatch failed for $SPEC" >&2
      rm -f "$RUN_JSON"
      exit "$RC"
    fi
    SID=$(jq -r 'select(.type == "thread.started") | .thread_id' "$RUN_JSON" | sed -n '1p')
    record_session "$SID"
    rm -f "$RUN_JSON"
  fi
  release_lease
  [ "$ONCE" -eq 1 ] && exit 0
done
