---
name: python
description: Python stack policy for octo-lite implementer work when durable repo signals show Python is in scope.
---

# Python

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use this skill only when the target repo contains durable Python signals such
as `.py` files, `pyproject.toml`, requirements files, `uv.lock`,
`poetry.lock`, `Pipfile`, Python tests, or Python CI docs.

## Rules

- Use the environment manager and test commands already selected by the repo.
- Do not introduce a new package manager or formatter unless the issue requires
  it.
- Preserve existing typing, linting, and test conventions.
- Keep dependency changes scoped and update lockfiles when required by the repo.
- Record validation commands and failures in the PR or handoff.

Stop for Issue Shaper/operator clarification when Python packaging or runtime
behavior needs a durable decision not present in specs or repo docs.
