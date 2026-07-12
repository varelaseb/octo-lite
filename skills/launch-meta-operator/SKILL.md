---
name: launch-meta-operator
description: Launch a persistent operator-level Claude or Codex session in Herdr to inventory active sessions, infer the current workstreams and likely objective, establish durable control state, and ask the user for the smallest missing objective or authority decisions before taking over orchestration. Use when the user explicitly asks to launch a meta-operator, consolidate or drive several Herdr sessions, supervise asynchronous agents, or create an operator that can maintain watchers and handoffs across long-running work.
---

# Launch Meta-Operator

Create a new interactive Herdr session whose first job is a read-only inventory,
not immediate execution. The spawned session owns the operator role after the
user confirms its objective and authority.

Only launch on an explicit user request. Do not silently turn ordinary work into
a background orchestration session.

## Choose the Runtime

- Always use `claude` (operator directive 2026-07-12): meta-operators run on
  Fable only — the launcher pins Fable at xhigh effort and uses
  `--permission-mode auto`. Sol/Codex is a poor meta-orchestrator; do not
  launch a `codex` meta-operator even if a Codex session is the caller.
- The `codex` runtime remains in the launcher only as an explicit operator
  override; it inherits the user's configured model and launches with
  `--yolo`.
- Treat these permissive runtime modes as execution plumbing, not expanded
  authority. The child still performs a read-only bootstrap and preserves every
  operator gate in its prompt.

## Launch

1. Verify `herdr status` reports a compatible running server.
2. Prepare a compact caller handoff containing only explicit objectives,
   authority, terminology, and constraints already supplied by the user. Do not
   preload summaries of every session; the new operator must inspect live state
   itself.
3. Resolve this skill's installed directory and run:

```bash
scripts/launch-meta-operator.sh \
  --runtime claude \
  --cwd "$PWD" \
  --handoff "<compact caller handoff>"
```

Useful overrides:

```bash
scripts/launch-meta-operator.sh --objective "<known starting objective>"
scripts/launch-meta-operator.sh --workspace w1 --name meta-operator-launch
scripts/launch-meta-operator.sh --dry-run --runtime claude
```

The launcher creates private durable state under
`${XDG_STATE_HOME:-$HOME/.local/state}/octo-lite/meta-operators/<name>/`, starts
the agent, and moves it into a role-named Herdr tab. Use `--state-root` to
override that location.

## Verify the Handoff

After launch:

1. Run `herdr agent get <name>` and read a bounded amount of recent output.
2. Confirm the reported runtime, pane, tab, and control-state path.
3. If the runtime presents a workspace-trust or permission prompt, approve it
   only when the user has established that the directory is trusted; otherwise
   ask the user.
4. Wait until the new operator begins its inventory or surfaces a real blocker.
5. Tell the user where the operator is running. Do not duplicate its
   orchestration in the caller session unless the user deliberately assigns
   shared responsibility.

The operator prompt is bundled at `assets/meta-operator-prompt.md` and composed
by the launcher. Do not paste a second copy into the child session.

## Failure Handling

- If Herdr is unavailable, stop and report that persistent operator launch is
  unavailable. Do not substitute an ordinary ephemeral subagent while claiming
  equivalent supervision.
- If the child exits or blocks before inventory, report the exact pane state and
  repair or relaunch only after diagnosing the cause.
- Never claim the child will wake or supervise future work until its selected
  persistence path is verified.
