---
name: codex-session-refresh
description: Rotate Codex CLI auth, restart the remote-control app-server, and refresh parent lanes plus their subagents, together or one at a time. Use when Codex lanes show a usage-limit banner, when codex login status says Not logged in or auth.json is missing, when the operator cannot pair a phone or second machine or remote-control pairing fails 401 token_revoked, or when lanes reject input with "access token could not be refreshed because you have since logged out or signed in to another account".
---

# Codex session refresh

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

## Intent

Two outcomes, every time, whatever the reported symptom:

1. **The fleet is working again.** Credentials valid, daemon serving, every lane
   that was stopped either transacting again or knowingly finished. Reconnecting
   a TUI is not the finish line: a lane sitting at a composer with interrupted
   work is still stopped.
2. **The operator can connect from mobile on the CURRENT authed session.** End
   every run by minting a pairing code and handing it over, even when the run
   was only an auth fix and nothing was restarted. The `environmentId` moves
   with the account, so a code minted before the last login is worthless.

The steps below are means. If a step is unnecessary, skip it; if the fleet is
still stopped after the steps, the run is not done.

## Install

Symlink `assets/codex-lanes` into `~/.local/bin`. Never copy it.

## Trigger

Any one of these:

- `You've hit your usage limit ... try again at <date>` across lanes.
- `codex remote-control pair` fails HTTP 401 `token_revoked`, or the operator
  cannot pair a phone or a second machine.
- A lane rejects every input with `access token could not be refreshed because you have since logged out or signed in to another account`.
- `codex login status` says `Not logged in`, or `/root/.codex/auth.json` is
  absent.

## Modes

Run the smallest thing that fixes the report. A full pass is three steps, but
most calls are one of them, and doing all three when one was asked for is how
live work gets killed for nothing.

- **Auth only.** Credentials are gone or capped, lanes are otherwise fine. Do
  step 1, then mint a pairing code and hand it over. The daemon keeps serving;
  it only holds a stale token once auth actually changes, so restart it in the
  same pass ONLY if lanes then reject input. Note that a login lands while
  lanes are already running, so every one of them is now `stale-auth` and needs
  a refresh even though nothing was restarted.
- **Server only, usually for remote.** The operator wants to pair a phone or a
  second machine. **Try `codex remote-control pair --json` first.** It very
  often just works, and then there is nothing to do but hand over the code. A
  restart is warranted only when pair fails, and it costs everything in the
  inventory in step 2.
- **Full pass.** Auth changed AND lanes must transact under it. Step 1, then 2,
  then 3.

## Order

When running more than one step: auth, then server, then parent lanes, then
their subs. Never reorder. Each step invalidates the one after it. Auth
rotation revokes the token the daemon holds. The daemon restart kills every
in-flight subagent and every process the daemon parents. Lane refresh is only
durable once both are done.

## 1 Auth

Back up first, then log in. Do not `codex logout` first: `login --device-auth`
replaces `auth.json` on its own, and a logout only opens a window with no
credentials at all.

`auth.json` absent is a normal starting state, not a separate fault. It means
something already logged out. There is nothing to back up, so skip the copy and
log in.

Backups are not a shortcut back. Every `.bak` holds an expired `id_token`
within days, and the newest one is always of the account the last run
REPLACED, never of the account it moved to, because the copy happens before the
login. Restoring one reinstates the account you previously rotated away from.
Read them to learn which accounts exist, then still do the device login.

```sh
cp -a /root/.codex/auth.json /root/.codex/auth.json.bak-preauth-$(date +%Y%m%d)
herdr tab create --workspace <WS> --cwd /root --label "codex re-auth" --no-focus
herdr pane run <PANE> codex login --device-auth
herdr pane wait-output <PANE> --regex '[A-Z0-9]{4}-[A-Z0-9]{4,6}' --timeout 40000
```

Hand the operator the URL `https://auth.openai.com/codex/device` and the code
the moment it prints. Codes expire in 15 minutes.

Read the code off the LIVE VIEWPORT before handing it over, never off a
`wait-output` match:

```sh
herdr pane read <PANE> --source visible --lines 20
```

`wait-output --regex` searches scrollback, so on a second attempt it re-matches
the EXPIRED code from the first one and reports it as current. Handing that
over burns another 15 minutes on a code that can never work.

A code that expires unused kills the login process. The pane prints
`Error logging in with device code: device auth timed out after 15 minutes` and
its foreground goes back to bash while the old code stays on screen, which
reads exactly like a login still waiting. Check the foreground before
believing the screen:

```sh
herdr pane process-info --pane <PANE>
```

Foreground `bash` means dead, so re-run `codex login --device-auth` for a fresh
code. Foreground `codex` means it is still waiting and a new code would
invalidate the one the operator may be mid-way through typing. Never re-mint
unprompted.

Then wait for completion in the background and **never interrupt the poller**:

```sh
herdr pane wait-output <PANE> --regex 'Successfully logged in|expired|[Ff]ailed' --timeout 870000
```

A code the operator authorized in the browser is lost if the local poller dies
before it exchanges the token. There is no recovery, only a new code.

That protects an exchange already in flight. It is not a reason to sit on the
turn. This step is operator-held access, so once the code is handed over and
the poller is running, say plainly that the refresh is blocked on their browser
and stop. Do not spin, and do not re-mint on a timer: a fresh code invalidates
the one they may be mid-way through typing.

Verify the account actually changed:

```sh
codex login status
python3 -c "
import json,base64
d=json.load(open('/root/.codex/auth.json')); t=d['tokens']
p=t['id_token'].split('.')[1]; p+='='*(-len(p)%4)
c=json.loads(base64.urlsafe_b64decode(p)); a=c.get('https://api.openai.com/auth',{})
print(c.get('email'), a.get('chatgpt_plan_type'), a.get('chatgpt_subscription_active_until'))
"
```

Sign in to an account with headroom. Re-authing the capped account reproduces
the cap.

## 2 Server

The daemon caches the old oauth token, so `pair` returns 401 `token_revoked`
until it restarts. That 401 is the signal for this step, not an auth defect.

**Try pairing before restarting anything.** A restart is a means, never the
request:

```sh
codex remote-control pair --json
```

A `pairingCode` back means the daemon is healthy and the job is done: hand over
`manualPairingCode` and stop. Only a 401 or a timeout earns the restart below,
which costs every service in the inventory and cannot give the tunnel URLs
back. Asked to "refresh the daemon for remote", pair first: the ask is working
remote access, not a restarted process.

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
DPID=$(python3 -c "import json;print(json.load(open('/root/.codex/app-server-daemon/app-server.pid'))['pid'])")
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
- **One-shot jobs**, such as a `claude -p` evaluation reading a `.tmp-*` input.
  These are somebody's in-flight work, not services. Do not blindly re-run
  them; report that they died and let their owning lane decide.

Read the pid file. Never `pgrep -f 'app-server --remote-control'`: it matches
the grepping shell itself.

Restart through systemd. `codex remote-control stop` followed by `start` does
not work, because `start` cannot recreate the control socket that `stop`
removed:

```sh
systemctl restart codex-remote-control.service
systemctl is-active codex-remote-control.service
```

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
carry those URLs into the lane messages in step 3. A lane that is not told its
review link changed will keep serving a dead one to a human.

Mint the pairing code last, at the moment the operator will use it:

```sh
codex remote-control pair --json
```

Codes live 10 minutes. Never hand over one minted earlier in the run. The
`environmentId` changes when the account changes, so a paired client from the
previous account has to pair again.

Mint one at the END of EVERY run, including runs that never restarted the
daemon. Mobile access on the current authed session is half the point of this
skill, and an auth-only pass silently invalidates whatever the operator paired
before.

## 3 Parent lanes

Classify before touching anything:

```sh
codex-lanes scan
```

- `health=stale`: the TUI process is older than the running daemon. It holds
  the previous account identity in memory and rejects every input, however
  healthy the CLI is. It must be restarted, not messaged.
- `health=stale-auth`: the TUI started before the current `auth.json` was
  written. A TUI reads credentials once, at startup, so a login that lands
  while lanes are already up leaves every one of them presenting the PREVIOUS
  account. They keep showing that account's usage-limit banner and cannot
  transact, while the file on disk is perfectly healthy and a `codex exec`
  probe passes. Daemon age cannot see this, so before this classification
  existed an entire fleet read as `live` while nothing worked. Refresh, do not
  message: a notify alone makes the lane re-hit the old account's cap
  instantly.
- `health=live`: started after both the daemon and the current credentials.
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

- auth rotated, to which account, at what time, prior account capped until when
- daemon restarted at what time, so every in-flight subagent is dead and will
  never report
- their own TUI was restarted and resumed at its exact session id
- instruction: treat all prior waiting-for-agents state as void, re-check the
  subagent roster, re-spawn every sub that had not reached a terminal state
- any new tunnel URL from step 2, since the lane is still holding the dead one
- that replayed scrollback above the message is history, so a usage-limit
  banner in it is stale rather than a live failure
- own-lane work only
- an explicit instruction to pick the work back up now

Message every lane the restart dropped, not only drivers. A plain lane mid-task
is just as stopped as a driver, and it has no way to learn why. The operator's
standing expectation is that anything killed by a refresh gets told to resume.

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

- `codex-lanes scan` shows no `stale` lane you meant to keep, and no `shell`
  lane you meant to keep.
- Diff the scan against `/tmp/lanes-before.txt`. Every lane that vanished is a
  TUI the restart killed, and each needs a `refresh` or an explicit decision.
- One throwaway probe proves the credentials LOAD, not that the plan has room:
  `codex exec --skip-git-repo-check 'Reply with exactly: OK'`. Run it before
  telling lanes to resume, not after: lanes waking onto dead credentials are a
  second outage. Do not read more into a pass than that. This probe spends
  about 6k tokens and has returned `OK` while every lane on the same account was
  hard-capped, so a green probe next to lanes reporting a usage limit is not a
  contradiction and not proof the banners are stale. The account is only proven
  by a real lane transacting.
- Every lane the run touched is transacting or has said it is finished. A
  roster of `live` lanes sitting at composers is not a working fleet.
- Every service from the step 2 inventory is back, its port listens, and every
  new tunnel URL answers 200.
- Only the steps the report actually called for ran. A pass that restarted the
  daemon when `pair` would have answered did damage for nothing.
- Resumed lanes replay their transcripts, so the old usage-limit and
  token-refresh banners reappear in scrollback. They are history, not live
  failures. Judge a lane by whether it reaches `Working`, never by a banner.
