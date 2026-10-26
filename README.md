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
~/.{codex,claude}/agents/<role>.md      -> agents/<role>.md
~/.{codex,claude,agents}/skills/<skill> -> skills/<skill>, agents/skills/tdd
~/.local/bin/<helper>                   -> scripts/*, skills/herdr-comms/assets/*
```

Each peer links only what it owns (ADR-004); Spec Chat's installer links its
own skills.

Install or verify all links:

```bash
scripts/install-octo-lite
scripts/install-octo-lite --check
scripts/install-octo-lite --after-pull
```

`--check` also reports version floors for each tool octo-lite uses at runtime
(git, herdr, jq, gh, and at least one of claude or codex), printing ok,
missing, or too old with the upgrade source.

`--after-pull` installs as a plain run does, asking nothing, then verifies as
`--check` does. It exits non-zero when the verification fails, the last line of
stderr naming the first failed check. A host runs it after fast-forwarding this
clone: every install publishes it as `after_pull` in the
[onboarding file](#onboarding).

`--project CHECKOUT` also links the skills a project declares on its
`AGENTS.md` [`Repo skills:` line](#repo-skills) from that checkout, the
project's live main clone, into the same skill directories, each under its
directory name. An existing link at one of those names that resolves anywhere
else is stale: install and `--check` warn, naming the link and where it points,
leave it untouched, and continue. Nothing repairs it.

## Onboarding

```bash
scripts/install-octo-lite --onboard
octo-lite-start --cwd WORKTREE [--name LANE] [--runtime claude|codex|pi] [--operating-model FILE]
```

`--onboard` installs the links, then asks whether agents may push, open pull
requests, and file issues, each defaulting to no. Every install publishes
octo-lite's one onboarding file,
`${XDG_STATE_HOME:-~/.local/state}/octo-lite/onboarding.toml`: `status`
(`pending` until consent is kept, then `done`), `doc`, a link here, and the
kept answers as a `[consent]` table (see
[consent](skills/octo-lite-github/SKILL.md#consent)). Kept answers are not asked
again, and a plain install keeps them; delete the file to answer afresh.
`after_pull` is the argument list a host runs, with no shell, after
fast-forwarding this clone: `install-octo-lite --after-pull` from this clone
with the `--prefix` and `--project` the last install ran with. Every install
rewrites it, so the step a host runs next is the pulled clone's.

`octo-lite-start`, installed on `PATH`, creates a Herdr space labelled with the
lane name and starts the lane's orchestrator alone in it at the worktree,
printing `workspace=` beside `pane=`. It is the published start command; callers never use
`herdr-spawn` inside the clone.

`octo-lite-state`, also on `PATH`, prints the caller's Herdr session state
directory: `${XDG_STATE_HOME:-~/.local/state}/octo-lite` in the default session,
its `sessions/<name>` in a named one. Lane records, their hand-off logs, and
`operator.toml` live there, so each session sees only its own lanes; the
onboarding file stays box-wide.

With Herdr on the box, every install registers `herdr-wake` as Spec Chat's
`wake` provider by writing
`${XDG_STATE_HOME:-~/.local/state}/spec-chat/hosting/default/providers/wake.toml`
atomically, in the format Spec Chat owns. `herdr-wake check OWNER` exits 0 when
the pane resolves; `herdr-wake send OWNER ARTIFACT MESSAGE` exits 0 sent, 75
deferred, other failed. It also finds Herdr in `~/.local/bin`, so a review
service started by any launcher (user service, cron, shell) wakes owners, and a
failed check or send writes a one-line reason to stderr: Herdr not found, owner
pane not found in its session, or Herdr's error. Install never replaces a `wake.toml` it did not
write, and `--undo` deletes that file only while it is unchanged.

`--prefix PATH` is the one root for everything install writes: links, and the
state and config above under `PATH/.local/state` and `PATH/.config`, ignoring
`XDG_*`.

`agents/*.md` are hand-written role contracts. Workers load them from
`herdr-spawn --role ROLE -- claude|codex|pi`: Claude through `--agent ROLE`,
Codex as developer instructions, pi as an appended system prompt. Spawn bare; the brief follows by `herdr-say`.
`herdr-close TAB` tears a worker down, detached processes
included; `herdr-close SPACE` tears down a lane space the lane owns alone, else
the operator closes only the owner's tab. The meta-operator is a persistent Herdr pane started with `herdr-spawn
--role meta-operator -- claude`; there is no supervised sweep.

## Workflow

Shape first, then implement the accepted spec.

```text
idea or rough Linear/GitHub issue
  -> $spec-chat-shape
  -> accepted spec + spec issue
  -> $implement-spec files blocking-linked tickets
  -> parallel Herdr implementers on ready tickets
  -> serialized Herdr integrators onto one PR branch
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

### Repo skills

Target repos declare their own skills in root `AGENTS.md` with one line,
`Repo skills:` followed by comma-separated repository-relative paths to skill
directories, for example `Repo skills: skills/ui-rules, tools/house-style`.
`install-octo-lite --project CHECKOUT` links them; implementers load the ones
their ticket needs by name. octo-lite names no project skill.

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
