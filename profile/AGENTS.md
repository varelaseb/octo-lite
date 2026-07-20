# octo-lite

Use octo-lite for Linear-first product and development work.

## Sources

- Linear owns issue identity, high-level decisions, context, non-goals,
  dependencies, and lifecycle state.
- Canonical specs and ADRs own detailed behavior, acceptance rules, interfaces,
  edge cases, and constraints.
- One evolving draft PR carries shaping, implementation, exact-head verdicts,
  code discussion, and merge readiness.
- Target root `AGENTS.md` exclusively owns repo-specific commands,
  architecture, validation, deployment, fixtures, and conventions.
- `roles.toml` and `roles/*.md` own generic role runtime and prose. Every role
  launch uses the resolver. Generated adapters are not raw spawn paths.

Stop on source conflict. Conversation and memory never silently override these
sources. Memory may retain only dated, evidence-backed gotchas with a durable
source or fix link.

## Workflow

- Use `$octo-lite-issue-shaper` for intake, grilling, specs, stories, draft PR,
  and final fresh shaping review.
- Linear `Shaped` means the complete issue, specs, draft PR, pinned logs, hard
  TDD contract, and clear exact-head shaping verdict agree.
- Use `$octo-lite-loop` only from that readiness gate; loop fire performs the
  mechanical `Shaped -> Todo` first delivery step per the canonical
  delivery-entry-gate, never `Shaped -> In Progress`.
- Every behavior change and fix uses spec-derived red, green, refactor unless
  shaping records a narrow operator waiver and alternative proof.
- Every implement, fix, review, re-review, QA capture, and QA review pass is a
  fresh exact-role instance. Never use `--last`.
- Default to action: prior explicit operator intent is authorization; former
  approval gates are act-then-notify steps with a prepared rollback and the
  operator vetoes by rollback. Lawful stops: operator-held access, legally
  binding irreversible actions without rollback, and the two human-gated
  carve-outs, actual acceptance of delivered work and live traffic shifts.
  No agent infers human acceptance, approves as the human, or merges.

## Artifacts

- Follow the target spec signal. `Spec format: spec-chat` selects canonical
  `*.spec.html` and its browser review loop. Otherwise use Markdown.
- Markdown is for agent instructions and lifecycle context. TOML is for
  octo-lite machine configuration and current control state. JSONL is for
  minimal append-only traces.
- Generated artifacts reference exact canonical sources instead of copying
  them.
- Be extremely concise. Sacrifice grammar for concision.
- No em dash or en dash in LLM-facing instructions or generated text.

## Runtime

- octo-lite is installed foreground tooling, never a target dependency or
  service.
- Generic skills, roles, workflows, and profile files install by symlink from
  the octo-lite source repo.
- Target instructions remain versioned inside each target worktree.
- Unless launch context explicitly confirms operator loopback access, never
  present localhost as usable operator access.
