---
name: launch-meta-operator
description: Launch exact Fable as the persistent octo-lite operator with durable control and atomic handoff support.
---

# Launch meta-operator

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use only on explicit operator request.

## Which launcher

Decision tree. Pick one path; the launchers are distinct scripts.

- No `operator-owner.toml` yet (first ever launch): INITIAL launch. Run
  `skills/launch-meta-operator/scripts/launch-meta-operator.sh`. Creates the
  revision-zero owner record; refuses if an owner record already exists.
- `operator-owner.toml` exists and operator wants a live Fable-to-Fable
  handoff: LIVE handoff. Run
  `skills/launch-meta-operator/scripts/handoff-meta-operator.sh`. Requires the
  existing owner record; refuses if none (that is the initial case). See
  operator-control `handoff-launcher-initial` / `handoff-launcher-live`.

## INITIAL launch

Run `skills/launch-meta-operator/scripts/launch-meta-operator.sh`. It:

- resolves `meta-operator` through `roles.toml`
- pins exact `claude-fable-5`, xhigh, auto mode, no fallback
- writes one parent brief, child status, TOML receipt, and owner TOML
- injects remote access facts from turn one
- launches through `herdr-spawn` as `🧠 operator`
- requires bootstrap acknowledgment before mutation
- installs one lifecycle-bound host timer that runs the operator heartbeat sweep

The operator heartbeat sweep fires on a schedule; only a changed sweep delta
messages Fable through the sweep's own delta path, so no periodic wake message
ever enters the operator context.

The new Fable begins with read-only inventory. It confirms objective, authority,
and done condition before redirecting work. It owns the reconciled operation
view, not every raw log.

An operator handoff occurs only on explicit request. The outgoing owner writes
`handoffs/<revision>.md`. The fresh Fable reconciles sources, then declares its
own readiness with `octo-control successor-ready`. `octo-control owner-transfer`
verifies that durable receipt and the exact successor session, then performs
one locked compare and atomic TOML replace. The prior owner becomes read-only.
No timeout or automatic failover transfers authority.

Use `operator-say` for all messages to Fable. It resolves the current owner on
every send.

## LIVE handoff

Run `skills/launch-meta-operator/scripts/handoff-meta-operator.sh --workspace ID --handoff DOC [--name NAME]`.
It:

- requires an existing `operator-owner.toml`; refuses fail-closed if absent
  (that is the initial case, use `launch-meta-operator.sh`)
- reads the current owner record: owner session id, route, revision R, and the
  INVARIANT `control_dir` (passed straight through, never reinvented)
- requires the `--handoff` doc to exist, its basename to equal the zero-padded
  R+1, and its parent dir to equal `control_dir/handoffs`; rejects a correct
  basename in the wrong dir and a wrong basename
- spawns ONE successor Fable that COEXISTS with the current owner under the same
  control dir, writing successor artifacts (receipt, brief, status) under its
  OWN `operators/<name>/` directory
- writes NO owner record and installs NO timer; owner-transfer is the sole
  authority commit
- never probes owner liveness (no ps/kill/pane-read); it cannot and does not
  distinguish a live from a dead owner
- pre-derives and prints exactly two runnable commands: the successor-ready
  command for the successor to run after reconciling, and exactly ONE
  owner-transfer command bound to the current owner identity for the current
  owner to run after the successor declares readiness

The successor reads the handoff, reconciles at source, runs its successor-ready
command, then signals the current owner. The current owner then runs the printed
owner-transfer command.

### Boundary (ruling-76 term A, `handoff-launcher-dead-owner-guidance`)

The printed owner-transfer is the normal owner-run handoff-atomic step, run ONLY
as the live current owner. A dead or ambiguous owner has no agent-callable
recovery path; it is recovered solely by manual operator takeover outside role
authority on operator instruction (ADR-0001 `decision-manual-takeover`,
`decision-no-recover-command`). The launcher prints exactly one owner-transfer
command and never derives a second command from any other or prior identity.

### Caller-identity property (ruling-76 term B, `handoff-launcher-owner-identity-preexisting`)

The owner-transfer caller-identity gate is a PRE-EXISTING octo-control property
(`transfer_owner` checks `caller == expected_owner_session_id`). The launcher
neither strengthens nor weakens it and invents NO new authentication. It only
pre-fills the exact current owner identity the gate already checks; a caller who
is not the current owner is rejected by that same pre-existing gate. Any future
session-authentication hardening is a separate operator-initiated change.
