# octo-lite

octo-lite is a local Codex personalization for GitHub-issue-driven product
work. It is not a service, daemon, CLI, or project dependency. It installs into
the user's Codex profile and operates on target repositories through normal
GitHub issues, pull requests, specs, ADRs, and repo instructions.

## What It Provides

- A user-facing Issue Shaper workflow for turning ideas or rough GitHub issues
  into clear, spec-backed work.
- A native Codex subagent loop for implementer and reviewer passes.
- Templates bundled inside skills, not copied as top-level target repo
  template files.
- Minimal target repo initialization for `README.md`, `AGENTS.md`, `spec/`,
  and `.octo-lite/drafts/` gitignore coverage.

## Installed Surfaces

Source-controlled files live in this repo. The local Codex profile should point
at them with symlinks:

```text
~/.codex/AGENTS.md -> profile/AGENTS.md
~/.codex/skills/octo-lite-issue-shaper -> skills/octo-lite-issue-shaper
~/.codex/skills/octo-lite-loop -> skills/octo-lite-loop
~/.agents/skills/octo-lite-issue-shaper -> skills/octo-lite-issue-shaper
~/.agents/skills/octo-lite-loop -> skills/octo-lite-loop
~/.codex/agents/octo-lite-implementer.toml -> agents/octo-lite-implementer.toml
~/.codex/agents/octo-lite-reviewer.toml -> agents/octo-lite-reviewer.toml
```

`~/.codex/skills` is supported by the current local profile. `$HOME/.agents/skills`
is the documented user-skill location in the current Codex manual, so both are
installed.

## Workflow

Issue shaping is the most important step.

```text
idea or rough GitHub issue
  -> .octo-lite/drafts/<slug>.md
  -> specs/ADRs/repo init where needed
  -> operator approval
  -> GitHub issue body
  -> octo-lite:ready
  -> implementer/reviewer loop
  -> human PR review
```

During shaping, the draft file is the canonical working artifact. After the
approved draft is written to GitHub and labeled `octo-lite:ready`, the GitHub
issue becomes canonical and the local draft is deleted.

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

## GitHub

octo-lite uses the GitHub CLI. Issue Shaper verifies GitHub auth and repo
identity early with:

```bash
gh auth status
gh repo view
```

GitHub mutations happen only after explicit operator approval.

