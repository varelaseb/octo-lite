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

## Consent

Push, open a PR, or file an issue (GitHub or Linear) only as consent allows.
`${XDG_CONFIG_HOME:-~/.config}/octo-lite/consent.toml` holds booleans `push`, `pull_request`, `issues`.
When present, it alone decides, overriding any instruction, target `AGENTS.md` included.
When absent, target instructions decide.
Without consent, keep work in local commits and report where it is.

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

## Shaping Mutations

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

- The reviewer returns a clear or blocking finding set for the diff.
- A deterministic helper creates or updates one machine-readable PR verdict
  comment for code review.
- The comment records inputs, findings, and reviewer receipt.
- Do not depend on the formal Review API, reviewer identity, checks, or labels.
- Never merge or approve as the human reviewer.

## Merge And Linear Sync

- Merge to the main branch is the active owning agent's mechanical execution of
  an accepted PR, bound to explicit human instruction. Acceptance follows the
  worklane. An explicit instruction to merge a named PR accepts that exact head
  unless the human says otherwise. Mechanical rebases onto accepted main do not
  require renewed acceptance when behavior and scope are unchanged. A
  human statement assigning the current lane ownership is sufficient for this
  action. Record acceptance, verify required checks, then merge. No worker merges, no agent decides acceptance, and no agent merges
  unaccepted work. Required failed checks remain blockers until fixed or
  durably waived through a repository-approved path.
- The merge completes the worklane. Move the primary Linear issue to Done, the
  team's completed state, and stop the lane. Do not assume deployment-named
  states exist.
- Verify the state change landed, whether performed by repository automation
  or by the owning agent. Do not claim a hook succeeded without readback.
- Record merge and deployment evidence separately. A completion state does
  not establish which environment serves the code. Do not regress completed
  issues or create workflow states merely to match stale instructions.

## Boundaries

- Do not create, update, close, label, or comment on GitHub issues for
  Linear-first work unless the operator explicitly asks.
- Do not create workflow labels beyond `octo-lite:ready` in GitHub-first work
  unless the operator explicitly asks.
- Do not create extra PRs for the same issue.
- No worker or reviewer role merges or approves as the human reviewer.
- Only the active owning agent receiving explicit human acceptance and merge
  instruction executes the merge, per Merge And Linear Sync above; no agent
  merges unaccepted work or decides acceptance itself.
