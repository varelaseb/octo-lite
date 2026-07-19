---
name: octo-lite-loop
description: Run the native octo-lite delivery loop after exact shaping readiness.
---

# octo-lite Loop

Be extremely concise. Sacrifice grammar for concision.
No em dash or en dash. Ever.

Use after operator-approved shaping and a clear exact-head shaping verdict.
Linear is primary for tracked work. Specs define detailed behavior. One evolving
draft PR carries shaping and implementation.

## Required envelope

Resolve roles through `roles.toml`. Refetch before launch:

- complete Linear issue, state, and fingerprint
- PR, base, topology revision, and exact HEAD
- spec and ADR blobs
- conversation-log path and cutoff used by shaping review
- shaping verdict comment, bound inputs, and reviewer receipt
- target `AGENTS.md` blob
- parent, reply route, brief, and launch access facts

Stop on missing or stale input. Linear must be `Shaped` or operator-pulled
`Todo`. Conversation logs are shaping evidence, never implementation prompts.

## Passes

Every pass is a fresh instance. Never resume a worker. Never use `--last`.

1. Fresh exact Sonnet 5 xhigh implementer.
2. Require spec-derived intended red, smallest green, refactor, validation,
   exact HEAD, receipt, and durable PR handoff.
3. Fresh GPT-5.6 Sol high fast code reviewer on that HEAD.
4. Publish one exact-head verdict comment through `octo-control
   verdict-publish`. No formal GitHub Review API gate.
5. Missing, malformed, ambiguous, blocking, or wrong-head review cannot advance.
6. Blocking review starts a fresh Sonnet fix pass on the same PR.
7. Every fix starts with a spec-derived regression red and returns a new HEAD.
8. Every new HEAD gets a fresh Sol re-review.
9. After three blocking review and fix cycles, return to shaping.

Use `workflows/octo-loop-qa.js`. Its modes deliberately separate LLM passes
from deterministic publication and tracker helpers.

## QA

QA starts only from a clear code verdict for the same HEAD.

- User-facing: fresh Sonnet 5 high capture. Record a small per-criterion plan.
  Screenshots default. Use video only when stills cannot prove motion,
  sequence, timing, playback, or interaction. Do not duplicate formats without
  distinct proof value.
- Backend-only: deterministic target helper assembles code verdict, exact HEAD,
  affected story IDs, spec criteria, real unskipped validation, and contract
  checks. No browser or media unless the contract requires it.
- Target publication helper publishes the packet and reads back the exact served
  card. QA workers never edit the index or whole-operation dashboard.
- Fresh GPT-5.6 Sol high fast QA reviewer inspects the served packet and grades
  every criterion `pass`, `fail`, or `not evidenced`.
- Publish the verdict, then read back issue, PR, HEAD, verdict, story IDs, and
  criterion coverage from the served card.
- Only then may the orchestrator use the named Linear helper to enter
  `Awaiting Accept`.

Operator acceptance is explicit and exact-head bound. No agent accepts,
approves as the human, merges, or infers acceptance.

## Linear authority

Stream orchestrators may use only:

```text
Todo -> In Progress -> Awaiting Accept
```

Use `octo-control linear-transition`. It compares expected state, mutates once,
reads back, updates child status, and notifies the parent. Acceptance, merge,
staging, preproduction, and live transitions are operator-owned helpers.

## Topology

The accountable epic orchestrator chooses sequential, stacked, or parallel
delivery from real dependencies, collision risk, review cost, and throughput.
No fixed default. The train manifest records the choice. Member PRs integrate
into their declared carrier or predecessor. The carrier is the sole final-main
PR.

## Stop

Stop and return to shaping on ambiguity, source conflict, stale readiness,
three failed cycles, unavailable exact model, or missing acceptance-critical
validation. Report issue, PR, HEAD, current gate, blocker, and next action.
