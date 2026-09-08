---
name: codex-session-refresh
description: Keep the Codex remote-control app-server following the ChatGPT account in auth.json, answer which account the operator must sign into on mobile, restart the daemon, and refresh parent lanes plus their subagents. Use when the operator asks what account to log into on the phone or cannot pair, when remote-control pairing fails, when the operator signed into a different ChatGPT account on this box, when lanes show a usage-limit banner, or when lanes show a WebSocket transport error with a Disconnected from this task or Reconnect line. Inference runs through the cliproxyapi gateway and is never rotated from this box.
---

# Codex session refresh

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

## Two identities

This box carries two ChatGPT identities. They are not the same account and
this skill never confuses them.

- **Inference** goes through the CLIProxyAPI gateway at
  `https://cliproxy.topicfinder.ai/v1`, selected by `model_provider =
  "cliproxyapi"` in `~/.codex/config.toml` and keyed by `CLIPROXYAPI_API_KEY`.
  The gateway holds a pool of six Codex accounts and rotates them itself.
  Nothing on this box logs in, logs out, or rotates for inference, ever. A
  usage-limit banner is the gateway's whole pool being capped, and the answer
  is the runbook at `scaling-octo-engine/docs/operations/cliproxyapi.md`, not
  a login here.
- **Remote control** is the ChatGPT account in `/root/.codex/auth.json`. The
  app-server daemon registers its `environmentId` under that account at
  startup and holds it for life. The phone must be signed into that exact
  account to see this box, and a daemon older than `auth.json` presents an
  account the file no longer holds.

The only auth this skill touches is the remote-control one, and only after the
operator has already changed it by signing in on this box. Rotation is never
the fix for anything here.

## Intent

Two outcomes, every time, whatever the reported symptom:

1. **The fleet is working again.** Daemon serving, every lane that was stopped
   either transacting again or knowingly finished. Reconnecting a TUI is not
   the finish line: a lane sitting at a composer with interrupted work is still
   stopped.
2. **The operator can connect from mobile on the account the daemon actually
   presents.** End every run by naming that account and minting a pairing
   code, even when nothing was restarted.

The steps below are means. If a step is unnecessary, skip it; if the fleet is
still stopped after the steps, the run is not done.

## Install

Symlink `assets/codex-lanes` into `~/.local/bin`. Never copy it.

## Which account for mobile

The answer to "what account do I need to log into on mobile" is one command:

```sh
codex-lanes identity
```

It prints the `auth.json` account, whether the running daemon started after
that file was written, and the inference provider. Read it as:

- `daemon follows auth.json: yes`: tell the operator that email, mint a code
  with `codex remote-control pair --json`, hand over `manualPairingCode`.
  Done.
- `daemon follows auth.json: no`: the file changed under a running daemon. The
  daemon still presents the old account and a code minted from it lands there.
  Run step 1 first, then answer.
- `daemon follows auth.json: no-daemon`: nothing is serving. Step 1.

Never answer from memory or from a backup file. Every `auth.json.bak-*` is the
account a previous login REPLACED, and the operator has held at least four
accounts on this box. The file on disk is the only source.

The daemon reads `auth.json` once. It does not watch the file, so an auth
change while it runs is exactly the case `identity` exists to catch. There is
no watcher and there must not be one: the restart kills every lane's
subagents, so it runs only when the operator asks (operator 2026-09-08). On
`no`, report the mismatch and the cost, then wait for the word.

## Trigger

Any one of these:

- The operator asks which account to sign into on the phone, or cannot see
  this box in the mobile app.
- `codex remote-control pair` fails, or the operator cannot pair a phone or a
  second machine.
- `auth.json` changed after the daemon started, so `codex-lanes identity`
  says `no`.
- Lanes show a WebSocket transport error plus `Disconnected from this task`
  and a `Reconnect:` line.
- `You've hit your usage limit ... try again at <date>` across lanes. Classify
  first: see the banners section.

## Modes

Run the smallest thing that fixes the report. A full pass is two steps, but
most calls are one of them, and doing both when one was asked for is how live
work gets killed for nothing.

- **Server only, usually for remote.** The operator wants to pair a phone or a
  second machine. Run `codex-lanes identity`. On `yes`, **try
  `codex remote-control pair --json` first.** It very often just works, and
  then there is nothing to do but name the account and hand over the code. A
  restart is warranted only when pair fails or `identity` says `no`, and it
  costs everything in the inventory in step 1.
- **Lanes only.** The daemon respawned on its own, most often an auto update,
  and the TUIs dropped. Step 2 alone.
- **Full pass.** The daemon must restart AND lanes must transact after it.
  Step 1, then 2.

## Reading the banners

A stopped lane shows one of two things, and neither is fixed by a login. They
look alike and mean completely different things, so classify before acting.

- `You've hit your usage limit ... try again at <date>` is **quota on the
  gateway pool**. No amount of refreshing or restarting on this box fixes it,
  and no login here touches it. Stop and say so. Each attempt spends a real
  turn to be refused. Report the reset date, because that is the actual
  unblock time unless the gateway operator adds capacity. Before blaming the
  pool, confirm the lane is actually on the gateway: a lane started with
  `--config model_provider=openai` bypasses it and caps on the `auth.json`
  account instead.
- A WebSocket transport error plus `Disconnected from this task` and a
  `Reconnect:` line is **the app-server having respawned**, most often an auto
  update replacing the binary under the running TUIs. Nothing is wrong with
  quota. Reconnect the lanes.

Say it plainly when quota is being exhausted faster than it resets. A large
fleet on high reasoning effort can burn a weekly allowance in an afternoon.
That is a fleet-size and effort problem, and no run of this skill fixes it.

## Order

When running both steps: server, then parent lanes, then their subs. Never
reorder. The daemon restart kills every in-flight subagent and every process
the daemon parents, so a lane refresh is only durable once the restart is done.

## 1 Server

**Check identity, then try pairing, before restarting anything.** A restart
is a means, never the request:

```sh
codex-lanes identity
codex remote-control pair --json
```

`identity` on `yes` plus a `pairingCode` back means the daemon is healthy and
the job is done: name the account, hand over `manualPairingCode`, stop. Only
`identity` on `no`, a pair failure, or a timeout earns the restart below,
which costs every service in the inventory and cannot give the tunnel URLs
back. Asked to "refresh the daemon for remote", check and pair first: the ask
is working remote access on the right account, not a restarted process.

`pair` succeeding is not proof of the right account. It succeeds against
whatever account the daemon registered at startup, so on `identity: no` a
green pair is a code for the wrong phone login.

Capture the lane roster first. The restart kills remote-control-attached TUIs
outright, not only subagents, and a dead TUI leaves no trace of what it was:

```sh
codex-lanes scan > /tmp/lanes-before.txt
```

Diff against it after the restart. A lane that appears in the before list and
not the after list is a TUI the restart killed.

Record what dies with it. Every process the daemon parents is killed by the
restart: MCP servers, watchers, pollers, and whole spec-chat review sessions.
A service already reparented to PPID 1 survives, so check before assuming.

Capture the cwd too. A service started from a lane runs in that lane's
worktree, and the same command in the wrong directory serves the wrong repo:

```sh
DPID=$(codex-lanes daemon-pid)
for pid in $(ps -eo pid,ppid --no-headers | awk -v p="$DPID" '$2==p {print $1}'); do
  echo "$pid cwd=$(readlink /proc/$pid/cwd)"
  tr '\0' ' ' < /proc/$pid/cmdline; echo
done
```

Two things in that list deserve a pause before restarting:

- **`cloudflared tunnel` processes.** The restart kills them and a relaunch
  mints a DIFFERENT public URL. Every link already handed to a human dies, and
  no amount of care gets the old hostname back. This is outward facing and
  irreversible: name the affected URLs to the operator and get a go-ahead
  before restarting, rather than after.
  Read the URL out of the tunnel's own pane BEFORE restarting, because nothing
  else records it. It is not in the review directory and not in the owning
  lane's scrollback, so once that pane dies the old address cannot even be
  quoted to the people who lost it, let alone restored.
- **One-shot jobs**, such as a `claude -p` evaluation reading a `.tmp-*` input.
  These are somebody's in-flight work, not services. Do not blindly re-run
  them; report that they died and let their owning lane decide.

`daemon-pid` reads the owner of the control socket and falls back to the pid
file, which newer codex builds no longer write. Never
`pgrep -f 'app-server --remote-control'`: it matches the grepping shell itself.

Restart through systemd. `codex remote-control stop` followed by `start` does
not work, because `start` cannot recreate the control socket that `stop`
removed:

```sh
systemctl restart codex-remote-control.service
systemctl is-active codex-remote-control.service
codex-lanes identity
```

`identity` must now say `yes`. The restarted daemon read the current
`auth.json`, so its `environmentId` belongs to that account and a paired phone
on any other account stops seeing this box. Say so when the account changed.

Check whether a recorded watcher is still needed before relaunching it. A
poller whose condition already went true is finished, and restarting it just
re-runs work that completed. Query its condition directly.

Relaunch every service still needed the way it was running, in its own herdr
pane, in its recorded cwd. Detaching with `setsid nohup` survives the next
restart but hides the service from the operator and from the lane that owns it,
and these are lane-visible services, not daemon infrastructure. Restore what
was there; do not upgrade it into something else:

```sh
PANE=$(herdr tab create --workspace <WS> --cwd <RECORDED_CWD> --label "<lane> spec review" --no-focus \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['result']['root_pane']['pane_id'])")
herdr pane run "$PANE" python3 tools/review-serve.py docs <PORT>
TUNNEL=$(herdr pane split "$PANE" --direction down --ratio 0.5 --no-focus \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['result'];print(d.get('pane',d)['pane_id'])")
herdr pane run "$TUNNEL" cloudflared tunnel --no-autoupdate --url http://127.0.0.1:<PORT>
```

A tunnel takes 10 to 20 seconds to print its URL, and the precheck lines land
first. Read it from the pane, then prove it end to end rather than trusting
that the process started:

```sh
herdr pane read <TUNNEL_PANE> --source recent-unwrapped --lines 60 \
  | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com'
curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 "<URL>/"
```

Confirm the ports listen and every new URL answers 200 before moving on, and
carry those URLs into the lane messages in step 2. A lane that is not told its
review link changed will keep serving a dead one to a human.

Mint the pairing code last, at the moment the operator will use it:

```sh
codex remote-control pair --json
```

Codes live 10 minutes. Never hand over one minted earlier in the run, and
always name the account from `identity` next to the code. A code without the
account it belongs to sends the operator guessing across four logins.

Mint one at the END of EVERY run, including runs that never restarted the
daemon. Mobile access is half the point of this skill.

## 2 Parent lanes

Classify before touching anything:

```sh
codex-lanes scan
```

- `health=stale`: the TUI process is older than the running daemon. It holds
  a dead connection and rejects every input, however healthy the CLI is. It
  must be restarted, not messaged.
- `health=live`: started after the running daemon.
- `health=shell`: the TUI stopped and the pane is at a shell prompt. `scan`
  claims such a pane only when codex itself printed a resume line, because
  herdr drops the `agent` field the moment a TUI exits and anything looser
  would adopt unrelated shells. Three forms count, and which one a pane carries
  depends on its codex build and on how the TUI stopped:
  `To continue this session, run codex resume <id>`,
  `To continue this session, run codex resume, then select <title> (<id>)`, and
  `Reconnect: codex resume <id>`. The third means the TUI was interrupted with
  a turn still in flight: that work continues server side and the resume
  reconnects to it, so the lane is live work, not a finished one.
  A live session also prints `To resume this session run codex resume, then
  select <title> (<id>)` on rename. That one is deliberately not an anchor: the
  TUI printing it is still running, and claiming a pane on it would adopt live
  lanes as dropped ones.
- Not every codex-looking pane is a lane. A spec-chat review session runs a
  `review-control.sh external ... wake-herdr.py` process that reads as a pane
  with no agent and names its owning lane in its own output. It is the verified
  external-wake channel for that lane. Never wake it and never kill it while
  its owner is alive.
- `role=driver`: the lane shows `Waiting for agents`, so it owns subagents.
  This reads a recent scrollback window, so it can miss a driver that has since
  scrolled. `GOAL` is the durable signal: any `thread_goals` status other than
  `complete` in `~/.codex/goals_1.sqlite` is a live driver.

Refresh drivers first, then whatever they wake. A driver whose subs were killed
sits in a dead wait forever, because the agents it is waiting on no longer
exist.

```sh
codex-lanes refresh <PANE>
```

That exits the TUI with Ctrl+C twice, harvests the exact session id the TUI
prints, resumes it, and verifies the composer came back. `/quit` is not a Codex
TUI command, it submits as a message. The Herdr key name is `ctrl+c`; `ctrl-c`
is rejected as an unsupported key. Never `codex resume --last`: resume the id
the pane printed.

The id comes from one of the three resume lines above, never from a bare
`codex resume <id>` string. A shell prompt echoing an older resume command
carries a stale id, and matching it resumes the wrong session into the pane.
When both are in scrollback the resume line wins, and the newest one wins over
an older one.

`scan` and `refresh` read scrollback plus the current viewport. A pane whose
whole content still fits on screen has no scrollback at all, so a scrollback
only read comes back holding just the prompt line and goes blind to exactly the
short-lived lane it was pointed at.

Three outcomes are not failures, and `refresh` reports each instead of dying on
the missing composer:

- `cwd ... no longer exists`: the lane's worktree was deleted. It cannot resume
  in place, and resuming it elsewhere silently relocates the work. Leave it for
  a human. The session file under `~/.codex/sessions` stays readable.
- `paused-goal prompt open`: the TUI is blocked on `Resume paused goal?`, which
  hides the composer. That is a live resume. Confirming the goal is a human
  decision, especially when the objective ends in a production action.
- a resume that lands in bash as garbage like `9;5:1ucodex resume <id>` is
  escape residue, not a dead lane. `refresh` verifies codex actually took the
  foreground and retypes once.

Then tell each driver what happened:

```sh
codex-lanes notify <PANE> "<message>"
```

`notify` refuses any pane whose foreground process is not codex, and any
message carrying shell metacharacters. Both guards exist because text typed at
a shell prompt executes: a wake message beginning `1)` produced
`bash: syntax error near unexpected token ')'` and the lane stayed dark.

Message content that works, as plain prose with no metacharacters:

- daemon restarted at what time, so every in-flight subagent is dead and will
  never report
- if the remote-control account changed, which account, so the lane does not
  report the old one to the operator
- their own TUI was restarted and resumed at its exact session id
- instruction: treat all prior waiting-for-agents state as void, re-check the
  subagent roster, re-spawn every sub that had not reached a terminal state
- any new tunnel URL from step 1, since the lane is still holding the dead one
- that replayed scrollback above the message is history, so a transport
  error in it is stale rather than a live failure
- own-lane work only
- an explicit instruction to pick the work back up now

Message every lane the restart dropped, not only drivers. A plain lane mid-task
is just as stopped as a driver, and it has no way to learn why. The operator's
standing expectation is that anything killed by a refresh gets told to resume.

**Prove the daemon on ONE lane before processing the fleet.** Refresh a single
lane, wake it, and watch what comes back. The first refreshed lane IS the
probe. Only when that lane actually transacts do the rest follow.

A canary costs one turn. Skipping it costs one dead turn per lane, and under a
usage cap every one of them comes back with the same banner. This has paid for
itself twice: eight lanes and seventeen lanes respectively, both times stopped
after one.

**Read each lane before waking it. Never blanket-notify.** A refresh drops
finished lanes and mid-task lanes alike, and they are indistinguishable from
the roster: both sit at a composer under `health=live`. Read the viewport and
sort them:

```sh
herdr pane read <PANE> --source visible --lines 24
```

- Wording like `no unfinished work remains`, `no retry needed`, `returning
  idle`, a completed verdict, or a `Linear: Done` summary means the lane
  finished before it was dropped. Leave it alone. Waking it spends a turn to be
  told again that it is done, and invites it to redo settled work.
- An interrupted tool call, a half-written diff, a plan with steps still open,
  or a driver mid-wait means real work stopped there. Wake that one.

Say what to resume, not just that a refresh happened. A lane that is only told
its transport reset will report health and stop again. Tell it to re-read its
last few messages, work out where it stopped, and continue that work now.

Goals resume on their own once the lane transacts. Expect the status bar to go
from `Goal stalled (/goal resume)` or `Goal hit usage limits` to
`Pursuing goal`. Only send `/goal resume` if it does not.

Do not wake lanes reporting `Goal achieved`. Their work is finished.

## Verify

- `codex-lanes identity` says `yes`, and the account it names is the one you
  told the operator.
- `codex-lanes scan` shows no `stale` lane you meant to keep, and no `shell`
  lane you meant to keep.
- Diff the scan against `/tmp/lanes-before.txt`. Every lane that vanished is a
  TUI the restart killed, and each needs a `refresh` or an explicit decision.
- One throwaway probe proves the CLI answers, not that the plan has room:
  `codex exec --skip-git-repo-check 'Reply with exactly: OK'`. Run it before
  telling lanes to resume, not after: lanes waking onto a dead backend are a
  second outage. Do not read more into a pass than that. This probe spends
  about 6k tokens and has returned `OK` while every lane was hard-capped, so a
  green probe next to lanes reporting a usage limit is not a contradiction and
  not proof the banners are stale. Only a real lane transacting proves it.
- Every lane the run touched is transacting or has said it is finished. A
  roster of `live` lanes sitting at composers is not a working fleet.
- Every service from the step 1 inventory is back, its port listens, and every
  new tunnel URL answers 200.
- Only the steps the report actually called for ran. A pass that restarted the
  daemon when `pair` would have answered did damage for nothing.
- Resumed lanes replay their transcripts, so old usage-limit and transport
  banners reappear in scrollback. They are history, not live
  failures. Judge a lane by whether it reaches `Working`, never by a banner.
