---
name: octo-lite-loop
description: Run the native octo-lite implementer-reviewer subagent loop for a GitHub issue that has octo-lite:ready. Use when the user asks to execute shaped work, spawn implementer/reviewer agents, or run the implementer -> reviewer -> implementer cycle.
---

# octo-lite Loop

Use this skill after an issue has been shaped and labeled `octo-lite:ready`.
This skill orchestrates Codex subagents. It is not a daemon, CLI, polling loop,
or background service.

## Inputs

- GitHub issue number or URL.
- Optional existing PR number or URL.
- Optional max cycle override. Default max is 3 reviewer fix cycles.

## Required Preflight

Run:

```bash
gh auth status
gh repo view
gh issue view <issue> --json number,title,labels,url,body
```

Refuse to proceed unless the issue has `octo-lite:ready`, unless the operator
explicitly overrides this guard.

Read target repo `AGENTS.md`, `spec/index.md`, relevant specs, and ADRs before
spawning agents when they are needed to build the initial task prompt.

## Agent Roles

Spawn these custom agents when available:

- `octo-lite-implementer`
- `octo-lite-reviewer`

If the custom agent names are unavailable in the current Codex surface, spawn a
`worker` for implementation and a `worker` or `default` agent for review, and
include the corresponding role instructions from the installed agent profile in
the prompt.

## Loop

Use at most 3 reviewer fix cycles by default.

1. Spawn `octo-lite-implementer` with the issue number, repo path, branch
   convention, PR convention, and any latest reviewer findings.
2. Wait for the implementer to finish.
3. Require the implementer to report PR URL/number, branch, HEAD, validation,
   and whether any ambiguity blocked implementation.
4. If implementation is blocked by ambiguity, env/config, or conflicting
   durable sources, stop and route back to `$octo-lite-issue-shaper`.
5. Spawn `octo-lite-reviewer` with the issue number, PR number, repo path, and
   expected review outcome format.
6. Wait for the reviewer to finish.
7. Require the reviewer to post a real GitHub PR review and return one of:
   `blocking`, `clear`, or `ambiguous`.
8. If `clear`, stop and report that the PR is ready for human review.
9. If `ambiguous`, stop and route back to `$octo-lite-issue-shaper`.
10. If `blocking`, send the blocking findings back to the implementer and start
    the next cycle.

Do not merge. Do not approve as the human reviewer.

## Durable Loop Surface

Use the PR as the durable loop surface:

- Implementer opens or updates one PR linked to the issue.
- Implementer posts a compact `## octo-lite handoff` PR comment.
- Reviewer posts a GitHub PR review directly.
- Fix cycles update the same branch and PR.

Use `assets/handoff.md` for the implementer handoff shape.

## Stop Conditions

Stop and summarize when:

- reviewer reports no blocking findings;
- 3 reviewer fix cycles have completed;
- implementer or reviewer finds ambiguous requirements;
- env/config needed for acceptance is missing;
- issue, specs, ADRs, or repo instructions conflict;
- validation cannot run and the missing validation affects acceptance.

Final summary should include:

- issue link;
- PR link;
- latest reviewer outcome;
- validation status;
- reason for stopping;
- recommended next action.

## Boundaries

- Do not create new GitHub workflow labels.
- Do not create extra PRs for the same issue.
- Do not continue past ambiguity by guessing.
- Do not run issue shaping inside the loop except to recommend returning to the
  Issue Shaper.

