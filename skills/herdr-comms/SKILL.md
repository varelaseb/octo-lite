---
name: herdr-comms
description: Spawn Herdr agents and send them messages, over native Herdr.
---

# herdr-comms

Two thin wrappers over native Herdr. Herdr itself owns the transport; these
exist only for the failure modes it leaves to the caller.

## Spawn an agent

```
herdr-spawn --workspace ID --name NAME --label LABEL --cwd DIR --role ROLE \
  -- claude --agent ROLE
herdr-spawn --workspace ID --name NAME --label LABEL --cwd DIR --role ROLE \
  -- codex
```

One tab, one pane, one agent, at an explicit worktree. Prints:

```
name= role= tab= pane= cwd= remote_control= provider_session_id=
```

The runtime comes from the agent definition and each CLI's own defaults. This
pins no model, effort, or service tier.

`--role` is not just a label. A Claude agent loads its own contract through
`--agent ROLE`, but Codex has no custom-agent file, so the contract is delivered
as the agent's first prompt, looked up at `~/.claude/agents/ROLE.md` in the
installed profile. Without it a Codex agent runs having read the operating model
but never the contract that bounds it, which is where its write surface is
stated. The output reports `contract=` so a silent miss is visible.

It wraps `herdr tab create` and `herdr agent start`, and handles three things
those leave to the caller:

- A freshly created pane is not yet at a shell prompt. Herdr reports
  `agent_pane_busy`; only that code is retried, with backoff.
- An agent that opens its trusted-folder dialog makes `agent start` report
  `agent_not_ready`. That is a started agent waiting on a keystroke, not a
  failure.
- The dialog is answered at the **pane**, never blindly. A blocked agent refuses
  agent-level input, and the highlighted row may be `No, exit`, where a bare
  Enter kills the agent being spawned. The selection is moved onto the trust
  option and verified before confirming.

Any failure closes the tab, so a failed spawn never leaves an orphan.

## Shaping-review launcher mapping

The pre-fleet shaping-review pass uses one fresh Codex worker with the
`shaping-reviewer` contract and this logical provider tool set: `repo-read`,
`linear-read`, `github-read`, and `session-log-read`. Launch it as:

```sh
herdr-spawn --workspace ID --name NAME --label LABEL --cwd DIR \
  --role shaping-reviewer -- codex -m gpt-5.6-sol -c model_reasoning_effort=xhigh
```

The contract is read-only and forbids edits, commits, pushes, and issue or PR
mutations. The model and effort are explicit launcher inputs from the canonical
role-runtime map, not additions to the model-free role contract. A host that
fails before command execution while applying `--sandbox read-only` may retry
this exact mapping without that wrapper; the
launcher still delivers the same read-only contract and the caller must verify
one real source-read result before accepting the verdict.

## Send a message

```
herdr-say TARGET MESSAGE
```

Wraps `herdr agent prompt TARGET TEXT --wait --until working --until idle`.

Exit codes are the contract:

| code | meaning |
|---|---|
| 0 | delivered, and Herdr observed the agent change state |
| 75 | target is blocked on interactive input; retry when it frees |
| other | anything else |

There is no acknowledgement step. `--wait --until` returns only on a state
change Herdr observed itself, which is stronger evidence than an agent
reporting on its own behalf. There is no deferred inbox and no drain: a message
is either delivered now or reported as not delivered.

Native Herdr refuses to prompt a blocked agent, so an open dialog is never
typed into.

## Reading a pane

`herdr pane read` returns raw text. `herdr agent get` returns JSON. Use the
agent view for state and the pane view only for what is literally on screen.

## Never submit text you did not write

A `❯` line in a pane may be the CLI's own suggestion, not something a human
typed. Only a real message, or text the operator explicitly quoted, authorizes
submitting anything on someone's behalf.
