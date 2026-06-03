---
name: pull
description: Pull latest origin/main into the current local branch and resolve merge conflicts with minimal, intention-preserving edits.
---

# Pull

Use this skill when an octo-lite branch must be updated from the remote default
branch or when push is rejected because the branch is stale.

## Workflow

1. Verify the working tree is clean or commit/stash intended work first.
2. Enable rerere locally:
   - `git config rerere.enabled true`
   - `git config rerere.autoupdate true`
3. Fetch latest refs with `git fetch origin`.
4. Pull the remote copy of the current branch with `git pull --ff-only origin $(git branch --show-current)` when it exists.
5. Merge the default branch, usually `origin/main`, using `git -c merge.conflictstyle=zdiff3 merge origin/main`.
6. Resolve conflicts by understanding both sides before editing.
7. Run target repo validation required by `AGENTS.md`, specs, and acceptance
   criteria.
8. Summarize conflicts, assumptions, and validation.

Ask only when a conflict requires a product or architecture decision that local
code, specs, ADRs, and issue context cannot answer.

