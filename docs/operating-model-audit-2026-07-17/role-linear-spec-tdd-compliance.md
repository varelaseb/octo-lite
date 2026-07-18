# Role, Linear, Spec, And TDD Compliance

Status: historical audit evidence. Current required behavior lives in
`../../spec/domains/operating-model.spec.html`; candidate remedies below do not
override Decisions 1 through 102.

## Audit question

This artifact tests the current system against octo-lite's declared path:

```text
operator idea
  -> issue-shaper
  -> docs-backed grill
  -> durable spec/ADR update
  -> acceptance-criteria walkthrough
  -> operator ruling/walkthrough approval
  -> reconcile spec + Linear + same draft PR
  -> fresh Sol xhigh/fast shaping review
  -> clear exact-revision readiness
  -> implementer
  -> reviewer/fix/re-review
  -> QA and acceptance
```

The answer is not simply "Linear-first." Recent sessions generally avoided
active GitHub issue tracking, which is good. The gap is that Linear is being
used as a fast issue-and-state command surface without consistently proving the
shaping, spec, role, and TDD gates that make a Linear issue ready.

## Declared octo-lite contract

The issue-shaper requires:

- A draft under `.octo-lite/drafts/`.
- The exact story headings `User Story`, `Background`, `Desired Outcome`,
  `Acceptance Criteria`, `Out Of Scope`, and `Context`; epics use `Epic goal`.
- A Fable/Sol shaping debate before the operator grill.
- A one-question-at-a-time docs-backed grill.
- Immediate durable spec/ADR updates when decisions are made.
- An explicit user-story and acceptance-criteria walkthrough.
- Operator approval before the issue is marked ready and implementation begins.
- A final independent post-grill review before readiness, distinct from the
  pre-grill Fable/Sol shaping debate.

The loop then says it must reject self-written or ungrilled scope, read the
repo's spec index and relevant specs before composing worker prompts, use the
configured implementer and reviewer roles, stop on ambiguity, and run up to
three implement/fix/re-review cycles.

The TDD skill requires behavior and evidence first, the smallest meaningful
failing test, confirmation of the intended red, the smallest green change,
refactoring, broader validation, and durable red/green evidence in the PR or
handoff.

## Recent Linear sample

The audit queried all 228 `TUR` issues created from 2026-07-10 through
2026-07-17 and inspected the newest contiguous sample, `TUR-418` through
`TUR-438`, in detail.

Corpus-level control-plane signals:

| Signal | Result |
| --- | ---: |
| Issues created in seven days | 228 |
| Issues with no Linear project | 228 |
| Unassigned issues | 218 |
| Issues with no labels | 214 |
| Current state: Shaped | 45 |
| Current state: In Progress | 6 |
| Current state: In Staging | 35 |
| Current state: Live | 80 |

Project, assignee, and label sparsity is not automatically wrong. Combined
with the operator's outcome-level visibility problems, however, it shows that
Linear is not currently providing a strong epic/outcome ownership surface.

Detailed `TUR-418`–`TUR-438` results:

| Check | Result |
| --- | ---: |
| Complete exact issue-shaper story headings | 5 / 21 |
| Contains a `User Story` section | 9 / 21 |
| Explicit TDD/test-first/red-green requirement | 0 / 21 |
| Traceable issue-key reference in `spec/**` on `origin/octo-lite/next-candidate` | 0 / 21 |
| Epic `TUR-431` uses required `Epic goal` section | No |

The missing issue-key references do not prove that no spec text changed: a
spec can be updated without naming an issue. They do prove that the loop has no
traceable attestation connecting ready scope to a specific spec revision.
Several sampled issues instead cite transient `/root/*.md` or `/root/*.js`
investigation artifacts. Those are useful discovery evidence, but they are not
the durable spec-chat source required by Turbo's repo instructions.

Concrete patterns:

- `TUR-419`, `TUR-420`, `TUR-423`, `TUR-424`, and `TUR-425` follow the complete
  story-heading contract.
- `TUR-422`, `TUR-426`, `TUR-427`, and others contain substantial engineering
  detail and acceptance criteria, but use ad hoc `Problem`, `Scope`, `Tests`,
  and `Notes` structures rather than the required shaped story contract.
- `TUR-431` is an epic but does not use the required `Epic goal` format.
- `TUR-432` through `TUR-436` were marked Shaped around an epic while the issue
  text deferred durable ADR/spec decisions and referenced scratch audit files.
- `TUR-437` moved directly into implementation with a detailed agent-written
  contract, but no user-voiced story, required shaping structure, or traceable
  durable-spec readiness evidence.

There is at least one strong counterexample: the `TUR-135` shaping session on
July 12 used `.octo-lite/drafts`, a Fable/Sol debate, a one-question grill,
spec updates, a shaping branch, operator walkthrough, and only then the loop.
The intended process is viable; it is not the default enforced path.

## TDD evidence audit

The workflow prompt currently says only `TDD where practical`. The TDD skill
itself activates only when the issue, spec, ADR, or operator explicitly asks
for test-first development. The newest 21 sampled issues contain no such
request.

The combined PR bodies, comments, and reviews for PRs `#388` through `#396`
contain no durable `TDD`, `test-first`, red-phase, or red/green evidence. Those
PRs may contain tests and their final validation may be green; this audit does
not infer the order in which private edits happened. The compliance failure is
that the required red/green proof is absent, so the operator and reviewer
cannot distinguish test-first implementation from tests added after the code.

The wider Codex corpus confirms that TDD is present but not reliably durable:
133 of 482 classified session files loaded the TDD skill, while only 22 posted
red/green evidence in a PR comment and 27 placed it in a PR body/edit. Those
categories may overlap. Test execution is common; proof of the intended red and
subsequent green is not.

The operator approved the stronger policy during the grill:

> Spec-driven TDD is a hard rule. Every behavior-changing implementation starts
> with a failing test derived from the canonical spec, and the implementer
> records the intended red and subsequent green. Shaping is incomplete without
> a linked Linear issue, PR, and canonical spec.

This removes both the current conditional skill trigger and `where practical`
prompt prose. The operator ruled that shaping and implementation share one
evolving draft PR: the spec/readiness commit is signed first, then code and
tests continue on the same branch and PR.

The later source-of-truth ruling makes the canonical spec/ADR the
implementer's primary detailed behavioral and acceptance contract. Linear
remains the primary tracker and holds the issue identity, high-level objective,
material decisions/context, non-goals, and lifecycle status. Relevant
conversation logs are inputs to the shaping review, not instructions an
implementer must reinterpret.

## Role-boundary audit

`role-skills.json` defines only three roles: issue-shaper, implementer, and
reviewer. The live system also requires a post-grill shaping reviewer,
meta-operator, stream orchestrator, QA capture, QA reviewer, acceptance/merge,
and deployment behavior, but these do not have equivalent canonical role/skill
entries.

Observed consequences:

1. Meta-operators and stream orchestrators can write a Linear scope and launch
   implementation in one session without proving they activated the
   issue-shaper contract.
2. The live workflow claims scope is already grilled but accepts a placeholder
   story and empty acceptance criteria; it has no readiness attestation to
   verify the claim.
3. Codex implementer and reviewer prompts receive shortened role prose instead
   of the canonical profiles required by the loop skill.
4. QA agents are generic Claude agents with large workflow literals, not
   canonical role profiles generated from `role-skills.json`.
5. Acceptance, merge, Linear state transitions, and deployment ownership are
   distributed between workflow prose, memory, and operator convention.
6. Role/model identity is not reliably executable or recorded. Native Codex
   implementers can inherit reviewer defaults, and relay follow-ups can attach
   to the wrong lane through `resume --last`.

This is an operating-model violation, not just a prompt-quality problem. A
single orchestrator may coordinate several phases, but each mutation must run
under an explicit role, an acknowledged parent-owned brief, and a
machine-checkable entry and exit contract.

## Linear correctness audit

What is working:

- Linear issue keys are normally used in PRs and workflow identity.
- The recent Claude corpus showed no active GitHub issue mutations.
- GitHub PRs, rather than GitHub issues, are generally used for code review.

At the Codex corpus level, only four session files used GitHub issue operations,
while 234 used the Linear CLI. That supports the Linear-first/GitHub-PR
separation. However, only 87 of 172 scratch relays queried Linear, so downstream
workers often rely on relayed prose instead of fetching the primary scope.

What is not:

- `Shaped` currently asserts a conclusion without a linked readiness manifest,
  spec/ADR revision, grill record, AC walkthrough, or approver revision.
- Sessions frequently create an issue at `Shaped`, pull it to `Todo`, and start
  a loop immediately from the same prose packet.
- Linear updates can fail silently because callers do not require read-after-
  write verification.
- `In Staging` is sometimes used after an integration-branch merge even when
  the accepted commit is not observably deployed to staging.
- Parent/epic grouping is inconsistent, and issue-centric status makes the
  product outcome, accountable owner, and next operator action hard to see.
- Scratch discovery artifacts outside the target repo become de facto scope
  sources even though Linear and the canonical specs should carry the durable
  result.

The correct conclusion is therefore:

> Linear-first tracking is mostly present, but Linear-governed readiness and
> lifecycle semantics are not.

## Reconciled readiness gate

Linear `Shaped` is the canonical readiness state. Set it only after a fresh
shaping reviewer posts a clear machine-readable verdict comment on the evolving
draft PR. The comment binds the relevant Linear content fingerprint, exact PR
and shaping HEAD, spec/ADR blobs, conversation-log references and cutoff,
verdict, and reviewer receipt reference. Linear links that verdict. Launch
refetches every bound source and returns stale work to shaping. There is no
separate readiness file or control-directory attestation.

## Reconciled role topology

| Role | May do | Must not do | Exit artifact |
| --- | --- | --- | --- |
| Meta-operator | Reconcile the whole operation and supervise bounded streams | Implement, accept for the human, or absorb every leaf log | Whole-operation view |
| Stream orchestrator | Own one bounded stream, topology, resources, and gates | Rewrite approved scope or act as worker/reviewer | Brief and status |
| Issue shaper | Investigate, debate, grill, reconcile specs/ADRs, high-level Linear context, TDD contract, and same draft PR | Implement, self-review, or mark ready without operator walkthrough and a clear fresh shaping review | Reconciled issue/spec/PR |
| Shaping reviewer | Independently audit the spec, relevant conversation logs, Linear issue, repo instructions, TDD contract, and draft-PR readiness HEAD | Edit sources, invent product decisions, implement, or resolve its own findings | Exact-revision `clear` or `blocking` verdict |
| Implementer | Execute the canonical spec contract within Linear's high-level decisions/context and non-goals, using spec-driven TDD | Infer behavior from chat, reshape, review own work, or merge | PR handoff with red/green evidence |
| Code reviewer | Review exact HEAD against story/spec/tests | Change scope, approve as human, merge | Exact-head verdict |
| QA capture | Produce evidence for exact reviewed HEAD | Decide product acceptance | Evidence manifest |
| QA reviewer | Judge evidence against each AC | Infer missing proof or accept stale HEAD | Exact-head QA verdict |
| Reconciler | Compare compact normalized facts and flag change, staleness, contradiction, or ambiguity | Mutate sources or overrule deterministic mismatches | Read-only classification |

The human operator accepts or rejects. Deterministic operator-authorized
helpers publish verdicts, transition Linear, merge, promote, and shift traffic;
they are not LLM roles.

Meta-operators and stream orchestrators should run in Claude auto mode by
default so ordinary tool approvals do not turn the operator into a babysitter.
Auto mode is execution plumbing only: the role's standing authority and
irreversible gates remain unchanged and must still be enforced.

## Fail-closed conformance tests

The eventual system should prove all of these:

- A loop refuses an issue with no clear exact-input shaping verdict comment on
  the evolving draft PR.
- A loop refuses a missing, blocking, reused-session, or stale-input shaping
  review.
- Changing a material Linear decision/context invalidates readiness.
- Changing a referenced spec blob invalidates or explicitly refreshes the
  brief.
- Changing the reviewed grill-log cutoff or draft-PR readiness HEAD requires a
  fresh shaping review.
- A shaping reviewer cannot edit a source or silently convert an unresolved
  product judgment into a clear verdict.
- An orchestrator cannot spawn an implementer under the shaper role.
- An implementer cannot run reviewer or issue-shaper skills.
- A behavior-changing handoff without red/green evidence fails unless an
  operator-approved
  test waiver names alternative evidence.
- A fix invalidates review and QA until the new HEAD is re-reviewed.
- A Linear mutation is not complete until read-back matches.
- A stale exact Linear gate read blocks dispatch, while harmless exploratory
  reads remain available without a facade requirement.
- A mechanical transition cannot claim success until expected-state comparison,
  Linear readback, `status.md`, and parent notification all agree; a partial
  failure retries only unfinished idempotent steps.
- `In Staging` cannot be set without the environment identity carrying the
  accepted commit.
