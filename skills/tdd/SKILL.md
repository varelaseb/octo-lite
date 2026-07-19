---
name: tdd
description: Apply mandatory spec-driven red-green-refactor during behavior-changing octo-lite implementer work.
---

# Test-Driven Development

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use this skill for every behavior-changing implementation and fix. Only a narrow
operator-approved shaping waiver may replace it, and that waiver must name the
alternative proof.

## Workflow

1. Identify the behavior and acceptance evidence before editing production code.
2. Add or update the smallest meaningful failing test.
3. Run the focused test and confirm the failure is for the intended reason.
4. Implement the smallest change that makes the test pass.
5. Refactor while keeping tests green.
6. Broaden validation according to risk and target repo conventions.
7. Record red/green validation evidence in the PR or handoff.

Do not call a test red when it fails for setup, syntax, missing dependencies, or
another unintended reason. Database coverage that silently skips is not green.

Do not write brittle tests around implementation details when a user-visible
contract, API behavior, or durable spec can be tested directly.
