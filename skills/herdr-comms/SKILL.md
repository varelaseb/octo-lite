---
name: herdr-comms
description: Modal-safe Herdr delivery, acknowledgments, queue drain, owner routing, and persistent-session spawn.
---

# Herdr communications

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

## Install

Symlink every executable in `assets/` into `~/.local/bin`. Never copy it.

## Send

Always use:

```sh
herdr-say [--kind info|command|ruling|ownership|question] \
  [--artifact REF] TARGET MESSAGE
```

Never hand-run raw transport. `herdr-say` fires one atomic agent prompt,
paste plus submit in one server-owned op, leaving the message pending.
Multi-line bodies round-trip literally; the TUR-485 single-line discipline is
retired. `herdr-say` reads the pane only to detect a modal, never to infer
composer state, consumption, or delivery. Modal-safe: an open dialog defers,
queues immediately, returns 75, never force-submits.
Queued and pending are not acknowledged or completed.
Put indispensable artifact paths in the message body as well as `--artifact`.
Send concise deltas and pointers; summarize large logs locally before returning
bounded excerpts. Do not reread or replay an unchanged fleet inventory.

Delivery confirmation is per-message and submission-correlated, never the exit
code and never a global counter (gh#31: the old `state_change_seq` heuristic
both false-confirmed a stuck-in-composer send on unrelated churn and
false-failed a delivered send into a busy pane). A send FIRES ONLY into a
NON-WORKING target (`agent_status` idle or done); a working, blocked, or
unreadable target DEFERS with no fire and no attempt burn, held for a later
`herdr-drain` when the target idles. From that gated non-working start the
prompt's OWN outcome is the proof: `agent_prompt_stalled` is a swallow
(unconfirmed, retry); a settled `agent_status` idle|done|blocked, or a timeout
meaning the turn started but has not settled, is delivered. Every fire runs
`agent prompt --wait --timeout` with `OCTO_PROMPT_CONFIRM_TIMEOUT_MS`
milliseconds (default 15000, invalid falls back to the default with a warning).
An unconfirmed outcome keeps the message pending with its retry item for
`herdr-drain`, under the attempt cap.

Transport class: bounded duplicate-prone transport with no delivery
guarantee. A message may arrive zero times, once, or up to the retry cap per
epoch. Every transported body carries `[msg:<id>]`, info included, so
duplicates are id-correlated. Only herdr-ack proves delivery; a
confirmed info submit completes on its own.

On every wake, run `herdr-drain <own-agent-name>`. It fires only into a
non-working target, and a pending retry re-fires the same atomic prompt with
the same message id, which never double-submits partially-pasted text. Because
a target cannot deliver to itself while it is working, the operator sweep runs
`herdr-drain --all` each cycle to deliver every target's deferred inbox on its
behalf, then ages any still-stuck message. Concurrent sends to one target are
serialized by a non-blocking per-target lock (`locks/target-<target>.lock`) so
a loser defers rather than racing the idle window. Retries are capped by
`OCTO_TRANSPORT_ATTEMPT_CAP` (default 3, per epoch): at the cap the message
goes stalled. A busy target defers, but the sweep stalls any retryable message
older than `OCTO_TRANSPORT_DEFER_MAX_AGE_S` (default 900s), so a stuck message
is surfaced within about the threshold plus one sweep interval (a further
interval only on momentary lock contention), always bounded, never unseen. A
stalled message never auto-fires again and the sweep surfaces it loudly every
cycle. `herdr-drain --resume <id>`
starts a new epoch (stalled to pending, attempts reset to 0). State reads, attempt
increments, and fires all run under the permanent per-message flock
`locks/<id>.lock`; nothing ever unlinks a lock. Reclamation is runbook-only:
`docs/runbooks/herdr-comms-lock-reclamation.md`.

Commands, rulings, ownership transfers, and blocking questions require:

```sh
herdr-ack MESSAGE_ID acknowledged --by OWN_AGENT_NAME
```

Dependent action waits for acknowledgment. No arbitrary timer converts silence
to rejection. Completion requires the named artifact or outcome:

```sh
herdr-ack MESSAGE_ID completed --by OWN_AGENT_NAME --artifact REF
```

Use `operator-say` for messages to the current Fable owner. It resolves
`operator-owner.toml` at send time, so an atomic handoff changes the next route.

On each owner wake or result check, make one bounded drain pass for its own
route and relevant owned workers; a working agent cannot wake itself. When its
own drain cannot fire, the active recipient reads pending command/ruling bodies
for its own route from the durable inbox/message records, acknowledges the same
IDs before dependent action, and consumes them without a second transport fire.
This is recipient consumption, never acknowledgment by a parent on its behalf.
Scope
manual drains to owned routes; the existing whole-fleet sweep keeps its bounds.
Read per-message state before retrying or acknowledging. Completed messages do
not transition back to acknowledged; duplicates do not repeat side effects.
Verify changed scope was acknowledged and completion has the named result,
then integrate/advance before optional reporting. Stalled required work is an
owner action: inspect the cause and resume the same message when resolved,
within transport bounds. Stop polling after a terminal outcome is consumed.

If modal detection disagrees with the visible pane, inspect once. A confirmed
false match in ordinary transcript text may be cleared by a display-only
refresh, then drained normally. Never force-submit through a real dialog or
infer consumption from display text. A missing tool/slash command requires a
supported equivalent and verified task start, not repeated identical dispatch.

## Spawn

Persistent issue orchestrators and temporary `implement-spec` workers get Herdr
tabs. Receipt-bound Claude launch rules apply to legacy role launches. Explicit
operator-selected direct Codex orchestrators keep the chosen runtime. Temporary
worker roles are `explorer`, `implementer`, `merger`, and `reviewer`. Close
their tabs after their commits or notes are safely integrated.

The orchestrator starts one Codex `/goal` for the user outcome and done
condition. A temporary worker starts one narrow goal for its ticket. Goals are
the continuation signal, not a second tracker: Linear owns issue state, the
spec owns behavior, and the brief/status owns pointers and current facts.

Launch orchestrators and their workers from the operator's current Herdr
session and workspace. Herdr manages session routing. Use the configured Codex
CLI default model unless the operator explicitly selects another runtime. Give
the agent one concise context pointer and verify one task acknowledgment. Do
not mark a goal blocked for a normal human gate or one transient failure.

Prefer `herdr-spawn`. Inspect help once when the invocation is unknown or changed.
It creates one pane, passes exact cwd, handles a trusted-folder prompt, and
fails closed on unsupported runtime settings.

Exception: when a wrapper rejects an already running server and the operator
has authorized native Herdr fallback, reuse that fallback for the same scope;
do not ask each lane again, retry the known preflight, switch model/provider,
or repair/restart shared runtime. Record the verified invocation in the existing
brief with session/workspace, model/effort/tier, cwd and evidence. Recheck only
missing or changed facts. Existing target-owned scoped access commands and
secure credential paths follow the same rule: an identity-specific denial is
not proof no authorized path exists, and successful read access is not a grant
of broader write authority. Never change global auth to reuse scoped access.

Native shape, only within that authorization:

```sh
herdr --session SESSION tab create --workspace WORKSPACE --label LABEL \
  --cwd WORKTREE --no-focus
herdr --session SESSION agent start NAME --kind codex --pane CREATED_PANE -- \
  --ask-for-approval APPROVAL \
  --sandbox SANDBOX --cd WORKTREE
```

Use returned IDs and exact authorized settings; do not add a second `codex`
after `--`. Verify the returned tab is in the current session/workspace and the
task acknowledgment once. A self-prompt is not delegation. Reuse an existing
worker for retry; a new session is not the default recovery. A real trust dialog
must be handled explicitly before normal queued delivery.

For a direct Codex `implement-spec` worker, use no receipt:

```sh
herdr-spawn --workspace WORKSPACE --name NAME --label LABEL --cwd WORKTREE \
  --role ROLE --direct -- \
  codex --ask-for-approval never --sandbox danger-full-access
```

Direct Codex launch enables the shared Codex Remote Control app-server before
creating a Herdr tab. A Remote Control failure creates no tab. Direct mode uses
no receipt, bootstrap, role resolver, generated adapter, or external control
plane. `ROLE` is `orchestrator`, `explorer`, `implementer`, `merger`, or
`reviewer`.

Legacy Claude launches keep the receipt-backed verified bootstrap. Before any
pane exists, `herdr-spawn` verifies the full BOOTSTRAP_ACK and resumes only the
exact verified provider session.

Labels:

```text
🧠 operator
[🎤] [◆]issue[/pr] · outcome
```

`◆` marks an epic orchestrator. Temporary workers use the ticket key in the
label. `🎤` appears only
during a direct investigation, diagnosis, or decision that needs the operator.
Remove it as soon as the agent can work autonomously.

Remote control: direct Codex launch enables the shared Codex Remote Control
app-server for every session. Legacy Claude `🎤` or `🧠` sessions must enable
Claude remote control durably at launch through `claude --rc` or a
`remoteControlAtStartup` settings injection. `herdr-spawn` fails closed when
the required Remote Control surface cannot be enabled.
