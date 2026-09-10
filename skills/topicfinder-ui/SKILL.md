---
name: topicfinder-ui
description: Apply TopicFinder's established visual and UX language during UI implementation or review.
---

# TopicFinder UI

Use this skill for UI work in the TopicFinder repository. Read
[the design constitution](references/design-constitution.md) before making
design decisions, then inspect the relevant shipped reference surface in the
target worktree.

Treat the constitution as design judgment, not an automated pass/fail gate.
The current ticket and canonical spec own requested behavior. The constitution
owns visual language, interaction patterns, copy voice, and quality intent.
When sources conflict or a requirement is ambiguous, surface the conflict to
the owner instead of inventing a new pattern.

Keep work scoped to the requested surface. Reuse existing tokens, components,
assets, and patterns. Explain any intentional exception briefly in the
handoff or review. Do not redesign unrelated surfaces or add enforcement code,
lint rules, scripts, or dependencies to make the constitution mechanical.

For implementation, use the constitution while choosing structure, states,
motion, copy, and accessibility behavior. For review, inspect the changed
surface against the constitution and report meaningful deviations as findings,
with the relevant section and a concrete correction.
