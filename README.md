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

- Spec Chat shaping that produces an accepted canonical spec and its issue.
- Explicit `$implement-spec` delivery that files the dependency-linked ticket
  graph after acceptance, fills the ready ticket frontier with
  parallel Herdr workers, integrates onto one branch, runs review, and
  leaves one PR ready for human review.
- Templates bundled inside skills, not copied as top-level target repo
  template files.

## Installed Surfaces

Source-controlled files live in this repo. `scripts/install-octo-lite` links
them into the Claude and Codex profiles:

```text
~/.codex/AGENTS.md, ~/.claude/CLAUDE.md -> annotateanything/AGENTS.md
~/.{codex,claude}/agents/<role>.md      -> agents/<role>.md
~/.{codex,claude,agents}/skills/<skill> -> skills/<skill>, agents/skills/tdd
~/.{codex,claude}/skills/spec-chat-*    -> sibling spec-chat clone
~/.local/bin/<helper>                   -> scripts/*, skills/herdr-comms/assets/*
```

Install or verify all links:

```bash
scripts/install-octo-lite
scripts/install-octo-lite --check
```

`agents/*.md` are hand-written role contracts. Workers load them: Claude
through `--agent ROLE`, Codex as developer instructions from `herdr-spawn
--role ROLE`. `herdr-close TAB` tears a worker down, detached processes
included. The meta-operator is a persistent Herdr pane started with `herdr-spawn
--role meta-operator`; there is no supervised sweep.

## Workflow

Shape first, then implement the accepted spec.

```text
idea or rough Linear/GitHub issue
  -> $spec-chat-shape
  -> accepted spec + spec issue
  -> $implement-spec files blocking-linked tickets
  -> parallel Herdr implementers on ready tickets
  -> serialized Herdr mergers onto one PR branch
  -> independent review + consolidated fixes; bounded repair of remaining defects
  -> PR ready for human review
```

Linear remains current for issue and ticket identity, scope, dependencies, and
state. Specs own detailed behavior. Worker messages point to those sources
instead of copying them.

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

octo-lite itself declares `Spec format: spec-chat`; its canonical spec
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

The shaper and worker skills read this signal before touching a spec. They
preserve the repo's declared format, and spec-chat work never regenerates a
Markdown counterpart.

## Trackers And GitHub

Linear is the default source of truth for issue identity, product/dev scope,
status, and dependencies. GitHub issues are used only for GitHub-first repos or
explicit operator requests.

octo-lite uses the GitHub CLI for pull requests and code review. The shaper or
implementer verifies GitHub auth and repo identity when GitHub operations are
needed:

```bash
gh auth status
gh repo view
```

GitHub issue mutations happen only after explicit operator approval.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
