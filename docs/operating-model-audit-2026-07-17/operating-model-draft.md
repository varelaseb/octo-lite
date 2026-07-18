# octo-lite Operating Model - Historical Working Draft

Status: shaping evidence and narrative history.

The canonical operating-model behavior now lives in
`spec/domains/operating-model.spec.html`. That spec wins if this historical
Markdown narrative diverges.

This document consolidates the approved rulings from the operating-model audit
and the subsequent architecture grill. It remains the narrative history. The
decision log in `optimal-model-grill.md` remains the chronological record of
how the rulings were reached.

Approved rulings are stated directly. A mechanism that has been discussed but
not explicitly approved is labeled **provisional**. Implementation details that
do not change the operating model still require normal issue shaping before
code changes begin.

Where this draft conflicts with an earlier proposal in the audit packet, this
draft wins unless the canonical spec differs. In particular, it replaces proposals for a policy compiler, a
large cryptographic spawn manifest, an octo-lite service, a scheduler service,
or a second operational state machine.

## Design target

Optimize in this order:

1. Trustworthy, observable delivery.
2. Low operator latency.
3. Throughput.
4. Token and compute cost.

Parallelism remains important, but it is useful only when ownership, scope,
gates, and the next human action remain legible.

The operating model has zero tolerance for:

- A worker starting in the wrong repo or with the wrong repo instructions.
- Treating visible or queued text as an acknowledged control message.
- Starting QA from an unreviewed or stale HEAD.
- Reporting lifecycle or deployment state without the corresponding fact.
- Calling work shaped without a Linear issue, canonical spec, evolving draft
  PR, and fresh post-grill shaping-review verdict that agree.
- Behavior-changing implementation without a spec-derived failing test, except
  for a narrow operator-approved waiver recorded during shaping.

## Product and tooling boundaries

### Turbo-Outreach

Turbo is the product repository. It does not depend on octo-lite, spec-chat, or
the optional control panel to build, test, deploy, or remain understandable to
developers.

The dependency direction is always:

```text
octo-lite / spec-chat / control panel  --->  adapt to Turbo
Turbo                                  -X->  depend on those tools
```

Deleting every local octo-lite, spec-chat, and control-panel installation must
leave Turbo's application build, tests, and deployment intact. Only enhanced
orchestration, spec authoring/inspection, and operator visualization disappear.

Turbo may contain inert developer-tooling adapters, mappings, and presentation
configuration outside its application dependency graph. Those files do not
become product dependencies and must not duplicate standing agent policy.

### octo-lite

octo-lite is optional installed developer tooling. It is not a service.

It consists of:

- Skills.
- Generic role contracts.
- Claude workflows.
- Small launch and workflow helper scripts.
- Schemas and templates.

It owns no standing daemon, API, database, scheduler service, queue service, or
unowned background runtime. Everything executes inside an explicitly launched
operator, orchestrator, or workflow session. An active Fable operator may use
an existing Claude/Herdr/host scheduling capability for one explicitly owned,
lifecycle-bound wake; octo-lite supplies only the foreground instructions and
helpers. Durable product and delivery state remains in Linear, specs, git,
GitHub PRs, evidence artifacts, and named operator control files.

### spec-chat

spec-chat is optional authoring and inspection tooling. Turbo's canonical
`*.spec.html` files remain readable, reviewable, and versionable without
spec-chat installed. spec-chat consumes and edits those durable artifacts; it
is not required by Turbo's product runtime.

### Optional control panel

The control panel is an optional component inside the octo-lite repo at
`control-panel/`. Its frontend dependencies and build output remain isolated
from the core workflow. Core installation and execution do not build, launch,
or depend on it unless explicitly invoked. It is not a sibling repository.

Its hosted operational surface is a static, read-only projection. It never
mutates Linear, GitHub, deployments, or running agents. A local operator-only
configuration mode may edit canonical octo-lite source files, show the git
diff, and validate the result. It never commits or pushes automatically.

The panel derives Turbo values from existing repo instructions, specs, git,
Linear, PRs, and evidence manifests. Turbo has no control-panel adapter by
default. Only a later shaped, proven non-derivable presentation mapping may add
`.octo-lite/control-panel.toml`. It is a read-only projection and contains no
agent instructions, lifecycle state, secrets, or product dependency. The
generic renderer, schemas, and role inspector do not live in Turbo.

## Artifact format policy

Both octo-lite and Turbo use spec-chat for canonical, human-reviewed system
behavior. Durable domain specifications and ADRs live as `*.spec.html` under
each repo's `spec/` tree. Generated control-panel and evidence HTML is a
projection, never canonical law.

Markdown remains canonical where agents or platforms load prose directly:
`AGENTS.md`, `SKILL.md`, Claude role contracts, README files, and concise
lifecycle-bound briefs, status, handoffs, and failure notes. Bounded context is
disposable with its owning control directory; standing instructions are not.

octo-lite-owned machine configuration and current control state use TOML,
including the role-skill map, owner pointer, and compact machine receipts.
Append-only workflow telemetry uses JSONL because each independently parseable
line is cheap to lock, append, tail, recover, and translate. JSON remains only
where a platform, API, schema ecosystem, or target consumer requires it.
Evidence remains in its native media format with a consumer-required manifest.

Format never grants authority. Each artifact still has one named owner and an
explicit lifecycle. TOML state carries a schema version and uses atomic
replacement; JSONL traces carry a schema version and use a small append lock.
Turbo-specific manifests remain in Turbo and keep the format required by their
current consumers.

Turbo main already declares `Spec format: spec-chat`. octo-lite now declares
the same signal. The audit packet remains Markdown shaping evidence; approved
system behavior is promoted into canonical spec-chat documents rather than
maintaining a generated Markdown twin.

## Canonical instruction ownership

Instruction sources own different concerns; they are not a pile of competing
files with one global override order.

| Concern | Canonical owner |
| --- | --- |
| Generic lifecycle, role gates, TDD loop, and review mechanics | octo-lite |
| Generic role responsibilities, model policy, and skill mapping | octo-lite |
| Turbo-specific repo mechanics and agent conventions | Turbo root `AGENTS.md` |
| Detailed product behavior, acceptance rules, interfaces, edge cases, and constraints | Turbo specs and ADRs |
| Issue identity, high-level objective, material decisions/context, non-goals, and workflow status | Linear |
| Operator rulings awaiting reconciliation | Relevant grill/conversation log |
| Code review and evolving implementation | One draft GitHub PR |
| Stream-specific authority and delivery topology | Parent-owned brief/train manifest |
| Current stream execution state | Orchestrator-owned `status.md` |
| Reconciled whole-operation state | Fable meta-operator control record |
| Memory | Non-authoritative dated gotchas and pointers only |

### Exact `AGENTS.md` identities

`<Turbo-Outreach worktree root>/AGENTS.md` is the sole canonical source for
Turbo-specific agent instructions. For example, the file at the tracked repo
path appears as `/root/turbo-main-wt/AGENTS.md` in one worktree. Its canonical
identity is the tracked root path, not that particular checkout.

That file contains only Turbo-specific instructions, and standing
Turbo-specific agent instructions exist exclusively there. They must not be
copied into octo-lite roles, octo-lite skills, Claude memory, Codex profiles,
workflow literals, or stream briefs.

Automation derives current Turbo rules and mappings from durable repo sources
and the signed unit-of-work brief. Add no speculative structured target block.
A real non-derivable standing workflow rule must be shaped before adding one
small canonical representation to root `AGENTS.md`; a panel-only presentation
mapping belongs only in `.octo-lite/control-panel.toml` and cannot redefine
repo law.

`<Turbo-Outreach worktree root>/CLAUDE.md` is a tracked relative symlink to
`AGENTS.md`. It is not an independently maintained policy file.

`/root/octo-lite/AGENTS.md` governs development of octo-lite itself.
`/root/octo-lite/profile/AGENTS.md` is the installed generic workflow-routing
profile. Neither may contain Turbo-specific instructions.

Turbo specs and ADRs may of course contain Turbo product behavior; the
exclusive `AGENTS.md` rule concerns standing agent/repository instructions,
not the product's durable behavioral specification.

### Worktrees and instruction currency

Turbo's root `AGENTS.md` remains versioned with Turbo and is never symlinked
across worktrees. Each worker consumes the version in its actual worktree. A
spawn checks that the branch includes the instruction revision from its
declared base. If the PR intentionally edits `AGENTS.md`, the branch version
applies and that instruction change is reviewed in the same PR.

Generic octo-lite installations use symlinks to the canonical octo-lite source
for the global profile, role-skill map, Claude/Codex runtime adapters, skills,
and workflows. Concretely, the current global profile links are
`~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` to
`/root/octo-lite/profile/AGENTS.md`; the installed role-skill map links to
`/root/octo-lite/role-skills.json`. A copied installed workflow is a drift
defect.

Role prose has exactly one canonical Markdown source per role. Claude profiles,
Codex TOML, and workflow launch metadata may differ in format, but they contain
only runtime metadata or are generated thin adapters; they do not restate the
role contract. The canonical Claude workflow reads that role source directly
and injects it verbatim for the Codex reviewer.

If a branch changes Turbo `AGENTS.md`, already-running sessions remain pinned
to the revision they acknowledged. No role-bearing session may continue under
the new repo law until a fresh worker starts or a persistent orchestrator
explicitly re-bootstraps and acknowledges the new revision.

Memory is never an instruction source. It may contain only a date, scope,
observed failure, and pointer to the durable fix or source. It cannot establish
current scope, status, authority, lifecycle position, or policy.

Any role may write a short dated, scoped, evidence-backed gotcha with a pointer
to its durable fix. At stream close, the stream orchestrator reviews those
entries and promotes, supersedes, or deletes them. There is no memory registry,
compiler, approval workflow, or automatic policy extraction.

## Role and model topology

The approved supervision tree is:

```text
Fable meta-operator
└── Claude Opus stream orchestrator
    └── Claude Opus subordinate orchestrator, when useful
        ├── Claude Sonnet 5 implement/fix workers
        ├── GPT-5.6 Sol post-grill shaping reviewers
        ├── GPT-5.6 Sol code reviewers
        ├── Claude Sonnet 5 QA capture workers
        └── GPT-5.6 Sol QA reviewers
```

- The sole meta-operator uses exact `claude-fable-5` at xhigh in auto mode and
  owns the reconciled operation-level view. Fable 5 has 1M context by default,
  so no `[1m]` suffix is used. Unavailability fails visibly with no silent
  Opus or other-model fallback.
- Every non-meta stream or subordinate orchestrator uses exact
  `claude-opus-4-8[1m]` at high effort in auto mode and owns one bounded
  coherent stream. Unavailability fails visibly; no silent model fallback.
- Fable also starts in auto mode. Runtime mode changes interaction friction,
  not authority.
- Orchestrators may nest to any useful depth, but every orchestrator has
  exactly one parent.
- Implementation and every fix pass use exact `claude-sonnet-5` at xhigh.
- Every post-grill shaping review uses a fresh Codex `gpt-5.6-sol` instance at
  xhigh reasoning effort on the fast service tier.
- Code review and every re-review use fresh Codex `gpt-5.6-sol` instances at
  high reasoning effort.
- QA capture uses a fresh exact `claude-sonnet-5` instance at high effort.
- QA review uses a fresh Codex `gpt-5.6-sol` instance at high reasoning effort
  on the fast service tier.
- Each reconciliation sweep uses fresh exact `claude-sonnet-5` at high effort
  with no fallback. Deterministic helpers perform exact checks and give Sonnet
  one compact normalized snapshot. Sonnet classifies only changed, missing,
  stale, contradictory, or `needs_fable`; it cannot write, override an exact
  mismatch, investigate open-endedly, or silently resolve ambiguity. Fable
  judges escalations.
- Rolling model aliases are not used for pinned roles.
- QA capture and QA review remain independent cross-provider roles, and every
  round starts new instances.

All LLM-facing roles, skills, launch instructions, briefs, handoffs, verdicts,
receipts, and statuses are extremely concise and may sacrifice grammar for
concision. They use no em dash or en dash characters. Generated artifacts
reference pinned canonical sources instead of restating specs, issues, roles,
logs, or prior artifacts. They carry only facts required for authority, gates,
recovery, or the next consumer. Detail expands only for a finding, failure,
ambiguity, operator decision, or explicit request. No arbitrary length cap may
truncate a required fact; compact schemas and references enforce leanness.

The complete LLM role roster is:

- Meta-operator.
- Orchestrator.
- Issue shaper.
- Post-grill shaping reviewer.
- Implementer.
- Code reviewer.
- QA capture.
- QA reviewer.
- Read-only reconciler.

Every fix uses a fresh implementer instance, every re-review uses a fresh code
reviewer, and every nested stream owner uses the same orchestrator contract.
Acceptance recording, merge, evidence publication, Linear transition,
preproduction promotion, and live traffic shift remain deterministic
operator-authorized helpers rather than LLM roles. The control panel displays
those gates and helpers separately from the role roster.

Every implementation issue has exactly one dedicated Opus issue orchestrator.
A multi-issue epic adds one separate Opus epic orchestrator above those issue
orchestrators. The epic Opus owns cross-issue dependencies, topology, carrier
integration, and the epic outcome. Each issue Opus owns only its issue scope,
branch, gates, fresh workers, and status. When the issue or epic finishes, its
durable state is archived and its orchestrator terminates; the session is never
recycled for later work.

## Role loading without a framework

Because all orchestrators are Claude Opus, octo-lite can lean on Claude
workflows instead of building a cross-runtime orchestration platform.

Every repo-bound Opus orchestrator launches through the canonical
`herdr-spawn` path with its cwd set to the target worktree. It verifies that
worktree's root `AGENTS.md` revision before directing repo work. Fable may start
in a neutral inventory context, but before directing a Turbo stream it records
the target repo, declared base, instruction revision, and child cwd. Changing
cwd after a session starts is not instruction bootstrap.

One canonical Claude workflow owns the loop. A small in-workflow role helper:

1. Reconciles the durable stream facts during ordinary orchestration, then at
   the launch boundary refetches the exact issue revision/status and current
   PR base/HEAD and verifies the pinned spec/readiness inputs still match.
2. Provisions the fresh pass worktree beneath an allowlisted workspace root,
   canonicalizes the path, and rejects the root itself, traversal, collision,
   or symlink escape.
3. Resolves the named canonical `roles/<role>.md` contract and executable
   configuration from `roles.toml`.
4. Preloads every required skill and only matched conditional skills so the
   role contract, map revision, and skill contents are pinned for that
   instance.
5. Pins provider, exact model, effort, and auto/permission mode.
6. Starts the worker in that worktree with a new spawn ID. The child repeats a
   single bootstrap check of canonical cwd, git root, remote, worktree, expected
   starting HEAD, and root `AGENTS.md` revision before mutation.
7. Supplies the current Linear/spec/PR/brief envelope, relevant grill record,
   shaping-review receipt when required by the role, and output shape.
8. Captures the exact provider session identity and validates the child's
   compact bootstrap acknowledgment.

Codex Sol shaping and code reviewers are external relays with distinct
canonical role contracts, even though they share a model family. The Claude
workflow injects the selected contract verbatim rather than maintaining a
shortened reviewer prompt.

`roles/<role>.md` owns role responsibilities, authority, stop conditions,
inputs, and outputs. `roles.toml` owns provider, exact model, effort, permission
mode, tools, required and conditional skills, and contract path. Neither
duplicates the other. The map contains no target rules, issue scope, live
state, secrets, or operator decisions.

One small resolver composes those sources before every native Claude Workflow
agent invocation or Sol relay. The launch receipt records role path and git
blob, `roles.toml` revision, exact runtime values, and resolved skills.
Generated Claude Markdown and Codex TOML adapters are launcher inputs and
diagnostics only. Installed adapters symlink to their source-repo copies and
never provide an alternate role-bearing spawn path.

Generation fails if an adapter cannot express a required platform field. One
path-filtered CI dry run proves the effective contract reached the spawned
session. If the Workflow runtime cannot read canonical files directly, a
deterministic build injects exact role text and source blob without handwritten
prompt literals.

Raw role-bearing worker spawns outside this helper are prohibited. This helper
is a workflow function, not a process or service. It does not need a policy
compiler, role registry service, global reconciliation sweep, or giant spawn
manifest. Containment is checked only at provisioning and child bootstrap, not
before every command. Thin revision identifiers remain where needed to prove
instructions, authority, scope, and topology.

A small startup receipt is enough:

```text
spawn ID, exact provider session identity, parent, and reply route
role and actual provider/model/effort/mode
repo/remote/worktree
Turbo AGENTS revision and included-from-declared-base check
Linear issue and readiness revision
spec revision and relevant grill-log cutoff
PR/base/topology/HEAD
four-section brief revision
required skills loaded
shaping-review verdict and reviewed revisions, for implementation and later gates
ready or blocker
```

A prompt glyph is not startup readiness. Implicit continuation such as
`--last` is prohibited. A mismatch in cwd, repo, remote, instructions, runtime,
scope, base, HEAD, or brief stops mutation. OS process, pane, and turn IDs stay
in ephemeral operational status when useful for cleanup or diagnosis; they are
not required in every durable gate artifact. The handoff records the final
HEAD separately because the receipt describes the pass's starting boundary.

Role and generic prompt changes are pinned when a session starts. Changes
apply to newly spawned sessions only; they do not silently rewrite an active
orchestrator or worker's role contract.

## Shaping and delivery contract

Linear is the primary tracking source for development issue identity, the
high-level objective, material operator decisions and context, explicit
non-goals, and lifecycle status. The canonical spec/ADR is the implementer's
primary behavioral contract and owns detailed behavior, acceptance rules,
interfaces, edge cases, constraints, and the facts from which tests are
derived. GitHub PRs own code review, branch discussion, and merge readiness.

The relevant grill/conversation log is evidence of what the operator considered
and ruled. It is an input to reconciliation, not a fourth implementation
contract. Once reconciled, an implementer should not have to infer behavior
from chat history. Linear should link to the spec and summarize high-level
decisions/context instead of duplicating the detailed contract.

Shaping is complete only when all four agree:

1. A Linear issue containing the high-level objective, material decisions and
   context, and explicit non-goals.
2. A canonical spec or ADR revision containing the complete implementable and
   testable behavioral contract.
3. One evolving draft PR linked to the Linear issue and containing the reviewed
   spec revision.
4. A clear verdict from a fresh post-grill shaping reviewer bound to those
   sources and the reviewed conversation-log cutoff.

The issue shaper performs a docs-backed adversarial grill and walks the
user-voiced story and every spec acceptance rule with the operator one question
at a time. It cannot treat scope it authored itself as operator-approved
readiness.

After the grill, the shaper reconciles the spec, Linear issue, and same draft
PR. A fresh, read-only shaping reviewer then independently inspects the
canonical spec/ADRs, the complete relevant grill/conversation log through an
explicit cutoff, the current Linear issue, target-repo instructions, the draft
PR readiness HEAD, and the proposed spec-driven TDD contract. The reviewer is
not another shaper: it may not edit sources, invent product decisions, or mark
an unresolved judgment as approved.

The reviewer receives durable raw transcript/session references and the
declared stream/issue log scope, not only a shaper-authored summary. It records
which logs and cutoffs it inspected. A relevant log that is missing or
inaccessible is blocking rather than silently excluded.

## User-story product surface

The user-story catalog has two uses. It is a product-facing surface and a QA
verification contract for full-pipeline checks. It is not QA evidence. Story
records do not embed screenshots, videos, verdicts, proof links, or acceptance
state.

Full-pipeline QA consumes a pinned catalog revision and produces separate
coverage, evidence, and verdict artifacts that reference stable story IDs. QA
capture and QA review do not author or silently rewrite product-story truth.
Turbo owns one indexed canonical spec-chat story document, initially
`spec/domains/topicfinder-user-stories.spec.html`. Each story has a stable
anchor and direct links to the spec anchors that define detailed behavior.
Story IDs use `TF-US-<origin Linear number>-<two-digit ordinal>`, such as
`TF-US-437-01`. The issue number records origin only. IDs are never renamed,
renumbered, or reused. The shaper finds the next ordinal in the document; no
registry exists. A retired story remains in place with `retired` status and an
optional successor link. The control panel discovers and renders the document
through the normal read-only spec path.

Each active record contains only its stable ID, short title, `active` status,
one user-voiced story sentence, exact spec-anchor links, and origin Linear
issue. A retired record may add one successor link. Product-surface sections
provide grouping and Git provides history. Records contain no ACs, QA fields,
owners, metrics, dates, or implementation detail.
There is no user-story Notion mirror or publisher, separate story service or
database, special control-panel backend, mandatory graph, or parallel chart
dataset. A small derived visual is optional only when it materially improves
comprehension.

The issue shaper updates the story document during shaping whenever approved
work creates, changes, or retires a user outcome. The story change and linked
spec changes stay on the same evolving draft PR before the final fresh shaping
review. That reviewer verifies story-to-spec alignment and blocks readiness on
a material mismatch. Implementers, reviewers, QA roles, acceptance helpers,
and merge helpers consume the pinned revision without maintaining it. After
merge, normal spec discovery makes `main` visible in the control panel. No
publication job runs.

The initial migration treats the 82-story QA-derived Markdown catalog only as
candidate source material. A shaper-led curation groups duplicate and bug-level
entries into durable user outcomes, removes evidence links, verdicts, AC dumps,
proven counts, and QA status, then assigns stable IDs and exact spec links. The
result receives direct spec-chat review. Delete legacy `spec/user-stories.md`
only after the replacement is approved.

Routine issue QA verifies only active story IDs changed or claimed by the
shaped issue. An explicit full-pipeline run verifies every active story against
one pinned story/spec revision. Retired stories are excluded; missing or
unexecutable active stories are `not evidenced`, never silently skipped. There
are no suite tags or secondary test catalog.

The shaping reviewer checks that every material operator ruling is represented
in the canonical spec or explicitly classified as high-level context or a
non-goal; that Linear and the spec do not contradict or accidentally expand
one another; that the spec is implementable and testable across behavior,
acceptance rules, interfaces, edge cases, and constraints; that the TDD
contract derives from the spec; and that the draft-PR readiness HEAD actually
contains the reviewed spec revisions. It returns only `clear` or `blocking`,
with source pointers and a reconciliation owner for every finding.

A documentary mismatch returns to the issue shaper. A missing product judgment
resumes the operator grill one question at a time. Any reconciliation that
changes a reviewed spec/ADR, material Linear decision/context, relevant log
cutoff, or readiness HEAD requires another fresh shaping-review instance. The
reviewer never fixes its own findings.

Linear `Shaped` is the canonical readiness state. Set it only after the fresh
shaping reviewer returns a clear durable verdict on the evolving draft PR. The
verdict binds the relevant Linear content fingerprint, exact PR and shaping
HEAD, canonical spec/ADR blobs, relevant grill-log references and cutoff,
clear or blocking result, and reviewer receipt reference. Linear links the PR
verdict without copying its proof. Launch refetches every source and returns
the issue to shaping when any binding is stale. There is no separate readiness
TOML or control-directory artifact.

Shaping and implementation use that same draft PR. A contract change returns
the same PR to shaping; it does not create a replacement spec PR or a second
implementation PR.

For Linear-tracked work, GitHub issues and historical mirror issues are not
active scope and are not created or updated unless the operator explicitly
requests a GitHub issue operation. GitHub PRs remain the code-review surface.
Turbo's generic instructions must distinguish unshaped requests from a shaped,
operator-ready loop so ready work is not sent through redundant planning.

Spec-driven TDD is a hard rule. Every behavior-changing implementation and fix
begins with a failing test derived from the canonical spec, proves the intended
red, makes the smallest green change, and records the red and green
commands/outcomes in the durable handoff. A waiver must be narrow,
operator-approved during shaping, and name the alternative proof.

If Linear's high-level decisions/context conflict with the canonical spec/ADR,
or if the spec is incomplete for implementation, implementation stops and
returns to shaping. Neither source silently wins, and the implementer never
fills the gap from conversation memory.

## Branch and release topology

The stable identity is Linear issue + spec + evolving draft PR. The PR's base
is not permanently frozen at shaping time.

The stream orchestrator may select and revise mainline, stacked, or
integration-train topology under standing authority. It escalates only when a
change affects product scope, ship grouping, or material risk. A topology
change must preserve shaped scope and verify merge base, ancestry, and
effective diff. Any PR-base or effective-diff change invalidates review and QA
for the prior topology. It does not invalidate shaping unless scope, story, AC,
or durable behavior changed.

A multi-PR train has one carrier PR and a small manifest listing member Linear
issues, PRs, pinned heads, order, integration branch, target, owner, and gate
status. The manifest owns delivery topology only; it does not duplicate Linear
scope or lifecycle state.

## Worker loop and gates

Every shaping review, implementation, fix, review, re-review, QA capture, and
QA review pass is a fresh instance. Never resume a worker for a later pass and
never use an implicit or global `--last`. Continuity lives in durable artifacts,
not worker memory.

The exact-head chain is:

```text
docs-backed grill
  -> reconciled spec/Linear/draft PR
  -> clear fresh Sol xhigh/fast shaping review
  -> shaped readiness bound to exact revisions
  -> spec-derived red/green implementation handoff
  -> clear independent code review
  -> appropriate QA/nonvisual evidence
  -> independent verdict
  -> explicit operator acceptance
  -> merge transaction
  -> deployment transitions
```

Every fix is followed by a fresh re-review. At most three review/fix cycles are
allowed. If the third re-review does not clear, the work returns to shaping.

Shaping and code review each publish one concise machine-readable PR verdict
comment through a deterministic helper. The comment records review type, clear
or blocking verdict, exact HEAD, bound inputs, findings, and reviewer receipt
reference. It is the only required GitHub review artifact. The workflow does
not depend on the formal Review API, reviewer-account preflight, check runs,
optional mirrors, or fallback branching.

If executable behavior, tests, or a canonical spec/ADR changes, review and
downstream QA rerun. A change limited to packet wording or evidence metadata
does not invalidate product gates when the effective product diff is
unchanged. This remains a judgment rule, not a classifier or hash system.

Worker or workflow completion is only a process fact. It never implies issue
readiness, operator acceptance, staging, or delivery. Every update names the
product gate separately from worker/run status.

The durable handoff records the target repo's canonical validation commands,
executed and skipped test counts, required environment capability, and the CI
result for the exact HEAD when available. Required DB-backed coverage cannot
silently skip. A missing dependency, environment, or validation capability is
a blocker when it affects acceptance, not permission to narrow the gate.

There is no global stage-duration rule. Each active pass has an accountable
owner and a watched completion condition. On silence, timeout, kill, or
provider overload, inspect the worktree, commits, process, and output artifact
before retrying. Preserve completed on-disk work and never create duplicate
work merely because the response channel timed out.

Only a failed or interrupted pass adds a small failure record to the existing
`status.md` or pass handoff. It contains the attempt and exact
session/worktree/starting HEAD, original error or output reference, one simple
class (`input/contract`, `environment`, `provider/session`,
`implementation/validation`, or `external dependency`), useful work found
(`none`, `uncommitted`, `committed`, `pushed`, or `artifact produced`), owner
and next action, and whether a fresh retry is safe or shaping/operator action is
required. If the worker cannot report, the accountable orchestrator records the
result of its inspection.

Every retry is a fresh role instance. A retry may start only after useful work
is preserved and the record names what the new instance should consume. A
successful pass carries no failure metadata. There is no retry database,
timer, automatic scheduler, circuit breaker, jitter policy, or elaborate
failure taxonomy; add such machinery only in response to measured recurring
failures the simple record cannot manage.

## QA and evidence

Evidence is selected per acceptance criterion:

- Before capture, QA capture writes a small per-AC evidence plan selecting the
  minimum honest proof set.
- Screenshots are the default for stable visible states.
- One screenshot or a concise ordered group may prove a stable state or state
  sequence when every image has a distinct purpose.
- Video is used only when motion, sequence, timing, playback, drag/drop, or
  another interaction cannot be proved honestly with stills.
- Do not capture both screenshots and video unless each format proves a
  distinct criterion or risk.
- Backend-only work uses code review, real validation, and contract-relevant
  nonvisual evidence rather than ceremonial browser capture.
- UI work captures the viewports required by the shaped story.
- QA review is performed by a fresh independent worker that actually inspects
  the artifacts and grades each AC pass, fail, or not evidenced.

Backend-only work still emits a typed nonvisual evidence manifest and an
independent per-AC verdict for the exact reviewed HEAD. A deterministic helper
assembles clear code review, exact HEAD, affected story IDs, spec criteria,
real unskipped validation, and contract-check outputs. A fresh QA reviewer
checks evidence sufficiency and per-criterion coverage without repeating code
review. Every issue entering `Awaiting Accept` receives a served acceptance
card even when there are no screenshots. `user_facing=false` changes the
evidence type, not the packet, review, or visibility gate.

Before reporting an issue ready for operator acceptance, the accountable
orchestrator opens or queries the served review page and confirms that its card
is present and reviewable for the current issue, PR/HEAD, verdict revision, and
AC coverage. This is a simple served-card readback, not a cryptographic accept
command.

The evidence site is the operator's acceptance-review surface. It presents the
visual or nonvisual artifacts plus the fresh QA reviewer's satisfied or
blocking verdict. Only a satisfied verdict may be offered for acceptance. The
operator reviews the served artifacts and verdict, then explicitly accepts or
rejects. The QA verdict is necessary but never acts as human acceptance.

QA capture produces artifacts and a manifest. A deterministic publication
helper updates the evidence site and queue index. QA workers never mutate the
site index or whole-operation dashboard directly. Evidence publication and QA
verdict changes are meaningful gate changes: the orchestrator updates
`status.md` and notifies its parent, then Fable reconciles the dashboard. Every
issue entering `Awaiting Accept`, including backend-only work, has a served
card.

Routine per-issue evidence publication targets no more than five seconds.
Explicit full-archive repair builds target no more than sixty seconds. Turbo's
evidence adapters and site instantiation live with Turbo; the optional generic
control-panel renderer and contracts do not.

Routine publication writes one durable per-issue manifest/card and atomically
updates the queue index through a single-flight path. Full-archive repair is an
explicit separate operation. Multiple lanes cannot concurrently rewrite the
shared index. Published evidence is checked for credentials, sensitive fixture
data, and inappropriate PII before it becomes operator-visible.

## Linear lifecycle ownership

Gate-critical reads use one small Linear-specific `read-exact` workflow helper
that returns the complete issue plus stable identity, revision, and current
status without lossy normalization. Dispatch, readiness, and lifecycle gates
consume that result. Shapers and operators may still perform direct read-only
Linear exploration; harmless reads are not placed behind a permission system.

Mechanical stream transitions may be performed by the stream orchestrator only
through a transition-and-notify operation that updates Linear, updates the
stream's status file, and safely notifies its parent.

The routine compares the expected current Linear state, performs the mutation,
reads Linear back, then updates `status.md` and notifies the parent. It cannot
report success until all three agree. A partial failure is recorded as blocked
and retries only unfinished idempotent steps; it never blindly repeats a state
mutation.

These are foreground workflow functions, not a tracker service, cache, mirror,
poller, plugin framework, or shadow state store. The value is limited and
observable: gate decisions see an exact current revision, and a write cannot be
reported successful when Linear readback, stream status, or parent notification
disagrees. If these helpers grow beyond exact read and named role-authorized
transitions, the added behavior requires new shaping evidence.

The normal loop transitions are:

```text
Todo -> In Progress -> Awaiting Accept
```

Operator acceptance is a ledger fact, not another Linear state. An accepted
member of an integration train remains `Awaiting Accept` until it actually
merges to `main`.

The operator-owned acceptance helper is the sole writer of that ledger. Each
entry binds the issue, PR, reviewed HEAD, verdict revision, decision, operator
identity, and time. Pane text, queued text, or message acknowledgment is never
an acceptance record.

- `In Staging` means merged to `main`, which deploys to staging.
- An integration-branch or stacked predecessor merge is not `In Staging`.
- `In Preprod` means a verified candidate exists at zero percent live traffic.
- `Live` means the operator-authorized traffic shift actually occurred.

Acceptance, merge, the transition to `In Staging`, promotion to `In Preprod`,
and the live traffic shift remain exclusively operator-owned gates.

## Lightweight workflow tracing

octo-lite aligns with Langfuse's session, trace, and observation concepts at
the data-contract level only. It does not install or run Langfuse, an
OpenTelemetry collector, an SDK, a daemon, a database, or an exporter.

Each bounded workstream may have one append-only `trace.jsonl` in its existing
control directory:

- A session is one bounded orchestrator workstream or release train.
- A trace is one issue-delivery execution.
- An observation is one workflow boundary such as spawn/bootstrap, completed
  pass, gate verdict, retry/failure, Linear transition, accepted control
  message, merge, or deployment fact.

Records use stable names and portable IDs. The minimal envelope contains a
schema version; session, trace, and observation IDs; optional parent
observation ID; name and type; start time and optional end time; status; small
attributes such as issue, role, model, repo, HEAD, gate, and attempt; and links
to existing artifacts. It does not copy raw prompts, responses, transcript
bodies, logs, secrets, evidence, or product data.

Only deterministic foreground workflow and named gate helpers append
observations, and only at meaningful boundaries. Language-model agents never
write trace records directly; they return their normal receipts and artifacts
to the helper. Roles and skills do not carry repeated tracing instructions. A
later adapter may translate these records to OpenTelemetry or Langfuse without
changing the workflow contract.

One path-filtered CI job validates this contract when workflow helpers, role
contracts, or tracing files change. It checks a generated happy path, a
generated failure/retry path, and a few intentionally invalid fixtures. The
checker covers schema and parent integrity, rejects sensitive/raw-content
fields, and enforces only high-value cross-event invariants such as bootstrap
before mutation, fresh re-review after a fix, complete Linear mutation
readback, and inspection before retry. It uses dry-run local inputs and never
mutates Linear or other external systems.

This small conformance check does not replace spec-driven TDD or target-repo
tests. It replaces the proposed broad workflow test matrix. Runtime traces may
be attached as CI or incident artifacts when useful; they do not create a new
source of operational truth.

`trace.jsonl` inherits the lifecycle of its existing stream control directory.
There is no separate trace archive, retention duration, cleanup timer, or
pruning mechanism. An operator may deliberately preserve a sanitized trace as
an incident artifact when it has durable diagnostic value.

Runtime tracing is fail-open and fail-visible. A trace append failure writes
one concise `trace degraded` warning into the existing stream status, then the
workflow continues. It does not retry, block a gate, or weaken the gate's
authoritative artifact requirements. CI validation of a changed trace contract
remains fail-closed.

## Operator awareness without context flooding

The Fable meta-operator is the sole owner and writer of the reconciled
whole-operation view. It is not the sole collector of raw facts.

Each orchestrated stream uses two plain Markdown files under the operator's
durable control directory:

```text
streams/<stream>/brief.md   # parent-owned objective and authority
streams/<stream>/status.md  # child-owned current execution state
```

This two-file status mechanism is the approved lightweight design, not a new
octo-lite state service.

The four-section brief contains:

1. Hard invariants.
2. Owned scope.
3. Standing authority.
4. Must-escalate conditions.

Parents flatten only the relevant effective rules into a child's brief. No
policy inheritance engine is needed.

The brief carries stream scope, authority, topology, and escalation conditions
only. It references the worktree's root `AGENTS.md`; it never copies standing
Turbo repo rules.

The status file stays small:

```text
current gate and health
owned issues and each issue's gate/PR/HEAD
material change
whether parent reconciliation is needed
next action
```

On a meaningful change, the orchestrator overwrites `status.md` and sends its
parent one safe one-line `herdr-say` message containing the summary and file
path. Notify upward only when a PR/HEAD, evidence, scope, or topology change
materially changes the outcome, gate, blocker, required decision, or operator
action. Routine commits and ordinary progress update `status.md` without a
proactive message.

Status compacts upward one parent at a time. Leaf workers do not all message
Fable. The complete hierarchy remains visible in the control panel, while
Fable consumes reconciled top-level deltas.

### Sweep backstop

At session launch, Fable installs one session-bound host timer whose only action
is `operator-say sweep`. That small foreground helper reads
`operator-owner.toml`, verifies the exact owning Fable session, and delegates
delivery to `herdr-say`. This is an owned wake path, not an octo-lite service.
It remains durable for the entire operator session, including periods with no
active streams, and is removed only when the operator lifecycle terminates.

The sweep may spawn one fresh read-only reconciliation worker to inspect:

- Changed stream status files.
- Bounded Herdr pane tails.
- Linear issue state.
- PR, HEAD, review, and CI state.
- Evidence/verdict presence.
- Relevant deployment state.

The worker returns only changed, stale, contradictory, or missing facts. It
does not write the authoritative operation view. Fable reconciles the compact
delta, updates its bounded current-state record, and triggers the static
control-panel projection. A wake with nothing to reconcile is a cheap no-op;
the session timer remains installed.

Pane tails are discovery hints only. Rendered suggestions, ghost text, or
unsubmitted input are never operator authority or lifecycle evidence. The wake
must actually reactivate Fable or safely queue a message for its verified next
wake; a process that only logs drift is not supervision.

There is no event bus, state database, per-lane watcher fleet, or unbounded
transcript ingestion.

## Operator handoff

An operator-requested transfer from one Fable session to another is a
first-class workflow action. It is never inferred from silence, age, context
size, or provider behavior.

The outgoing operator writes one concise durable handoff artifact containing
the current objective, active stream tree and owners, current gates and exact
issue/PR/HEAD facts, pending operator decisions, granted authorities, blockers,
control-directory location, child reply routes, and owned timer. The successor
starts fresh from canonical instructions plus this artifact and reconciles it
against source systems. Full transcript replay is optional context, not a
correctness dependency.

Each requested handoff writes one immutable Markdown artifact at
`handoffs/<zero-padded-revision>.md` relative to the operator control directory,
starting with `handoffs/0001.md`. `operator-owner.toml` references the accepted
revision and path. The files inherit the control directory lifecycle and have
no separate archive.

The control directory contains one small `operator-owner.toml` with schema
version, exact owning Fable session ID, handoff revision, and control-directory
identity. After the successor reconciles and declares readiness, one helper
locks the record, verifies its expected old owner and revision, writes a
complete temporary TOML file, and atomically renames it over the prior record.
That rename is the sole authority commit.

Operator-owned mutation helpers verify their caller against this record before
changing the reconciled operation view or exercising operator-owned gates.
This is not a per-command check. The session timer and top-level child
notifications use `operator-say`, so their next delivery resolves the new
exact owner from the same commit. The old operator loses write authority at
the rename and may only forward late direct messages until cleanup.

Langfuse places no format requirement on this unrelated local control record.
TOML is used for the owner pointer; append-only telemetry remains in
`trace.jsonl`.

If the recorded owner dies before a requested handoff can commit, takeover
requires explicit operator authorization. The recovery helper verifies the
exact recorded Herdr session is dead or absent, starts a fresh Fable,
reconciles the handoff and source systems, then performs the same locked
expected-owner/revision atomic replacement. Ambiguous liveness blocks. No
timeout or automatic failover may transfer authority.

## Direct conversations with orchestrators

The operator may enter any Opus orchestrator's Herdr tab and hold a deeper
conversation without routing every sentence through Fable.

Herdr reserves `🧠` for the sole Fable operator tab and temporarily prefixes
`🎤` only while the operator must remain engaged in a direct investigation,
grill, diagnosis, or decision conversation. Reporting, commands,
acknowledgments, handoffs, and parent-child updates do not qualify. Fable judges
from bounded pane context and message provenance, not focus, keywords, turn
counts, or timeouts. The mic must disappear as soon as the Opus has enough
direction to begin autonomous work and the operator can look away. This is
required behavior, not optional cleanup.

Normal unattended tabs use no status emoji. Labels stay as short as possible
while remaining unique and human-readable. `◆` immediately precedes an epic
identity; normal issue identities are unmarked. Labels order the optional
operator signal, compact issue and PR numbers, then the very short outcome. The
tab omits the tracker team prefix; durable artifacts and receipts retain the full
issue key. The identity token is bare `issue/pr`, or only `issue` before a PR
exists. Only persistent Fable and Opus orchestrator sessions receive Herdr tabs.
Workflow subagents run inside the owning Opus session and never create tabs.
The sole Fable label is exactly `🧠 operator`, with no issue, PR, or outcome
suffix.

```text
🧠 operator
🎤 ◆443/6 · operating model
◆443/6 · operating model
🎤 446/6 · modal messaging
446/6 · modal messaging
445 · role contracts
```

- The orchestrator remains owner of its stream.
- The generic role contract remains pinned.
- An explicit operator ruling that affects only that stream is recorded in the
  child-owned `status.md` and may be applied immediately.
- The orchestrator sends a compact conversation delta to its parent.
- The scheduled bounded pane sweep catches the conversation if notification
  fails.
- The operator never has to repeat the conversation to Fable.

The child never edits its parent-owned `brief.md`. The parent incorporates any
material scope or authority change into a new brief revision before the next
child spawn or handoff. Acceptance, merge, and traffic-shift authority still
require their named durable gate artifacts and are never inferred from pane
text.

If a ruling affects siblings, shared branch topology, release order,
acceptance, or deployment, the orchestrator records the ruling but pauses the
cross-stream consequence until Fable reconciles it globally. The ruling is not
discarded or re-litigated; the pause prevents sibling streams from acting on
stale topology.

## Messaging

Every Herdr message uses `herdr-say`; raw paste-and-Enter sequences are
prohibited. `herdr-say` either submits at a verified safe prompt or durably
queues the message. Queued messages may auto-submit when the target becomes
safe through a verified Herdr/host mechanism, but never while a modal or
question dialog is active. octo-lite does not implement a queue service.

Every control message has a small durable identity: message ID, sender/reply
route, intended recipient/session, stream reference, and artifact pointer. Its
states are `queued`, `submitted`, `acknowledged`, and `completed` or `rejected`.
Exit success from the paste/submit helper alone is not acknowledgment.

Explicit recipient acknowledgment is required only for:

- Commands.
- Operator rulings.
- Ownership transfers.
- Blocking questions.

There is no arbitrary acknowledgment timeout. An action that depends on the
message waits for acknowledgment; unrelated work may continue. Completion is
proved by the durable artifact or observable outcome, not by the acknowledgment
alone.

## Optional control-panel surfaces

The optional panel contains:

1. **Operations** — outcomes, hierarchy, owners, gates, blockers,
   dependencies, PRs, deployment position, and next operator action.
2. **Evidence** — AC coverage, validation, screenshots/videos, verdicts,
   served-card readiness, and acceptance history.
3. **Specs** — spec-chat inspection and issue/spec/PR traceability.
4. **Roles & Configuration** — the current effective octo-lite system.

Once accurate and digestible across all streams, the TopicFinder-dev
operations/cards/Kanban view is the primary whole-operation surface. Until it
meets that bar, Fable provides complete outcome-first workstream updates; the
operator must never reconstruct the fleet from partial cards.

Each operation item shows outcome/epic, accountable orchestrator, current gate
and gate age, issue/PR/branch/train/HEAD, blocker and owner, last acknowledged
control message, next automatic action, separate next operator action, and
evidence/decision links.

The Roles & Configuration tab shows:

- Every role and orchestration relationship.
- Provider, exact model, effort, and permission mode.
- Required and conditional skills.
- The actual symlink-resolved `SKILL.md` contents.
- Generic lifecycle gates and target Linear mappings.
- Editable canonical role prompts and generic profile/system prompt.
- Workflow spawn graph.
- Claude/Codex installation and symlink health.
- A preview of the effective envelope a new role would receive.

Target Linear mappings shown here are projections of the one standing mapping
in Turbo's root `AGENTS.md`; the panel cannot own or override them.

Local edits are limited to `roles/*.md`, `roles.toml`, `profile/AGENTS.md`, and
`skills/*/SKILL.md` in `/root/octo-lite`. Generated adapters, workflows,
target-repo instructions, specs, and runtime state remain read-only. Save
validates and shows a git diff but never commits or pushes. Four path patterns
are sufficient; there is no per-file registry. Edits apply to future sessions
only. Hosted operation and evidence views remain read-only.

Static projections rebuild after meaningful gate changes and explicit refresh.
A failed build is surfaced; readiness is not claimed until the served card is
actually readable.

Evidence hosting remains target-repo operations. octo-lite adds no access
control, per-card permission, redaction, retention, or recurring broken-link
subsystem. Publication performs one exact-card and linked-artifact readback
before readiness. There is no periodic sweeper or cleanup timer. Known secrets
and credentials are never intentionally published.

## Workspace and resource hygiene

Do not build a scheduler or lease service. Before expensive work starts, the
accountable orchestrator checks disk health, isolated worktree availability,
conflicting ownership of branch/fixture/port/deployment resources, and active
provider overload.

Every pass has one dedicated worktree and exactly one writer. No other worker
or orchestrator may mutate its branch, index, generated outputs, or owned
runtime. The target repo provides one fail-fast worktree bootstrap covering
remote/base identity, dependencies, package/tool versions, environment
capability without copying secrets from a dirty checkout, required DB access,
disk/inodes, and canonical validation commands.

Fresh isolation does not require cold setup. One clean control clone supplies
shared Git objects to fresh per-pass worktrees. Target-repo bootstrap may reuse
only native, safely shareable caches; each worktree retains its own mutable
dependency tree and build outputs unless a cache is demonstrably immutable and
correctly keyed. Cache misses fall back to the normal correct installation.

octo-lite owns only that generic boundary. Turbo owns its actual bootstrap
command and cache details. For Turbo's current nested npm applications, that
means repo-local lockfiles, a shared native npm download cache and reusable
Puppeteer/browser downloads where compatible, with per-worktree `node_modules`.
Cold and warm bootstrap are measured before adding further machinery. There is
no cache daemon, dependency service, custom registry, copied mutable
`node_modules`, or persistent mutable issue checkout.

Worker worktrees are removed when a pass finishes. A dirty worktree stops
cleanup for inspection; it is never silently deleted. Cleanup starts only when
the handoff, commits, and pushes needed by the next fresh instance are durable
and recoverable. State-mutating QA
verifies and records fixture state and avoids concurrent mutation. Read-only QA
may share stable fixtures. Use unique fixtures only when already cheap.

Each applicable pass records its owned process IDs, ports, mutable fixture,
artifact root, and deployment resource. QA verifies the running app identity
before capture and tears down only its own processes. A stale shared resource
has a named owner and recovery path; it is never silently stolen.

Before declaring a provider or fleet outage, surface the original error,
inspect the pass worktree for completed work, run a fresh exact-model probe,
and classify the failure as lane-, session-, account-, provider-, or
fleet-scoped. Never promote one stale resumed-session auth failure into a fleet
outage. A pinned model waits or retries under the accountable orchestrator. It
is never substituted by a fallback model.

## Migration direction

There is no active work that requires a compatibility period. Perform a
coordinated cutover, validate it, and only then start new streams under the new
contracts.

The cutover must at minimum:

1. Remove Turbo-specific policy and credentials from octo-lite.
2. Make Turbo's root `AGENTS.md` the exclusive Turbo instruction source and
   make root `CLAUDE.md` its relative symlink.
3. Symlink installed octo-lite skills, role profiles, and Claude workflows to
   their canonical source, including both global profile entry points and the
   role-skill map.
4. Consolidate the nine LLM role/model/skill mappings, and expose acceptance,
   merge, publication, Linear transition, promotion, and traffic shift as
   separate deterministic helpers.
5. Make the Claude workflow load canonical role contracts and required skills.
6. Repair the implement -> review -> fix -> fresh re-review state machine.
7. Add the fresh Sol xhigh/fast post-grill shaping-review and reconciliation
   gate, preserve spec-driven TDD, and keep the same evolving draft PR
   throughout shaping and implementation.
8. Move Turbo evidence/site adapters into Turbo without creating a product
   dependency.
9. Fix every Fable/Opus launcher to use the canonical role-aware
   `herdr-spawn`, explicit trusted cwd, verified auto mode, and startup receipt.
10. Add the minimal `brief.md` + `status.md` + `herdr-say` + owned sweep
    supervision pattern.
11. Retire `/root/Turbo-Outreach-staging` as a canonical registry/source;
    establish a clean fetch/control repo and inventory existing worktrees by
    owner, HEAD, instruction revision, and dirty state.

The optional role/configuration inspector is a parallel enhancement, not a
core cutover gate. Its first useful slice may be a local read/edit/diff/validate
view over generic octo-lite sources; hosted operations/evidence/spec surfaces
can evolve independently.

## Known current gaps this draft is intended to close

- The installed Claude workflow is currently copied rather than symlinked.
- Role contracts are duplicated between Claude Markdown, Codex TOML, and
  workflow prompt literals.
- `role-skills.json` is descriptive rather than enforced by the loop.
- The current Codex reviewer relay receives abbreviated role prose.
- The executable role map omits operator, orchestrator, and QA roles; helper
  boundaries for acceptance, merge, publication, Linear transition,
  promotion, and traffic shift are also not enforced.
- The current workflow fixes a blocking review and can proceed without a fresh
  re-review.
- There is no independent post-grill shaping-review role or fail-closed receipt
  proving that the spec, conversation rulings, Linear context, TDD contract,
  and draft-PR readiness HEAD were reconciled before implementation.
- Generic octo-lite workflow text contains Turbo-specific paths, fixtures,
  credentials, state names, and dashboard mechanics.
- User-story maintenance remains legacy Turbo logic embedded in the generic
  workflow and a TopicFinder-specific generator under octo-lite. It conflates
  the product story surface with QA evidence, publishes to Notion, and does not
  define the new stable-ID and spec-anchor contract.
- Turbo's `AGENTS.md` and `CLAUDE.md` currently duplicate and diverge.
- Registered Turbo worktrees contain stale instruction variants.
- The current operator surface can report a packet ready before its served
  evidence card exists.
- High-level state reconciliation currently depends too heavily on session
  context and ad hoc manual sweeps.
- A stale resumed Codex 401 was incorrectly broadcast as a fleet outage before
  a fresh exact-model auth probe.
- GitHub rejected self-authored request-changes reviews in 82 audited Codex
  session files.
- Fresh worktrees repeatedly lacked dependencies or silently skipped required
  DB validation.
- `Awaiting Accept` backend work could lack a typed verdict and served card.
- Mutable `/root/Turbo-Outreach-staging` is stale and must not remain a
  coordination source.

## Grill status

None.
