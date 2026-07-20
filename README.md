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
  issues into clear, spec-backed work, plus an independent fresh shaping
  review before readiness.
- A native Claude Workflow delivery loop for fresh implementer, code-reviewer,
  QA-capture, and QA-reviewer passes, with Codex relays for shaping and review
  roles.
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
~/.codex/octo-lite/roles.toml -> roles.toml
~/.codex/octo-lite/roles/<role>.md -> roles/<role>.md
~/.codex/skills/<skill> -> skills/<skill>
~/.agents/skills/<skill> -> skills/<skill>
```

Codex has no generated custom-agent adapter. Per Decision 109 every worker role
runs as a Claude Workflow subagent of the owning session, and an OpenAI-backed
role pass runs inside a Claude relay subagent that executes one explicit
`codex exec` relay, carrying the canonical role contract as the exec prompt and
returning the codex findings verbatim; see ADR 0001.

The Claude Code surface reuses the same source repo. Skills share the SKILL.md
format and symlink directly. Claude uses generated Markdown + YAML frontmatter
subagent adapters, which install the same way:

```text
~/.claude/CLAUDE.md -> profile/AGENTS.md
~/.claude/octo-lite/roles.toml -> roles.toml
~/.claude/octo-lite/roles/<role>.md -> roles/<role>.md
~/.claude/octo-lite/adapters/<role>.md -> agents/<role>.md
~/.claude/skills/<skill> -> skills/<skill>
~/.claude/workflows/octo-loop-qa.js -> workflows/octo-loop-qa.js
```

`workflows/octo-loop-qa.js` is the target-neutral native Claude Workflow.
Target repos supply their own instructions and evidence publication helpers.
The workflow, roles, mappings, skills, and profile always install by symlink.

Install or verify all links:

```bash
scripts/install-octo-lite
scripts/install-octo-lite --check
```

`~/.codex/skills` is supported by the current local profile. `$HOME/.agents/skills`
is the documented user-skill location in the current Codex manual, so both are
installed.

Install every directory under `skills/`. `roles.toml` defines required and
conditional skills for all eight roles. `roles/<role>.md` is the sole prose
contract. `agents/` is generated and must match the resolver exactly.

Validate or regenerate after role changes:

```bash
python3 workflows/lib/role_resolver.py check
python3 workflows/lib/role_resolver.py generate
python3 -m unittest tests/test_role_resolver.py
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
  -> evolving draft PR
  -> fresh shaping review (clear verdict required)
  -> implement with spec-derived red, green, refactor
  -> fresh code review, fresh fix when blocking
  -> QA capture and fresh QA review when user-facing
  -> operator acceptance
  -> merge and lifecycle transition
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

octo-lite itself declares `Spec format: spec-chat`; its canonical domain specs
and ADRs live under `spec/` as `*.spec.html`.

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
