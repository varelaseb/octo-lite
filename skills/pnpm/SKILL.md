---
name: pnpm
description: pnpm package-management policy for octo-lite implementer work when durable repo signals show pnpm is the selected package manager.
---

# pnpm

Use this skill only when the repo already selects pnpm through `pnpm-lock.yaml`,
`pnpm-workspace.yaml`, a `packageManager` field, `.npmrc`, or repo docs.

## Rules

- Use pnpm for installs, scripts, and lockfile updates in pnpm repos.
- Do not switch package managers as part of unrelated issue work.
- Keep lockfile changes scoped to dependency changes required by the issue.
- Prefer repo scripts over ad hoc commands.
- Preserve workspace boundaries and existing `.npmrc` behavior.
- Record exact pnpm validation commands in the PR or handoff.

Stop for clarification when the issue requires dependency or package-manager
changes without an observable acceptance need.

