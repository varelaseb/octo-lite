---
name: herdr-comms
description: Spawn Herdr agents and send them messages, over native Herdr.
---

# herdr-comms

Three thin wrappers over native Herdr. Herdr itself owns the transport; these
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
name= role= tab= pane= cwd= contract= provider_session_id=
```

The runtime comes from the agent definition and each CLI's own defaults. This
pins no model, effort, or service tier.

`--role` is not just a label. A Claude agent loads its own contract through
`--agent ROLE`. Codex has no custom-agent file, so the contract at
`~/.claude/agents/ROLE.md` is passed as `-c developer_instructions=...`. It
binds at the developer layer and the agent waits for its brief; a contract sent
as a prompt is worked as a task. The output reports `contract=` so a silent miss
is visible.

Codex runs with `--no-daemon`, so its thread and commands live in the tab's own
process tree, not the shared app-server that outlives the tab.

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
`shaping-reviewer` contract. Its tools are Read, Grep, Glob, Bash, and Skill,
used read only: `repo-read` and `session-log-read` are Read, Grep, Glob;
`github-read` is read-only `gh`; `linear-read` is Linear GraphQL queries, never
mutations. Launch it as:

```sh
herdr-spawn --workspace ID --name NAME --label LABEL --cwd DIR \
  --role shaping-reviewer -- codex -m gpt-5.6-sol -c model_reasoning_effort=xhigh -c service_tier=fast \
  --sandbox read-only
```

The contract is read-only and forbids edits, commits, pushes, and issue or PR
mutations. The model, effort, and service tier are explicit launcher inputs,
not additions to the model-free role contract. Launch with
`--sandbox read-only`. If the host sandbox fails before any command runs (bwrap
`loopback: Failed RTM_NEWADDR` fails `read-only` and `workspace-write` alike),
relaunch with no sandbox flag. Codex then runs under the configured
`sandbox_mode`, often `danger-full-access`, so only the read-only contract
binds; the caller verifies one real source-read result before accepting the
verdict.

## Close an agent

```
herdr-close TAB
```

The teardown step. Closes the tab, then sends TERM to every process whose
environ carries `HERDR_TAB_ID=TAB`, which catches detached children that tab
close alone leaves running. Never signals itself or its ancestors. Prints
`tab= tab_close_rc= killed=` and exits with the tab close status.

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
