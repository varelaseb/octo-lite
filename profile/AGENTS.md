# octo-lite

## Local Codex Workflow

- octo-lite is the default local Codex workflow for GitHub-issue-driven product
  work.
- Use `$octo-lite-issue-shaper` for new ideas, rough GitHub issues, repo
  initialization, spec/ADR shaping, and readiness approval.
- Use `$octo-lite-loop` for the native implementer/reviewer subagent loop after
  a GitHub issue has the `octo-lite:ready` label.
- Role-specific skill wiring lives in the octo-lite source repo
  `role-skills.json`; agents should use only the skills configured for their
  current role.
- Target repo `AGENTS.md` files define repo-specific conventions and override
  generic octo-lite defaults for that repo's code, commands, architecture, and
  validation.
- octo-lite workflow mechanics live in the installed octo-lite skills and
  agents. Do not copy octo-lite product skills, agents, or templates into target
  repos.
