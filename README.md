# octo-lite

octo-lite is a local Codex personalization for Linear-first product and
development work, with GitHub used primarily for pull requests and code review.
It is not a service, daemon, CLI, or project dependency. It installs into the
user's Codex profile and operates on target repositories through normal Linear
issues, GitHub pull requests, specs, ADRs, and repo instructions.

This repository contains general-purpose development workflows and tooling
maintained as reusable personal/background IP. It is not specific to any one
client, product, or engagement.

## What It Provides

- A user-facing Issue Shaper workflow for turning ideas or rough Linear/GitHub
  issues into clear, spec-backed work.
- A native Codex subagent loop for implementer and reviewer passes.
- A cross-client meta-operator launcher for consolidating and supervising
  long-running Herdr workstreams.
- Templates bundled inside skills, not copied as top-level target repo
  template files.
- Minimal target repo initialization for `README.md`, `AGENTS.md`, `spec/`,
  and `.octo-lite/drafts/` gitignore coverage.

## Installed Surfaces

Source-controlled files live in this repo. The local Codex profile should point
at them with symlinks:

```text
~/.codex/AGENTS.md -> profile/AGENTS.md
~/.codex/octo-lite-role-skills.json -> role-skills.json
~/.codex/skills/<skill> -> skills/<skill>
~/.agents/skills/<skill> -> skills/<skill>
~/.codex/agents/octo-lite-implementer.toml -> agents/octo-lite-implementer.toml
~/.codex/agents/octo-lite-reviewer.toml -> agents/octo-lite-reviewer.toml
```

The Claude Code surface reuses the same source repo. Skills share the SKILL.md
format and symlink directly, but subagents use a different format
(Markdown + YAML frontmatter instead of Codex TOML), so the repo carries
parallel `agents/*.md` profiles that install the same way:

```text
~/.claude/CLAUDE.md -> profile/AGENTS.md
~/.claude/skills/<skill> -> skills/<skill>
~/.claude/agents/octo-lite-implementer.md -> agents/octo-lite-implementer.md
~/.claude/agents/octo-lite-reviewer.md -> agents/octo-lite-reviewer.md
~/.claude/workflows/octo-loop-qa.js (copy of workflows/octo-loop-qa.js)
```

`workflows/octo-loop-qa.js` is the Claude Code Workflow implementation of the
loop with QA stages (see `skills/octo-lite-loop/SKILL.md`). Its CONVENTIONS
and QA_APP blocks are per-target configuration (currently Turbo-Outreach), so
copy it rather than symlinking and rewrite those blocks per target repo.

`~/.codex/skills` is supported by the current local profile. `$HOME/.agents/skills`
is the documented user-skill location in the current Codex manual, so both are
installed.

Install every directory under `skills/`; the role-specific mapping in
`role-skills.json` determines which skills each workflow role should load.

Current octo-lite role skills:

```text
Issue Shaper:
  octo-lite-issue-shaper, grill-with-docs, octo-lite-github

Implementer:
  commit, frontend-design, octo-lite-github, nodejs, pnpm, pnpm-patching,
  pull, push, python, tdd, typescript

Reviewer:
  octo-lite-debug, octo-lite-github, pull
```

Operator utility skills are not role-bound. Invoke `launch-meta-operator`
explicitly when a separate Claude or Codex session should inventory and take
responsibility for active Herdr workstreams.

## Workflow

Issue shaping is the most important step.

```text
idea or rough Linear/GitHub issue
  -> .octo-lite/drafts/<slug>.md
  -> specs/ADRs/repo init where needed
  -> operator approval
  -> Linear issue/spec updates, or GitHub issue body for GitHub-first work
  -> ready status/approval
  -> implementer/reviewer loop
  -> human PR review
```

During shaping, the draft file is the canonical working artifact. In
Linear-first repos, Linear becomes canonical after finalization and specs remain
the durable behavior source. In GitHub-first repos, the approved draft may be
written to GitHub and labeled `octo-lite:ready`.

Issue Shaper uses `$grill-with-docs` during shaping to preserve the useful
thoroughness octo-lite needs: docs-first clarification, one question at a time
with a recommendation, acceptance-criteria classification, ADR checkpoint,
spec/doc updates, and explicit ready-gate review.

## Target Repositories

octo-lite product files are not copied into target repos. A target repo may
contain ordinary project artifacts created or maintained by octo-lite:

```text
README.md
AGENTS.md
spec/index.md
spec/domains/
spec/adr/
.octo-lite/drafts/   # ignored
```

`README.md` is human/product-facing. `AGENTS.md` is Codex-facing and records
repo-specific conventions that can diverge from the initial octo-lite scaffold.

### Spec format capability

Target repos declare their canonical spec format in `AGENTS.md` with the exact
signal `Spec format: spec-chat`. Repos without that signal, or with
`Spec format: markdown`, continue to use the existing Markdown layout and
templates unchanged.

Spec-chat repos keep `*.spec.html` as the only canonical spec source under the
declared `spec/` root. Each document uses one sentence per prose line, a stable
`data-anchor` on every meaningful block, and pretty-printed JSON semantic
islands for charts or other visual state. They commit a shared `.viz/` runtime
with vendored libraries so rendering works offline, ignore `*.review/` event
spools, and run the browser review loop during shaping: serve, annotate, hand
off, drain, edit, and reply.

The shaper, grill, loop, and role profiles read this signal before touching a
spec. They preserve the repo's declared format, and spec-chat work never
regenerates a Markdown counterpart.

## Trackers And GitHub

Linear is the default source of truth for issue identity, product/dev scope,
status, and dependencies. GitHub issues are used only for GitHub-first repos or
explicit operator requests.

octo-lite uses the GitHub CLI for pull requests and code review. Issue Shaper or
Implementer verifies GitHub auth and repo identity when GitHub operations are
needed:

```bash
gh auth status
gh repo view
```

GitHub issue mutations happen only after explicit operator approval.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
