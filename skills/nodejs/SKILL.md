---
name: nodejs
description: Node.js runtime policy for octo-lite implementer work when durable repo signals show a Node.js project and the issue touches runtime scripts, modules, env loading, or server-side JavaScript.
---

# Node.js

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use this skill only when the target repo contains durable Node.js signals such
as `package.json`, lockfiles, Node config, server entrypoints, or Node-specific
validation docs.

## Rules

- Follow the package manager already selected by the repo.
- Preserve the existing module system unless the issue requires changing it.
- Prefer existing scripts from `package.json` and repo docs.
- Keep env/config names explicit and never record raw secrets.
- Do not impose Node.js conventions on non-Node repositories.
- Record validation commands and failures in the PR or handoff.

If the issue needs a runtime policy decision that is not already specified,
route back to Issue Shaper before implementing.
