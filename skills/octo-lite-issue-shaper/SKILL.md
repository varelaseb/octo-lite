---
name: octo-lite-issue-shaper
description: Shape ideas and rough Linear or explicit GitHub issues into spec-backed work with one evolving draft PR and an exact final review.
---

# octo-lite issue shaper

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use for intake, grilling, spec and ADR changes, story maintenance, repo setup,
tracker reconciliation, and readiness. The one issue orchestrator loads this
skill through `roles.toml` in shaping mode. Do not load implementer or
reviewer skills.

## Source ownership

- Linear owns issue identity, high-level decisions, context, non-goals,
  dependencies, and lifecycle state.
- Canonical specs and ADRs own detailed behavior, acceptance rules, contracts,
  edge cases, and constraints.
- One evolving draft PR carries shaping and later implementation.
- Target `AGENTS.md` owns only target commands, architecture, validation,
  deployment, fixtures, and conventions.
- Conversation and memory are evidence, never unrecorded law.

Stop on conflict. Reconcile every authoritative source before readiness.

## Intake

1. Fetch the complete current Linear issue first for Linear-tracked work.
2. Use GitHub issues only for GitHub-first work or an explicit operator request.
3. Read target instructions, spec index, relevant specs, ADRs, code, and current
   draft PR.
4. Keep temporary shaping context in `.octo-lite/drafts/<slug>.md` using
   `assets/github-issue.md`. Never commit the draft.
5. Open or update the same draft PR early. Never create an implementation PR
   after shaping.

The issue body uses:

```text
## User Story
## Background
## Desired Outcome
## Acceptance Criteria
## Out Of Scope
## Context
```

Epics use `## Epic goal`, not a user story.

## Specs and stories

Inspect `AGENTS.md` before touching specs. `Spec format: spec-chat` selects
canonical `*.spec.html`; absent signal or `Spec format: markdown` selects
Markdown. Never create a parallel copy in the other format.

Detailed behavior belongs in durable-area specs, not issue prose. Record a
surprising or hard-to-reverse architectural choice in an ADR. State when no ADR
is needed.

Maintain the target user-story document when work creates, changes, or retires
a user outcome. Each active story has only stable ID, short title, status, one
user-voiced sentence, exact spec-anchor links, and origin Linear issue. QA
evidence and acceptance state never live in the story record. Downstream roles
read its pinned revision but do not edit it.

Initialize only missing target surfaces from `assets/`: README, target-only
`AGENTS.md`, spec index, spec directories, and draft ignore entry. Never copy
octo-lite roles, agents, skills, or workflows into a target repo.

## Grill

Use `$grill-with-docs`. Ask one unresolved question at a time after checking
durable sources. Give a recommendation. Challenge fuzzy behavior, hidden
dependencies, unobservable criteria, environment needs, and scope creep.

Record every ruling immediately in Linear high-level context, canonical specs,
an ADR when needed, the story document when affected, and the draft PR. Do not
wait for a final chat summary.

Walk every acceptance criterion with the operator. Each must be observable,
spec-backed, and classified clear, gap, or not needed. Resolve every material
gap and `TBD`.

Shape spec-derived TDD before implementation. Each behavior or contract change
names the smallest intended failing test and acceptance evidence. Only a narrow
operator-approved waiver may replace red, green, refactor, and it must name the
alternative proof.

## Final shaping review

After grilling and reconciliation, the workflow spawns one fresh
`shaping-reviewer` resolved through `roles.toml` as a codex relay subagent that
returns findings verbatim. The workflow-layer gates admit it and bind its result
by the workflow journal plus a schema-forced acknowledgment echo. The reviewer
reads:

- exact Linear issue and content fingerprint
- same draft PR and immutable shaping HEAD
- target instructions blob
- canonical spec and ADR blobs
- a nonempty list of exact conversation log references plus the pinned cutoff;
  a cutoff alone is not enough
- TDD contract and story revision when affected

The reviewer returns clear or blocking. Publish one deterministic TOML verdict
comment on the PR with `octo-control verdict-publish`, including the exact
conversation log references. Bind all inputs, HEAD, findings, and reviewer
receipt. Read it back. Never use the formal GitHub Review API as the shaping
gate.

Blocking documentary gaps return here. Missing judgment returns to the operator
grill. Material reconciliation requires another fresh shaping review.

## Finalize

Default to action: prior explicit operator intent authorizes finalization.
Notify the operator with human-sensical context only: a plain-language
what-changed-since-your-last-look summary plus the rendered pages, never an
exact head or hash; tooling stamps the exact head at action time onto the PR
and status surfaces. The operator vetoes by rollback.

On clear verdict readback, act then notify:

1. Commit durable spec, ADR, story, repo instruction, and PR changes.
2. Update Linear with concise high-level context and the verdict link.
3. Set Linear to `Shaped`.
4. Delete the local draft.

Implementation launch must refetch every bound source. Any mismatch returns to
shaping. Never implement, self-review, infer approval, accept, merge, or mutate
a Linear-tracked GitHub issue without explicit authority.
