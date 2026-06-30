---
name: push
description: Push the current octo-lite branch and create or update the linked GitHub PR using the target repo's conventions and validation evidence.
---

# Push

Use this skill when an implementer needs to publish branch changes and open or
update the PR for shaped Linear-first work or an explicitly GitHub-first issue.

## Prerequisites

- `gh auth status` succeeds.
- `git remote -v` shows the intended target repo.
- Target repo validation has run or the failure is recorded with rationale.

## Workflow

1. Identify the branch with `git branch --show-current`.
2. Verify the branch matches the target repo convention. For Linear-first work,
   prefer the repo's existing branch convention or
   `octo-lite/<linear-key-lower>-<slug>`; for GitHub-first work, use
   `octo-lite/<issue-number>-<slug>`.
3. Push with upstream tracking: `git push -u origin HEAD`.
4. If push is rejected because the branch is stale, use the `pull` skill, rerun
   validation, then push again.
5. Use `--force-with-lease` only when history was deliberately rewritten.
6. Create or update exactly one PR for the issue.
7. PR title should match the Linear issue or GitHub issue title unless the
   target repo has a stronger convention.
8. For Linear-first work, PR body must start with `Tracks <LINEAR-KEY>` and
   include `## Summary` and `## Validation`. For GitHub-first work, PR body
   must start with `Closes #<issue-number>` and include those sections.
9. Return the PR URL.

Do not merge. Surface auth, permissions, branch protection, and workflow errors
directly instead of changing remotes or bypassing policy.
