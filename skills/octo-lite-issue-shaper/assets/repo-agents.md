# Agent Instructions

## Repository Role

This repository uses octo-lite for Linear-first development unless the operator
explicitly selects GitHub-first tracking for a specific task.
Repo-specific guidance in this file overrides generic octo-lite defaults for
this repository's code, commands, architecture, and validation.

## Durable Sources

- Linear issues define issue-specific scope, status, dependencies, and
  acceptance criteria for Linear-tracked work.
- `spec/` defines durable product and system behavior.
- `spec/adr/` records hard-to-reverse architectural decisions.
- GitHub pull requests provide implementation evidence, code discussion, and
  human review.
- GitHub issues are not the canonical tracking surface for Linear-tracked work
  unless the operator explicitly asks for a GitHub issue operation.

## Spec Format

- Omit the format signal, or declare `Spec format: markdown`, to use the
  backward-compatible Markdown spec layout.
- Declare the exact signal `Spec format: spec-chat` only when this repo commits
  spec-chat scaffolding and treats `*.spec.html` as its canonical spec source.
- Spec-chat repos keep prose one sentence per line, anchor every meaningful
  block with `data-anchor`, store visual state in pretty-printed semantic-island
  JSON, vendor the shared `.viz/` runtime for offline rendering, and ignore
  `*.review/` event spools.
- Shaping runs the spec-chat review loop (serve, annotate, hand off, drain,
  edit, reply) before readiness; agents do not regenerate Markdown counterparts.

## Local Workflow

- Shape work with octo-lite before implementation.
- Do not implement from vague or unresolved issue scope.
- Keep `.octo-lite/drafts/` uncommitted.
- Update `spec/` or `spec/adr/` when implementation changes durable behavior.
- For Linear-tracked work, PR bodies should reference the Linear issue key, for
  example `Tracks TUR-50`, rather than closing a GitHub issue mirror.

## Validation

- TODO: add repo test, lint, typecheck, and build commands.

## Conventions

- TODO: add repo-specific code, architecture, naming, dependency, and review
  conventions.
