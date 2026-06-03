---
name: typescript
description: TypeScript policy for octo-lite implementer work when durable repo signals show TypeScript is in scope.
---

# TypeScript

Use this skill only when the target repo contains durable TypeScript signals
such as `.ts` or `.tsx` files, `tsconfig*.json`, TypeScript package scripts,
Vitest/MSW files, or TypeScript lint/test config.

## Rules

- Preserve the existing compiler, module, lint, and test conventions.
- Prefer typed interfaces at module boundaries over broad `any` usage.
- Keep generated types and lockfile changes scoped to the issue.
- Use existing test and typecheck scripts before inventing commands.
- Record exact validation commands and failures in the PR or handoff.

If TypeScript configuration changes affect durable repo behavior, update specs
or route back to Issue Shaper when the issue did not authorize that change.
