---
name: octo-lite-github
description: Use GitHub issues, labels, comments, branches, and PRs as octo-lite's durable workflow surface for Issue Shaper, implementer, and reviewer roles.
---

# octo-lite GitHub

Use this skill whenever an octo-lite role needs issue, label, branch, PR, or
comment context.

## Source Of Truth

- During Issue Shaper work, `.octo-lite/drafts/<slug>.md` is canonical until
  the operator approves GitHub mutation.
- After finalization, the GitHub issue body and `octo-lite:ready` label are the
  issue source of truth.
- During implementation and review, the PR is the durable loop surface.
- Specs under `spec/` and ADRs under `spec/adr/` remain durable behavior
  sources and can outrank stale issue or PR text.

## Required Reads

Use `gh` for GitHub context:

```sh
gh auth status
gh repo view
gh issue view <issue> --json number,title,labels,url,body,state
gh pr view <pr> --json number,title,url,body,state,headRefName,baseRefName,files,reviews,comments
```

Read target repo `AGENTS.md`, `spec/index.md`, relevant specs, ADRs, and repo
docs before changing durable workflow artifacts.

## Issue Shaper Mutations

Do not mutate GitHub during shaping until the operator approves the final
mutation. After approval:

1. Create or update exactly one GitHub issue with the approved draft body.
2. Create `octo-lite:ready` if missing.
3. Apply `octo-lite:ready`.
4. Delete the local draft.

Do not create extra workflow labels unless the operator explicitly asks.

## Implementer Mutations

- Work on one branch named `octo-lite/<issue-number>-<slug>`.
- Open or update exactly one PR linked to the issue.
- PR body starts with `Closes #<issue-number>` and includes `## Summary` and
  `## Validation`.
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

- Do not create workflow labels beyond `octo-lite:ready` unless the operator
  explicitly asks.
- Do not create extra PRs for the same issue.
- Do not merge.
- Do not approve as the human reviewer.
