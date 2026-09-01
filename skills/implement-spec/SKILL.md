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
octo-lite role resolver, worker contracts, loop workflow, receipts, journals,
exact-role gates, or lifecycle ceremony.

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
Do not copy ticket or spec prose into agent messages. Send pointers.

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

Inspect `herdr-spawn --help` before the first launch. Spawn every exploration,
implementation, merge, review-fix worker through Herdr. Prefer background tabs
and fill available capacity from the current frontier.

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

## Review and finish

After every ticket is integrated:

1. Run `/code-review` on the integration branch.
2. If review reports issues, create one fix branch and worktree and spawn one
   implementer to fix all findings. Merge it through one merger agent, then
   rerun `/code-review` once on the new integration head.
3. Run the target repo's required validation.
4. Mark the PR ready for review only when the final review is clear and every
   required validation succeeds. Otherwise keep it draft and report the
   blocker. Keep the spec issue open until human review or repository
   automation closes it.
5. Remove every temporary worker worktree only after it is clean and its
   commits are reachable from the integration branch. Never force-remove a
   worktree with uncommitted or unmerged work.

Return the PR, integrated tickets, validation, review result, and any truthful
remaining blocker.
