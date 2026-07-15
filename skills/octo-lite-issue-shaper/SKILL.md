---
name: octo-lite-issue-shaper
description: Shape new ideas or rough Linear/GitHub issues into concise, spec-backed octo-lite work. Use for operator-driven issue intake, repo initialization, .octo-lite draft maintenance, Linear-first scope updates, explicitly requested GitHub issue operations, readiness approval, and spec/ADR decisions before implementation.
---

# octo-lite Issue Shaper

Use this skill when the user wants to create, clarify, refine, or finalize
Linear-first or explicitly GitHub-first work with octo-lite. This is a
user-facing operator workflow, not an implementer/reviewer role.

Issue shaping is intentionally thorough. The final GitHub issue is intentionally
concise when the target repo is GitHub-first; in Linear-first repos, the final
Linear issue/spec updates are intentionally concise.

## Role Skills

Use only the Issue Shaper role skills from `role-skills.json`:

- `$octo-lite-issue-shaper` for the operator-facing shaping workflow.
- `$grill-with-docs` for docs-backed clarification.
- `$octo-lite-github` for approved GitHub PR operations and explicitly
  requested GitHub issue/label/context operations.

Do not load implementer or reviewer role skills while shaping unless the
operator explicitly changes roles.

## Core Rule

During shaping, `.octo-lite/drafts/<slug>.md` is the canonical working artifact.
Conversation is scratch. Linear or GitHub is mutated only after explicit
operator approval. In Linear-first repos, Linear is canonical after finalization
and GitHub issues are not mutated unless the operator explicitly requested a
GitHub issue operation. In GitHub-first repos, the GitHub issue is canonical
after finalization and the draft is deleted.

## Target Spec Format

Before reading or writing a target repo's specs, inspect its `AGENTS.md` for the
exact signal `Spec format: spec-chat`.

- With no signal or `Spec format: markdown`, keep the existing Markdown
  canonical sources and Markdown templates.
- With `Spec format: spec-chat`, write and maintain `*.spec.html` under the
  repo's declared spec root as the only canonical sources.
- Spec-chat documents use one sentence per prose line, stable `data-anchor`
  attributes on every meaningful block, and pretty-printed parseable JSON in
  semantic islands for visual state.
- Ensure the shared `.viz/` runtime and vendored libraries are present for
  offline rendering, and keep `*.review/` event spools ignored.
- Include the browser review loop in shaping: serve the spec, annotate it,
  hand off the batch, drain comments, edit the HTML in place, and reply through
  the review channel before readiness.

Follow the target declaration when updating specs. Do not create a Markdown
counterpart for a spec-chat document or regenerate domain/ADR Markdown after
conversion.

## Bundled Templates

Read only the template needed for the current operation:

- `assets/github-issue.md` for the active draft and, only in GitHub-first
  repos, the final GitHub issue body.
- `assets/readme.md` for target repo README initialization.
- `assets/repo-agents.md` for target repo `AGENTS.md` initialization.
- `assets/spec-index.md` for the target repo's canonical index: `spec/index.md`
  in Markdown repos or `spec/index.spec.html` in spec-chat repos.
- `assets/spec-domain.md` for canonical domain specs.
- `assets/adr.md` for ADRs.
- `assets/gitignore-entry.txt` for target repo draft ignore coverage.

## Target Repo Initialization

When a target repo lacks octo-lite durable surfaces, initialize only the missing
minimal files:

- `README.md`
- `AGENTS.md`
- the canonical spec index (`spec/index.md` for Markdown repos or
  `spec/index.spec.html` for spec-chat repos)
- `spec/domains/`
- `spec/adr/`
- `.gitignore` entry for `.octo-lite/drafts/`

Use the bundled templates. Do not copy octo-lite product skills, agent profiles,
or workflow templates into the target repo.

`README.md` is human/product-facing. `AGENTS.md` is Codex-facing and records
repo-specific conventions. The target repo may diverge from the initial scaffold
over time.

## Shaping Workflow

### 1. Establish Scope

Start from exactly one new idea, one existing Linear issue, or one explicitly
requested GitHub issue.

If an existing Linear issue is named, fetch focused context from Linear first.
If an existing GitHub issue is explicitly named or the repo is GitHub-first,
fetch focused context with `gh issue view`. If the work is a new idea in a
Linear-first repo, shape locally first and create/update the Linear issue only
at finalization.

Preflight the relevant tracker early. For GitHub operations:

```bash
gh auth status
gh repo view
```

Do not create labels, edit issues, create issues, close issues, or post tracker
comments until the final approved mutation step. In Linear-first repos, this
restriction applies to Linear; GitHub issue mutation remains out of scope unless
explicitly requested.

### 2. Create Or Refresh The Draft

Create `.octo-lite/drafts/<slug>.md` from `assets/github-issue.md`. If shaping
an existing rough Linear or GitHub issue, seed the draft from its current
title/body, then normalize it to the template.

The draft must use exactly these headings:

```md
## User Story
## Background
## Desired Outcome
## Acceptance Criteria
## Out Of Scope
## Context
```

User stories are feature-level and user-voiced: `As a <specific user or the
operator>, I want <capability>, so <benefit>`. Never write a story voiced as
"the team", "the product", or "the flip", and never put a User Story
section on an epic — epics carry `## Epic goal` instead. The story is the
operator's artifact: shaped at intake, consumed verbatim by loops, QA
review, the octo-lite dashboard, and the story catalog.

Keep the draft clean enough to paste directly into Linear or GitHub. Do not add
an intake diary, long transcript, raw logs, secrets, or scratch notes. If a
decision is unresolved, represent it as `TBD` in the relevant final section.

### 3. Cross-Model Debate (Fable × Sol)

Once the draft stabilizes and before the grill pass, run a two-model debate on
it (operator convention 2026-07-12, order fixed same day: debate first, then
grill): Fable (Claude) and Sol (`gpt-5.6-sol`, reasoning effort high) each
attack the draft — cheapest-viable scope, missing or unobservable ACs, hidden
dependencies, spec conflicts, and what the other side rationalized. Whichever
runtime hosts the shaping session relays to the other model (Claude host →
`codex` relay / `codex exec -m gpt-5.6-sol -c model_reasoning_effort="high"`;
Codex host → Claude subagent). Fold each side's surviving objections into the
draft or the grill agenda; record material disagreements and their resolutions
in the issue's Context/decision log, and carry unresolved splits into the
grill as operator questions with recommended answers — never silently pick a
side.

### 4. Grill With Docs

Load and follow `$grill-with-docs` for the clarification pass. Stress-test the
work against target repo instructions, README, specs, ADRs, code, package
scripts, provider docs already present in the repo, existing Linear issue
context, and relevant GitHub PR context. Use GitHub issue context only when
explicitly requested or when the repo is GitHub-first.

Ask one question at a time only after checking available durable sources. Every
question should include a recommended answer. Challenge fuzzy terms, overloaded
scope, hidden dependencies, unobservable acceptance criteria, and unclear
runtime or env expectations.

As answers crystallize, update the draft and any affected spec/ADR/repo doc
immediately. Do not rely on final conversation distillation.

Use these shaping thoroughness patterns:

- Keep unresolved behavior questions visible as `TBD` in the draft and relevant
  specs until answered.
- Resolve discoverable gaps from durable context before asking the operator.
- Update durable spec, ADR, README, or AGENTS.md behavior at the moment the
  decision becomes clear.
- Record deliberate follow-up work in the Linear issue/specs or shape a
  separate issue only after operator approval. Use GitHub issue bodies only for
  GitHub-first work or explicitly requested GitHub issue updates.

### 5. Resolve Spikes, Env, And Architecture

Run a bounded spike only when a behavior-affecting question cannot be answered
from durable sources or direct operator input and the answer is needed before
safe implementation.

For env/config needs, identify names, destination, purpose, required timing, and
whether local/mock evidence is acceptable. Never record raw secrets.

Discuss architecture before final acceptance review. Record durable behavior in
`spec/`; record hard-to-reverse, surprising trade-offs in `spec/adr/`.
State the ADR checkpoint result explicitly, even when the result is "no ADR
required."

### 6. Maintain Specs And ADRs

Use the same spec file rules as Octo:

- In Markdown repos, canonical specs live under
  `spec/domains/<durable-area>.md`, ADRs live under `spec/adr/0001-slug.md`,
  and `spec/index.md` links canonical specs and ADRs.
- In spec-chat repos, use the corresponding `*.spec.html` files under the
  repo's declared spec root, with `index.spec.html` as the navigation surface.
  Keep the same durable section structure and valid internal links.
- File names describe durable areas, not issue IDs.
- Linear/GitHub issue IDs belong in references and decision logs.

Canonical specs use this structure:

```md
## Intended behavior
## Domain concepts
## Rules and invariants
## Interfaces/contracts
## Edge cases
## Constraints
## Non-goals
## Open questions about system behavior
## Decision log or links to ADRs
## References to source issues
```

For spec-chat, each section and meaningful block in this structure becomes an
anchored HTML block. Prose remains one sentence per line, and any chart or
diagram is represented by a pretty-printed semantic island rather than copied
rendered output.

### 7. Review Acceptance Criteria

Walk acceptance criteria one by one with the operator. Classify each as:

- `clear`: in scope, observable, and specific enough for implementation and PR
  review.
- `gap`: missing behavior, evidence, scope, env, dependency, architecture, or
  validation detail.
- `not needed`: duplicate, superseded, out of scope, or already covered.

Ask only about gaps or ambiguities that cannot be resolved from durable sources.
Do not mark criteria clear while any behavior-affecting `TBD` remains.
Record the compact review result in the draft's `## Context` section when it is
useful for implementer/reviewer evidence, but keep the final issue concise.

### 8. Finalize Follow-Up Scope

When shaping discovers adjacent or prerequisite work:

- Propose a separate issue only when the work is independently valuable or a
  real blocker for the current issue.
- Show the proposed title, relationship to current scope, blocker status, and
  whether it should be created now or deferred.
- Do not create child, related, or follow-up Linear or GitHub issues without
  explicit operator approval.
- Do not use blocking relationships as a priority mechanism.

### 9. Final Ready Gate

Before marking work ready, all of this must be true:

- The draft has the exact final issue headings.
- No unresolved `TBD` remains.
- Acceptance criteria were reviewed and are observable.
- Relevant specs/ADRs are updated, or no-change rationale is explicit.
- Env/config needs are known, scoped out, or recorded as operator-owned
  prerequisites.
- Target repo initialization files are present when needed.
- `.octo-lite/drafts/` is ignored.
- Durable artifacts are ready to commit.
- The operator has reviewed the issue draft and relevant repo diff.
- The operator explicitly approved final tracker mutation.
- The Issue Shaper role used `$grill-with-docs` or recorded why docs-backed
  grilling was not applicable.

### 10. Commit Durable Artifacts

Use a shaping branch:

```text
octo-lite/shape/<slug>
```

After operator approval, commit only durable artifacts such as repo init files,
specs, ADRs, repo docs, and `.gitignore` updates. Do not commit
`.octo-lite/drafts/`, scratch notes, raw logs, or secrets.

Do not open a separate artifact-only PR. The implementer later creates the
implementation branch from the shaping branch commit.

### 11. Finalize Tracker

For Linear-first repos, after approval and durable commit:

1. Create or update the Linear issue using the approved draft body.
2. Set or confirm the Linear status/labels/dependencies requested by the
   operator.
3. Leave GitHub issues untouched unless the operator explicitly requested a
   GitHub issue operation.
4. Delete `.octo-lite/drafts/<slug>.md` when finalization succeeds.

For GitHub-first repos, after approval and durable commit:

1. Create or update the GitHub issue using the approved draft body.
2. Create the label `octo-lite:ready` if missing.
3. Apply `octo-lite:ready` to the issue.
4. Delete `.octo-lite/drafts/<slug>.md`.

GitHub-first examples:

```bash
gh issue create --title "<title>" --body-file .octo-lite/drafts/<slug>.md
gh issue edit <number> --body-file .octo-lite/drafts/<slug>.md
gh label create "octo-lite:ready" --description "Shaped by octo-lite and ready for implementation" --color "0969da"
gh issue edit <number> --add-label "octo-lite:ready"
```

If tracker mutation fails, keep the draft and report the exact blocker.

## Boundaries

- Do not implement the shaped work.
- Do not start the implementer/reviewer loop.
- Do not create extra workflow labels beyond the target tracker's established
  readiness/status convention.
- Do not create child issues unless the operator explicitly asks for that
  separate tracker mutation. Prefer recording split recommendations in the
  issue or shaping a separate issue one at a time.
