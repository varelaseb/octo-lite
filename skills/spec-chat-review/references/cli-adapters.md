# CLI adapters - how the review loop attaches per agent

The loop protocol (park → drain → apply → reply → re-park) is identical everywhere; only *how the watch is hosted* differs. The invariant: the review loop runs in the user's open authoring thread whenever possible, because the spec was born there and that context is what makes annotations addressable.

## Claude Code (primary)

One collection watch runs **in-session as a background task** - Claude Code forbids foreground sleep loops, and backgrounding keeps the session interactive. The harness re-invokes the agent when `watch-specs.sh` exits. Continuity is native; nothing extra to install. A page-specific `watch.sh` process is an explicit narrowing mode, not the default.

## Codex

Two attachment classes exist; the host determines which user experience is possible:

- **Active interactive window**: first reconcile with `watch-specs.sh <spec-root> .cursor-codex-session 0 3`, draining and cursoring each ready result until the scan exits 3. Then run a fresh bounded watcher through Codex's yielded tool-call wait and keep the authoring turn open. The yielded cell remains completely silent while the watcher is parked-no heartbeat output and no periodic chat/tool wakeups. Wait until the watcher exits with a real batch; that completion re-invokes the same root agent, which then emits visible activity, drains the batch, reconciles any additional backlog, and silently re-parks. This preserves full shared chat context, but the host may continue to show the turn as “working”; use it only while the human explicitly wants an active review window.
- **Idle same-thread reactivation (preferred for long waits)**: use a host-native event trigger or scheduled work attached to the current task. It must return to the existing task, not create standalone runs. This lets the turn look finished while idle and later restores shared context. Availability and cadence are host capabilities; when the current Codex surface does not expose them, report that constraint rather than substituting a shell watcher.

### Interrupted-turn recovery

Pressing Stop severs Codex's continuation from the originating interactive turn. The cancelled watcher may exit or briefly survive, but neither its output nor a returned tool-session id can reliably wake the stopped thread. The thread cannot wake itself; the user must send one new message.

Treat that message as a reconnect signal. Do not resume or depend on the cancelled watcher/tool session. Instead:

1. Run `watch-specs.sh <spec-root> .cursor-codex-session 0 3`.
2. On exit 0, process the printed filenames in order, emit every required reply, externalize durable context, and only then append exactly those filenames to that page's cursor.
3. Repeat the zero-wait scan until it exits 3. A failed or partial drain leaves the cursor unchanged, so the next reconnect sees the same batch.
4. If review mode remains active, start a fresh interactive watcher. Never reuse the cancelled one.

This recovery is lossless because human event files are durable and `watch-specs.sh` never advances cursors. The new user message supplies reactivation; backlog reconciliation supplies automatic recovery.

Where the ChatGPT/Codex surface exposes scheduled work attached to the current task, a minute-based same-task heartbeat is the context-preserving long-idle host. Prefer the yielded watcher only for a deliberately active, low-latency review window; use a same-task schedule for coarse background monitoring, never a standalone scheduled task.

Detached review is unsupported because it cannot wake the original thread and can race an interactive owner.

## pi.dev

Watch runs in-session via a pi extension when that host supports same-thread reactivation.

**Status: documented, not live-verified (by decision, 2026-07-05).** The loop is pure file I/O, transport-agnostic, and validated end-to-end on two independent CLIs (Claude Code in-session, Codex via wrapper); pi would run the identical `watch-specs.sh` / `emit-reply.sh` / spec-edit flow. Not tested live because pi/omp are BYOK - separate inference billing that cuts against the Pro-account-inference model. Revisit if pi becomes the primary driver.

## Session continuity (all CLIs)

Files are the contract; session resume is an optimization. Every drain cycle externalizes durable agreements - into the spec and `review/context.md` - so a different session, or a different CLI, can resume cold. Long-lived threads should rotate (checkpoint to files, start fresh) after enough batches, because a resumed session grows until compaction makes the preserved context probabilistic. Resume buys latency and nuance; it is never durable memory.
