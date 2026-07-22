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

Delivery confirmation is observed state, never the exit code: a prompt can
return rc 0 without submitting when the composer holds residual text. Every
fire runs `agent prompt --wait --timeout` with
`OCTO_PROMPT_CONFIRM_TIMEOUT_MS` milliseconds (default 15000, invalid falls
back to the default with a warning); only a matched post-submission state
(idle, done, blocked) confirms. `agent_prompt_stalled`, a timeout, a nonzero
rc, or any unmatched outcome is unconfirmed: the message stays pending with
its retry item for `herdr-drain`, under the attempt cap.

Transport class: bounded duplicate-prone transport with no delivery
guarantee. A message may arrive zero times, once, or up to the retry cap per
epoch. Every transported body carries `[msg:<id>]`, info included, so
duplicates are id-correlated. Only herdr-ack proves delivery; an
observed-state-confirmed info submit completes on its own.

On every wake, run `herdr-drain <own-agent-name>`. It fires only when the
prompt is safe, and a pending retry re-fires the same atomic prompt with the
same message id, which never double-submits partially-pasted text. Retries
are capped by `OCTO_TRANSPORT_ATTEMPT_CAP` (default 3, per epoch): at the cap
the message goes stalled, never auto-fires again, and the operator sweep
surfaces it loudly every cycle. `herdr-drain --resume <id>` starts a new
epoch (stalled to pending, attempts reset to 0). State reads, attempt
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
