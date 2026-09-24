---
name: frontend-design
description: Apply production-quality frontend design practice during octo-lite implementer work when the shaped issue touches UI, styling, interaction, or visual polish.
---

# Frontend Design

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use this skill only when the Linear/GitHub issue, specs, ADRs, repo instructions, or
code clearly put UI/frontend work in scope.

When the target has a domain-specific UI skill or design constitution, load it
before making visual or interaction decisions. That source supplies the local
language; this skill supplies the general frontend practice.

## Scope

- Respect existing design systems, component libraries, tokens, and patterns.
- Build the actual requested interface, not a marketing placeholder.
- Keep layouts responsive, readable, and free of text overlap.
- Use target repo assets and UI libraries before inventing new ones.
- Use icons for common tool actions when the project has an icon library.
- Validate through the target repo's normal checks and browser/screenshot
  evidence when the issue or repo convention calls for it.

## Boundaries

- Do not redesign unrelated surfaces.
- Do not introduce a new design system unless the issue explicitly asks.
- Do not hide incomplete behavior behind decorative UI.
- Stop for shaping/operator clarification when visual requirements,
  brand constraints, or acceptance evidence are ambiguous.
- Treat design guidance as agent judgment. Do not turn it into product code,
  lint gates, or new enforcement machinery unless the issue explicitly asks.
