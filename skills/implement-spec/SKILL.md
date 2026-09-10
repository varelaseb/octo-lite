---
name: implement-spec
description: Implement a specification in code.
disable-model-invocation: true
---

# Implement Spec

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Implement the complete spec on one branch and leave one PR ready for human
review. Use octo-lite skills as useful implementation guidance. Do not use the
octo-lite role resolver, worker contracts, loop workflow, legacy launch/workflow
receipts, journals,
exact-role gates, or lifecycle ceremony.

## Goal

The owning orchestrator starts one Codex `/goal` for the requested outcome and
done condition. Keep it active through shaping, implementation, review, and
authorized QA. Complete it only when the requested handoff is ready. Each
temporary worker starts one narrow goal for its ticket and returns its result to
the owning orchestrator. Goals point to Linear, the canonical spec, and status
artifacts; they do not duplicate them or replace human gates. Do not mark a
goal blocked for a normal human gate or one transient failure.

## Inputs

Require:

- canonical spec
- spec issue
- implementation tickets linked to that issue
- explicit blocking relations between tickets
- target root `AGENTS.md`

The tickets are a task graph, not ordered steps. The ready frontier contains
every incomplete ticket whose blockers are complete. Keep Linear titles,
descriptions, relations, assignees, and states aligned with reality throughout.
Do not copy ticket or spec prose into agent messages. Send essential absolute
source paths in the message body; artifact metadata alone is insufficient.

Record the requested handoff in the existing brief. Manual QA readiness means
a usable feature deployment, required dependencies, working account roles and
starting scenarios, with a secure credential pointer and stated limitations.
Do not replace that outcome with exhaustive agent proof. Required spec/target
evidence still applies; human QA, code readiness and acceptance are separate.

## Start

1. Read the spec, issue, tickets, and enough of the graph to identify the first
   frontier.
2. When exploration would remove duplicated implementation work, spawn one
   optional exploration agent. Give it write access only to a shared directory
   outside the repo. Its deliverable is concise Markdown notes linked from the
   relevant tickets.
3. Create the integration branch from the target base and open one draft PR.
   Put `Closes <issue-key>` lines in the PR body for the spec issue and every
   implementation ticket.

## Herdr workers

Use the verified launch path from `herdr-comms`; inspect help only when that
invocation is unknown or changed. Spawn every exploration,
implementation, merge, review-fix worker through Herdr. Prefer background tabs
and fill available capacity from the current frontier.

Use the same current Herdr session and workspace routing as the owning
orchestrator. Herdr owns session selection. Use the configured Codex CLI
default model unless the operator explicitly selects another runtime. Keep the
worker-specific nuance: every writer still gets its own worktree, and only one
merger writes the integration branch.

For each ready ticket:

1. Create a dedicated worktree and branch from the current integration branch.
2. Mark the Linear ticket In Progress only when its worker starts.
3. Spawn a direct Herdr implementer in that worktree. Prompt it with pointers
   to the ticket, spec, target `AGENTS.md`, optional research notes, integration
   branch, and relevant prior commits.
4. Tell it to load only applicable octo-lite skills such as `tdd`,
   `frontend-design`, `nodejs`, `pnpm`, `python`, or `typescript`. The worker
   owns only that ticket, validates it, commits it, and returns the commit plus
   terse evidence. It does not merge, update unrelated tickets, or follow the
   octo-lite delivery contract.

Use `herdr-say` for commands and `herdr-ack` for command completion. Keep
messages sparse. A status pointer or commit is better than a recap.

## Integrate and advance

When an implementer completes:

1. Spawn a merger agent in a clean integration worktree.
2. Give it the ticket, worker commit, integration branch, and spec pointers.
3. Have it merge or cherry-pick the worker commit, resolve only integration
   conflicts, run proportionate validation, push the integration branch, and
   report the resulting commit.
4. Mark the ticket Done only after its change is integrated and pushed. If the
   merge fails or validation is red, reflect that truth in Linear and return
   the ticket to active work.
5. Recompute the frontier and immediately fill newly available capacity.

One merger writes the integration branch at a time. Implementers may continue
in parallel on independent frontier tickets.
Each writer has a distinct worktree, including the merger; a separate tab in
the same checkout is not isolation. Read-only explorers may share source only
when they do not install dependencies, change branches or generate files there.

Consume completed results at the next owner wake, before optional status work,
and continue integration or the next ready task in that turn. Reuse an available
merger instead of creating another. An owner waiting on workers drains their
inboxes once per check and verifies acknowledgment plus the named result through
`herdr-comms`. Record one truthful current state, next action and dependency.
Do not end delivery at startup, dispatch, worker completion or review forwarding.

## Validation and preview setup

Read target `AGENTS.md` and applicable CI commands before broad validation,
including DB isolation, shard/file concurrency, schema and dependencies.
Do not run parallel destructive suites on one shared DB when CI isolates them.
On topology failures, stop the owned invalid run and diagnose before retrying.
Reuse passing evidence only for unchanged code/head and compatible environment
when target rules permit; final-head required checks and integration-sensitive
tests remain required. Repeat or broaden tests only for a change, failure,
unresolved risk or explicit required check, not because a handoff occurred.

Use one preview deployment/fork owner. Its current receipt in existing control
state binds feature SHA, revision, DB fork/schema, scoped access, fixture
namespace and secure credential pointer. A base-only healthy preview is not the
feature. Share the receipt and setup window; do not infer access from another
identity's grants. Before recreation, preserve fixtures/paid progress and agree
closure with affected owners; restore and verify after the new receipt. Keep
rollback and target safety checks. No new receipt framework is required.
Stop watching an operation after its terminal outcome is consumed. Retry a
known deployment/access blocker only after a relevant state change; continue
independent work and report the exact remaining dependency.

## Review and finish

After every ticket is integrated:

1. Run `/code-review` on the integration branch. If unsupported in this runtime,
   use the available independent review mechanism with the same exact head,
   base, spec and scope. Verify acknowledgment and actual review work once;
   do not retry an unrecognized slash command or count pasted text as review.
2. If review reports issues, create one fix branch and worktree and spawn one
   implementer to fix all findings. Merge it through one merger agent, then
   review the new integration head. One consolidated batch is the default,
   not a lifetime repair cap. If a confirmed defect remains, continue a bounded
   repair of that finding and changed surface. If the same attempt makes no
   progress, diagnose or route the concrete unresolved blocker through the
   repo-approved path while independent tasks continue. Never park an
   actionable defect solely because a cycle completed, repeat unchanged
   reviews blindly, or implicitly waive a failed required check.
3. Run the target repo's required validation.
4. Mark the PR ready for review only when the final review is clear and every
   required validation succeeds. Otherwise keep it draft and report the
   blocker. Keep the spec issue open until human review or repository
   automation closes it.
5. Remove every temporary worker worktree only after it is clean and its
   commits are reachable from the integration branch. Never force-remove a
   worktree with uncommitted or unmerged work.

Continue any authorized deployment/seeding/manual-QA handoff after code review
readiness; report its actual state separately. Human acceptance, preproduction
promotion and live traffic shifts still require explicit human instruction.

Return the PR, integrated tickets, validation, review result, and any truthful
remaining blocker.

## Human acceptance callback

If the human explicitly accepts and instructs this owning lane to merge the
named PR, treat a merge instruction as acceptance of that exact head unless the
human says otherwise. Load `octo-lite-github`, verify required checks and exact
head, record acceptance, execute the merge, and verify post-merge Linear sync.
Do not consult `operator-owner.toml`; it only routes meta-operator handoffs and
messages. A human statement that this lane owns the action is sufficient.
Failed required checks still block merge until fixed or durably waived through
a repository-approved path.
