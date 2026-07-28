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

## Spawn

Only persistent Fable and Opus orchestrators get Herdr tabs. Workflow workers
run inside the owning Opus session.

Always use `herdr-spawn`. Before any pane exists, it runs a read-only print-mode
bootstrap itself and verifies the full BOOTSTRAP_ACK; the child never runs
bootstrap-ack or mutates the receipt. Only the exact verified provider session is
then resumed into the persistent pane. It creates one pane, passes exact cwd,
handles the trusted-folder prompt, and enforces exact Claude model and auto mode
for operator and orchestrator roles.

Labels:

```text
🧠 operator
[🎤] [◆]issue[/pr] · outcome
```

`◆` marks epic Opus. Normal issues have no marker. `🎤` appears only during a
direct investigation, grill, diagnosis, or decision that needs the operator.
Fable removes it as soon as the Opus can work autonomously. No worker tabs.

Remote control: every `🎤` or `🧠` session must have Claude remote control
enabled durably at launch through the launcher (`claude --rc` flag or a
`remoteControlAtStartup` settings injection), never post-hoc. `herdr-spawn`
fails closed on a `🎤` or `🧠` spawn without it. Flipping `🎤` on is a Fable
duty that requires ensuring remote control is active on that session.
