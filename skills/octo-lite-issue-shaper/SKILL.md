---
name: octo-lite-issue-shaper
description: Compatibility entrypoint for old octo-lite shaping requests. Redirects Spec Chat repositories to spec-chat-shape.
---

# octo-lite Issue Shaper

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

The octo-lite shaping contract is retired for Spec Chat repositories. Load and
follow `$spec-chat-shape`.

Shaping must leave:

- one reviewed canonical spec
- its current Linear issue
- linked implementation tickets describing bounded code outcomes
- explicit tracker blocking relations forming the task graph

Do not create octo-lite drafts, shaping verdict blocks, role-resolved reviewers,
receipts, journals, or a `Shaped` lifecycle gate. Do not implement during
shaping. Post-shaping delivery uses explicit `$implement-spec`.

For a target that explicitly declares `Spec format: markdown`, stop and ask for
the repository-selected Markdown shaping workflow instead of silently creating
a Spec Chat document.
