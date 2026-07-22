---
name: octo-lite-github
description: Use GitHub PRs, branches, reviews, and explicitly requested GitHub issue operations in octo-lite workflows, while respecting Linear-first tracking when the target repo is Linear-tracked.
---

# octo-lite GitHub

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use this skill whenever an octo-lite role needs branch, PR, review, comment, or
explicit GitHub issue context.

## Source Of Truth

- In Linear-first target repos, Linear is the source of truth for product/dev
  scope, status, dependencies, and issue identity. Start from the Linear issue
  key and treat GitHub issues as read-only context unless the operator
  explicitly asks for a GitHub issue operation.
- During Linear-first shaping, `.octo-lite/drafts/<slug>.md` is only a local
  working artifact until the operator approves mutation to Linear/specs.
- In GitHub-first target repos, `.octo-lite/drafts/<slug>.md` is canonical until
  the operator approves GitHub mutation; after finalization, the GitHub issue
  body and `octo-lite:ready` label are the issue source of truth.
- The evolving draft PR is the durable shaping and delivery surface.
- Specs under `spec/` and ADRs under `spec/adr/` remain durable behavior sources
  and can outrank stale Linear, GitHub issue, or PR text.

## Required Reads

Use `gh` for PR context. Use `gh issue view` only when the operator explicitly
names a GitHub issue or the repo is GitHub-first:

```sh
gh auth status
gh repo view
gh issue view <issue> --json number,title,labels,url,body,state
gh pr view <pr> --json number,title,url,body,state,headRefName,baseRefName,files,reviews,comments
```

Read target repo `AGENTS.md`, its declared canonical index (`spec/index.md` or
`spec/index.spec.html`), relevant specs, ADRs, and repo docs before changing
durable workflow artifacts.

## Issue Shaper Mutations

For Linear-first work, do not create, update, close, label, or comment on GitHub
issues unless the operator explicitly asks for that exact GitHub issue mutation.
Update Linear and specs instead.

For GitHub-first work, do not mutate GitHub during shaping until the operator
approves the final mutation. After approval:

1. Create or update exactly one GitHub issue with the approved draft body.
2. Create `octo-lite:ready` if missing.
3. Apply `octo-lite:ready`.
4. Delete the local draft.

Do not create extra workflow labels unless the operator explicitly asks.

## Implementer Mutations

- Work on one branch for the tracked unit of work. For Linear-first work, prefer
  the target repo's existing branch convention or
  `octo-lite/<linear-key-lower>-<slug>`. For GitHub-first work, use
  `octo-lite/<issue-number>-<slug>`.
- Continue the shaped unit's existing draft PR. Open it only when shaping did
  not already create it. Never create a second implementation PR for the unit.
- For Linear-first work, the PR body starts with `Tracks <LINEAR-KEY>` and
  includes `## Summary` and `## Validation`.
- For GitHub-first work, the PR body starts with `Closes #<issue-number>` and
  includes `## Summary` and `## Validation`.
- Post or update a compact `## octo-lite handoff` PR comment.
- Do not merge.
- Do not approve as the human reviewer.

## Verdict Mutations

- The reviewer returns a clear or blocking finding set bound to exact HEAD.
- A deterministic helper creates or updates one machine-readable PR verdict
  comment for shaping review and one for code review.
- The comment binds HEAD, inputs, findings, and reviewer receipt.
- Do not depend on the formal Review API, reviewer identity, checks, or labels.
- Never merge or approve as the human reviewer.

## Merge And Linear Sync

- Merge to the main branch is not a separate carve-out; it is the operator
  agent's mechanical execution of an accepted PR, bound to the human acceptance
  instruction. The operator or meta-operator agent executes the merge on that
  acceptance instruction. No worker merges, no agent decides acceptance, and no
  agent merges unaccepted work.
  Once a merge lands, its tracked issue owes the `In Staging` transition: the
  merge is not complete until Linear reflects that the merge-sha is genuinely
  an ancestor of the deployed main branch.
- Do not rely on a human remembering that move. Where the target repo provides
  a post-merge hook that records `In Staging` from the merge-sha reality check,
  that hook is the enforcement; state the expectation, let the hook fire it, and
  verify it landed.
- Only advance, never regress: leave an issue already at or beyond `In Staging`
  untouched, and never claim a rung the repository reality has not reached.

## Boundaries

- Do not create, update, close, label, or comment on GitHub issues for
  Linear-first work unless the operator explicitly asks.
- Do not create workflow labels beyond `octo-lite:ready` in GitHub-first work
  unless the operator explicitly asks.
- Do not create extra PRs for the same issue.
- No worker or reviewer role merges or approves as the human reviewer.
- Only the operator or meta-operator agent executes a merge, and only on
  explicit human acceptance and instruction, per Merge And Linear Sync above;
  no agent merges unaccepted work or decides acceptance itself.
