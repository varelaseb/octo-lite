---
name: commit
description: Create a well-formed git commit from current changes using session history, issue scope, and repo conventions; use when asked to commit or finalize staged octo-lite work.
---

# Commit

Use this skill when the operator asks to commit durable shaping artifacts or
implementation changes.

## Inputs

- Session history for intent and rationale.
- GitHub issue or draft context for scope.
- `git status`, `git diff`, and `git diff --staged`.
- Target repo commit conventions from `AGENTS.md`, README, or contributing
  docs.

## Steps

1. Inspect the working tree and staged changes.
2. Stage only intended files, including new files.
3. Check for unrelated changes, generated artifacts, logs, temp files, secrets,
   or `.octo-lite/drafts/` files that should not be committed.
4. Choose a concise conventional subject when the repo has no stronger rule.
5. Write a body that records summary, rationale, and validation.
6. Use a file-backed commit message with `git commit -F <file>`.

## Commit Shape

```text
<type>(<scope>): <short summary>

Summary:
- <what changed>

Rationale:
- <why it changed>

Validation:
- <command or "not run (reason)">
```

Add `Co-authored-by: Codex <codex@openai.com>` unless the operator requests a
different identity.

