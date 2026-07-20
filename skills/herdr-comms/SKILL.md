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

Never hand-run raw send plus Enter. `herdr-say` reads the pane only to detect a
modal, never to infer composer state, consumption, or delivery. At a safe
prompt it pastes and presses Enter, leaving the message pending. At a modal it
queues immediately and returns 75. Queued and pending are not acknowledged or
completed.

On every wake, run `herdr-drain <own-agent-name>`. It retries transport only
when the prompt is safe, and for a pending message it only presses Enter,
never re-pastes text that already landed.

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
