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
- `agents/*.md` own the role contracts. They are hand-written and pin no
  model, so each CLI applies its own default.
- `$implement-spec` owns post-shaping delivery. Its Herdr workers run under the
  `implementer` and `code-reviewer` contracts, which declare their skills.

Stop on source conflict. Conversation and memory never silently override these
sources. Memory may retain only dated, evidence-backed gotchas with a durable
source or fix link.

## Workflow

- A worklane is one coherent outcome owned by one orchestrator, tracked by one
  primary Linear issue, and delivered through one integration head and PR. Its
  child tickets, workers, reviewers, and QA artifacts belong to that lane. They
  advance through the owner and do not create competing lanes or PRs. One
  orchestrator owns one coherent worklane and its single integration PR.
- Use `$spec-chat-shape` to produce the reviewed spec, spec issue, and
  dependency-linked implementation tickets.
- A processed human **Finish review** hand-off is acceptance of the reviewed
  canonical spec. It closes the browser review loop and permits implementation
  dispatch under that spec. It is distinct from implementation PR acceptance,
  merge, preproduction promotion, and live traffic gates, which remain explicit.
- Use `$implement-spec` to deliver the whole spec on one PR branch.
- Every owning orchestrator starts one Codex `/goal` with the concrete user
  outcome and done condition. Workers use one narrow ticket goal. Goals guide
  continuation and completion; Linear, canonical specs, and status artifacts
  remain their sources of truth.
- Worker lifecycle is explicit: every worker starts one concrete `/goal` before
  work, naming its narrow outcome, source or ticket pointers, and observable
  done condition. Keep it active while working. A worker that is blocked,
  stalled, interrupted, or unable to finish messages its owner or operator
  before idling with current state, evidence, blocker, and concrete next need.
  It does not report completion or go idle without that handoff. A transient
  failure or normal human gate is reported, but is not itself a blocked goal.
- Each worker is single-ticket and single-use. Never reuse a worker for another
  ticket. Start a fresh worker for each ticket or repair pass while preserving
  the blocked, stalled, interrupted, and unable-to-finish handoff above.
- `$implement-spec` keeps Linear truthful, fills the ready ticket frontier with
  parallel Herdr workers, integrates each worker through a merger agent, runs
  independent review, resolves findings through bounded repair, and marks the
  PR ready for human review only with clear review and required checks passed.
- Implementation workers follow their role contract, target `AGENTS.md`, and
  relevant octo-lite skills. They do not follow the delivery ceremony.
- Keep communication sparse and point agents to durable context instead of
  repeating it.
- On worker completion, consume its result, integrate and advance the next
  ready task. Owners remain responsible through authorized QA setup; a finished
  command or idle tab is not a finished workstream. Operators verify changed
  scope acknowledgments and wake unfinished idle owners through `herdr-comms`.
- Reuse verified launch/access paths within their recorded scope. A known
  authorized fallback needs no repeat approval. Recheck only changed or
  missing facts; preserve target-owned validation and deployment rules.
- Default to action: prior explicit operator intent is authorization; former
  approval gates are act-then-notify steps with a prepared rollback and the
  operator vetoes by rollback. Lawful stops: operator-held access, legally
  binding irreversible actions without rollback, and the three human-gated
  carve-outs, actual acceptance of delivered work, preproduction promotion,
  and live traffic shifts.
  No agent infers, self-authorizes, or decides acceptance, a preproduction
  promotion, or a traffic shift, and no agent merges unaccepted work.
  Acceptance follows the worklane. An explicit human
  instruction to merge a named PR accepts that exact head unless the human says
  otherwise. Mechanical rebases onto accepted main do not require renewed
  acceptance when behavior and scope are unchanged. The
  active owning agent receiving that instruction records acceptance and
  executes the merge.
  Required failed checks remain blockers until fixed or durably waived through
  a repository-approved path.
- An accepted PR merged into target main completes its worklane. When the lane
  finishes, the owner closes the orchestrator goal and reconciles the PR and
  worklane state together, then reconciles the primary Linear issue to Done and
  stops the lane. Residual QA gaps are historical notes only: never infer,
  create, reopen, or drive follow-up work from them. Follow-up exists only
  under an explicit new ticket or explicit operator instruction. Explicit human
  gates for spec review, QA evidence review, acceptance, promotion, and traffic
  shifts are unchanged.

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
- Generic skills, role contracts, helpers, and profile files install by symlink
  from the octo-lite source repo.
- Target instructions remain versioned inside each target worktree.
- Unless launch context explicitly confirms operator loopback access, never
  present localhost as usable operator access.
