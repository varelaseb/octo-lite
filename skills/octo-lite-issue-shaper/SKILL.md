---
name: octo-lite-issue-shaper
description: Shape new ideas or rough GitHub issues into concise, spec-backed octo-lite work. Use for operator-driven issue intake, repo initialization, .octo-lite draft maintenance, GitHub issue creation/update, octo-lite:ready labeling, and spec/ADR decisions before implementation.
---

# octo-lite Issue Shaper

Use this skill when the user wants to create, clarify, refine, or finalize
GitHub-issue-based work with octo-lite. This is a user-facing operator workflow,
not an implementer/reviewer role.

Issue shaping is intentionally thorough. The final GitHub issue is intentionally
concise.

## Role Skills

Use only the Issue Shaper role skills from `role-skills.json`:

- `$octo-lite-issue-shaper` for the operator-facing shaping workflow.
- `$grill-with-docs` for docs-backed clarification.
- `$octo-lite-github` for approved GitHub issue, label, and context
  operations.

Do not load implementer or reviewer role skills while shaping unless the
operator explicitly changes roles.

## Core Rule

During shaping, `.octo-lite/drafts/<slug>.md` is the canonical working artifact.
Conversation is scratch. GitHub is mutated only after explicit operator
approval. After successful GitHub finalization, the GitHub issue is canonical
and the draft is deleted.

## Bundled Templates

Read only the template needed for the current operation:

- `assets/github-issue.md` for the active draft and final GitHub issue body.
- `assets/readme.md` for target repo README initialization.
- `assets/repo-agents.md` for target repo `AGENTS.md` initialization.
- `assets/spec-index.md` for target repo `spec/index.md`.
- `assets/spec-domain.md` for canonical domain specs.
- `assets/adr.md` for ADRs.
- `assets/gitignore-entry.txt` for target repo draft ignore coverage.

## Target Repo Initialization

When a target repo lacks octo-lite durable surfaces, initialize only the missing
minimal files:

- `README.md`
- `AGENTS.md`
- `spec/index.md`
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

Start from exactly one new idea or one existing GitHub issue.

If an existing issue is named, fetch focused context with `gh issue view`.
If the work is a new idea, shape locally first and create the GitHub issue only
at finalization.

Preflight GitHub identity early:

```bash
gh auth status
gh repo view
```

Do not create labels, edit issues, create issues, or post comments until the
final approved mutation step.

### 2. Create Or Refresh The Draft

Create `.octo-lite/drafts/<slug>.md` from `assets/github-issue.md`. If shaping
an existing rough issue, seed the draft from its current title/body, then
normalize it to the template.

The draft must use exactly these headings:

```md
## User Story
## Background
## Desired Outcome
## Acceptance Criteria
## Out Of Scope
## Context
```

Keep the draft clean enough to paste directly into GitHub. Do not add an intake
diary, long transcript, raw logs, secrets, or scratch notes. If a decision is
unresolved, represent it as `TBD` in the relevant final section.

### 3. Grill With Docs

Load and follow `$grill-with-docs` for the clarification pass. Stress-test the
work against target repo instructions, README, specs, ADRs, code, package
scripts, provider docs already present in the repo, and existing GitHub issue/PR
context.

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
- Record deliberate follow-up work in the issue body or shape a separate issue
  only after operator approval.

### 4. Resolve Spikes, Env, And Architecture

Run a bounded spike only when a behavior-affecting question cannot be answered
from durable sources or direct operator input and the answer is needed before
safe implementation.

For env/config needs, identify names, destination, purpose, required timing, and
whether local/mock evidence is acceptable. Never record raw secrets.

Discuss architecture before final acceptance review. Record durable behavior in
`spec/`; record hard-to-reverse, surprising trade-offs in `spec/adr/`.
State the ADR checkpoint result explicitly, even when the result is "no ADR
required."

### 5. Maintain Specs And ADRs

Use the same spec file rules as Octo:

- Canonical specs live under `spec/domains/<durable-area>.md`.
- ADRs live under `spec/adr/0001-slug.md`.
- `spec/index.md` links canonical specs and ADRs.
- File names describe durable areas, not issue IDs.
- Issue IDs belong in references and decision logs.

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

### 6. Review Acceptance Criteria

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

### 7. Finalize Follow-Up Scope

When shaping discovers adjacent or prerequisite work:

- Propose a separate issue only when the work is independently valuable or a
  real blocker for the current issue.
- Show the proposed title, relationship to current scope, blocker status, and
  whether it should be created now or deferred.
- Do not create child, related, or follow-up GitHub issues without explicit
  operator approval.
- Do not use blocking relationships as a priority mechanism.

### 8. Final Ready Gate

Before applying `octo-lite:ready`, all of this must be true:

- The draft has the exact final GitHub issue headings.
- No unresolved `TBD` remains.
- Acceptance criteria were reviewed and are observable.
- Relevant specs/ADRs are updated, or no-change rationale is explicit.
- Env/config needs are known, scoped out, or recorded as operator-owned
  prerequisites.
- Target repo initialization files are present when needed.
- `.octo-lite/drafts/` is ignored.
- Durable artifacts are ready to commit.
- The operator has reviewed the issue draft and relevant repo diff.
- The operator explicitly approved final GitHub mutation.
- The Issue Shaper role used `$grill-with-docs` or recorded why docs-backed
  grilling was not applicable.

### 9. Commit Durable Artifacts

Use a shaping branch:

```text
octo-lite/shape/<slug>
```

After operator approval, commit only durable artifacts such as repo init files,
specs, ADRs, repo docs, and `.gitignore` updates. Do not commit
`.octo-lite/drafts/`, scratch notes, raw logs, or secrets.

Do not open a separate artifact-only PR. The implementer later creates the
implementation branch from the shaping branch commit.

### 10. Finalize GitHub

After approval and durable commit:

1. Create or update the GitHub issue using the approved draft body.
2. Create the label `octo-lite:ready` if missing.
3. Apply `octo-lite:ready` to the issue.
4. Delete `.octo-lite/drafts/<slug>.md`.

Use the GitHub CLI. Examples:

```bash
gh issue create --title "<title>" --body-file .octo-lite/drafts/<slug>.md
gh issue edit <number> --body-file .octo-lite/drafts/<slug>.md
gh label create "octo-lite:ready" --description "Shaped by octo-lite and ready for implementation" --color "0969da"
gh issue edit <number> --add-label "octo-lite:ready"
```

If GitHub mutation fails, keep the draft and report the exact blocker.

## Boundaries

- Do not implement the shaped work.
- Do not start the implementer/reviewer loop.
- Do not create extra workflow labels beyond `octo-lite:ready`.
- Do not create child issues unless the operator explicitly asks for that
  separate GitHub mutation. Prefer recording split recommendations in the issue
  or shaping a separate issue one at a time.
