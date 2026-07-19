---
name: octo-lite-loop
description: Run the native octo-lite delivery loop after exact shaping readiness.
---

# octo-lite Loop

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use after operator-approved shaping and a clear exact-head shaping verdict.
Linear is primary for tracked work. Specs define detailed behavior. One evolving
draft PR carries shaping and implementation.

## Required envelope

Resolve roles through `roles.toml`. Refetch before launch:

- complete Linear issue, state, and fingerprint
- PR, base, topology revision, and exact HEAD
- spec and ADR blobs
- nonempty conversation-log references and the pinned cutoff used by shaping
  review; a cutoff alone is not enough
- shaping verdict comment, bound inputs, and reviewer receipt
- target `AGENTS.md` blob
- parent, reply route, brief, and launch access facts

Stop on missing or stale input. Linear must be `Shaped` or operator-pulled
`Todo`. Conversation logs are shaping evidence, never implementation prompts.

## Passes

Every pass is a fresh instance. Never resume a worker for another pass. Never
use `--last`.

Before each pass, run `octo-launch launch`. It refetches exact sources, creates
the fresh worktree, resolves the role, bootstraps and verifies BOOTSTRAP_ACK,
then resumes that exact same provider session to run the pass. It is the sole
LLM execution for the pass. It parses the role's structured result, binds it to
the receipt, and prints the exact receipt plus a machine-readable `pass_result`.

Then invoke one `workflows/octo-loop-qa.js` mode, passing that exact receipt and
`pass_result`. The Workflow never launches a worker itself; it only performs
deterministic gating: it independently recomputes the result binding, checks it
against the receipt's stored binding, checks role, launch revision, exact HEAD,
and mode-specific schema, then advances or returns a fix or blocked stage. Read
back its exact output before resolving the next pass. Never precompute receipts
for future unknown HEADs. Never run a second worker for the same pass.

1. Fresh exact Sonnet 5 xhigh implementer.
2. Require spec-derived intended red, smallest green, refactor, validation,
   exact HEAD, receipt, and durable PR handoff.
3. Fresh GPT-5.6 Sol high code reviewer on that HEAD.
4. Publish one exact-head verdict comment through `octo-control
   verdict-publish`. No formal GitHub Review API gate.
5. Missing, malformed, ambiguous, blocking, or wrong-head review cannot advance.
6. Blocking review starts a fresh Sonnet fix pass on the same PR.
7. Every fix starts with a spec-derived regression red and returns a new HEAD.
8. Every new HEAD gets a fresh Sol re-review.
9. After three blocking review and fix cycles, return to shaping.

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

Use `octo-control linear-transition`. It verifies the exact caller against
stream ownership or a bound role receipt, compares expected state, mutates
once, reads back, updates child status, and notifies the parent. Acceptance,
merge, staging, preproduction, and live transitions are operator-owned
helpers. Use `octo-control accept` for the exact-HEAD acceptance record; it
verifies the caller against `operator-owner.toml` and never infers a decision.

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
