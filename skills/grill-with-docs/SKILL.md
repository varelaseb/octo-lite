---
name: grill-with-docs
description: Run a docs-backed grilling session for octo-lite issue shaping; stress-test a draft or rough Linear/GitHub issue against target repo specs, ADRs, code, repo instructions, and domain language before implementation.
---

# Grill With Docs

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use this skill from `$octo-lite-issue-shaper` when a new idea, rough Linear or
GitHub issue, or issue draft needs clarification before it can be marked ready.

This skill keeps issue shaping grounded in the target repo's durable context:
Linear issues, GitHub PRs, explicitly requested GitHub issues, `.octo-lite`
drafts, specs, ADRs, repo docs, code, and configuration.

## Operating Rules

- Ask one question at a time and wait for the operator's answer.
- Include a recommended answer with each question.
- Explore code, specs, ADRs, repo docs, package scripts, existing Linear issue
  context, GitHub PRs, explicitly requested GitHub issues, and the active
  `.octo-lite/drafts/<slug>.md` before asking when the answer is discoverable.
- Challenge fuzzy or overloaded terms against existing specs and repo language.
- Use concrete scenarios to stress-test boundaries, edge cases, ordering,
  dependencies, evidence, runtime expectations, and env/config needs.
- Update the active draft and any affected spec, ADR, README, or AGENTS.md as
  decisions crystallize.
- Do not batch durable terminology or behavior updates until the end.
- Do not mutate Linear or GitHub tracker state unless Issue Shaper has reached
  its approved final mutation step. In Linear-first repos, do not mutate GitHub
  issues unless the operator explicitly requested a GitHub issue operation.

## Domain Awareness

Start with the smallest useful context set:

1. Target repo `AGENTS.md` for repo-specific Codex conventions.
2. The target repo's spec format signal (`Spec format: spec-chat`, or the
   Markdown default when absent).
3. `spec/index.md` or `spec/index.spec.html`, when present.
4. Relevant canonical specs under `spec/domains/` as Markdown or
   `*.spec.html`.
5. Existing ADRs under `spec/adr/`, in the declared format, when present.
6. Repo docs such as `README.md`, `CONTRIBUTING.md`, `WORKFLOW.md`, or setup
   docs.
7. Code, tests, configuration, and package scripts directly related to the
   planned change.
8. Existing Linear issue context and GitHub PR context when shaping an existing
   issue or a follow-up from PR review. Use GitHub issue context only when the
   repo is GitHub-first or the operator explicitly names a GitHub issue.

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
Follow the target repo's declared format. Use octo-lite's target repo spec
structure in either Markdown or spec-chat HTML:

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
lazily under `spec/domains/<durable-area>.md` for Markdown repos or the matching
`*.spec.html` path for spec-chat repos, then update the matching index.

For a spec-chat repo, run the review loop as part of shaping: serve the HTML,
let the operator annotate it, hand off the batch, drain the events, edit the
canonical HTML in place, and reply on the anchored threads. Never regenerate a
domain or ADR Markdown counterpart after conversion.

## ADRs

Offer an ADR only when all three are true:

1. The decision is hard to reverse.
2. The decision would be surprising without context.
3. The decision is the result of a real trade-off.

ADRs live in `spec/adr/` and use the next sequential `0001-slug.md` style name
in Markdown repos or the matching `0001-slug.spec.html` name in spec-chat repos.
They may be short. Record context, decision, and rationale. Do not create an ADR
for ordinary priority ordering, obvious implementation details, or choices that
are easy to change.
