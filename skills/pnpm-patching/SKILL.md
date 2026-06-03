---
name: pnpm-patching
description: Create or maintain pnpm dependency patches for octo-lite implementer work when a shaped issue requires a pnpm-managed third-party hotfix.
---

# pnpm Patching

Use this skill only when the repo is pnpm-managed and the issue or debugging
evidence requires patching a third-party dependency.

## Rules

- Confirm the patch is necessary and issue-scoped before editing dependencies.
- Prefer upstream configuration or ordinary dependency upgrades when sufficient.
- Use pnpm's patch workflow and preserve existing `patchedDependencies`.
- Include minified or built dependency outputs only when the package actually
  consumes them and the repo convention allows it.
- Document why the patch exists, what would remove it, and how it was verified.
- Do not introduce pnpm patches in npm, yarn, bun, uv, cargo, or other package
  manager repos.

