# Optimal Operating Model Grill

Status: complete through Decision 94. The decision table is the chronological
authority for this audit. Earlier questions and recommendations are historical
grill material and may be superseded by later rulings.

## Grill protocol

This document began as an agenda, not a questionnaire to answer in bulk.

During the live grill:

- Ask one question at a time.
- Lead with the problem in operator terms.
- Include a recommended answer and its trade-off.
- Record the ruling immediately.
- Carry the ruling's revision into later questions.
- Do not silently choose a side when the answer changes the system shape.

## First-principles invariants to test

These are proposed constraints, not yet approved:

1. One canonical owner exists for every fact.
2. No worker mutates state until it proves which instructions and scope it
   loaded.
3. No downstream gate starts without a clear exact-head upstream artifact.
4. Chat, visible TUI text, and memory never grant irreversible authority.
5. Product/dev state is represented once; supporting ledgers do not become
   competing state machines.
6. Target-specific policy lives with the target repo.
7. Generic role and workflow mechanics are generated from one octo-lite source.
8. Every ephemeral resource has an owner, TTL, and cleanup path.
9. The operator view is outcome-first and makes the next human action obvious.
10. Recovery is explicit and resumable; it does not depend on reconstructing a
    long session's private context.

## Decision 1: optimization target

**Problem:** The current system often maximizes parallel activity, then pays for
it in correction, verification, and operator supervision.

**Recommended answer:** Optimize first for trustworthy, observable delivery;
second for operator latency; third for throughput; and fourth for token/compute
cost.

This does not mean serial execution.
It means parallelism is valuable only when ownership and gates remain legible.

Questions to resolve:

- Is this priority order correct?
- What measurable failure budget is acceptable for stale-head, wrong-base,
  missed-message, and unreviewed-fix incidents?
- Which delays feel worse: waiting on a hard gate or discovering late rework?

## Decision 2: definition of ready and test contract

**Problem:** `Shaped` currently does not prove a docs-backed grill, user-voiced
story, AC walkthrough, durable spec/ADR revision, or test-first contract.
Orchestrators can assert that these happened and immediately launch a loop.

**Recommended answer:** `Shaped` means a machine-verifiable readiness
attestation matches the current Linear issue, canonical spec/ADR blobs, same
draft-PR readiness HEAD, relevant grill-log cutoff, and a clear independent
post-grill shaping review. Every behavior change uses spec-driven TDD by
default, with red/green evidence; a narrow test waiver must be approved during
shaping and name the alternative evidence.

Resolve:

- Is test-first the default for every behavior-changing slice?
- Which work classes can receive a waiver: docs-only, generated artifacts,
  one-time operations, visual-only styling, or something narrower?
- Must a changed spec or acceptance criterion automatically invalidate ready?
- Does the operator personally approve every ready attestation, or may a
  delegated shaper approve low-risk mechanical work under a standing rule?
- Where does the grill/AC walkthrough artifact live so Linear remains the
  primary issue/status truth without bloating the issue body?

## Decision 3: unit of delivery and branch topology

**Problem:** Current instructions assume `main`, while live operations often use
`next-candidate` and stacked integration branches.
This drives PR-base flips, review disputes, and incorrect `In Staging` state.

**Updated recommendation after operator correction:** Keep the Linear
issue/spec/draft-PR identity stable, but make branch topology a separate,
versioned delivery contract. The same draft PR may target `main`, an explicit
release train, or a predecessor branch in a stack. Retargeting is allowed when
the topology revision authorizes it and automated checks prove the intended
spec diff and commit ancestry. A base/diff change invalidates review and QA,
but does not invalidate shaping unless behavior, scope, AC, or spec changes.

Alternatives:

- Always target an integration branch and cut batches to `main`.
- Use stacked PRs with predecessor PR bases, then retarget after merge.
- Use main-targeting PRs from stacked commits and accept temporarily wide
  diffs.

Follow-on rulings:

- Which topology transitions are standing-authorized versus operator-approved?
- Who owns stack/train creation and retargeting?
- What event makes code "in staging"?
- Can an accepted issue remain `Awaiting Accept` until its train reaches main,
  with acceptance represented only in the ledger?
- Who owns train order, cut, rollback, and partial removal?

## Decision 4: authority model

**Problem:** Operator words are relayed across several sessions and can be
superseded or mistaken for TUI text.

**Simplified recommendation after operator complexity check:** Do not build a
hierarchical policy engine. Every spawned orchestrator receives one
self-contained authority brief with four sections: hard invariants, owned
scope, standing authority, and must-escalate conditions. A parent may have
several levels above it, but it flattens the effective rules into the child's
brief and names the parent brief for traceability. The child acknowledges one
brief hash at spawn.

Routine instructions then travel through ordinary acknowledged messages with
no authority metadata attached. Only a material change to the four-section
brief requires a new revision and acknowledgment.

Resolve:

- Which actions need explicit per-event authority?
- Which reversible actions are standing authority for a stream orchestrator?
- Which rules belong in the small global hard-invariant set?
- What may the parent decide locally when flattening a nested child's brief?
- Who may mark issues ready, accepted, merged, staged, preprod, and live?
- How are partial transactions repaired?

## Decision 5: session topology

**Problem:** Long-lived sessions accumulate unrelated context, while disposable
workers lose repo and role instructions.

**Current approved answer:** Decisions 5 and 93 require exactly one dedicated
Opus issue orchestrator per implementation issue. A multi-issue epic adds one
separate Opus epic orchestrator above those issue orchestrators. Every
post-grill shaping review, implementation, fix, review, re-review, QA capture,
and QA-review pass uses a fresh disposable instance. No worker session is
resumed for a later cycle.
Continuity lives in the canonical spec, Linear issue, evolving PR, exact HEAD,
review artifact, and durable handoff, making every worker independently
replaceable. An issue orchestrator terminates when its issue completes; an epic
orchestrator terminates when its epic completes. Neither session is recycled
for later work, including a related follow-on issue or epic.

Resolve:

- When is a stream large enough to deserve an orchestrator?
- Should a completed session always be killed rather than reused?
- Superseded by Decision 93: one issue orchestrator never owns several issues.
- What context belongs in the brief versus the decision ledger?
- Should every Claude orchestrator be required to launch in auto mode while
  retaining only the authority granted by its signed brief? Recommended: yes,
  and fail bootstrap if the runtime mode cannot be verified.
- What minimum durable input envelope must every fresh worker receive so that
  session memory is never required for correctness?

## Decision 6: instruction precedence

**Problem:** Global policy, role profiles, repo files, specs, memory, and live
briefs overlap.

**Recommended answer:** Use this ownership model for non-conflicting domains:

1. Target repo spec/ADR is the implementer's detailed behavioral and acceptance
   contract.
2. Linear owns issue identity, the high-level objective, material decisions and
   context, non-goals, and lifecycle status.
3. Target repo `AGENTS.md` and target adapter own repo mechanics.
4. Versioned octo-lite role/kernel contract owns generic workflow mechanics.
5. The explicit operator ruling and relevant conversation log drive shaping
   reconciliation but are not a substitute implementation contract.
6. Memory is a non-authoritative pointer only.

An operator ruling takes effect immediately as a product decision, but it must
be reconciled into the spec and, where material at the high level, Linear before
implementation. A worker that sees an unreconciled ruling or source conflict
stops and returns to shaping rather than choosing by precedence.

Resolve conflict behavior rather than relying only on ordering:

- Which conflicts must stop and return to shaping?
- Should stale branches consume branch-local instructions, current target
  baseline instructions, or both with an explicit diff?
- Does `CLAUDE.md` remain, and if so what is allowed in it?

## Decision 7: memory policy

**Problem:** Memory captures valuable gotchas but also preserves obsolete state
and rulings.

**Recommended answer:** Keep incident memories as dated, scoped, supersedable
pointers to versioned fixes; ban live status and standalone policy.

**Approved boundary:** Memory is non-authoritative. It may record a dated
failure mode, gotcha, or pointer to a durable source, but it cannot establish
current scope, status, authority, lifecycle state, or policy. Load-bearing
truth must live in Linear, the canonical spec/ADR, target-repo instructions,
the active authority brief, or another named versioned contract.

Any role may write a short evidence-backed gotcha. Keep the format minimal:
date, scope, observed failure, and durable source/fix link. There is no memory
registry, compiler, approval workflow, or automatic policy extraction. The
bounded stream orchestrator reviews, promotes, supersedes, or deletes entries
when closing the stream.

Resolve:

- Who may write memory?
- Should the index be generated and linted for superseded entries?
- What expires automatically?
- Which current memories should move into Turbo runbooks, specs, or octo-lite
  tests?

## Decision 8: inter-agent messaging

**Problem:** Visible text is not proof that a message was submitted or accepted.

**Recommended answer:** Use durable message IDs and explicit accepted/completed
acks; orchestrators escalate unacknowledged messages after a bounded timeout.

**Approved scope:** Explicit recipient acknowledgment is required only for
control messages: commands, operator rulings, ownership transfers, and blocking
questions. Routine status/FYI messages do not require an acknowledgment.
There is no fixed acknowledgment timeout. A dependent action cannot proceed
until acknowledgment arrives; unrelated work may continue, and the control
view shows the message as awaiting acknowledgment.
Queued text may auto-submit once the recipient is at a verified safe prompt.
It must never inject or press Enter while a modal/question dialog is active.

Resolve:

- Is accepted ack required for every message or only commands/decisions?
- What is the timeout by message class?
- Can queued inbox messages auto-submit, or must a recipient explicitly drain?
- What evidence counts as completed?

## Decision 9: review and QA gates

**Problem:** The workflow can proceed after a fix without re-review and can bind
evidence to stale heads.

**Recommended answer:** A single exact-head chain:

```text
implementation handoff
  -> clear code review
  -> QA capture manifest
  -> independent QA verdict
  -> explicit operator acceptance
  -> merge transaction
```

Any HEAD change invalidates downstream artifacts from the changed point.

**Approved cycle bound:** At most three review/fix cycles. Each fix and
re-review uses a fresh instance. If the third cycle does not clear, stop and
return the issue to shaping; do not launch a fourth blind retry.

**Approved invalidation boundary:** A change to executable code, tests, or a
canonical spec/ADR invalidates the clear review and all downstream QA. A change
limited to evidence metadata, acceptance-packet wording, or other non-product
bookkeeping preserves those gates, provided the effective product diff and
tested HEAD content are unchanged. Apply this as a plain judgment rule:
behavior/contract changed means rerun; only packet/evidence wording changed
means do not rerun. Do not build a hash protocol, file classifier, or automated
invalidation engine.

Resolve:

- Maximum review/fix cycles before return to shaping.
- When visual QA is required.
- What is the nonvisual evidence equivalent.
- Whether minor docs-only changes can preserve earlier QA.

## Decision 10: state semantics

**Problem:** Nine Linear states, the acceptance ledger, integration branches,
and deployment position do not currently reconcile.

**Recommended answer:** Linear state represents observable lifecycle position;
acceptance remains a ledger fact; deployment states move only when the named
environment actually carries the accepted commit.

**Approved staging meaning:** `In Staging` means merged to `main`, which deploys
the commit to staging. A merge into `next-candidate`, a stacked predecessor, or
another integration branch is not `In Staging`.

**Approved accepted-train state:** Operator acceptance is recorded in the
acceptance ledger. Until the accepted train/member actually merges to `main`,
the Linear issue remains `Awaiting Accept`; do not add another Linear state.

**Approved promotion meaning:** `In Preprod` means a verified preproduction
candidate exists at 0% live traffic. `Live` means the operator-authorized
traffic shift actually occurred.

Resolve:

- State after operator accepts but before merge.
- State after integration-branch merge but before main/staging.
- Whether `In Staging` means merged to main or verified running in staging.
- Owner and proof for `In Preprod` and `Live`.

## Decision 11: resource and workspace admission

**Problem:** Worktree sprawl, disk exhaustion, shared DB fixtures, 529s, OOMs,
ports, and leases are managed through conventions and memory.

**Recommended answer:** A lightweight local scheduler/registry owns capacity,
worktrees, ports, fixtures, processes, and shared mutation leases.

**Approved simpler starting point:** Do not build a scheduler service yet.
Before every expensive spawn, the accountable orchestrator checks that disk is
healthy, the worker has an isolated worktree, no other owner holds the same
branch/database fixture/port/deployment lease, and the selected provider is not
actively failing from overload. Unsafe capacity waits; no numeric quota system
is required initially.

Worker worktrees are removed when the pass completes. If a worktree is dirty,
cleanup stops and the orchestrator inspects/reconciles the changes; it is never
silently deleted or abandoned.

For state-mutating QA, verify the fixture's starting state, ensure no concurrent
lane is using it, and record it in the QA manifest. Create a unique local
fixture when the existing test path already supports that cheaply. Read-only QA
may share stable fixtures. Do not build a fixture allocator or lease database.

Resolve:

- Maximum concurrent implementation, review, and QA lanes.
- Whether capacity is per model, host, repo, or shared state.
- Worktree retention and dirty-worktree escalation.
- Who can preempt a lane and how its state is preserved.

## Decision 12: operator control surface

**Problem:** Issue/run/tab identifiers do not answer what outcome is moving,
who owns it, which gate it is at, or what the operator must do next.

**Recommended answer:** The primary view is outcome-first and groups work by
epic/product outcome, with issue/PR IDs as secondary references.

**Approved reporting direction:** Stream orchestrators produce outcome-first
updates for their parent/meta-operator; the meta-operator and operator control
surface present the same ordering to the human operator. Lead with product
outcome, current gate, blocker, and next operator action. Issue/PR/run IDs are
secondary references.

Proactively push only required decisions, blockers, failures, and meaningful
gate or outcome changes. Routine progress remains available on demand.

**Approved primary surface:** Prefer the TopicFinder-dev website/cards/Kanban
as the primary view of the entire operation, not only QA evidence. It must make
all workstreams, outcomes, owners, gates, dependencies, blockers, and next
actions accurate and easy to digest. Until it meets that bar, the meta-operator
still provides a complete overall workstream update so the operator never has
to reconstruct the fleet from partial cards.

The TopicFinder operator website, evidence generators, target paths, and
target-specific lifecycle presentation live in Turbo-Outreach. Octo-lite owns
only generic role, workflow, state-contract, and adapter mechanics.

Minimum fields:

- Outcome and epic.
- Accountable orchestrator.
- Current exact gate and age.
- Issue, PR, branch/train, and HEAD.
- Blocker and owner.
- Last acknowledged message.
- Next automatic action.
- Next operator action.
- Evidence/decision links.

Resolve:

- Whether Herdr tabs remain issue-first.
- Which status is pushed versus inspected on demand.
- What counts as stale and how it is highlighted.

## Decision 13: migration strategy

**Problem:** Rewriting every prompt at once would mix operating-model decisions
with implementation risk.

**Recommended answer:** Migrate in fail-closed slices:

1. Readiness attestation, Linear revision, and spec/TDD contract.
2. Instruction manifest, correct cwd, auto mode, and repo bootstrap.
3. Exact-session relay and acknowledged messaging.
4. Exact-head review/QA state machine and reviewer identity.
5. Target config extraction and source/install unification.
6. Workspace/resource registry.
7. Memory cleanup and operator control surface.

**Approved migration timing:** There is no active work to preserve during this
migration. Perform the operating-model cutover now as one coordinated repo-level
change, with validation before new work starts; no live-lane compatibility
period is needed.

Resolve:

- Whether to freeze new workflow features during migration.
- Which active streams can safely adopt the new bootstrap first.
- What compatibility period is acceptable.

## Decision 14: post-grill reconciliation review and implementation source

**Problem:** A shaper can finish a long operator grill yet miss a ruling,
preserve a contradiction, or let the Linear issue, spec, TDD contract, and
evolving draft PR diverge. Sending the same shaper directly into readiness
does not provide an independent check.

**Approved answer:** After the operator grill and source reconciliation, run a
fresh Codex `gpt-5.6-sol` shaping reviewer at xhigh reasoning effort on the
fast service tier. It reads the canonical spec/ADRs, complete relevant
conversation logs through an explicit cutoff, current Linear issue, target
repo instructions, same draft-PR readiness HEAD, and proposed TDD contract.
It is read-only and returns `clear` or `blocking` with source pointers and a
reconciliation owner for each finding.

The reviewer receives raw durable transcript/session references plus the
declared issue/stream log scope, records every log and cutoff inspected, and
blocks if a relevant log is missing or inaccessible. A curated summary alone
is not sufficient review input.

The canonical spec/ADR is the implementer's primary detailed behavioral
contract. Linear remains the primary tracker and holds issue identity,
high-level objective, material decisions/context, non-goals, and lifecycle
status; it links to rather than duplicates the detailed spec. Conversation
logs evidence operator rulings for reconciliation and audit but are not an
implementation contract.

A documentary mismatch returns to the issue shaper. A missing product judgment
resumes the operator grill one question at a time. The reviewer neither edits
the sources nor invents the resolution. Any material reconciliation to a
reviewed spec, Linear decision/context, log cutoff, or readiness HEAD requires
another fresh shaping review. Only a clear verdict bound to the exact source
revisions permits `Shaped` and implementation.

## Decision 15: minimal launch boundary

**Problem:** Symphony's containment, stale-dispatch, and execution-identity
ideas address observed wrong-cwd, stale-source, and cross-lane continuation
failures, but its complete scheduler/runtime model and a giant immutable spawn
manifest would make octo-lite too heavy.

**Approved answer:** Use one canonical foreground role-spawn helper. Ordinary
orchestration reconciles durable stream facts; immediately before dispatch the
helper refetches the exact Linear issue revision/status and current PR
base/HEAD, verifies pinned spec/readiness inputs, provisions a fresh worktree
beneath an allowlisted root, and launches the exact role there.

Containment is validated exactly twice: when provisioning and inside the child
before mutation. Each check canonicalizes cwd and verifies git root, remote,
worktree identity, expected starting HEAD, and target root `AGENTS.md`; the
workspace root itself, collisions, traversal, and symlink escapes are rejected.

The child returns one compact bootstrap acknowledgment bound to the spawn ID,
exact provider session, parent/reply route, actual role/model/effort/mode,
repo/worktree/starting HEAD, instruction and loaded-skill revisions, Linear
readiness, spec, PR/base/topology, brief, and shaping-review revision when
applicable. Implicit continuation such as `--last` is prohibited. Final HEAD
belongs in the handoff; process/pane/turn IDs remain ephemeral unless needed
for cleanup or diagnosis.

There is no global reconciliation service, per-command cwd validation,
cryptographic receipt chain, or giant spawn manifest.

## Decision 16: minimal Linear correctness boundary

**Problem:** Gate-critical reads can become stale and Linear mutations have
repeatedly appeared successful without changing the board. Wrapping every
tracker interaction or creating a generic tracker subsystem would add more
machinery than value.

**Approved answer:** Add one Linear-specific `read-exact` workflow function for
dispatch, readiness, and lifecycle gates. It returns the complete issue plus
stable identity, revision, and current status. Shapers and operators retain
direct read-only exploration.

Every mutation uses a named role-authorized helper that compares expected
state, mutates once, reads Linear back, updates `status.md`, and notifies the
parent. It reports success only when the resulting facts agree. A partial
failure records the unfinished step and retries only that idempotent remainder;
it never blindly repeats the state mutation.

These are small foreground workflow functions. There is no generic tracker
plugin layer, service, cache, mirror, polling loop, read permission system, or
octo-lite-owned copy of Linear state. Their tangible value must remain covered
by stale-read and false-success conformance tests.

## Decision 17: fast fresh worktrees

**Problem:** Fresh instances and per-pass worktrees protect role and branch
isolation, but repeated network clones, cold dependency downloads, and missing
worktree dependencies have produced long setup times, `Cannot find module`, and
disk pressure. Persistent mutable issue checkouts would recover speed by
giving up the isolation the operating model requires.

**Approved answer:** One clean control clone supplies shared Git objects to a
fresh worktree for every role pass. The target repo owns one fail-fast bootstrap
command and may reuse native safely shareable caches. Each worktree keeps its
own mutable dependency tree and ordinary build outputs; a cache miss falls back
to the normal correct install.

octo-lite defines only the generic boundary. Turbo owns its repo-specific
implementation: its checked-in nested npm lockfiles, a native shared npm
download cache, compatible reusable Puppeteer/browser downloads, and
per-worktree `node_modules`. Measure cold and warm bootstrap before adding any
further cache layer.

Do not build a cache daemon, dependency service, custom registry, shared or
copied mutable `node_modules`, or persistent mutable issue checkout. Cache
corruption must be discardable without losing source or completed work.

## Decision 18: minimal failure and retry record

**Problem:** Timeouts, kills, stale-session auth failures, and provider errors
have triggered duplicate work or over-broad outage claims because prior
workspace state was not inspected and the original failure was not preserved.
A retry scheduler and detailed failure system would be disproportionate.

**Approved answer:** Only a failed or interrupted pass adds a small record to
the existing stream `status.md` or handoff: attempt and exact
session/worktree/starting HEAD; original error or output reference; one class
(`input/contract`, `environment`, `provider/session`,
`implementation/validation`, or `external dependency`); useful work found
(`none`, `uncommitted`, `committed`, `pushed`, or `artifact produced`); owner
and next action; and whether a fresh retry is safe or shaping/operator action is
required. If the worker cannot report, its accountable orchestrator records the
inspection result.

Before retrying, the orchestrator inspects the prior worktree/process/output,
preserves useful work, and gives a fresh role instance an envelope pointing to
it. A response timeout alone is not proof that work failed. Successful passes
add no failure metadata.

There is no retry database, timer, automatic scheduler, circuit breaker,
jitter policy, or elaborate taxonomy. Those remain deferred until measured
recurring failure demonstrates that the small record is insufficient.

## Decision log

Record each ruling here during the grill:

| Revision | Decision | Ruling | Consequences | Follow-up question |
| --- | --- | --- | --- | --- |
| 0 | Audit baseline | No operating-model rulings yet | Prompt changes remain proposed | Decision 1 |
| 1 | Optimization target | Approved: optimize first for trustworthy, observable delivery; second for operator latency; third for throughput; fourth for token/compute cost. Zero tolerance for wrong repo/instructions, treating unacknowledged commands as delivered, wrong-base changes, unreviewed HEADs reaching QA, and lifecycle state without evidence. | Parallelism and speed are subordinate to fail-closed bootstrap, messaging, exact-head, base, and state gates. | Decision 2 |
| 2 | Definition of ready and test contract | Approved: spec-driven TDD is a hard rule. Every behavior-changing implementation begins with a failing test derived from the canonical spec and records red/green evidence. Shaping cannot be called complete without a linked Linear issue, PR, and canonical spec. Scope, AC, or spec changes invalidate readiness. | Remove `TDD where practical`; readiness must attest all three durable artifacts and the exact revisions that agree. | Decision 2a |
| 3 | Shaping PR topology | Approved: shaping and implementation use the same evolving draft PR. The Linear issue, PR, and canonical spec are bound as one unit so they cannot diverge. Shaping establishes a signed readiness commit; implementation continues on the same branch/PR. A later contract change returns that PR to shaping. | Preserve one issue/branch/PR through the lifecycle; distinguish the signed shaping commit from later implementation HEADs inside the same PR. Do not create a separate spec PR. | Decision 3 |
| 4 | Branch flexibility constraint | Rejected a permanently immutable shaping-time PR base. Opening the shared draft PR must not foreclose stacked branches, integration trains, or other deliberate topologies that provide velocity. | Separate stable issue/spec/PR identity from a versioned topology contract. Retargeting must be explicit and diff/ancestry-verified; review and QA are invalidated when the effective diff changes. | Decision 3a |
| 5 | Topology authority | Approved: the stream orchestrator has standing authority to select and revise `main`, stacked-branch, and integration-train topology without per-change approval. Every transition records a topology revision, proves merge-base/ancestry/effective diff, preserves signed scope, and invalidates affected review/QA. Escalation is required only when ship grouping, product scope, or material risk changes. | Branching remains a velocity tool while topology changes become observable, testable transitions rather than prompt convention. | Decision 3b |
| 6 | Release-train representation | Approved: every multi-PR release train is a first-class delivery object with a carrier PR and machine-readable manifest listing member Linear issues, PRs, pinned HEADs, order, integration branch, target, owner, and gate status. Linear remains the issue identity, high-level scope/decision, and status record; the manifest owns delivery topology only. | Branch names are no longer treated as sufficient train identity or membership evidence. Member issues reference the train without duplicating its topology state. | Decision 4 |
| 7 | QA evidence default | Approved direction: screenshots cover most stable states; video is required only when motion, sequence, timing, media playback, or interaction cannot be proven honestly with stills. | Remove workflow-wide mandatory video. Select evidence type per AC and state the proof rationale. Exact sufficiency rules will be completed at Decision 9. | Decision 4 |
| 8 | Authority-model constraint | Rejected a flat rule requiring one central decision ID for every cross-session ruling. Meta-operators and nested orchestrators may carry different rules and stack several levels deep. | Replace the flat ledger with inherited, locally refinable authority envelopes and compiled effective-rule hashes; reserve durable ruling revisions for material changes. | Decision 4a |
| 9 | Authority complexity check | The full override-class/inheritance compiler is deferred as overengineering. Use a self-contained four-section authority brief per orchestrator: hard invariants, scope, standing authority, and must-escalate conditions. Parents flatten relevant rules for nested children; one brief hash is acknowledged only at spawn or material revision. | No policy engine and no authority token on routine messages. Add machinery later only if real conflicts survive the simpler contract. | Decision 4b |
| 10 | Authority model | Approved: use the simple four-section authority brief. Nested parents flatten the effective rules for each child; the child acknowledges the brief at spawn. Routine messages need no policy metadata. | Implement the minimum contract first and add inheritance machinery only in response to observed failures. | Decision 5 |
| 11 | Implementer/reviewer model split | Approved: implementation and every fix pass use exact Anthropic `claude-sonnet-5` at xhigh effort; code review and re-review remain Codex `gpt-5.6-sol` at high effort. Do not use rolling aliases. | Preserve cross-provider review while replacing Luna Ultra. Runtime metadata must attest the actual model; a fresh-session probe distinguishes stale session auth from provider/fleet outage. | Decision 5 |
| 12 | Worker session lifecycle | Approved: every implementation, fix, review, re-review, QA-capture, and QA-review pass is a new instance. Never resume a worker for a later cycle and never use `--last`. The shared draft PR persists, but agent context does not. | Each new worker must receive a complete durable envelope: issue/spec revisions, authority brief, repo/instruction manifest, PR/base/topology, exact HEAD, prior handoff, and current findings. Orchestrators may persist for their bounded stream. | Decision 5a |
| 13 | Orchestrator stream boundary | Superseded by Decision 93. The earlier ruling allowed one persistent orchestrator to own multiple same-epic issues with shared delivery topology. | Current rule: exactly one dedicated Opus issue orchestrator per implementation issue. A multi-issue epic adds a separate Opus epic orchestrator above them. | Decision 5b |
| 14 | Orchestrator retirement | Approved: when a bounded epic/release-train stream completes, archive its durable control record and terminate the orchestrator. Never recycle the session for subsequent work, even a related follow-on stream. | Follow-on work starts a fresh orchestrator from explicit durable inputs, preventing stale rulings, hidden context, and accumulated session state from leaking forward. | Decision 5c |
| 15 | Orchestrator runtime mode | Approved from the operator's prior ruling: every newly spawned orchestrator launches in auto mode and bootstrap must verify it. Auto mode changes interaction friction, not authority; the four-section authority brief still bounds permissible actions. | The canonical spawn helper must pin and attest auto mode. A child that cannot verify mode is not ready and must not silently continue or wait at a permission prompt. | Decision 6 |
| 16 | Linear/spec conflict handling | Approved: if Linear's high-level objective, material decisions/context, or non-goals conflict with the canonical spec/ADR, implementation stops and returns to shaping. Neither source silently wins. | Reconcile Linear, spec/ADR, and the evolving draft-PR contract; obtain operator approval; issue a new readiness revision before implementation resumes. | Decision 6a |
| 17 | Evidence publication performance | Approved: routine per-issue card publication is incremental with a ≤5-second SLA; explicit full-archive repair builds have a ≤60-second SLA. | The 20.079-second cached whole-site hotfix is interim only. Move the Turbo-specific generator into Turbo-Outreach, emit immutable per-issue cards/manifests, update the queue index atomically, and measure both SLAs in CI/runtime telemetry. | Decision 9 |
| 18 | Acceptance-surface enforcement | Rejected a cryptographic issue/HEAD/verdict receipt and hard-failing `accept` command as premature overengineering. Use a simple readiness preflight: before saying an item is ready, the accountable orchestrator opens or queries the served review page and confirms the issue card is present and reviewable. | No custom hash protocol or override syntax. Missing/stale cards block the “ready” claim; ordinary operator acceptance remains simple. Add stronger machinery only if failures persist after publication becomes incremental. | Decision 9a |
| 19 | Memory authority | Approved: Claude/Codex memory is strictly non-authoritative. It may contain dated gotchas and pointers, but never current scope, status, authority, lifecycle state, or standalone policy. | Move load-bearing rules into Linear, canonical specs/ADRs, target-repo instructions, or active authority briefs. Memory entries must name the durable source and be supersedable. | Decision 7a |
| 20 | Memory write ownership | Approved with a simplicity constraint: any role may write a short, dated, evidence-backed gotcha; the bounded stream orchestrator prunes or promotes entries at stream close. | Use only date, scope, observed failure, and durable source/fix link. No registry, compiler, approval workflow, or automatic policy extraction. | Decision 7b |
| 21 | Messaging acknowledgment scope | Approved: require explicit recipient acknowledgment for commands, operator rulings, ownership transfers, and blocking questions only. Routine status/FYI messages do not require acknowledgment. | Close the unsubmitted/unaccepted-control-message gap without turning all communication into protocol traffic. Completion still requires the named durable artifact or observable outcome, not merely an acknowledgment. | Decision 8a |
| 22 | Messaging acknowledgment timing | Rejected a fixed acknowledgment timeout. Control-message dependency, not elapsed time, determines blocking. | A dependent action cannot proceed until the recipient acknowledges; unrelated work may continue. The control view exposes awaiting-ack state without arbitrary clock-based escalation. | Decision 8b |
| 23 | Queued-message delivery | Approved: queued text may auto-submit when the recipient reaches a verified safe prompt. Manual inbox draining is not required. | Delivery remains dialog-aware and may never inject or press Enter into a modal. Control messages still require recipient acknowledgment before dependent work proceeds. | Decision 8c |
| 24 | Review/fix cycle bound | Approved: permit at most three fresh review/fix cycles. If the third re-review does not clear, stop and return the issue to shaping. | Prevent blind retry loops; persistent findings are treated as a contract/scope/design problem requiring a new readiness revision. | Decision 9b |
| 25 | Review/QA invalidation boundary | Approved as a simple judgment rule: behavior or contract changed means rerun review/QA; only packet or evidence wording changed means do not rerun. | No hash protocol, file taxonomy, classifier, or automated invalidation engine. Avoid rerunning expensive gates for harmless bookkeeping. | Decision 9c |
| 26 | `In Staging` semantics | Approved: merged to `main` means deployed to staging and therefore `In Staging`. Integration-train, `next-candidate`, or stacked-branch merges do not qualify. | Linear deployment state follows the actual main→staging delivery boundary. Current routines that set `In Staging` after any merge must be corrected; TUR-437 is a concrete mis-transition. | Decision 10a |
| 27 | Accepted integration-train state | Approved: operator acceptance is recorded in the acceptance ledger while Linear remains `Awaiting Accept` until the commit/train merges to `main`. Do not add a separate accepted state. | Preserve the compact Linear lifecycle while distinguishing human acceptance from actual staging delivery. Train position comes from the delivery manifest, not a false deployment state. | Decision 10b |
| 28 | Preprod/live semantics | Approved: `In Preprod` means a verified preproduction candidate exists at 0% live traffic; `Live` requires the actual operator-authorized traffic shift. | State transitions follow observable promotion facts. Candidate creation cannot imply live traffic, and only the operator's explicit shift authority moves work to `Live`. | Decision 10c |
| 29 | Spawn admission | Approved as a lightweight pre-spawn check, not a scheduler service: verify disk health, isolated worktree, no conflicting owner for branch/fixture/port/deployment lease, and no active provider overload. | Unsafe work waits instead of compounding resource failures. Add quotas or a registry only if the simple check repeatedly proves insufficient. | Decision 11a |
| 30 | Worker worktree cleanup | Approved: remove a worker worktree when its pass completes. If it is dirty, stop cleanup and require orchestrator inspection/reconciliation. | Prevent disk/worktree sprawl while protecting completed or partial work from destructive cleanup. | Decision 11b |
| 31 | QA fixture isolation | Approved in minimal form: state-mutating QA verifies starting state, avoids fixtures used by another lane, and records the fixture in its manifest; read-only QA may share stable fixtures. | Create unique local fixtures only where already cheap. No fixture allocator service or lease database. | Decision 11c |
| 32 | Operator reporting order | Approved: stream orchestrators report upward outcome-first; the meta-operator and operator control surface use the same order. Lead with product outcome, current gate, blocker, and next operator action; tracker/run IDs are secondary. | The human operator can understand and act on fleet state without decoding issue numbers or internal process jargon. | Decision 12a |
| 33 | Operator notification scope | Approved: proactively message the operator only for required decisions, blockers, failures, and meaningful gate/outcome changes. Routine progress is available on demand. | Preserve attention and make proactive notifications reliably actionable rather than a stream of process updates. | Decision 12b |
| 34 | Primary operator surface | Approved: the TopicFinder-dev website/cards/Kanban should be the primary view of the entire operation once it is accurate and easily digestible across all workstreams. Until then, the meta-operator supplies complete overall workstream updates. | Expand the website beyond evidence cards to outcomes, owners, gates, dependencies, blockers, and next actions; do not force the operator to reconstruct state from partial views. | Decision 12c |
| 35 | Migration timing | Approved: perform the operating-model migration now with no active work and no live-lane compatibility period. | Make a coordinated repo-level cutover, validate it, then start new work under the new contracts instead of supporting old and new paths concurrently. | Decision 13a |
| 36 | Operator-site source ownership | Approved: TopicFinder operator UI, evidence generators, target paths, and target-specific lifecycle presentation belong in Turbo-Outreach; octo-lite owns generic workflow/state contracts and adapters only. | Version the currently live untracked gallery tooling in the target repo and remove TopicFinder-specific implementation from generic octo-lite prompts. | Decision 13b |
| 37 | Product/tool dependency direction | Approved: Turbo does not depend on octo-lite, spec-chat, or the control panel for its product build, tests, deployment, or comprehensibility. These optional developer tools adapt to Turbo. | Turbo may carry inert target adapters outside the application graph, but deleting the tools must leave the product intact. | Instruction ownership |
| 38 | Exact Turbo instruction source | Approved: the tracked root `AGENTS.md` in each Turbo worktree is the sole canonical source for Turbo-specific agent instructions, and it contains only Turbo-specific instructions. | Turbo standing policy is a defect if copied into octo-lite, role prompts, workflow literals, or memory. Specs/ADRs remain the source for durable product behavior. | Claude compatibility |
| 39 | Turbo Claude compatibility | Approved direction: Turbo root `CLAUDE.md` is a tracked relative symlink to root `AGENTS.md`, not independent prose. | Claude and Codex consume the same repo law; branch/worktree instruction changes remain versioned and reviewable. | Worktree currency |
| 40 | Worktree instruction currency | Approved: Turbo `AGENTS.md` stays versioned with the branch and is never symlinked across worktrees. Generic octo-lite roles, skills, and workflows symlink to their canonical source. Spawn verifies the branch includes the instruction revision from its declared base. | Preserve branch reproducibility while preventing copied global/workflow policy drift. | Role loading |
| 41 | octo-lite runtime boundary | Approved: octo-lite is installed developer tooling, not a service. | No daemon, API, database, scheduler, queue, or octo-owned runtime state. Small workflow helpers execute inside explicit sessions. | Role loading |
| 42 | Role-loading architecture | Approved lightweight direction: Claude workflows are the canonical loop runtime. A small in-workflow helper selects the canonical role, resolves `role-skills.json`, preloads required skills, pins model/mode, starts in the target worktree, and supplies the durable envelope. The Codex reviewer receives the canonical reviewer contract verbatim. | Do not build a universal spawning service, policy compiler, or giant manifest. Raw role-bearing worker spawns must not bypass the helper. | Model hierarchy |
| 43 | Supervision model hierarchy | Approved: Fable is the meta-operator; every stream or subordinate orchestrator is Claude Opus; implement/fix workers are exact Sonnet 5 at xhigh; code review/re-review is fresh GPT-5.6 Sol at high. | Starting from Codex still routes orchestration into the canonical Claude/Fable/Opus path. QA pins remain to resolve. | Nested reporting |
| 44 | Nested orchestrator reporting | Approved: orchestrators may stack to useful depth, but every orchestrator has exactly one parent and status compacts upward one level at a time. | Leaf lanes do not flood Fable; the control surface may still render the full tree. Sweeps catch broken reporting chains. | Direct conversations |
| 45 | Direct orchestrator conversations | Approved: the operator may hold a deep conversation directly in any orchestrator tab. Stream-local rulings apply immediately and are durably summarized upward; cross-stream consequences pause until Fable reconciles them. | The operator never has to repeat the conversation. Role contracts stay pinned while stream briefs may incorporate explicit new rulings. | State ownership |
| 46 | Reconciled operation ownership | Approved direction: Fable is the sole writer/owner of the reconciled high-level operation view, but not the collector of every raw fact. | Orchestrators emit compact changes; a bounded read-only sweep worker returns deltas; Fable updates current state and the dashboard without ingesting full logs. | Sweep mechanism |
| 47 | Minimal stream supervision | Approved lightweight mechanism: one parent-owned `brief.md`, one child-owned `status.md`, safe one-line `herdr-say` notifications, and one lifecycle-bound Fable sweep while active work exists. | No event bus, orchestration database, per-lane watcher service, or large status protocol. | Linear transitions |
| 48 | Mechanical Linear transitions | Approved: stream orchestrators may perform mechanical `Todo -> In Progress -> Awaiting Accept` transitions only through an atomic transition/status/notify path. Acceptance, merge, staging, preprod, and live transitions remain operator-owned. | Preserve delivery velocity while guaranteeing Fable receives durable evidence of visible state changes. | Control-panel authority |
| 49 | Control-panel operational authority | Approved: hosted operations/evidence/spec views are read-only projections and cannot mutate Linear, GitHub, deployments, or agent state. | Source systems remain authoritative; the panel may link to actions but is not a second control plane. | Optional packaging |
| 50 | Optional octo-lite control panel | Approved direction: the control panel is an optional octo-lite companion, with generic operations, evidence, spec inspection, and role/configuration views. Turbo owns only its inert target instantiation. | Reframes Decision 36: Turbo-specific presentation/adapters stay in Turbo, while the reusable panel model may be generalized outside Turbo without making octo-lite core depend on it. | Configuration editing |
| 51 | Role/configuration inspector | Approved: a control-panel tab shows current roles, model/effort/mode, Linear mappings, actual resolved skills, workflow spawn graph, symlink health, editable canonical role prompts, and the generic system/profile prompt. | Local operator mode edits canonical octo-lite files, validates, and shows a git diff; it never commits/pushes and the hosted panel remains read-only. | Prompt pinning |
| 52 | Prompt pinning | Approved: role and generic prompt changes apply only to newly spawned sessions. Existing sessions remain pinned to the role contract with which they launched. | Prevent mid-run semantic drift while keeping future launches immediately aligned through canonical sources and symlinks. | Sweep implementation |
| 53 | spec-chat dependency boundary | Approved: Turbo's canonical `*.spec.html` artifacts remain usable without spec-chat; spec-chat is optional authoring/inspection tooling. | Preserve durable specs as repo artifacts rather than a tool-owned runtime format. | Remaining open questions |
| 54 | Post-grill shaping review and implementation source | Approved: after grilling and reconciliation, a fresh `gpt-5.6-sol` shaping reviewer at xhigh on the fast service tier reads the canonical spec/ADRs, relevant conversation logs through a pinned cutoff, Linear issue, repo instructions, same draft-PR readiness HEAD, and TDD contract. It must return a clear exact-revision verdict before `Shaped`. The spec is the implementer's detailed behavioral contract; Linear carries high-level decisions/context, issue identity, non-goals, and status. | Add a canonical read-only shaping-reviewer role and receipt. Documentary findings return to the shaper; missing judgments resume the one-question operator grill; material reconciliation requires another fresh review. Do not duplicate the detailed spec into Linear or make workers infer behavior from chat. | Shaping-review artifact location |
| 55 | Minimal launch boundary | Approved: one foreground role-spawn helper performs a final exact Linear and PR/HEAD readback, verifies pinned spec/readiness inputs, provisions a contained fresh worktree, launches the exact role, captures the provider session ID, and requires a compact bootstrap acknowledgment. Containment is checked only at provisioning and child bootstrap. | Ban `--last`, raw role-bearing spawns, workspace-root launches, path escape, and mutation before acknowledgment. Keep final HEAD in the handoff and ephemeral process/pane/turn IDs out of routine durable receipts. Build no daemon, global reconciliation service, per-command cwd monitor, or giant manifest. | Linear read/write boundary |
| 56 | Minimal Linear correctness boundary | Approved with a tangible-value constraint: gate-critical dispatch/readiness/lifecycle reads use one Linear-specific exact-read helper; exploratory read-only use remains direct. Every write uses a named role-authorized compare/mutate/readback/`status.md`/notify helper and partial failures retry only unfinished idempotent steps. | Prevent stale dispatch and false-success board transitions without a generic tracker abstraction. Build no service, plugin system, cache, mirror, poller, read ACL, or shadow Linear state. Preserve current transition ownership. | Fast fresh worktrees |
| 57 | Fast fresh worktrees | Approved: one clean control clone supplies shared Git objects to fresh per-pass worktrees. Target repos own a fail-fast bootstrap and may reuse native safe caches while mutable dependencies/build outputs remain worktree-local. Turbo specifically uses its nested npm lockfiles, native npm download cache, compatible Puppeteer/browser downloads, and per-worktree `node_modules`; measure cold and warm startup first. | Preserve fresh role/branch isolation without repeated cold clones and downloads. Cache misses fall back correctly; build no cache daemon, dependency service, custom registry, copied/shared mutable `node_modules`, or persistent mutable issue checkout. | Minimal failure/retry record |
| 58 | Minimal failure/retry record | Approved: only failed or interrupted passes add a small record to existing status/handoff with exact attempt identity, original error, a five-class failure category, useful work disposition, owner/next action, and whether fresh retry or shaping/operator action is required. The owner inspects and preserves work before a fresh retry; timeout alone is not failure. | Prevent duplicate work and false fleet outages while keeping successful passes clean. Build no retry database, timer, automatic scheduler, circuit breaker, jitter policy, or elaborate taxonomy unless measured recurring failures require it. | Incident-derived conformance suite |
| 59 | Lightweight Langfuse-aligned tracing | Approved: align to Langfuse's session, trace, and observation data concepts using one local append-only `trace.jsonl` per bounded stream. Foreground helpers emit only meaningful workflow boundaries with portable IDs, compact attributes, and artifact references. | No Langfuse deployment, service, SDK, collector, database, exporter, raw prompt/response capture, or prompt bloat. Replace the broad workflow matrix with one path-filtered CI checker over generated happy and failure/retry traces plus a few invalid fixtures. This does not replace spec-driven TDD or target-repo tests. | Runtime trace retention |
| 60 | Runtime trace retention | Approved: `trace.jsonl` inherits the lifecycle of its existing stream control directory. Preserve a sanitized trace separately only through an explicit incident-artifact action. | No independent archive, retention duration, cleanup timer, or pruning machinery. Trace data remains a disposable projection, not a new durable source of truth. | Runtime trace failure semantics |
| 61 | Runtime trace failure semantics | Approved: runtime append failure is fail-open and fail-visible. Write one concise `trace degraded` warning into existing stream status, then continue without retrying or blocking a gate. | Authoritative gate artifacts still fail closed. CI validation of a changed trace contract also remains fail-closed. Observability failure cannot become a delivery outage. | Trace writer ownership |
| 62 | Trace writer ownership | Approved: only deterministic foreground workflow and named gate helpers append trace observations. Language-model agents return their normal receipts and artifacts and never write trace records directly. | Keep trace paths, serialization, and event procedure out of prompts and role contracts. Prevent fabricated agent-authored events without adding a service. | Remaining operating-model gaps |
| 63 | Session-durable Fable sweep wake | Approved: install one host timer at Fable launch whose sole action is `herdr-say` to the verified Fable session. It persists for the entire operator session, including idle periods, and is removed only at session termination or transferred through an explicit operator handoff. | A no-change wake is a cheap no-op. No persistent sweep process, timer-owned reconciliation, or octo-lite service. | Operator handoff |
| 64 | First-class operator handoff | Approved direction: only an explicit operator request triggers transfer from one Fable session to a fresh Fable session. The outgoing operator writes a concise durable state artifact; the successor loads canonical instructions, reconciles the artifact against source systems, and takes over the timer and child reply routes. Authority transfer must have one atomic commit point. | Full transcript replay is optional and non-authoritative. Split-brain writing is prohibited. Timer routing, child acknowledgments, and old-session cleanup are separate effects, not the authority commit. Exact atomic mechanism remains under grill. | Atomic handoff mechanism |
| 65 | Atomic TOML owner pointer | Approved: one `operator-owner.toml` in the control directory contains schema version, exact owner session ID, handoff revision, and control-directory identity. After successor readiness, a helper locks and compare-checks the expected owner/revision, writes complete temporary TOML, and atomically renames it over the old record. The rename is the sole authority commit. | Operator-owned mutation helpers verify the caller; ordinary commands do not. Timer and top-level child messages use `operator-say`, which resolves the pointer then delegates to `herdr-say`. Langfuse does not constrain this control file; append-only telemetry remains `trace.jsonl`. | Dead-owner recovery |
| 66 | Dead-owner recovery | Approved: takeover requires explicit operator authorization, verification that the exact recorded Herdr owner session is dead or absent, a fresh Fable reconciliation against durable state and source systems, and the same locked expected-owner/revision atomic replacement. | Ambiguous liveness blocks. No timeout or automatic failover may transfer operator authority. | Handoff artifact |
| 67 | Artifact format policy and spec-chat scope | Approved: both octo-lite and Turbo use spec-chat `*.spec.html` for canonical human-reviewed domain behavior and ADRs. Markdown remains the agent-native format for standing instructions and lifecycle-bound human context; TOML is the default for octo-lite-owned machine configuration/current state; JSONL is the append-only trace format; JSON or other formats remain only where an external tool or target consumer requires them. | Format never grants authority. State/events carry schema versions; TOML updates atomically and JSONL appends under a small lock. Turbo already has the spec-chat signal; octo-lite adds it now. The audit packet remains shaping evidence and gains no generated Markdown twin after promotion. | Operating-model spec promotion |
| 68 | Canonical operating-model spec | Approved and applied: octo-lite's current approved operating-model behavior is promoted to `spec/domains/operating-model.spec.html` and linked from `spec/index.spec.html`. | The Markdown audit packet remains evidence and chronology, not a generated twin. New durable behavior updates the HTML spec; the chronological decision log may remain Markdown context. | Handoff artifact path |
| 69 | Operator-handoff artifact path | Approved: each explicitly requested operator handoff writes one immutable Markdown artifact at `handoffs/<zero-padded-revision>.md` relative to the operator control directory, starting with `handoffs/0001.md`. `operator-owner.toml` references the accepted revision and path. | Handoff files inherit the control directory lifecycle and require no separate archive, registry, or retention machinery. | Canonical role source |
| 70 | Claude-native canonical role resolution | Approved: orchestrated Claude Workflows are the primary loop runtime. `roles/<role>.md` owns canonical prose; `roles.toml` owns provider, exact model, effort, mode, tools, required/conditional skills, and contract path. One resolver supplies both before every Workflow agent invocation or Sol relay and records contract blob, map revision, runtime values, and resolved skills. Generated Claude Markdown and Codex TOML adapters are launcher inputs and diagnostics only. | Role prose and machine config do not duplicate. Raw adapter spawns are prohibited. The map holds no target rules, issue scope, live state, secrets, or operator decisions. Generation fails on platform field loss. A path-filtered dry run proves the effective contract reached the spawned session. If runtime file loading is unavailable, use a deterministic build with source blob, never handwritten prompt literals. | Role roster |
| 71 | Minimal LLM role roster | Approved: canonical LLM roles are meta-operator, orchestrator, issue-shaper, shaping-reviewer, implementer, code-reviewer, QA capture, QA reviewer, and read-only reconciler. Fix and re-review use fresh implementer and code-reviewer instances; nested stream owners reuse the orchestrator contract. | Acceptance, merge, evidence publication, Linear transitions, promotion, and traffic shift remain deterministic operator-authorized helpers, not LLM roles. The control panel presents gates/helpers separately. | QA model pins |
| 72 | QA evidence planning, publication, and dashboard ownership | Approved: before capture, QA capture selects and records the minimum honest proof set per criterion. Stable behavior uses one screenshot or a concise purposeful group; video is used only when stills cannot honestly prove motion, sequence, timing, playback, or interaction. Do not duplicate screenshots and video without distinct proof value. | QA capture returns artifacts and a manifest. A deterministic helper publishes every acceptance card, including backend-only work, and reads back exact issue/PR/HEAD/verdict/coverage. Publication and verdict changes flow through stream status and parent notification; Fable alone reconciles the dashboard. QA workers never mutate the site index or dashboard. | QA model pins |
| 73 | QA model pins | Approved: every QA capture round uses a fresh exact Anthropic `claude-sonnet-5` instance at high effort. Every QA review round uses a fresh Codex `gpt-5.6-sol` instance at high reasoning effort on the fast service tier. | Preserve a faster capture role and independent cross-provider judgment. No worker reuse or `--last`; backend-only work does not spawn browser QA roles. | Orchestrator model pin |
| 74 | User-story surface and QA boundary | Approved: the user-story catalog is a product-surface artifact mirrored to Notion and also a QA contract for full-pipeline verification. It is not QA evidence and does not carry screenshots, videos, verdicts, proof links, or acceptance state. | Full-pipeline QA consumes a pinned catalog revision and emits separate coverage/evidence/verdict artifacts keyed to stable story IDs. QA roles cannot author or silently rewrite product-story truth. Canonical source and mirror trigger remain to resolve. | User-story source |
| 75 | Minimal spec-chat user-story surface | Approved, superseding Decision 74's Notion clause: Turbo owns one indexed canonical spec-chat user-story document, initially `spec/domains/topicfinder-user-stories.spec.html`. Stable story anchors link directly to detailed spec anchors. The optional control panel renders it through the existing read-only spec path. | Cut user-story Notion publishing and synchronization entirely. Build no story service, database, special control-panel backend, mandatory graph, or parallel visualization dataset. Optional visuals must derive from the document and add clear comprehension value. | Story maintenance trigger |
| 76 | Shaping-owned story maintenance | Approved: the issue shaper updates the user-story document during shaping whenever approved work creates, changes, or retires a user outcome. The story and linked behavior specs stay on the same evolving draft PR before the final fresh shaping review. | The shaping reviewer blocks readiness on material story/spec mismatch. Implementers, reviewers, QA, acceptance, and merge consume but never maintain the catalog. After merge, normal control-panel spec discovery reflects `main`; no publication job runs. | Story identity |
| 77 | Lightweight story identity | Approved: story IDs use `TF-US-<origin Linear number>-<two-digit ordinal>`, such as `TF-US-437-01`. The Linear number records origin only. IDs are never renamed, renumbered, or reused. | The shaper finds the next ordinal for the issue by reading the canonical document, so no registry or allocation service exists. Retirement preserves the story in place with `retired` status and an optional successor link. | Legacy story migration |
| 78 | Curated legacy story migration | Approved: treat the existing 82-story QA-derived Markdown catalog as candidate source material, not authority. A shaping pass groups duplicate and bug-level entries into durable product outcomes, removes evidence/verdict/AC/count/QA-status material, and assigns stable IDs plus exact spec links. | Review the replacement directly in spec-chat. Delete legacy `spec/user-stories.md` only after approval. Do not mechanically preserve historical QA clutter as canonical product truth. | Minimal story record |
| 79 | Minimal user-story record | Approved: each active record contains only stable ID, short title, `active` status, one user-voiced story sentence, exact spec-anchor links, and origin Linear issue. A retired record may add one successor story link. | Product-surface sections provide grouping and Git provides history. Do not add acceptance criteria, QA fields, owners, metrics, dates, or implementation details. | QA story selection |
| 80 | Story selection and evidence-site acceptance | Approved: issue-level QA verifies only active stories changed or claimed by the shaped issue; explicit full-pipeline QA verifies every active story at one pinned story/spec revision. Retired stories are excluded, and missing or unexecutable active stories are not evidenced rather than skipped. | The evidence site presents QA artifacts plus the fresh QA reviewer's verdict for operator review. User-facing and full-pipeline packets require a satisfied QA verdict before being offered. The operator still explicitly accepts or rejects; agent verdict is never human acceptance. No suite tags or secondary story catalog. | Backend-only acceptance |
| 81 | Backend-only QA acceptance | Approved: backend-only work skips browser capture, screenshots, video, and app boot unless the contract requires them. A deterministic helper assembles clear code review, exact HEAD, affected story IDs, spec criteria, real unskipped validation, and contract-check outputs into a nonvisual packet. | A fresh QA reviewer checks evidence sufficiency and per-criterion coverage without repeating code review. The evidence site serves the packet and verdict through the same explicit operator acceptance path. Every acceptance packet now requires a satisfied fresh QA-review verdict. | Orchestrator model pin |
| 82 | Orchestrator model pin | Approved: every stream and nested orchestrator uses exact `claude-opus-4-8[1m]` at high effort in auto mode. | Long-lived orchestration gets the 1M context window while high effort balances judgment and speed. Model unavailability fails visibly; never silently fall back to another model version or family. | Lean runtime artifacts |
| 83 | Lean LLM instructions and artifacts | Approved: every LLM-facing role, skill, launch instruction, brief, handoff, verdict, receipt, and status is extremely concise, may sacrifice grammar, and uses no em dash or en dash. Generated artifacts reference pinned canonical sources rather than restating them and carry only facts required for authority, gates, recovery, or the next consumer. | Expand detail only for findings, failures, ambiguities, operator decisions, or explicit requests. Do not impose brittle word, character, or token caps that could truncate correctness-critical facts. | Fable model pin |
| 84 | Meta-operator model pin | Approved: the meta-operator uses exact `claude-fable-5` at xhigh effort in auto mode. Fable 5 includes 1M context by default, so the redundant `[1m]` suffix is omitted. | Replace the current rolling `--model fable` launcher value during implementation. Model unavailability fails visibly; never silently fall back to Opus or another model. | Reconciler model pin |
| 85 | Narrow Haiku reconciler | Approved with explicit comfort boundary: deterministic helpers run exact checks and feed a compact normalized read-only snapshot to a fresh exact `claude-haiku-4-5-20251001` instance. Haiku receives no effort value or fallback and classifies only changed, missing, stale, contradictory, or `needs_fable`. | Haiku cannot mutate, override exact mismatches, investigate open-endedly, or silently resolve ambiguity. Missing/unparseable input and ambiguity route to Fable. No automatic Sonnet pass. This keeps routine sweeps cheap without moving judgment or correctness into Haiku. | Control-panel packaging |
| 86 | Sonnet reconciler supersedes Haiku | Approved correction: Haiku leaves a false-negative gap because escalation helps only when the model notices its own uncertainty. Reconciliation therefore uses fresh exact `claude-sonnet-5` at high effort with no fallback. | Deterministic helpers still run exact checks and feed one compact normalized snapshot. Sonnet remains read-only, cannot override exact mismatches, and returns ambiguity to Fable. Decision 85 is superseded. | Control-panel packaging |
| 87 | In-repo optional control panel | Approved: the control panel remains part of octo-lite under `control-panel/`, not a sibling repository. Frontend dependencies and build output stay isolated, and core installation/workflows do not build, launch, or depend on it unless invoked. | Hosted mode is a static read-only projection. Local mode may edit only approved canonical octo-lite files, validate, and show a git diff. No service or independent cross-repo schema lifecycle. Turbo retains only an inert adapter. | Turbo adapter path |
| 88 | Linear readiness state and PR proof | Approved: Linear `Shaped` is the canonical readiness state. The final shaping verdict lives as a durable artifact on the evolving draft PR and binds the relevant Linear content fingerprint, exact PR and shaping HEAD, spec/ADR blobs, conversation-log references and cutoff, verdict, and reviewer receipt reference. | Linear links the verdict. Launch refetches and compares every bound source. Stale inputs return to shaping. Create no separate readiness TOML or control-directory artifact. | GitHub reviewer artifact |
| 89 | One PR-comment review artifact | Approved: shaping and code review each publish one concise machine-readable PR verdict comment through a deterministic helper. It records review type, clear or blocking verdict, exact HEAD, bound inputs, findings, and reviewer receipt reference. | This is the only required GitHub review artifact. Build no formal Review API dependency, reviewer-account preflight, check-run integration, optional mirror, or fallback tree. | Evidence-site policy |
| 90 | Minimal evidence-hosting boundary | Rejected an evidence-site access, per-card permission, redaction, retention, and broken-link subsystem. Evidence hosting remains target-repo operations. | Keep only one exact-card and linked-artifact readback before claiming readiness. Add no periodic sweeper or cleanup timer. Never intentionally publish known secrets or credentials. | Control-panel edit boundary |
| 91 | Minimal control-panel edit allowlist | Approved: local panel mode may edit exactly `roles/*.md`, `roles.toml`, `profile/AGENTS.md`, and `skills/*/SKILL.md`. Generated adapters, workflows, target-repo instructions, specs, and runtime state remain read-only. | Save validates and shows the git diff but never commits or pushes. Use four path patterns, not a per-file registry. Hosted mode remains read-only. | Turbo adapter necessity |
| 92 | No speculative Turbo adapter | Approved: create no Turbo control-panel adapter or structured target-config file now. Derive values from existing repo instructions, specs, git, Linear, PRs, evidence manifests, and the signed brief. | Only a later shaped, proven non-derivable presentation mapping may add `.octo-lite/control-panel.toml`. It contains no agent instructions, lifecycle state, secrets, or product dependency. This supersedes Decision 87's implication that Turbo necessarily retains an adapter. | Grill complete |
| 93 | Orchestrator cardinality | Approved clarification: every implementation issue has exactly one dedicated Opus issue orchestrator. A multi-issue epic adds one separate Opus epic orchestrator above the issue orchestrators, creating two Opus layers below Fable. | The epic Opus owns cross-issue dependencies, carrier integration, topology, and epic outcome. Each issue Opus owns its issue scope, branch, gates, fresh workers, and status. Status compacts upward one level at a time. Both use the same canonical orchestrator role and exact model pin. | Post-grill topology clarification |
| 94 | Flexible topology judgment | Approved clarification: sequential, stacked, and parallel issue delivery are choices made intelligently by the accountable epic orchestrator from actual dependencies, collision risk, review cost, and throughput. No fixed default or programmatic merge policy chooses for it. | The manifest records the current chosen topology and revision but does not select or enforce it. The epic Opus may revise topology under Decision 5 and escalates only when ship grouping, product scope, or material risk changes. | Post-grill topology clarification |
