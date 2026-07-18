# Operating Model Audit — 2026-07-17

Status: historical audit evidence. The operator grill is complete through
Decision 102. Canonical current behavior lives in
`../../spec/domains/operating-model.spec.html`; it wins over proposals and
pre-decision language in this packet. The coordinated octo-lite cutover is
tracked by `TUR-443`.

## Purpose

This packet audits the local octo-lite, Claude Code, Codex, Herdr, and
Turbo-Outreach operating model over the seven-day window from 2026-07-10
through 2026-07-17 UTC.

It was deliberately created as a pre-decision artifact.
It records what is failing now, separates reusable octo-lite policy from
Turbo-Outreach policy, and prepares a first-principles operator grill before
any prompt consolidation or workflow rewrite.

## Coverage

The audit corpus includes:

- 147 recent top-level Claude project sessions.
- 1,057 recent Claude subagent and workflow-agent transcripts, for 1,204
  recent Claude project JSONLs in total.
- 482 recent Codex rollout files in the classified audit snapshot.
- 101 Claude project-memory files and their indexes.
- 153 Claude workflow run records with explicit status, including 119
  completed, 25 killed, and 3 failed `octo-loop-qa` runs, plus six completed
  custom workflows.
- The octo-lite global profile, role-skill map, role profiles, issue-shaping
  and loop skills, meta-operator prompt, Herdr helpers, workflow source, and
  installed workflow copy.
- Turbo-Outreach `AGENTS.md`, `CLAUDE.md`, relevant repo state, and the
  registered worktree fleet.
- All 228 `TUR` issues created during the window, with detailed issue-shaping,
  spec-linkage, and TDD inspection of `TUR-418` through `TUR-438`, plus recent
  PR evidence packets.

Every recent session file was included in corpus-level searches and metadata
analysis.
Representative sessions, workflow journals, user corrections, and incident
memories were then read in full where needed to establish mechanisms and root
causes.
Raw logs, secrets, and copied transcripts are intentionally excluded from this
packet.

## Executive conclusion

The dominant problem is not weak individual agents.
It is a control-plane problem.

The current system has several partially overlapping sources of authority:

1. Versioned generic octo-lite files.
2. Versioned Turbo-Outreach repo instructions and specs.
3. Copied and locally patched installed workflows.
4. Claude project memory, split or shared according to project identity.
5. Per-session briefs, relayed chat rulings, and manual operator corrections.

No bootstrap manifest proves which versions a spawned agent received.
No delivery protocol proves that an inter-agent message was submitted and
accepted.
No workflow state machine prevents downstream work after a missing,
ambiguous, or stale review.
The result is a recurring correction tax: agents often recover successfully,
but only after the operator or another agent detects drift.

## Highest-confidence findings

1. **Codex relay agents often start outside the target repo.**
   A relay launched from a Claude scratch directory receives global Codex
   guidance but not Turbo-Outreach `AGENTS.md` in its initial instruction
   stack.
   Entering a worktree later does not retroactively load repo instructions.

2. **The workflow substitutes shortened role prose for the versioned role
   contract.**
   This violates octo-lite's own loop instructions and leaves critical
   requirements—durable-source precedence, role skills, ambiguity stops,
   spec format, and tracker behavior—to agent initiative.

3. **A blocking code review is fixed but not re-reviewed.**
   The current workflow can proceed directly to QA after one fix.
   Missing or ambiguous review results can also fall through.

4. **Source and installed workflow copies have diverged.**
   The installed Claude workflow contains a live PR-base patch absent from the
   octo-lite source.
   Copy-and-rewrite installation makes drift an expected condition.

5. **Generic octo-lite contains Turbo-specific policy and credentials.**
   Paths, fixtures, validation, dashboard publishing, TopicFinder policy, and
   deployment semantics are embedded in reusable octo-lite surfaces.

6. **The checkout treated as canonical is neither canonical nor current.**
   `/root/Turbo-Outreach-staging` is on a stale review branch, is dirty, and is
   826 commits behind `origin/main`, yet the workflow uses it for repo identity,
   dependencies, environment, and worktree creation.

7. **Instruction presence is not instruction currency.**
   The registered Turbo worktree fleet currently carries five different
   `AGENTS.md` variants.
   A worktree can have an instruction file and still have obsolete repo law.

8. **Claude memory is useful incident evidence but unsafe policy.**
   Current memory indexes simultaneously point to superseded and active Linear
   state models, merge ownership rules, and workflow workarounds.

9. **Inter-agent messaging lacks delivery semantics.**
   Text visible in a TUI may be injected but not submitted.
   Current helpers do not distinguish queued, injected, submitted, accepted,
   completed, rejected, or expired messages.

10. **Resource and workspace lifecycle is unmanaged.**
    Hundreds of worktrees, killed workflows, 529 overloads, OOM incidents,
    shared fixtures, stale processes, orphaned leases, and disk exhaustion are
    symptoms of missing admission control and cleanup ownership.

11. **Linear-first exists, but the ready gate is mostly asserted rather than
    proved.**
    Only 5 of the newest 21 sampled issues use the complete issue-shaper story
    contract; none carries a traceable TDD requirement or issue-key link in the
    canonical spec tree.

12. **Spec-driven TDD is not the operating default.**
    The workflow says `TDD where practical`, sampled issues do not request it,
    and recent PR packets do not record red/green evidence.

13. **The executable role model stops at shaper/implementer/reviewer.**
    Orchestrator, QA, acceptance, merge, and deployment behavior lives in
    prompt literals and memory rather than equivalent canonical role
    contracts.

14. **Child orchestrator auto mode is conventional, not guaranteed.**
    The meta-operator launcher pins its own Claude session to auto mode, but the
    shared spawn helper accepts arbitrary commands. Eleven of 51 recent Claude
    `herdr-spawn` command lines omitted an explicit permissive mode.

15. **The Codex relay misses repo law at measurable scale.**
    Of 172 scratch-directory relays, 29 never read an `AGENTS.md`; only three
    launch prompts explicitly requested it, and none named the role-skill map
    or canonical role profile.

16. **Spec-chat drift is widespread.**
    Two hundred eighty Codex session files hard-coded nonexistent Markdown
    domain specs, and at least 16 recorded actual missing-spec errors.

17. **Reviewer GitHub identity is wrong for the requested operation.**
    Eighty-two Codex session files recorded GitHub rejecting a request-changes
    review on the agent's own PR identity.

## Historical pre-decision cautions

These cautions governed the audit phase. The canonical spec and decision log
now contain the approved resolution.

- Do not encode current memory as permanent policy.
- Do not copy more octo-lite mechanics into Turbo-Outreach.
- Do not update Linear or GitHub issue state from this audit.
- Do not treat the proposed architecture in this packet as approved.

## Packet map

- [Failure catalog](failure-catalog.md) — recurring incidents, mechanisms, and
  current workaround debt.
- [Evidence index](evidence-index.md) — corpus counts, representative session
  paths, contract locations, and the audit's counting caveats.
- [Role, Linear, spec, and TDD compliance](role-linear-spec-tdd-compliance.md)
  — evidence that issue readiness, role boundaries, durable-spec linkage, and
  red/green behavior are not enforced.
- [Instruction and prompt architecture](instruction-and-prompt-architecture.md)
  — current routing, proposed ownership boundaries, and a spawn bootstrap
  contract.
- [Optimal-model grill](optimal-model-grill.md) — decision sequence for the
  operator discussion, one question at a time.
- [Integrated operating-model draft](operating-model-draft.md) — the current
  coherent architecture after the live grill, including the later dependency,
  instruction, role-loading, control-panel, and operator-supervision rulings.
- [Symphony assessment](symphony-assessment.md) — pinned review of OpenAI's
  scheduler/service spec and Elixir implementation, with adopt/adapt/reject
  mappings against the approved octo-lite and Turbo operating-model direction.
- [Reconciled gap backlog](gap-backlog.md) — approved and deferred
  implementation work after Decisions 1 through 102.
- [Target promotion map](target-promotion-map.md) — approved repo-specific
  decisions that must be shaped and implemented in the target repo rather than
  generic octo-lite.

## Completed discussion sequence

1. Define the operating model's optimization target.
2. Define what `Shaped` proves and make the spec-driven TDD contract explicit.
3. Choose the delivery and branch topology.
4. Define authority and lifecycle ownership.
5. Set instruction precedence and memory boundaries.
6. Set session, auto-mode, messaging, and acknowledgment semantics.
7. Lock the code-review, QA, acceptance, merge, and deployment gates.
8. Choose resource admission, worktree lifecycle, and operator visibility.
9. Only then rewrite prompts and workflows.
