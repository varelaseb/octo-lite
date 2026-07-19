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

## Prompt TDD

Apply this to every prompt, role, or skill instruction change.

1. Write the behavior contract first: exact inputs, the observable decisions,
   actions, or fields required, forbidden behavior, and acceptable proof.
2. Run the smallest scenario against the actual unchanged instructions in a
   fresh model session. Record only a genuinely wrong or ambiguous decision as
   red, never a missing file, module, export, or script.
3. Change the instructions. In a different fresh model session, run the same
   scenario and judge the observable decision against the contract for green.
4. Run narrow regression scenarios for adjacent behavior the change could shift.
5. Deterministic tests cover loading, wiring, schema, invariants, and forbidden
   characters. They do not substitute for judged model behavior.

Never accept an exact prose snapshot or keyword presence as behavioral proof.
Never fabricate red chronology; if prior red evidence cannot be honestly
reconstructed, say so instead of claiming it. Keep eval evidence to the one-off
scenario record; do not build an eval service or general harness for it.
