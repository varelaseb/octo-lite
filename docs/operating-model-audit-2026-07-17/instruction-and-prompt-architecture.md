# Instruction And Prompt Architecture

> Historical audit/proposal document. The canonical
> [operating-model spec](../../spec/domains/operating-model.spec.html) wins.
> The integrated [operating-model draft](operating-model-draft.md) preserves
> approved narrative context. Proposals below remain evidence unless repeated
> in the canonical spec.

## Artifact formats

- spec-chat HTML: canonical domain behavior and ADRs in both octo-lite and
  Turbo.
- Markdown: agent-native standing instructions plus lifecycle-bound human
  context such as briefs, status, and handoffs.
- TOML: octo-lite-owned machine configuration and current control state.
- JSONL: append-only workflow traces and their conformance fixtures.
- JSON or another native format: only an external platform, API, schema, or
  target consumer boundary.
- Native media: screenshots and necessary video evidence.
- Generated HTML: read-only projections, never authority.

Every state or event format carries a schema version. TOML state changes use
atomic replacement; JSONL event writes use a small append lock. Format does not
replace source ownership or lifecycle rules. The existing `role-skills.json`
is replaced in one shaped migration by `roles.toml`, covering all readers,
generated adapters, validation, and installed symlinks.

Every LLM-facing role, skill, launch instruction, brief, handoff, verdict,
receipt, and status is extremely concise and may sacrifice grammar. It uses no
em dash or en dash characters. Generated artifacts reference exact durable
sources rather than copying them and contain only facts required for authority,
gates, recovery, or the next consumer. Detail expands for findings, failures,
ambiguities, decisions, or explicit requests. No arbitrary length cap may
truncate correctness-critical facts.

## Audit-snapshot routing

```text
octo-lite profile/AGENTS.md
  ├─ symlinked into Codex/Claude global profile
  ├─ contains generic rules
  └─ also contains TopicFinder-specific rules

octo-lite role profiles + role-skills.json
  ├─ installed as Codex TOML
  ├─ installed as Claude Markdown
  └─ partially restated by workflow prompt literals

Turbo-Outreach AGENTS.md + CLAUDE.md
  ├─ loaded only when runtime starts in a matching repo/project context
  ├─ duplicated across the two files
  └─ version varies by branch/worktree

Claude memory + per-session briefs + relayed rulings
  ├─ project-scoped and sometimes shared across registered worktrees
  ├─ absent in arbitrary new folders
  └─ currently mixes durable policy, incident heuristics, and live status

Claude workflow → Codex relay
  ├─ starts Codex in a Claude scratch cwd
  ├─ sends a shortened role paragraph
  └─ asks Codex to create/enter a target worktree later
```

There is no artifact that says which exact global contract, role contract,
target instructions, spec index, issue scope, branch base, or operator decision
revision a worker received.

## Proposed ownership model for grilling

This is a candidate, not an approved design.

### Layer 1: generic octo-lite kernel

Owned by `/root/octo-lite`.

It should contain only reusable mechanics:

- Workflow roles and separation of duties.
- Readiness, ambiguity, review, QA, acceptance, and stop gates.
- Generic tracker/GitHub boundaries.
- Worktree and message protocol interfaces.
- Generic schemas for briefs, bootstraps, handoffs, verdicts, and receipts.
- Platform adapters for Claude and Codex.

It should not contain:

- Turbo paths, branch names, ports, hosts, credentials, demo users, or fixture
  identities.
- TopicFinder Notion URLs, design rules, deployment topology, or Linear state
  names.
- Target validation commands or spec paths.

### Layer 2: canonical role contracts

Owned by `/root/octo-lite`, one source per role.

Canonical prose lives at `roles/<role>.md`. It owns responsibilities,
authority, stop conditions, inputs, and outputs. `roles.toml` owns provider,
exact model, effort, permission mode, tools, required and conditional skills,
and contract path. It contains no target rules, issue scope, live state,
secrets, or operator decisions.

One resolver supplies both sources to the native Claude Workflow launcher or
Sol relay and records contract path/blob, map revision, runtime values, and
resolved skills. Generated Claude Markdown and Codex TOML adapters are launcher
inputs and diagnostics, not independent spawn paths. Generation fails on
platform field loss. A small path-filtered CI dry run proves exact resolution.

Canonical LLM roles:

- Meta-operator.
- Orchestrator.
- Issue shaper.
- Post-grill shaping reviewer.
- Implementer.
- Code reviewer.
- QA capture.
- QA reviewer.
- Read-only reconciler.

Pinned worker models:

- Meta-operator: exact `claude-fable-5`, xhigh, auto, default 1M context, no
  silent fallback.
- Orchestrator: exact `claude-opus-4-8[1m]`, high, auto, no silent fallback.
- Reconciler: fresh exact `claude-sonnet-5`, high, no fallback, compact
  deterministic read-only snapshot only; ambiguity returns `needs_fable` to
  Fable.
- Implementer and fix: fresh exact `claude-sonnet-5`, xhigh.
- Shaping reviewer: fresh `gpt-5.6-sol`, xhigh, fast service tier.
- Code reviewer and re-review: fresh `gpt-5.6-sol`, high.
- QA capture: fresh exact `claude-sonnet-5`, high.
- QA reviewer: fresh `gpt-5.6-sol`, high, fast service tier.

Fix and re-review reuse fresh implementer and code-reviewer instances. Nested
stream owners reuse the orchestrator contract. Acceptance, merge, evidence
publication, Linear transitions, promotion, and traffic shift are deterministic
operator-authorized helpers, not LLM roles.

Each platform-specific profile is generated or mechanically assembled from the
same role source.
Model and reasoning policy should be executable configuration, not only prose.

The optional control panel lives at `control-panel/` inside octo-lite. Its
frontend dependencies and build output are isolated. Core installs and
workflows ignore it unless explicitly invoked. Hosted mode is static and
read-only. Local mode may edit only `roles/*.md`, `roles.toml`,
`profile/AGENTS.md`, and `skills/*/SKILL.md`, then validate and show a diff.
Generated adapters, workflows, target-repo instructions, specs, and runtime
state remain read-only. It never commits or pushes and has no per-file edit
registry. It is not a sibling repo or service.

### Layer 3: target repo contract

Owned by Turbo-Outreach.

`AGENTS.md` should be the cross-runtime human-readable contract for:

- Linear/TUR tracking rules: issue identity, high-level objective, material
  decisions/context, non-goals, and lifecycle status.
- Spec format and the rule that canonical specs/ADRs are the implementer's
  primary detailed behavioral and acceptance contract.
- Branch and PR topology.
- State-transition ownership.
- Worktree ownership and validation expectations.
- TopicFinder visual and architecture rules.
- Runtime config, QA, fixture, deployment, and Notion conventions.
- Rules for distinguishing branch source, deployed source, and live runtime.

`CLAUDE.md` should contain only Claude-specific compatibility notes that cannot
live in `AGENTS.md`.

Workflows derive target facts from root `AGENTS.md`, the spec index, git,
Linear, PRs, evidence manifests, and the signed brief. Add no speculative
target-config file. Only a later shaped, proven non-derivable control-panel
presentation mapping may add `.octo-lite/control-panel.toml`; core workflows
do not consume it.

### Layer 4: signed unit-of-work brief

Owned by the orchestrator for one bounded stream.

It should contain only issue-specific and operator-specific facts:

- Objective and outcome.
- Issue key, high-level objective, material decisions/context, and explicit
  non-goals.
- Branch base and required PR base.
- Canonical spec/ADR references and clear shaping-review receipt.
- Granted authority and irreversible gates.
- Expected evidence and stopping condition.
- Reply route and accountable owner.

It must not become a second procedure manual.

### Layer 5: ephemeral control state

Owned by the active orchestrator and stored outside prompt/memory sources.

Examples:

- Session and message IDs.
- Worktree leases.
- PIDs and port assignments.
- Fixture allocation.
- Staging mutation leases.
- Current gate and latest exact HEAD.
- Wake paths and timeouts.

This state needs an explicit lifecycle, owner, and cleanup semantics. A
time-based TTL exists only where the underlying resource actually expires.

The Fable wake is session-bound, not active-work-bound. One host timer invokes
`operator-say sweep`; the helper resolves the exact owner from
`operator-owner.toml` and delegates to `herdr-say`. It persists through
operator handoffs and is removed only when the operator lifecycle terminates.
A wake with no delta is a no-op.

An operator-requested handoff is a first-class action. The outgoing Fable
writes a concise artifact with objective, active stream tree, gates,
issue/PR/HEAD facts, pending decisions, authorities, blockers, control path,
child reply routes, and timer ownership. The successor starts fresh from
canonical instructions plus that artifact and reconciles source systems.
Transcript replay is not required for correctness. Exact cutover semantics
use one `operator-owner.toml` in the control directory. It contains only schema
version, exact owner session ID, handoff revision, and control-directory
identity. After successor readiness, a helper locks and compare-checks the old
record, writes a complete temporary TOML file, then atomically renames it over
the old record. The rename is the authority commit.

Only operator-owned state and gate mutation helpers check the owner record;
ordinary commands do not. Timer and top-level child delivery resolve the owner
through `operator-say`. The old session becomes read-only at commit. TOML is a
local control choice unrelated to Langfuse; `trace.jsonl` remains the
append-only telemetry projection.

The handoff artifact path is
`handoffs/<zero-padded-revision>.md` relative to the control directory, starting
at `handoffs/0001.md`. Each file is immutable, `operator-owner.toml` references
the accepted path and revision, and the files inherit the control directory
lifecycle without a separate archive.

Dead-owner recovery is operator-authorized only. Verify the exact recorded
Herdr session is dead or absent, launch a fresh Fable, reconcile durable state
and source systems, then use the same expected owner/revision atomic replace.
Ambiguous liveness blocks. No timeout or automatic failover transfers
authority.

### Layer 6: local trace projection

Only deterministic foreground workflow and named gate helpers may append
stable, Langfuse-shaped session, trace, and observation records to one
`trace.jsonl` in the bounded stream's existing control directory. Agents
return normal receipts and artifacts; they never write trace records directly.
This is a local projection of facts already produced by workflow boundaries,
not a prompt source or authority layer.

The record contains compact identity, timing, status, role/model/repo/HEAD/gate
attributes, and artifact references. It excludes raw prompts, responses,
transcripts, logs, secrets, evidence bodies, and product data. No role or skill
repeats tracing procedure. No service, SDK, collector, database, exporter, or
background flush exists. Stable IDs permit a later OpenTelemetry or Langfuse
adapter.

The trace inherits the containing stream control directory's lifecycle. There
is no independent archive, retention duration, timer, or pruning path. A
sanitized trace may be promoted manually as an incident artifact.

Runtime append failure is fail-open and fail-visible: write one concise
`trace degraded` warning to existing stream status, then continue without
retrying or relaxing any authoritative gate. CI validation of trace-contract
changes remains fail-closed.

### Layer 7: memory

Memory should be a recall aid, never an authority layer.

Allowed content:

- Incident heuristic.
- Pointer to the versioned rule or runbook that fixed it.
- Date, scope, status, and supersession metadata.

Disallowed content:

- Current issue status.
- Current branch head or deployment position.
- A standalone workflow law that can contradict the repo or octo-lite.
- Operator authority or an irreversible approval.

Rejected earlier memory header, preserved only as audit history:

```yaml
status: active | superseded | historical
scope: generic | turbo-outreach | topicfinder
observed_at: 2026-07-17
superseded_by: path-or-decision-id
expires_at: optional
source: issue-pr-run-or-session-reference
```

## Required spawn bootstrap

The approved boundary is deliberately smaller than the earlier candidate
manifest. Ordinary stream orchestration reconciles durable facts. Immediately
before launch, the canonical role helper refetches the exact Linear issue
revision/status and current PR base/HEAD, verifies the pinned spec/readiness
inputs, and provisions a fresh contained worktree.

Containment is checked twice: once while provisioning and once by the child at
bootstrap. Both checks canonicalize the path and verify the allowlisted root,
git root, remote, worktree identity, expected starting HEAD, and target root
`AGENTS.md`. The child must not run at the workspace root or through a symlink
escape. There is no per-command cwd check or global reconciliation service.

The helper supplies a compact envelope rather than restating every source:

```text
spawn_id
parent and reply route
role and actual provider/model/effort/mode
repo/remote/worktree/starting HEAD
target AGENTS revision
role contract and loaded skill revisions
Linear issue and readiness revision
canonical spec revision and grill-log cutoff
draft PR/base/topology/readiness HEAD
brief revision
shaping-review verdict/revisions when required
```

The child starts in the provisioned worktree, resolves those sources, and
returns a bootstrap acknowledgment before mutation:

```json
{
  "spawn_id": "...",
  "provider_session_id": "...",
  "parent": "...",
  "reply_route": "...",
  "role": "implementer",
  "actual_model_effort_mode": "...",
  "repo": "Turbo-Video/Turbo-Outreach",
  "remote": "...",
  "worktree": "...",
  "starting_head": "...",
  "target_agents_revision": "...",
  "role_and_skills_revision": "...",
  "linear_readiness_revision": "...",
  "spec_revision": "...",
  "pr_base_topology_readiness": "...",
  "brief_revision": "...",
  "ready": true,
  "blocker": ""
}
```

A mismatch is a stop condition, not a warning. The exact provider session ID
is captured; implicit continuation such as `--last` is prohibited. Process,
pane, and turn IDs may be recorded in ephemeral status when required for
cleanup or diagnosis, but are not part of every durable receipt. The worker's
handoff records the final HEAD separately.

## Fast fresh workspace boundary

Use one clean control clone as the Git object source, then create a new
worktree for every role pass. Fresh worktrees must not imply a fresh network
clone or cold dependency download.

The target repo owns one fail-fast bootstrap command. octo-lite calls it but
does not encode the target's package layout or cache paths. The command may use
native shared download/object caches when they are safe; mutable dependency
trees and ordinary build outputs remain private to the worktree.

For Turbo's current nested npm applications, the repo-specific implementation
uses the checked-in npm lockfiles, a shared native npm download cache, and a
reusable compatible Puppeteer/browser download cache. Every worktree retains
its own `node_modules`. A cache miss runs the normal correct install, and cache
corruption may be discarded without losing source or completed work.

Record cold and warm bootstrap measurements before considering another cache
layer. Do not create a cache daemon, dependency service, custom registry,
copied/hard-linked mutable `node_modules`, or persistent mutable issue checkout.

## Failure and retry boundary

Successful passes add no retry metadata. A failed, killed, timed-out, or
interrupted pass writes this small record into the existing stream status or
handoff; if the worker cannot write it, the accountable orchestrator does so
after inspecting the workspace and process:

```text
attempt + exact session/worktree/starting HEAD
original error or output reference
class: input/contract | environment | provider/session |
       implementation/validation | external dependency
useful work: none | uncommitted | committed | pushed | artifact produced
owner + next action
fresh retry safe | shaping required | operator action required
```

The orchestrator inspects and preserves useful work before launching a fresh
retry instance, and the new envelope points to that work. Do not infer failure
from a response timeout alone. Build no retry database, timer service,
automatic scheduler, circuit breaker, jitter policy, or larger taxonomy until
measured recurring failures demonstrate the need.

## Linear access boundary

Use two small Linear-specific workflow functions, not a generic tracker layer:

```text
read-exact(issue)
  -> complete issue body + stable identity + revision + current status

transition(issue, expected_state, next_state, authority)
  -> compare expected current state
  -> mutate once
  -> read Linear back
  -> update status.md
  -> notify parent
  -> retry only an unfinished idempotent step after partial failure
```

Only reads that drive dispatch, readiness, or lifecycle gates must use
`read-exact`. Shapers and operators retain direct read-only exploration. All
writes use a named role-authorized operation; current mechanical stream
transitions remain limited to `Todo -> In Progress -> Awaiting Accept`, while
operator-owned gates keep their existing owners.

There is no tracker service, plugin interface, read ACL, cache, mirror, polling
loop, or octo-lite copy of Linear state. Tangible value is demonstrated by
tests that reject stale launch input and prevent a successful transition claim
when readback/status/notification disagree.

The operator selected a single evolving draft PR rather than a separate
spec-only PR. The issue shaper opens the draft PR and establishes the canonical
spec plus a signed readiness HEAD. The implementer continues on that same
branch and PR. The readiness HEAD remains immutable evidence even as the PR
HEAD advances; any scope/spec/AC change invalidates readiness and routes the
same PR back to shaping.

The PR base is not permanently frozen at shaping time. Branch topology is a
separate versioned contract so stacked work and explicit release trains remain
available. An authorized retarget must update the topology revision and prove
the expected merge-base, commit ancestry, and effective diff. It invalidates
code-review/QA artifacts tied to the old diff; it invalidates readiness only if
the user story, AC, scope, or canonical spec changed.

The stream orchestrator has standing authority for these topology transitions.
It escalates only when a transition changes ship grouping, product scope, or
material risk. The transition itself is not complete until its recorded base,
merge-base, ancestry, effective diff, and invalidated downstream gates have
been verified.

Any multi-PR train has a carrier PR and a machine-readable manifest containing
its member Linear issues, PRs, pinned HEADs, order, integration branch, target,
owner, topology revision, and gate status. The manifest owns delivery topology
only; it does not duplicate or supersede Linear scope/status.

For every Fable meta-operator or Opus stream-orchestrator session, the launcher
must pin `--permission-mode auto`. Fable is the sole meta-operator runtime.
The permissive runtime mode removes routine TUI approval stalls but does not
widen the authority in the acknowledged brief. `herdr-spawn` currently accepts arbitrary argv and therefore
cannot guarantee this. It needs a role-aware interface or a dedicated
orchestrator launcher, followed by runtime-mode verification in the bootstrap
ack.

This is an observed gap, not merely a theoretical one. A command-level scan of
the week's top-level Claude sessions found 51 `herdr-spawn` lines launching
Claude; 11 omitted an explicit auto/bypass permission mode. Recent examples
include several `shape-*` stream sessions launched as bare `-- claude`.

## Prompt envelope by role

The prompt should be assembled, not independently authored for every runtime.

### Shared envelope

1. Role identity and separation of duties.
2. Instruction manifest location and required bootstrap ack.
3. Required runtime/model/effort/permission mode.
4. Linear issue fetch and revision proof.
5. Canonical spec/ADR refs as the detailed implementation contract.
6. Relevant grill-log ref/cutoff and shaping-review receipt.
7. Signed brief location.
8. Exact workspace and branch topology.
9. Authority boundary and irreversible gates.
10. Required output schema and reply route.
11. Stop conditions.

### Shaping reviewer body

- Run as a fresh Codex `gpt-5.6-sol` instance with xhigh reasoning effort on
  the fast service tier after the operator grill and source reconciliation.
- Read the canonical spec/ADRs, complete relevant conversation logs through a
  pinned cutoff, current Linear issue, target-repo instructions, same draft-PR
  readiness HEAD, and proposed spec-driven TDD contract.
- Inspect raw durable transcript/session refs across the declared issue/stream
  log scope, list the refs and cutoffs actually read, and block on a relevant
  missing or inaccessible log; do not accept a curated summary as a substitute.
- Check that every material ruling is reconciled; Linear and the spec do not
  contradict or accidentally expand one another; the spec is complete,
  implementable, and testable; the TDD contract derives from it; and the PR
  HEAD contains the reviewed spec blobs.
- Return only `clear` or `blocking`, bound to exact reviewed revisions. Every
  blocking finding includes source pointers, the missing/divergent fact, and
  whether the shaper can reconcile it or the operator grill must resume.
- Never edit the spec, Linear, or PR; invent a product decision; implement; or
  convert ambiguity into approval.
- Any material reconciliation requires another fresh shaping-review instance.
- Use a dedicated read-only shaping-review role/skill mapping. Do not preload
  issue-shaper mutation capabilities or substitute the code-review contract
  merely because both reviewer roles use Sol.

### Implementer body

- Implement only signed scope.
- One owned worktree, branch, and PR.
- Treat the canonical spec/ADR as the primary detailed behavior and acceptance
  contract; use Linear for high-level decisions/context, non-goals, identity,
  and status.
- Require a clear shaping-review receipt matching the current spec, Linear
  revision, grill cutoff, and draft-PR readiness HEAD before mutation.
- Stop on ambiguity or source conflict.
- Run the target validation profile.
- Return exact HEAD and structured handoff.
- Never self-review or merge.

### Code reviewer body

- Review the exact implementer HEAD against signed scope and durable sources.
- Own code correctness, regressions, security, tests, and spec conflicts.
- Treat PR-base topology as a signed input, not a preference.
- Publish the one exact-HEAD machine-readable PR verdict comment through the
  deterministic helper.
- Return clear, blocking, or ambiguous bound to exact HEAD.
- Never fix, approve as human, or merge.

### QA capture body

- Consume only a clear code-review artifact for the same HEAD.
- Allocate isolated runtime, ports, fixtures, and durable artifact root.
- Exercise signed flows on required viewports.
- Before capture, write a small per-AC evidence plan choosing the minimum
  honest proof set.
- Use screenshots by default for stable states. Require video only when an AC
  depends on motion, sequence, timing, media playback, or interaction that
  stills cannot prove; record the evidence-choice rationale per AC.
- One screenshot or a concise ordered group is valid when every image proves a
  distinct state. Do not add video as ceremony or duplicate proof.
- Record app/runtime identity and exact HEAD in the manifest.
- Hand the manifest and artifacts to the deterministic evidence-publication
  helper. Never mutate the evidence-site index or operation dashboard.
- Report broken or missing evidence honestly.

### QA reviewer body

- Visually inspect the artifacts.
- Grade every criterion pass/fail/not-evidenced.
- Bind verdict to exact HEAD and artifact manifest SHA.
- Never substitute code/log plausibility for visible proof.
- Never merge or infer operator acceptance.

### Evidence publication and dashboard boundary

- A deterministic helper publishes every acceptance packet to the evidence
  site, atomically updates its index, and reads back the exact issue, PR, HEAD,
  verdict, and AC coverage.
- Backend-only work still receives a served evidence card before
  `Awaiting Accept` is reported ready.
- Backend-only work skips browser capture. A deterministic helper packages
  exact review, HEAD, stories, spec criteria, real validation, and contract
  outputs; a fresh QA reviewer checks sufficiency and criterion coverage
  without repeating code review.
- Evidence publication and QA verdict changes update stream status and notify
  the parent. Fable alone reconciles the whole-operation dashboard.
- QA capture and QA review never write the dashboard directly.
- The evidence site presents QA artifacts and the fresh reviewer's verdict as
  the operator acceptance-review surface. A satisfied verdict is required,
  but only the operator may accept.

### User-story surface boundary

- The user-story catalog is a product surface and full-pipeline QA contract,
  not an evidence manifest or verdict store.
- Turbo owns one indexed spec-chat story document with stable story anchors and
  direct canonical spec-anchor links.
- IDs use `TF-US-<origin Linear number>-<two-digit ordinal>`, never change or
  get reused, and need no registry. Retired stories remain with an optional
  successor link.
- An active record contains only ID, short title, status, one user-voiced
  sentence, exact spec links, and origin Linear issue. Product sections group
  records; Git supplies history. No AC, QA, owner, metric, date, or
  implementation fields.
- The control panel renders it through the existing read-only spec path.
- There is no user-story Notion mirror or publisher, story service, database,
  special control-panel backend, mandatory graph, or parallel chart dataset.
- The issue shaper maintains stories during shaping on the same draft PR as
  linked behavior specs. The fresh shaping reviewer verifies alignment before
  readiness.
- QA consumes a pinned catalog revision and writes separate coverage,
  evidence, and verdict artifacts keyed by stable story IDs.
- Issue QA selects the changed or claimed active story IDs. Explicit
  full-pipeline QA selects every active story at one pinned revision. Missing
  or unexecutable stories are not evidenced, never skipped.
- Implementers, reviewers, QA roles, acceptance helpers, and merge helpers
  never maintain or rewrite the catalog.
- After merge, the control panel reads the story document from `main` through
  normal spec discovery. No publication helper exists.
- The one-time migration curates the legacy QA-derived catalog into durable
  outcomes. It removes evidence, verdict, AC, count, and QA-status material,
  then receives direct spec-chat review before the old Markdown file is
  deleted.

### Acceptance/merge body

- Require explicit operator acceptance tied to verdict/HEAD.
- Reconcile PR head, review head, QA head, and accepted head.
- Apply the approved branch/state model exactly.
- Perform tracker comment, ledger, generated artifact, and state changes as one
  idempotent transaction or surface a partial failure.
- Never perform deployment traffic shifts without their separate authority.

## Message delivery contract

Visible TUI text is not delivery.

The earlier state-machine proposal below was rejected as unnecessary machinery.
Decisions 21 through 23 require only safe queued or submitted delivery, explicit
acknowledgment for commands, operator rulings, ownership transfers, and blocking
questions, plus the named durable outcome for completion. There is no timeout.

Historical proposal:

```text
queued -> injected -> submitted -> accepted -> completed
                                  \-> rejected
                     \-> expired -> escalated
```

Every command message should carry:

- Immutable message ID.
- Sender and reply route.
- Recipient and expected session ID.
- Related issue/stream.
- The related issue/stream and expected acknowledgment. Authority remains tied
  to the recipient's acknowledged spawn brief; attach a new brief revision only
  when scope, risk, grouping, or an irreversible gate materially changes.
- Expected acknowledgment state and timeout.
- Durable artifact pointer for nontrivial detail.

The orchestrator should be able to query delivery state without reading pixels
and guessing whether Enter was processed.

## Drift checks

Before spawning:

- Installed octo-lite version matches source or reports an explicit build ID.
- Target remote matches the signed brief.
- Worktree HEAD and branch base match the manifest.
- Target instruction blob is expected and not silently stale.
- Role profile and skill-map hashes match the selected octo-lite commit.

Before every downstream gate:

- Prior gate exists and is clear.
- Prior artifact refers to the current exact HEAD.
- PR base still matches the brief.
- No decision revision superseded the signed scope.
