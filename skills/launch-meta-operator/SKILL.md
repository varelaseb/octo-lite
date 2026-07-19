---
name: launch-meta-operator
description: Launch exact Fable as the persistent octo-lite operator with durable control and atomic handoff support.
---

# Launch meta-operator

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use only on explicit operator request.

Run `scripts/launch-meta-operator.sh`. It:

- resolves `meta-operator` through `roles.toml`
- pins exact `claude-fable-5`, xhigh, auto mode, no fallback
- writes one parent brief, child status, TOML receipt, and owner TOML
- injects remote access facts from turn one
- launches through `herdr-spawn` as `🧠 operator`
- requires bootstrap acknowledgment before mutation
- installs one lifecycle-bound host timer that only sends `operator-say sweep`

On each `sweep` wake, Fable runs `operator-sweep`. The timer never reads stream
state or launches a reconciler itself.

The new Fable begins with read-only inventory. It confirms objective, authority,
and done condition before redirecting work. It owns the reconciled operation
view, not every raw log.

An operator handoff occurs only on explicit request. The outgoing owner writes
`handoffs/<revision>.md`. A fresh Fable reconciles sources and declares ready.
Then `octo-control owner-transfer` performs one locked compare and atomic TOML
replace. The prior owner becomes read-only. No timeout or automatic failover
transfers authority.

Use `operator-say` for all messages to Fable. It resolves the current owner on
every send.
