# octo-lite

## Local Codex Workflow

- octo-lite is the default local Codex workflow for Linear-first,
  Linear-tracked product and development work.
- Treat Linear as the primary source of truth for dev scope, status, and issue
  identity. Start from the relevant Linear issue, such as `TUR-50`, before
  using GitHub issues, local drafts, or specs as supporting artifacts.
- For Linear-tracked work, do not create, update, label, or depend on GitHub
  issues unless the operator explicitly asks for a GitHub issue operation.
  Historical GitHub mirror issues are read-only context, not active scope.
- Use specs for durable behavior and GitHub PRs for branch review, code
  discussion, and merge readiness. PR bodies should reference Linear issue keys
  directly, for example `Tracks TUR-50`, instead of closing GitHub issue mirrors.
- Use `$octo-lite-issue-shaper` for new ideas, rough Linear/GitHub issues,
  repo initialization, spec/ADR shaping, and readiness approval.
- Use `$octo-lite-loop` for the native implementer/reviewer subagent loop after
  a Linear issue or explicitly requested GitHub issue has been shaped and marked
  ready by the operator.
- Role-specific skill wiring lives in the octo-lite source repo
  `role-skills.json`; agents should use only the skills configured for their
  current role.
- Target repo `AGENTS.md` files define repo-specific conventions and override
  generic octo-lite defaults for that repo's code, commands, architecture, and
  validation.
- Before touching specs, follow the target repo's declared format signal:
  `Spec format: spec-chat` selects canonical `*.spec.html` documents and the
  browser review loop; an absent signal or `Spec format: markdown` keeps the
  Markdown default.
- octo-lite workflow mechanics live in the installed octo-lite skills and
  agents. Do not copy octo-lite product skills, agents, or templates into target
  repos.

## TopicFinder Notion

- Use Notion Todos for non-dev work tracking. Do not treat Notion Todos as the
  source of truth for product/dev implementation scope or status.
- For TopicFinder Notion work, use Product -> Dev Section as the primary
  operating page:
  `https://app.notion.com/p/Dev-Section-1196e88b1e6482caa8cb815f150df2f7`.
- This page is a child of Product:
  `https://app.notion.com/p/Product-38b6e88b1e6480409bbad1564ed419b5`.
- Product -> Dev Section contains the migrated TopicFinder Home index, the
  Roadmap page, Todos database, Meeting Notes database, and Golden Samples.
  Keep its Map and Recent sections updated when changing TopicFinder Notion.
- When reviewing a TopicFinder Notion meeting note or transcript, fetch the
  actual page content with `ntn pages get <page-id>` before updating specs,
  Linear, or GitHub. The installed Notion CLI uses `ntn pages get`; there is no
  top-level `ntn get` command. If Markdown output is truncated, rerun with
  `ntn pages get <page-id> --json`.
