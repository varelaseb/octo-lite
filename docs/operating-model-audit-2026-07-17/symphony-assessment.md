# Symphony assessment for the octo-lite operating model

Status: historical pinned comparison. Decisions 55 through 62 and 87 through
92 resolve the applicable boundary. The canonical operating-model spec wins.

## Source snapshot

This assessment pins the official `openai/symphony` repository at commit
`7af5a7648c9fbffa08825fe0c0b18be00100aff3`, dated 2026-07-18 UTC. The commit
introduces a generic tracker boundary while retaining Linear as the production
adapter.

Primary sources:

- <https://github.com/openai/symphony>
- <https://github.com/openai/symphony/blob/7af5a7648c9fbffa08825fe0c0b18be00100aff3/SPEC.md>
- <https://github.com/openai/symphony/tree/7af5a7648c9fbffa08825fe0c0b18be00100aff3/elixir>
- <https://github.com/openai/symphony/blob/7af5a7648c9fbffa08825fe0c0b18be00100aff3/elixir/WORKFLOW.md>
- <https://openai.com/index/open-source-codex-orchestration-symphony/>

At the pinned revision the Elixir implementation identifies itself as version
`0.0.1`. The project calls Symphony a trusted-environment engineering preview,
calls the Elixir runtime a prototype for evaluation, and recommends that users
implement a hardened version from the spec. This assessment therefore treats
the spec, implementation, bundled workflow, and product narrative as separate
surfaces rather than assuming every demo claim is a scheduler guarantee.

## Executive verdict

Symphony is useful prior art but the wrong runtime boundary for octo-lite.

Use it as a pinned design reference. Do not make it:

- an octo-lite dependency;
- a Turbo-Outreach dependency;
- an optional octo-lite execution backend;
- an octo-lite or Turbo fork;
- the control-panel backend;
- the source of Turbo workflow policy.

Reimplement a small set of its invariants inside the existing foreground
Claude/Herdr workflow helpers: workspace containment, reconcile-before-dispatch,
immediate stale-state revalidation, exact session identity, session-bound
configuration receipts, secret isolation, explicit retry metadata, and a
conformance-test mindset.

This is not NIH. Symphony's central product is explicitly a long-running
scheduler/runner service with its own claim state, retry timers, worker runtime,
prompt contract, and observability server. octo-lite has explicitly rejected
becoming a service and has selected Fable plus Claude Opus orchestrators as the
authority tree. Making Symphony optional would still introduce a second owner
for scheduling, policy, state, and workers.

## What Symphony actually is

The implemented runtime is approximately:

```text
repository-owned WORKFLOW.md
  YAML: tracker, polling, hooks, workspace, concurrency, Codex policy
  Markdown: complete first-turn agent prompt
                    |
           hot-reloaded WorkflowStore
                    |
      tracker read adapter (Linear in production)
                    |
        one in-memory Orchestrator authority
                    |
        supervised worker task per claimed issue
                    |
       persistent deterministic issue workspace
                    |
       one Codex app-server thread, up to N turns
                    |
  raw provider-native tracker tool + repo-local skills
```

It continuously polls active tracker states, reconciles current workers,
revalidates an issue immediately before dispatch, starts work within bounded
global/state/host concurrency, and retries failures with capped exponential
backoff. A successful turn is not itself completion: if the issue remains
active, the same Codex thread receives another continuation turn. Once the
worker exits, a short continuation retry checks whether another worker session
is needed.

The core scheduler has only two tracker reads:

```text
fetch_issues_by_states(states)
fetch_issues_by_ids(ids)
```

Ticket writes are deliberately not centralized in the orchestrator. The
bundled Linear adapter exposes raw `linear_graphql` to the coding agent and
executes it host-side with the configured token.

The isolation unit is a persistent directory per issue, not a fresh git
worktree per pass. VCS setup is outside the core. The sample `after_create`
hook performs a shallow clone and dependency setup; later synchronization is
delegated to prompt policy and skills.

The dashboard is a live view of the Symphony process: workers, retries,
blocked sessions, turns, tokens, rate limits, recent events, and runtime. It is
not an operation-level view of shaping, specs, role topology, independent
reviews, evidence, acceptance, deployment, or parent/child orchestrators.

## Strong ideas to adapt

### 1. Workspace containment as a launch invariant

Symphony validates both workspace creation and agent launch:

- the workspace cannot equal the configured root;
- it must remain under that root after canonicalization;
- local symlink escapes are rejected;
- the agent cwd is checked again when app-server starts;
- sanitized identifiers receive stable hash suffixes to avoid collisions.

octo-lite should retain those ideas and add the facts Symphony does not know:

- expected repository and remote;
- declared base and effective ancestry;
- exact worktree and branch owner;
- root Turbo `AGENTS.md` revision and inclusion from the declared base;
- role, model, effort, mode, and loaded-skill receipt;
- Linear readiness, spec, PR, and HEAD revisions.

Do not adopt Symphony's persistent mutable issue checkout. For our fresh-pass
model, use a stable local object/dependency cache plus a fresh dedicated
worktree for each implement, fix, review, re-review, QA capture, or QA review
instance. This preserves clean role boundaries without paying full network and
dependency bootstrap cost on every pass.

### 2. Reconcile before dispatch, then revalidate at the boundary

Symphony's useful ordering is:

```text
reconcile current workers
-> validate current workflow
-> fetch candidates
-> apply ownership and capacity checks
-> refetch the exact issue immediately before launch
-> claim and start
```

The foreground octo-lite equivalent should be:

```text
reconcile durable Linear/spec/PR/worktree facts
-> validate canonical generic and repo instruction revisions
-> verify shaped readiness and spec-derived TDD contract
-> verify no conflicting writer/resource owner
-> exact Linear and PR/HEAD readback
-> record parent-owned claim
-> spawn through the canonical role helper
-> record and validate the startup receipt
```

This should be a transaction in the existing Claude workflow, not a daemon,
poller, claim database, or timer service.

### 3. Narrow reads and role-gated writes

The two-read tracker kernel is a good abstraction for reconciliation. Full
normalized refreshes are valuable because state, labels, assignment, blockers,
and routing can all change after the first poll.

For octo-lite, use a small Linear-first read facade. Keep mutations behind
named role/authority helpers that perform:

```text
expected-current-state comparison
-> mutation
-> Linear readback
-> status artifact update
-> parent notification
```

Do not build a generic tracker plugin system yet. Do not expose Symphony's raw
Linear mutation surface to every worker. The Symphony documentation explicitly
states that `project_slug` scopes reads but not raw tool calls, and that the raw
tool has no idempotency key, retry, mutation scope guard, or rate-limit policy.

### 4. Exact execution identity

Symphony records a session as `<thread_id>-<turn_id>` and carries process,
workspace, issue, event, token, and timing data. The broader principle is
correct: never infer which session completed.

Our receipt should bind at least:

```text
provider session/thread/turn identity
OS process and Herdr pane/tab identity
parent and reply route
role, exact provider/model/effort/mode
repo/remote/worktree/branch/base/HEAD
AGENTS, role, role-skills, and loaded-skill revisions
Linear readiness, spec, draft PR, and brief revisions
```

This reinforces the ban on implicit `--last` and prevents a stale resumed
session from becoming evidence about a fresh fleet-wide outage.

### 5. Session-bound configuration snapshots

Symphony binds tracker adapter choice, tool declarations, and effective tracker
settings to an app-server session so a workflow reload cannot advertise one
tool and execute another. Apply that principle to the complete role envelope.

New octo-lite workers should snapshot canonical revisions when launched.
Changes affect future workers, not active ones. Unlike Symphony's general
last-known-good reload behavior, an invalid current canonical role or workflow
configuration should block a new role-bearing spawn rather than silently use
stale policy.

### 6. Failure and observability vocabulary

Useful fields to adapt into `status.md`, handoffs, and the optional panel:

- running, blocked, retrying, stopped;
- accountable owner and parent;
- attempt and failure class;
- due time or watched condition;
- last event and last real acknowledgment;
- process/session/workspace identity;
- exact gate, PR/base/HEAD, and spec revision;
- evidence/verdict revision;
- next automatic action and next operator action.

Keep Symphony's distinction between a clean continuation and a failed attempt.
Before retrying, add our stronger rule: inspect the prior worktree, commits,
process, output, and artifacts; preserve completed work; and start the next
role pass as a fresh instance.

### 7. Coupled lifecycle ownership

The Elixir implementation now supervises the orchestrator and its worker task
supervisor as one restart unit. That repaired a concrete bug in which workers
could survive an orchestrator restart and be redispatched by the fresh
authority.

The portable lesson is that the entity owning a child must also own its stop,
recovery, and cleanup path. In our hierarchy, every spawned worker needs one
named parent and reply route; orphaned sessions must not survive a parent
handoff as unowned work.

### 8. Conformance matrices

Symphony's spec enumerates configuration, containment, tracker, dispatch,
reconciliation, retry, app-server, observability, CLI, and real-integration
tests. That is a good structure for octo-lite workflow tests.

The first octo-lite matrix should cover:

- wrong cwd, remote, or repo;
- missing, stale, or un-ancestral Turbo `AGENTS.md`;
- copied rather than symlinked generic workflow/skill sources;
- wrong role, model, effort, or auto mode;
- missing required role skill;
- stale Linear/spec/draft-PR readiness;
- duplicate branch/worktree/resource writer;
- queued or visible text mistaken for submitted/acknowledged text;
- blocking review followed by fix without a fresh re-review;
- required DB tests silently skipped;
- dirty worktree cleanup refusal;
- stale session auth failure misclassified as a provider/fleet outage;
- missing evidence card despite a claimed acceptance gate.

## Direct conflicts with the approved operating model

| Area | Symphony | Approved octo-lite/Turbo direction | Decision |
| --- | --- | --- | --- |
| Runtime boundary | Long-running daemon, scheduler, retry timers, API | Foreground Fable/Opus sessions; octo-lite is not a service | Reject runtime |
| Authority tree | One in-memory scheduler launches Codex | Fable -> Opus orchestrators -> fresh Sonnet/Sol/QA roles | Reject topology |
| Worker continuity | Same Codex thread for up to 20 turns; persistent issue workspace | Fresh instance for every implement/fix/review/re-review/QA pass | Reject continuation |
| Prompt ownership | Repo-owned monolithic `WORKFLOW.md` | Generic roles/lifecycle in octo-lite; Turbo standing rules only in Turbo root `AGENTS.md` | Reject ownership |
| Installation | Copy workflow and optionally copy skills into target repo | Symlink generic installed sources; no copied octo mechanics in Turbo | Reject copying |
| Readiness | Active tracker state is sufficient; sample has no required label | Linear + canonical spec/ADR + same draft PR + operator walkthrough receipt | Reject eligibility |
| TDD | Reproduce and validate, but no spec-derived red-first gate | Spec-driven red/green/refactor is a hard rule | Reject workflow |
| Review | Same agent consumes feedback and can continue/land | Fresh independent Sol review and fresh re-review after every fix | Reject workflow |
| Rework | Close PR, delete workpad, create fresh branch | Preserve the same evolving draft PR and durable issue/spec identity | Reject workflow |
| Linear writes | Raw broad GraphQL by the coding agent | Role-gated compare/mutate/readback/notify transaction | Reject mutation model |
| Merge | Agent lands after human moves issue to `Merging` | Acceptance, merge, staging, preprod, and live remain operator-owned | Reject authority |
| QA evidence | Prompt/skills convention; demo emphasizes walkthrough video | Per-AC typed evidence; screenshots default, video only when needed | Reject default, keep concept |
| Dashboard | Live in-memory scheduler/runtime view with refresh control | Static read-only projection of durable operation/evidence/spec/role facts | Reject backend |
| Workspace | Persistent mutable clone per issue | Fresh one-writer worktree per pass with shared safe caches | Adapt isolation only |

## Gaps Symphony would not solve

Adopting the runtime would not solve the failures that motivated this audit:

1. It does not prove which `AGENTS.md`, role contract, or skills a worker
   loaded.
2. It has no Fable/Opus hierarchy, parent-owned brief, child status, or safe
   Herdr delivery semantics.
3. It has no shaped readiness record binding Linear, canonical spec, the same
   draft PR, and operator-walked AC.
4. It does not require spec-derived red/green TDD.
5. It does not independently enforce implementer/reviewer/fix/re-review/QA
   separation.
6. It does not provide exact-HEAD evidence, served-card readback, acceptance
   ledger, or deployment gates.
7. It does not distinguish queued TUI text from submitted or acknowledged
   control messages.
8. It does not classify auth failures across lane, session, account, provider,
   or fleet scope before broadcasting an outage.
9. It does not optimize our repeated fresh-worktree bootstrap and build path.
10. Its dashboard cannot represent our whole operation or editable canonical
    role configuration.

## Reliability and safety findings in the reference implementation

These findings reinforce the preview warning and should prevent uncritical
adoption.

### No provider-level circuit breaker or outage classifier

Failures retry per issue with deterministic capped exponential backoff. There
is no shared Codex auth health state, no fresh exact-model probe before an
outage declaration, or provider/account circuit breaker. A revoked or stale
credential can therefore create simultaneous failed lanes and synchronized
retries. Rate limits are displayed, not used for admission control.

This is especially incompatible with our observed false fleet-outage incident.
Borrow the metadata and backoff vocabulary, but keep our required evidence-led
failure classification and accountable provider admission control.

There is also no jitter, so lanes failing together can retry together. A
separate display of rate-limit telemetry does not apply backpressure or pause
new work.

### Scheduler state is memory-only

Claims, running sessions, retries, blocked items, and live thread identity are
lost on restart. Workspaces persist and tracker state drives recovery. The
implementation explicitly notes that a blocked issue may be dispatched again
after restart. This is reasonable for a prototype but insufficient as an
authoritative delivery control plane.

Normal completion also has no terminal retry budget. If the issue remains in
an active state after the configured turn cap—because a state mutation failed,
for example—the orchestrator starts another worker after one second. Failures
retry without a maximum-attempt budget or permanent/transient classification.
The result can be an indefinite high-cost continuation or retry loop.

### Raw Linear authority is broader than the scheduler scope

The host protects the token from the child process, which is good. The exposed
raw GraphQL tool can nevertheless act anywhere the token can act. Prompt text
owns idempotency, mutation scoping, and rate-limit behavior. A malicious or
mistaken issue prompt can cross the scheduler's project boundary.

### The child environment and approval posture are intentionally high trust

The launcher removes declared tracker-token variables, but otherwise starts
the app-server through an inheriting host shell. The bundled command explicitly
requests full shell-environment inheritance and enables turn network access.
The default turn sandbox limits writes to the workspace but grants full
read-only host access. Protecting `LINEAR_API_KEY` therefore does not protect
unrelated credentials, config files, source trees, or host data from a
prompt-injected issue.

The implementation also derives `auto_approve_requests=true` when
`approval_policy` is `never`. If app-server still emits command or file-change
approval requests, the harness approves them for the session. For structured
user-input prompts it searches option labels and selects labels beginning with
`approve` or `allow`. That is acceptable only inside the project's stated
trusted, unattended preview posture. It is not a substitute for our named
acceptance, merge, deployment, or traffic-shift authority artifacts.

### Claims and workspace ownership are local to one process

The in-memory claim set prevents duplicate dispatch inside one orchestrator.
There is no cross-process lease, filesystem lock, or external owner check. Two
Symphony processes pointed at the same tracker and workspace root can dispatch
the same issue and write the same checkout, branch, PR, and Linear workpad.

We do not need a lease service, but our foreground preflight must prove one
parent, one worktree owner, and one writer before mutation.

### Workspace preparation and deletion can lose useful state

If a new workspace's clone or dependency bootstrap fails partway through, the
directory remains. The retry sees an existing directory, skips the
`after_create` bootstrap, and can run in a partial checkout. A safe bootstrap
needs a completion marker or atomic staging/rename.

At the other end of the lifecycle, `before_remove` failure is deliberately
ignored and deletion continues. If that hook was supposed to preserve a dirty
workspace, push a branch, archive evidence, or close a PR, its failure does not
stop `rm -rf`. That directly conflicts with our rule that dirty or
not-yet-durable work blocks cleanup.

There is also no global registry, TTL, quota, disk/inode admission check, or
cleanup path for issues that become deleted, inaccessible, renamed, or leave
the configured scope. The default workspace root is under the system temp
area, so stale workspaces can recreate the disk-exhaustion class already seen
in our fleet.

### Liveness is activity-based, not progress- or deadline-based

Turn and stall handling primarily detect silence. Incoming messages restart
the receive timeout, and the orchestrator measures inactivity from the last
event. A chatty but non-progressing session can therefore remain alive
indefinitely. We should distinguish:

- absolute pass deadline;
- event inactivity;
- lack of observable product progress;
- waiting on a named external condition.

No arbitrary stage-duration SLA is required, but every pass still needs an
accountable watched condition and recovery action. This is Symphony-comparison
analysis, not an octo-lite recommendation: octo-lite's own liveness rule is
activity-based, and timeout alone is never failure.

### Worker termination does not prove process-tree cleanup

Stopping the BEAM task and closing the app-server port does not establish a
process group, cgroup/container boundary, child PID registry, or remote kill
receipt. Servers, shell descendants, ports, or SSH-side processes may survive.
This is the same leaked-process/resource class in the audit. Our pass receipt
must record owned PIDs, ports, fixtures, and teardown proof.

### Remote containment is weaker than local containment

Local workspace validation canonicalizes paths and detects symlink escape.
Remote validation rejects empty/control-character paths but does not prove
canonical containment beneath the remote root before launch.

### The optional HTTP surface has no authentication layer

The dashboard and JSON routes have no authentication middleware. The API
exposes issue/session identity, worker host, absolute workspace path, recent
messages, errors, and rate-limit state, and it accepts `POST /api/v1/refresh`.
Loopback is the safe default, but binding the service broadly exposes
operational metadata and a control trigger without TLS or authentication.
This reinforces the choice to keep the hosted octo-lite panel a static,
read-only projection. octo-lite itself adds no access-control, redaction,
retention, or broken-link subsystem (Decision 90); a redaction layer would be
Symphony's own gap to close, not an octo-lite recommendation.

### The documented startup command is currently incomplete

The CLI requires
`--i-understand-that-this-will-be-running-without-the-usual-guardrails`, but
the README's primary source-run and packaged-run examples omit it. Following
the documented command fails before startup.

### The coverage percentage is not meaningful for the runtime

The Mix project sets a 100% threshold while excluding nearly every core
runtime, scheduler, workspace, tracker, app-server, CLI, and dashboard module
from coverage. There are many substantive tests, including real-process and
optional live E2E tests, but the headline coverage gate cannot be interpreted
as 100% runtime coverage. This is exactly why our validation handoff must
record executed/skipped tests and environment capability, not only a green
aggregate gate.

### The sample bootstrap trades speed for isolation but still repeats work

Each newly created issue workspace performs a network clone and Elixir
dependency setup. Persistent reuse avoids repeating it within that issue, but
creates stale mutable-state risk and does not support fresh role-pass
worktrees. The better translation for us is a local bare/object cache,
dependency-store reuse, and fast ephemeral worktrees with per-pass ownership.

## What the OpenAI narrative changes in our thinking

The official write-up supports several strategic choices already made:

- manage deliverables rather than babysit terminal sessions;
- use the tracker as the visible work control plane;
- let agents execute routine, well-harnessed work continuously;
- invest in repository tests, guardrails, skills, and documentation;
- use dependencies to unlock safe parallelism;
- preserve a human interactive path for ambiguous or judgment-heavy work;
- avoid treating intelligent agents as tiny rigid state-machine nodes;
- give an accountable agent an objective plus tools and context.

That last point is important. Our hard gates should protect authority,
evidence, identity, and irreversible transitions. They should not prescribe
every reasoning step inside an Opus orchestrator's coherent stream. The
approved `brief.md` shape—hard invariants, owned scope, standing authority, and
must-escalate conditions—is more consistent with Symphony's lesson than a
large policy compiler or micro-step workflow would be.

The write-up also says not every task fits unattended Symphony-style work.
That validates the direct-conversation path with an Opus orchestrator for
ambiguous or expert work; it does not justify bypassing spec, TDD, independent
review, evidence, or operator-owned ship gates.

The reported throughput gains are evidence that issue-level autonomy can be
valuable, not evidence that this specific prototype or bundled workflow fits
our authority model.

## Recommended classification

| Option | Decision | Rationale |
| --- | --- | --- |
| Direct dependency | Reject | Adds an Elixir daemon, scheduler, prompt runtime, and Codex execution authority. |
| Optional backend | Reject | Optionality still creates a second scheduler and policy/state owner. |
| Fork | Reject | Removing incompatible core behavior would discard most of the product while retaining maintenance burden. |
| Ignore | Reject | Several small invariants are directly useful. |
| Pinned reference | **Recommend** | Reimplement selected ideas inside current foreground Claude/Herdr helpers. |

The clean boundary is:

```text
cite Symphony as prior art
copy no runtime
vendor no code
add no Turbo dependency
create no second state owner
implement only selected invariants in octo-lite helpers and tests
```

## Proposed additions to the operating-model backlog

Unless explicitly marked approved below, these remain shaping candidates rather
than pre-approved implementation tasks:

1. **Approved in minimal form by operating-model Decision 55:** define one
   foreground launch preflight and compact startup receipt using Symphony's
   containment and stale-dispatch patterns, with checks only at provisioning
   and child bootstrap and no daemon or giant manifest.
2. **Approved in minimal form by operating-model Decision 56:** one exact
   gate-read function plus named role-authorized compare/mutate/readback/status/
   notify transitions; exploratory reads remain direct, with no generic tracker
   service, plugin system, cache, mirror, poller, or read ACL.
3. **Approved in minimal form by operating-model Decision 58:** failed or
   interrupted passes add a small existing-status/handoff record, the owner
   inspects and preserves work, and any retry uses a fresh instance. Keep the
   already-approved fresh exact-model probe for suspected auth/provider scope;
   defer circuit breakers, jitter, timers, and automatic retry machinery until
   measured recurring failures prove they are needed.
4. **Approved in minimal form by operating-model Decision 57:** use a clean
   control clone for shared Git objects, native target-owned dependency/download
   caches, and fresh per-pass worktrees with private mutable dependency trees;
   measure cold and warm bootstrap before adding machinery, and build no cache
   service or persistent mutable issue checkout.
5. Deferred optional presentation idea: show exact session/worktree identity,
   attempt/failure class, watched condition, and last acknowledged message only
   when it materially improves the approved control-panel view.
6. **Approved in minimal form by operating-model Decision 59:** add a local,
   append-only, Langfuse-shaped trace projection at meaningful workflow
   boundaries and one path-filtered CI checker over generated happy and
   failure/retry traces plus a few invalid fixtures. Keep target-specific DB
   and served-card validation in the target repo. Build no trace service,
   collector, exporter, broad Cartesian conformance matrix, or independent
   trace-retention machinery. Runtime traces inherit their stream control
   directory lifecycle under Decision 60. Runtime trace failure warns once and
   remains non-blocking under Decision 61; CI contract validation still blocks.
   Only deterministic workflow and gate helpers write under Decision 62.

## Grill closure

The Symphony boundary is reference only. Decisions 60 through 62 resolved
runtime trace lifecycle, failure semantics, and writer ownership.
