# Reconciled Operating-Model Gap Backlog

## Status

This backlog is reconciled to the canonical operating-model spec through
Decision 104. It separates the coordinated octo-lite cutover from target-repo
follow-up. The canonical spec wins if wording here drifts.

## Current state

| Category | Status |
| --- | --- |
| Generic kernel: roles.toml, 8 role contracts, resolver, generated adapters | Implemented, live-installed |
| Prompt TDD lean contract (behavior-first, fresh-session red/green, narrow regression) | Implemented in spec, this compliance artifact, and the decision log |
| One-issue-Opus shaping topology (orchestrator resolves issue-shaper as a skill) | Implemented; real receipt on file, PR 6 fix pass 4 |
| Codex custom-agent adapter, Herdr ack-only delivery, dead-owner recovery, cross-issue Linear authority | Boundary cut and signed by ADR 0001, superseding PR 6's fix-pass-5 patches; carrier PR 6 still exact-head review blocked pending a fresh review of the final head |
| Repo-owned generic QA evidence capture skill (`skills/qa-evidence-capture`) | Implemented; qa-capture role no longer depends on an external profile copy |
| Turbo PR 423 (target-repo consumer of this model) | Draft, returned to shaping after eight blocking review cycles |
| Optional control panel, evidence-site visuals, Symphony-derived ideas | Deferred optional; not built, not scheduled |

This table summarizes current status only. It does not replace or rewrite the
historical backlog below.

## Approved P0 reliability work

### P0 — fail closed

- Make null, malformed, stale-head, blocking, and ambiguous reviews stop the
  workflow.
- Re-review every implementation fix before QA.
- Bind implementation handoff, review, QA manifest, QA verdict, acceptance,
  and merge to exact commit SHAs.
- Remove mandatory-video capture; select screenshots or video per acceptance
  criterion based on what must actually be proven.
- Require a small per-AC evidence plan before capture. Prefer one screenshot or
  a concise purposeful group; use video only when stills cannot prove the
  behavior, and avoid duplicate ceremonial proof.
- Publish every acceptance packet, including backend-only packets, through one
  deterministic evidence-site helper with exact-card readback. QA workers do
  not mutate the site index or dashboard.
- Treat evidence publication and QA verdict changes as meaningful stream
  status deltas. Notify upward and let Fable alone reconcile the operation
  dashboard.

#### Turbo target follow-up, not TUR-443

- Extract TopicFinder user-story catalog maintenance from generic octo-lite
  workflow code. Preserve it as a product surface and full-pipeline QA
  contract, not QA evidence. Turbo owns its indexed spec-chat content;
  octo-lite owns only reusable QA consumption mechanics.
- Give stories stable product IDs and explicit links to canonical spec anchors.
  Add a path-filtered link check for unique IDs and resolvable anchors; do not
  duplicate detailed acceptance rules into the story catalog.
- Use `TF-US-<origin Linear number>-<two-digit ordinal>` IDs. Preserve retired
  stories in place with optional successor links; never rename or reuse IDs.
- Keep story records minimal: ID, short title, active/retired, one user-voiced
  sentence, spec links, origin issue, and optional retirement successor.
- Make issue QA select only changed or claimed active stories. Make explicit
  full-pipeline QA select every active story at one pinned revision, with no
  silent skips or secondary suite tags.
- Present QA artifacts and the fresh QA-review verdict together on the evidence
  site before operator acceptance. Keep human acceptance explicit and
  separate from the agent verdict.
- For backend-only work, collect real validation and contract outputs without
  browser capture, then require a fresh QA-review sufficiency verdict before
  offering the served packet for operator acceptance.
- Remove the user-story Notion publisher, synchronization state, and merge
  failure gate. Render the canonical story document through the control
  panel's existing read-only spec path, with no separate story backend.
- Make issue shaping update the story document when an approved outcome is
  created, changed, or retired. Require the final shaping reviewer to verify
  story-to-spec alignment. Keep every downstream delivery role read-only.
- Curate the 82-story legacy Markdown catalog rather than converting it
  mechanically. Dedupe durable outcomes, strip QA-derived fields, add stable
  IDs and spec links, review in spec-chat, then remove the old file.

#### octo-lite cutover resumes

- Refuse an empty high-level objective, missing spec behavior/acceptance rules,
  and missing readiness identity.
- Refuse implementation when the PR shaping verdict does not match the current
  material Linear decisions/context and referenced spec/ADR blobs.
- Require spec-derived red/green evidence for every behavior change; remove
  `where practical` and conditional TDD activation.
- Refuse `Shaped` unless a durable verdict on the shared draft PR binds the
  relevant Linear content, shaping HEAD, canonical spec revision, relevant
  grill-log cutoff, and a clear result from a fresh shaping reviewer.
- Refuse implementation when the shaping-review verdict is blocking, missing,
  produced by a reused session, or bound to stale Linear/spec/PR/log inputs.
- Treat a relevant missing or inaccessible raw conversation log as a blocking
  shaping-review input failure; a curated shaper summary is not sufficient.
- Verify Linear transitions with read-back.
- Add one Linear-specific exact gate-read helper and named role-authorized
  transition helpers. Keep exploratory reads direct and build no generic
  tracker service, plugin system, cache, mirror, poller, or read ACL.
- Verify PR base and topology revision after every stage, without assuming the
  correct base is `main`; allow only declared, diff/ancestry-checked
  transitions.
- Remove target credentials and raw fixture passwords from versioned generic
  prompts.
- Replace Codex `resume --last` with exact session IDs.
- Publish shaping and code-review gates as concise exact-HEAD PR verdict
  comments through one deterministic helper.

### P0 — prove bootstrap and delivery

- Route every role-bearing spawn through one foreground helper; start the child
  in the provisioned target worktree and capture its exact provider session ID.
- During ordinary orchestration reconcile durable facts, then at the launch
  boundary refetch the exact Linear revision/status and PR base/HEAD and verify
  pinned spec/readiness inputs.
- Provision beneath an allowlisted workspace root and validate canonical cwd,
  git root, remote, worktree, starting HEAD, and target `AGENTS.md` at exactly
  two boundaries: provisioning and child bootstrap.
- Launch every Claude meta/stream orchestrator with `--permission-mode auto`
  and verify the effective mode in its bootstrap acknowledgment.
- Require one compact bootstrap acknowledgment covering spawn/session,
  parent/reply route, role/model/mode, repo/worktree/starting HEAD, instruction
  and skill revisions, Linear readiness, spec, PR/topology, brief, and shaping
  review when applicable; keep final HEAD in the pass handoff.
- Add message IDs plus submitted/accepted/completed acknowledgments.
- Make send/spawn helpers propagate command failures.
- Reject workspace-root launches, collisions, traversal, symlink escape,
  mismatched receipts, mutation before acknowledgment, and implicit `--last`.
- Do not build per-command cwd policing, a global reconciliation service, or a
  giant cryptographic spawn manifest.

## Resolved grill dependencies

### Branch, merge, and state model

Decisions 3, 3a, 3b, 10a, 10b, and 10c resolve this boundary:

- One evolving draft PR continues through shaping and implementation.
- The orchestrator may choose `main`, stack, or release-train topology under a
  versioned ancestry/effective-diff contract.
- A train uses one carrier PR and one topology-only member manifest.
- Linear stays `Awaiting Accept` for accepted stack/train work until the commit
  reaches `main`; merge to `main` means staging and `In Staging`.
- Preprod is a verified zero-traffic candidate; Live requires the actual
  operator-authorized traffic shift.

### Session and authority model

Resolved direction:

- Bounded persistent orchestrators; fresh instances for every worker pass.
- Four-section authority brief and compact spawn acknowledgment.
- Session-durable Fable sweep wake.
- Explicit first-class operator handoff with one atomic
  `operator-owner.toml` authority commit and operator-authorized dead-owner
  recovery.

### Resource scheduler scope

Decisions 11a through 11c reject a scheduler or allocator service:

- One lightweight pre-spawn check covers disk, isolated worktree, conflicting
  branch/fixture/port/deployment ownership, and provider overload.
- Completed worker worktrees are removed after durable handoff, commit, and
  push; dirty worktrees stop for inspection.
- State-mutating QA verifies and records a non-conflicting fixture; read-only QA
  may share stable fixtures.

## Candidate octo-lite changes

### Generic kernel and role contracts

Targets:

- `profile/AGENTS.md`
- New `roles.toml`
- New canonical `roles/<role>.md` contracts
- Existing `role-skills.json` for coordinated removal
- `agents/octo-lite-implementer.{md,toml}`
- `agents/octo-lite-reviewer.{md,toml}`
- New canonical post-grill shaping reviewer, orchestrator, QA capture, QA
  review, meta-operator, issue-shaper, and read-only reconciler role contracts.
  Superseded by Decision 104: implemented as exactly eight roles, with issue
  shaping a conditional skill the orchestrator resolves in its own session,
  not a separate role contract.
- Pin QA capture to fresh exact `claude-sonnet-5` at high and QA review to
  fresh `gpt-5.6-sol` at high on the fast service tier. Start new instances
  every round.
- Pin every stream and nested orchestrator to exact
  `claude-opus-4-8[1m]`, high, auto. Fail visibly if unavailable; never use a
  silent model fallback.
- Pin the meta-operator to exact `claude-fable-5`, xhigh, auto, using Fable's
  default 1M context. Replace the launcher's rolling `fable` selector and fail
  visibly rather than falling back.
- Use fresh exact `claude-sonnet-5` at high for reconciliation with no
  fallback. Feed it deterministic normalized snapshots, forbid writes and
  mismatch overrides, and route ambiguity to Fable.
- Add the optional panel under `control-panel/` in octo-lite with isolated
  frontend dependencies and build output. Core workflows ignore it unless
  invoked. Build no sibling repo or service.
- Make every role, skill, launch instruction, brief, handoff, verdict, receipt,
  and status minimally complete. Reference pinned sources instead of copying
  them, expand only for exceptions, and use no brittle length caps.

Changes:

- Remove TopicFinder-specific policy from the global profile.
- Make one canonical role body generate Claude, Codex, and workflow adapters.
- Pin model/effort in executable role configuration.
- Pin the shaping reviewer to a fresh `gpt-5.6-sol` instance at xhigh on the
  fast service tier and attest the actual runtime values.
- Add a dedicated read-only `shaping-reviewer` entry to `roles.toml` with
  access to specs, raw session logs, Linear, and PR state but no source, issue,
  or PR mutation authority; do not reuse the code-reviewer contract.
- Add bootstrap, authority, exact-head, and output schema requirements.
- Make each role's allowed skills and state mutations machine-checkable.
- Define the minimal machine-readable PR verdict-comment shape from the
  issue-shaper and reviewer contracts; create no separate readiness file.
- Replace the octo-lite-owned role-skill JSON with `roles.toml` in one shaped
  change covering all readers, prompts, generated adapters, documentation,
  validation, and installed symlinks. Keep JSON only at required
  interoperability boundaries.
- Add one role resolver. Record contract path/blob, map revision, runtime
  values, and resolved required/conditional skills in launch receipts.
- Treat generated Claude Markdown and Codex TOML adapters as canonical-launcher
  inputs and diagnostics only. Fail on platform field loss and prohibit raw
  adapter spawns.
- Add one path-filtered check for TOML validity, exact generated adapters, and
  dry-run native Workflow role resolution. Do not add a broad matrix.
- Keep acceptance, merge, evidence publication, Linear transition, promotion,
  and traffic shift as deterministic operator-authorized helpers rather than
  adding LLM role contracts for them.
- Maintain octo-lite's canonical operating-model behavior in
  `spec/domains/operating-model.spec.html`; keep the Markdown audit packet as
  evidence and chronology only. Do not generate Markdown twins.

### Workflow engine

Targets:

- `workflows/octo-loop-qa.js`
- `skills/octo-lite-loop/SKILL.md`
- Workflow installation docs/tests.

Changes:

- Replace literal target configuration with discovery from root `AGENTS.md`,
  the spec index, git, Linear, PRs, evidence manifests, and the signed brief.
- Add the post-grill reconciliation loop: shaper update -> fresh shaping review
  -> shaper or operator-grill reconciliation -> fresh shaping re-review ->
  exact-revision readiness.
- Implement bounded implement → review → fix → re-review cycles.
- Stop on ambiguous or missing gates.
- Preserve exact role sessions.
- Add exact-head and PR-base assertions.
- Route dispatch/readiness/lifecycle reads through the exact Linear read helper
  and mechanical transitions through compare -> mutate -> readback ->
  `status.md` -> notify, retrying only unfinished idempotent steps.
- Split generic workflow result from business outcome state.
- On failed or interrupted passes only, write the minimal failure record to the
  existing status/handoff; inspect and preserve useful work before a fresh
  retry, with the accountable orchestrator recording it when the worker cannot.
- Install by symlink or deterministic build with source/adapter hashes.

### Messaging and session bootstrap

Targets:

- `skills/herdr-comms/assets/herdr-say`
- `skills/herdr-comms/assets/herdr-spawn`
- `skills/herdr-comms/SKILL.md`
- `skills/launch-meta-operator/*`
- Claude Codex relay profile.

Changes:

- Durable message envelope and state ledger.
- Accepted/completed ack commands.
- Atomic queued-message drain.
- Explicit target cwd/remote and bootstrap manifest.
- Exact Codex session resume.
- One spawn primitive used by the launcher itself.
- Role-aware spawn defaults so orchestrator auto mode is mandatory rather than
  an example argv callers can omit.
- One session-bound host timer installed at Fable launch. Its sole action is
  `operator-say sweep`, which resolves `operator-owner.toml` and delegates to
  `herdr-say`. It persists through idle periods and operator handoffs, then is
  removed when the operator lifecycle terminates.
- A first-class, explicitly requested operator-handoff action with a concise
  durable state artifact, fresh successor launch, source reconciliation, timer
  transfer, child reply-route update, and atomic fail-closed single-writer
  cutover.
- One small owner helper using a lock, expected owner/revision comparison,
  complete temporary TOML write, and atomic rename. Only operator-owned state
  and gate mutation helpers verify it; ordinary commands do not.
- Dead-owner recovery verifies the exact recorded Herdr session is dead or
  absent, launches a fresh reconciled Fable, and uses the same atomic replace.
  Ambiguous liveness blocks; no timeout or automatic failover exists.
- Write immutable operator handoffs as
  `handoffs/<zero-padded-revision>.md` under the control directory and reference
  the accepted path and revision from `operator-owner.toml`.

### Lightweight tracing and conformance

Add one foreground append helper for stable Langfuse-shaped session, trace,
and observation records in a bounded stream's existing `trace.jsonl`. Only
deterministic workflow and named gate helpers call it. Language-model agents
return normal receipts and never write trace records directly. Emit only at
meaningful workflow boundaries. Store compact identity, timing, status,
role/model/repo/HEAD/gate attributes, and artifact references. Reject raw
prompts, responses, logs, transcripts, secrets, evidence bodies, and product
data.

Add one path-filtered CI checker. Run it only when workflow helpers, role
contracts, or trace-contract files change. Inputs:

- One generated happy-path dry run.
- One generated failure/retry dry run.
- A few intentionally invalid fixtures.

The checker validates schema and parent integrity plus these incident-derived
invariant families:

- Correct role, instructions, model/mode, workspace, exact Linear input, and
  bootstrap acknowledgment before mutation.
- Shaping receipt, spec/TDD readiness, review, QA, acceptance, and merge facts
  remain bound to the required HEAD and revision.
- Fixes require fresh re-review before QA.
- Linear mutation success requires compare, mutate, readback, status update,
  and notification agreement.
- Retry requires prior-work inspection and preservation; timeout alone is not
  failure.

Use local dry-run inputs. Never mutate Linear or another external system from
CI. Do not build the earlier Cartesian workflow matrix. This checker does not
replace spec-driven TDD or target-specific tests.

The runtime trace inherits its existing stream control directory lifecycle.
Add no separate archive, retention duration, timer, or pruning system.
Incident preservation is an explicit sanitized artifact action.

Runtime append failure writes one `trace degraded` warning into existing
stream status and continues. Add no retry path or gate dependency. The
path-filtered CI contract check remains blocking when relevant files change.

## Candidate Turbo-Outreach changes

These belong in the target repo, not octo-lite.

### Cross-runtime repo contract

Targets after selecting a clean branch/worktree:

- `AGENTS.md`
- `CLAUDE.md`

Changes:

- Consolidate Linear, spec format, branch topology, state ownership, validation,
  TopicFinder design, runtime config, QA, deployment, and Notion rules.
- State the difference between unshaped implementation requests and a signed
  octo-lite loop so ready work is not re-planned or paused.
- Reduce `CLAUDE.md` duplication.
- Make PR base an explicit brief input.

### Target runbooks

Move durable gotchas out of memory where appropriate:

- Worktree and dependency-cache setup.
- Add one Turbo-owned bootstrap command for its nested npm applications using
  repo lockfiles, a native shared npm download cache, compatible reusable
  Puppeteer/browser downloads, and per-worktree `node_modules`; record cold and
  warm measurements before adding another cache layer.
- DB-gated validation and CI parity.
- QA fixture isolation and evidence publishing.
- Staging mutation lease recovery.
- Deployment source identity and no-shift verification.
- One-time corpus/data operations separated from repeatable promotion.
- Linear transition verification.
- One repo-owned worktree bootstrap command that fails fast on missing
  dependencies, tools, env, DB capability, disk, and instruction/spec inputs.

Detailed behavior, acceptance rules, interfaces, edge cases, and constraints
belong in specs/ADRs. Linear owns issue identity, high-level objective,
material decisions/context, non-goals, and lifecycle status. Operational
procedures belong in runbooks; ephemeral execution status belongs in the
control record.

## Workspace repair candidate

- Establish a clean control clone or bare repo for fetch/worktree operations.
- Reuse that control repo's Git objects for every fresh pass worktree instead
  of recloning from the network.
- Stop treating `/root/Turbo-Outreach-staging` as canonical.
- Inventory every registered worktree with owner, purpose, HEAD, instruction
  blob, dirty state, and last use.
- Preserve dirty/user-owned worktrees.
- Remove only proven disposable clean worktrees after operator-approved policy.
- Add disk/inode admission checks before new worktrees or dependency installs.
- Keep mutable dependency trees and ordinary build outputs worktree-local; use
  only native safely shareable caches with correct fallback on a miss. Build no
  cache daemon, dependency service, custom registry, or persistent issue
  checkout.

## Memory repair candidate

- Generate a memory inventory with scope, active/superseded status, and durable
  destination.
- Move current policy to versioned octo-lite or Turbo files.
- Move current operational state to control records.
- Retain only incident heuristics with links to the durable fix.
- Regenerate indexes so stale entries are not presented as active law.

## Suggested implementation sequence after the grill

1. Record decisions; reconcile the canonical spec, high-level Linear record,
   relevant grill log, and same draft PR; then obtain a clear fresh shaping
   review for one issue or an approved small epic with valuable slices.
2. Land P0 fail-closed gates and exact-session relay.
3. Land instruction manifest and acknowledged delivery.
4. Remove literal Turbo configuration, derive target facts from durable repo
   sources and the signed brief, and unify workflow installation.
5. Consolidate role sources and Turbo repo instructions.
6. Add lightweight spawn admission, deterministic worker cleanup, and the
   operator outcome view.
7. Migrate memories and remove superseded live patches.
8. Run adversarial end-to-end conformance tests on one low-risk Turbo issue.

## Acceptance criteria for the operating-model migration

- Every spawned role proves its repo, HEAD, PR base, octo-lite version, role
  contract, target instruction blob, spec format, signed brief, and decision
  revision before mutation.
- No code reaches QA without a clear review on the same HEAD.
- No acceptance or merge acts on evidence for a different HEAD.
- No inter-agent command is considered delivered until it is submitted and
  accepted.
- Generic octo-lite contains no Turbo/TopicFinder paths, credentials, hosts,
  fixtures, states, or Notion policy.
- Turbo-specific mechanics are versioned in Turbo-Outreach and loaded by both
  Claude and Codex.
- Source and installed workflow behavior are reproducibly identical for a
  given octo-lite commit, target instruction/spec blobs, and signed brief.
- Memory cannot override versioned policy and exposes superseded entries as
  historical only.
- Worktrees, ports, processes, fixtures, leases, and artifact roots have an
  accountable owner and cleanup state.
- The operator can see outcome, epic, owner, gate, blocker, next action, and
  evidence without reconstructing session transcripts.
- `Shaped` can be mechanically traced to the Linear high-level
  objective/decisions/context/non-goals, operator walkthrough, relevant
  grill-log cutoff, canonical spec/ADR behavior and acceptance blobs, same
  draft-PR readiness HEAD, TDD contract, and clear fresh shaping-review verdict
  on those exact inputs.
- Implementer prompts identify the canonical spec/ADR as the detailed
  behavioral contract and Linear as the high-level decision/context/status
  record; conversation logs are review inputs, not implementation instructions.
- A prompt, role, or skill instruction change proves behavior-first: unchanged
  instructions in a fresh model session prove red only for a genuinely wrong
  or ambiguous decision, changed instructions in a different fresh session
  prove green, narrow adjacent regressions run, and deterministic tests cover
  only loading, wiring, schema, invariants, and forbidden characters.
