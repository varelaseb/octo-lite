# Repository Instructions

Spec format: markdown
Canonical spec paths: TODO: exact target spec path(s), comma-separated
Canonical ADR paths: none

## Commands

- TODO: install, test, lint, typecheck, build, and run commands.

## Architecture

- TODO: repo-specific boundaries and dependency rules.

## Validation

- TODO: required checks by change type.

## Operator-visibility surface

octo-lite publishes each delivered issue onto this repo's operator-visibility
surface through the sole verified publication helper (octo-control
publish-evidence). octo-lite owns only the publish mechanism and readback; this
repo declares the concrete surface with all three signals below. An incomplete
declaration fails the publish loud (never a silent no-publish).

- Operator-visibility served root: TODO: dir where the per-issue served-evidence link is created
- Operator-visibility verdict index: TODO: builder-read (operator-read) verdict-index dir
- Operator-visibility rendered-card verify: TODO: command emitting the rendered operator card as JSON on stdout (fields issue, pr, head, verdict, story_ids, criterion_coverage)

## Deployment

- TODO: repo-specific environments and release rules.

## Fixtures

- TODO: safe test data and concurrency constraints.

## Conventions

- TODO: repo-specific naming and review conventions.
