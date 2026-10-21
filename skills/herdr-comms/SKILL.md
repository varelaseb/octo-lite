---
name: herdr-comms
description: Spawn Herdr agents and send them messages, over native Herdr.
---

# herdr-comms

Thin wrappers over native Herdr. Herdr itself owns the transport; these
exist only for the failure modes it leaves to the caller, and for parking an
idle Claude agent so it holds no memory while it waits.

Every wrapper acts only in the caller's Herdr session,
`${HERDR_SESSION:-default}`: pane, tab, and space ids repeat across sessions.
`octo-lite-state` prints the caller's session state directory, holding `lanes/`
(lane records, hand-off logs, notes, `archive/`), `operator.toml`, and
`operator.handoffs.jsonl` (spec `#session-state`).

## Spawn an agent

```
herdr-spawn --workspace ID --name NAME --label LABEL --cwd DIR --role ROLE \
  -- claude    # default
herdr-spawn --workspace ID --name NAME --label LABEL --cwd DIR --role ROLE \
  -- codex     # non-default alternative
herdr-spawn --workspace ID --name NAME --label LABEL --cwd DIR --role ROLE \
  -- pi        # non-default alternative
```

A lane worker spawns into its lane space, `--workspace "$HERDR_WORKSPACE_ID"`,
named `<role>-<ticket>` lowercase (`implementer-ann-64`). A pane never moves
between spaces: Herdr rewrites its ids.

Spawn bare, then send the brief with `herdr-say`. Nothing follows the runtime:
with an inline prompt, `herdr agent start` times out waiting for readiness.

One tab, one pane, one agent, at an explicit worktree. Prints:

```
name= role= tab= pane= cwd= contract= provider_session_id=
```

The runtime comes from the agent definition and each CLI's own defaults. This
pins no model, effort, or service tier.

`--role` is not just a label. A Claude agent loads its own contract through
`--agent ROLE`, which `herdr-spawn` passes. Codex has no custom-agent file, so
the contract at `~/.claude/agents/ROLE.md` is passed as `-c developer_instructions=...`. It
binds at the developer layer and the agent waits for its brief; a contract sent
as a prompt is worked as a task. Pi has neither, so it gets the contract file
through `--append-system-prompt FILE`. The output reports `contract=` so a
silent miss is visible.

`--operating-model FILE` is optional. It hands that file to the agent at start,
so no global instruction file is needed: Claude gets
`--append-system-prompt-file FILE`, Codex gets it ahead of the contract in
`developer_instructions`, pi gets `--append-system-prompt FILE` ahead of the
contract's. It defaults to `$OCTO_LITE_OPERATING_MODEL`, and the
spawn exports that path into the new tab, so every child inherits the model
without passing the flag. Without either, nothing changes.

A new tab gets the Herdr server's environment, so the spawn always exports the
caller's `HOME` into it. The agent and every child it spawns keep the caller's
home: git identity, consent, and sessions.

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

`--resume SESSION` (Claude only) starts a parked agent as it was launched:
Claude gets `--agent ROLE --resume SESSION` and keeps its conversation. An
owner resumes through `octo-lite-start --cwd WORKTREE --name LANE --resume
SESSION`, in a new lane space. `herdr-say` does both for you; see below.

## Close an agent or a lane space

```
herdr-close TAB
herdr-close SPACE
```

The teardown step. An id with a colon (`w5:t2`) is a tab, one without (`w5`) is
a space. Closes it, then sends TERM to every process of the caller's session
whose environ carries `HERDR_TAB_ID=TAB` or `HERDR_WORKSPACE_ID=SPACE`, which
catches detached children that close alone leaves running. Run it from outside
what it closes: the spawner closes a tab, the operator closes a finished lane's
own space, or only its owner tab when the lane started in a shared space.
Prints `tab= tab_close_rc= killed=` or `space= space_close_rc= killed=` and
exits with the close status.

## Park an idle agent

```
herdr-close --park PANE >>"$lanes/<lane>.handoffs.jsonl"
```

`$lanes` is `$(octo-lite-state)/lanes`. Reads the Claude session of PANE, a
pane of the caller's session, by `herdr-claude-session` (below), closes its
tab, or its whole space when that tab is the space's only one (a lane owner in
its own space), and prints one parked line (`at kind pane name role cwd
session`) on stdout, even when the close fails; the close report goes to
stderr. The parker appends the line: the operator for an owner, the owner for a
worker. An agent Herdr does not report idle is refused with exit 75, a Codex or
pi agent (no Claude session file) with 65; nothing is closed.

## Find a pane's Claude session

```
herdr-claude-session PANE
```

The one lookup `herdr-close --park` and `herdr-say` share (spec
`#transport-claude-session`). Prints one JSON line: Claude's own record
`~/.claude/sessions/<pid>.json` plus `transcript`, the path of
`~/.claude/projects/*/<sessionId>.jsonl`, `null` before its first message.
Exits 1 when no record counts. A record counts when its live process carries
`HERDR_PANE_ID=PANE` and the caller's `HERDR_SESSION`, foreground or not (a
spare Claude claimed into the pane), and its `procStart` is that process's
start time, so a record left at a reused pid is never read. Of those, the one
whose transcript holds the latest reply (an assistant record off any sidechain)
wins.

## Send a message

```
herdr-say TARGET MESSAGE
```

Wraps `herdr agent prompt TARGET TEXT --wait --until working --until idle`.

Exit codes are the contract:

| code | meaning |
|---|---|
| 0 | delivered, and Herdr observed the agent change state; a Claude agent also processed it |
| 69 | not processed: a Claude agent's turn died on an API rate limit at every send for about two hours; stderr names the target, the number of sends, and the last API error; every re-send is already spent, so never send it again |
| 75 | target is blocked on interactive input; retry when it frees |
| other | anything else; 1 for a message never taken in, stderr naming the target |

There is no acknowledgement step. `--wait --until` returns only on a state
change Herdr observed itself, which is stronger evidence than an agent
reporting on its own behalf. There is no deferred inbox and no drain: a message
is either delivered now or reported as not delivered.

Native Herdr refuses to prompt a blocked agent, so an open dialog is never
typed into.

A Claude agent whose turn dies at once on an API rate limit (credentials
cooling down) has not processed the message, though Herdr saw it work (spec
`#transport-say-rate-limit`). After each send, the transcript of the pane's
Claude session (`herdr-claude-session`) decides: processed unless the
message's own reply, within a few seconds, is a rate-limit error. Its own reply
is the first reply after the record carrying it, a slash command's as Claude
records it, its name and args: Herdr does not track turns, so for a target
already working, the state change and the reply after it are the running
turn's. A message enqueued behind a running turn waits until taken in, however
long that turn runs; one still not taken in once that turn has ended or Claude
has exited never reached the agent, and `herdr-say` exits 1. Otherwise
`herdr-say` sends the same message again, waits doubling from a minute,
capped, until processed (exit 0) or about two hours pass (exit 69). The retry
lives in that one send, so a caller bounded tighter does not hold it in the
foreground. Codex and pi keep no Claude session: the state change alone
confirms.

A target Herdr does not find may be parked. The latest parked line naming it,
by pane or name, in any lane hand-off log in `$lanes` decides: a live agent
under the line's name gets the message; otherwise the agent is resumed (an
owner, the line named after its log, in a new lane space; a worker in the
caller's `$HERDR_WORKSPACE_ID`), gets the message, and `herdr-say` prints its
new `pane=`. Every re-send does the same, so a target parked during a wait is
resumed. `herdr-say --parked TARGET` prints that line, or exits 1.
`herdr-wake check` counts a parked owner as present, so a spec review hand-off
resumes it. `herdr-wake send` runs `herdr-say` in a session of its own, so a
send outliving Spec Chat's send bound (a resume, a rate-limit wait) keeps
delivering after Spec Chat counts it sent. Spec Chat then no longer waits on
it, so when it ends deferred or failed, `herdr-wake` sends its one-line reason,
naming the owner, once to the operator pane (`pane` in
`$(octo-lite-state)/operator.toml` of the owner's session). Within the bound
the reason goes to Spec Chat, which retries.

The review service may run in another Herdr session, so register a review row
with `--owner "${HERDR_SESSION:-default}/$HERDR_PANE_ID"`: `herdr-wake` checks
and wakes a `SESSION/PANE` owner in that session, a bare pane in its caller's.

## Reading a pane

`herdr pane read` returns raw text. `herdr agent get` returns JSON. Use the
agent view for state and the pane view only for what is literally on screen.

## Never submit text you did not write

A `❯` line in a pane may be the CLI's own suggestion, not something a human
typed. Only a real message, or text the operator explicitly quoted, authorizes
submitting anything on someone's behalf.
