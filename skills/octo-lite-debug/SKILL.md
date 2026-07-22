---
name: octo-lite-debug
description: Diagnose octo-lite workflow blockers in local Codex, git, gh, validation, branch, and PR state.
---

# octo-lite Debug

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Use this skill when an octo-lite implementer/reviewer pass is stuck, validation
cannot run, GitHub operations fail, branch state is confusing, or review cannot
proceed from the available durable context.

Diagnose the local repo, GitHub CLI, git history, PR state, specs, and role
handoff artifacts.

## Checks

Start with the smallest relevant set:

```sh
gh auth status
gh repo view
git status --short --branch
git remote -v
git branch --show-current
gh issue view <issue> --json number,title,labels,state,url
gh pr view <pr> --json number,title,state,url,headRefName,baseRefName,reviews,comments
```

Then inspect:

- Target repo `AGENTS.md` and validation commands.
- Relevant specs under `spec/` and ADRs under `spec/adr/`.
- The PR body and latest `## octo-lite handoff` comment.
- Reviewer findings and unresolved requested changes.
- Validation output, package manager state, env/config availability, and
  failing test logs.

## Outcomes

Return one of:

- `resolved`: the blocker was diagnosed and the next action is clear.
- `ambiguous`: Issue Shaper/operator clarification is required.
- `blocked`: auth, permissions, env/config, or unavailable tooling prevents
  progress.

Always report the exact command or durable source that established the result.
