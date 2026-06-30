---
name: tdd
description: Apply a red-green-refactor loop during octo-lite implementer work when the issue, specs, or operator asks for test-first development.
---

# Test-Driven Development

Use this skill when the Linear/GitHub issue, specs, ADRs, or operator explicitly asks
for TDD, test-first work, red-green-refactor, or integration-test-first
development.

## Workflow

1. Identify the behavior and acceptance evidence before editing production code.
2. Add or update the smallest meaningful failing test.
3. Run the focused test and confirm the failure is for the intended reason.
4. Implement the smallest change that makes the test pass.
5. Refactor while keeping tests green.
6. Broaden validation according to risk and target repo conventions.
7. Record red/green validation evidence in the PR or handoff.

Do not write brittle tests around implementation details when a user-visible
contract, API behavior, or durable spec can be tested directly.
