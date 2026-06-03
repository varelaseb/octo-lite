# Agent Instructions

## Repository Role

This repository uses octo-lite for GitHub-issue-driven development.
Repo-specific guidance in this file overrides generic octo-lite defaults for
this repository's code, commands, architecture, and validation.

## Durable Sources

- GitHub issues define issue-specific scope and acceptance criteria.
- `spec/` defines durable product and system behavior.
- `spec/adr/` records hard-to-reverse architectural decisions.
- Pull requests provide implementation evidence and human review.

## Local Workflow

- Shape work with octo-lite before implementation.
- Do not implement from vague or unresolved issue scope.
- Keep `.octo-lite/drafts/` uncommitted.
- Update `spec/` or `spec/adr/` when implementation changes durable behavior.

## Validation

- TODO: add repo test, lint, typecheck, and build commands.

## Conventions

- TODO: add repo-specific code, architecture, naming, dependency, and review
  conventions.

