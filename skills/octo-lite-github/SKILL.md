---
name: octo-lite-github
description: Use GitHub PRs, branches, reviews, and explicitly requested GitHub issue operations in octo-lite workflows, while respecting Linear-first tracking when the target repo is Linear-tracked.
---

# octo-lite GitHub

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
- During implementation and review, the PR is the durable loop surface.
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

Read target repo `AGENTS.md`, `spec/index.md`, relevant specs, ADRs, and repo
docs before changing durable workflow artifacts.

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
- Open or update exactly one PR for the tracked unit of work.
- For Linear-first work, the PR body starts with `Tracks <LINEAR-KEY>` and
  includes `## Summary` and `## Validation`.
- For GitHub-first work, the PR body starts with `Closes #<issue-number>` and
  includes `## Summary` and `## Validation`.
- Post or update a compact `## octo-lite handoff` PR comment.
- Do not merge.
- Do not approve as the human reviewer.

## Reviewer Mutations

- Post a real GitHub PR review with `gh pr review`.
- Use request-changes for blocking findings.
- Use a non-approving comment when no blocking findings remain.
- Keep findings first and include file/line references when possible.
- Do not merge and do not approve as the human reviewer.

## Boundaries

- Do not create, update, close, label, or comment on GitHub issues for
  Linear-first work unless the operator explicitly asks.
- Do not create workflow labels beyond `octo-lite:ready` in GitHub-first work
  unless the operator explicitly asks.
- Do not create extra PRs for the same issue.
- Do not merge.
- Do not approve as the human reviewer.
