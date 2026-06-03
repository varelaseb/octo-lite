---
name: grill-with-docs
description: Run a docs-backed grilling session for octo-lite issue shaping; stress-test a draft or rough GitHub issue against target repo specs, ADRs, code, repo instructions, and domain language before implementation.
---

# Grill With Docs

Use this skill from `$octo-lite-issue-shaper` when a new idea, rough GitHub
issue, or issue draft needs clarification before it can be labeled
`octo-lite:ready`.

This skill keeps issue shaping grounded in the target repo's durable context:
GitHub issues, `.octo-lite` drafts, specs, ADRs, repo docs, code, and
configuration.

## Operating Rules

- Ask one question at a time and wait for the operator's answer.
- Include a recommended answer with each question.
- Explore code, specs, ADRs, repo docs, package scripts, existing GitHub
  issues/PRs, and the active `.octo-lite/drafts/<slug>.md` before asking when
  the answer is discoverable.
- Challenge fuzzy or overloaded terms against existing specs and repo language.
- Use concrete scenarios to stress-test boundaries, edge cases, ordering,
  dependencies, evidence, runtime expectations, and env/config needs.
- Update the active draft and any affected spec, ADR, README, or AGENTS.md as
  decisions crystallize.
- Do not batch durable terminology or behavior updates until the end.
- Do not mutate GitHub issues, labels, comments, or PRs unless Issue Shaper has
  reached its approved GitHub mutation step.

## Domain Awareness

Start with the smallest useful context set:

1. Target repo `AGENTS.md` for repo-specific Codex conventions.
2. `spec/index.md`, when present.
3. Relevant canonical specs under `spec/domains/`.
4. Existing ADRs under `spec/adr/`, when present.
5. Repo docs such as `README.md`, `CONTRIBUTING.md`, `WORKFLOW.md`, or setup
   docs.
6. Code, tests, configuration, and package scripts directly related to the
   planned change.
7. Existing GitHub issue or PR context when shaping an existing issue or a
   follow-up from PR review.

When a term conflicts with existing domain language, call out the conflict and
ask which meaning should become canonical. When a term is vague, recommend a
precise term and record the accepted wording in the draft and relevant spec.

## Shaping Thoroughness

Use these shaping patterns:

- Keep the active draft as the source of truth during shaping.
- Keep unresolved behavior questions visible as `TBD` until answered.
- Classify acceptance criteria as `clear`, `gap`, or `not needed`.
- Ask only about gaps or ambiguities that durable context cannot resolve.
- Record durable product or system behavior in specs, not only in chat.
- Surface ADR-worthy decisions before readiness.
- Propose follow-up issues only when the work is independently valuable or a
  real prerequisite; do not create them without operator approval.
- Treat the final ready gate as a quality bar, not a formatting step.

## Spec Updates

Record resolved product or system behavior in the relevant canonical spec.
Use octo-lite's target repo spec structure:

- `## Intended behavior`
- `## Domain concepts`
- `## Rules and invariants`
- `## Interfaces/contracts`
- `## Edge cases`
- `## Constraints`
- `## Non-goals`
- `## Open questions about system behavior`
- `## Decision log or links to ADRs`
- `## References to source issues`

Keep unresolved behavior questions visible in both the draft and spec until the
operator answers them. If no canonical spec exists for the area, create one
lazily under `spec/domains/<durable-area>.md` and update `spec/index.md`.

## ADRs

Offer an ADR only when all three are true:

1. The decision is hard to reverse.
2. The decision would be surprising without context.
3. The decision is the result of a real trade-off.

ADRs live in `spec/adr/`, use the next sequential `0001-slug.md` style name,
and may be short. Record context, decision, and rationale. Do not create an ADR
for ordinary priority ordering, obvious implementation details, or choices that
are easy to change.
