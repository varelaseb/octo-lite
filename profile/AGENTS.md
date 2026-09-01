# octo-lite

Use octo-lite for Linear-first product and development work.

## Sources

- Linear owns issue identity, high-level decisions, context, non-goals,
  dependencies, and lifecycle state.
- Canonical specs and ADRs own detailed behavior, acceptance rules, interfaces,
  edge cases, and constraints.
- Shaping artifacts and the implementation PR link the same Linear issue and
  canonical spec; implementation uses one integration branch and one PR.
- Target root `AGENTS.md` exclusively owns repo-specific commands,
  architecture, validation, deployment, fixtures, and conventions.
- `roles.toml` and `roles/*.md` own legacy role-launched workflows.
- `$implement-spec` owns post-shaping delivery. Its Herdr workers use relevant
  octo-lite skills but do not use role contracts, the resolver, or loop gates.

Stop on source conflict. Conversation and memory never silently override these
sources. Memory may retain only dated, evidence-backed gotchas with a durable
source or fix link.

## Workflow

- Use `$spec-chat-shape` to produce the reviewed spec, spec issue, and
  dependency-linked implementation tickets.
- Use `$implement-spec` to deliver the whole spec on one PR branch.
- `$implement-spec` keeps Linear truthful, fills the ready ticket frontier with
  parallel Herdr workers, integrates each worker through a merger agent, runs
  `/code-review`, fixes findings once, and marks the PR ready for human review.
- Implementation workers follow target `AGENTS.md` and relevant octo-lite
  skills. They do not follow the octo-lite delivery contract or ceremony.
- Keep communication sparse and point agents to durable context instead of
  repeating it.
- Default to action: prior explicit operator intent is authorization; former
  approval gates are act-then-notify steps with a prepared rollback and the
  operator vetoes by rollback. Lawful stops: operator-held access, legally
  binding irreversible actions without rollback, and the three human-gated
  carve-outs, actual acceptance of delivered work, preproduction promotion,
  and live traffic shifts.
  No agent infers, self-authorizes, or decides acceptance, a preproduction
  promotion, or a traffic shift, and no agent merges unaccepted work. On
  explicit human instruction, the operator agent executes the acceptance
  record, merge, preproduction promotion, or traffic shift.

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
