# Agent Instructions

## Repository Role

This repository is the source for the local octo-lite Codex personalization.
octo-lite installs into the user's Codex profile and operates on separate
target repositories.

## Durable Sources

- `README.md` explains the product and install shape.
- `role-skills.json` records the Issue Shaper, implementer, and reviewer skill
  mapping.
- `profile/AGENTS.md` is the global user-profile guidance to install.
- `skills/` contains reusable octo-lite skills and their bundled templates.
- `agents/` contains custom subagent profiles: Codex `*.toml` and the parallel
  Claude Code `*.md` (Markdown + YAML frontmatter) profiles. Keep both in sync
  when changing implementer/reviewer behavior.
- `workflows/` contains Claude Code Workflow scripts (currently
  `octo-loop-qa.js`, the loop-with-QA implementation); their conventions
  blocks are per-target configuration.

## Target Spec Format Capability

- A target repo may opt into native spec-chat documents by declaring the exact
  signal `Spec format: spec-chat` in its `AGENTS.md`.
- An absent signal, or `Spec format: markdown`, keeps Markdown specs as the
  backward-compatible default.
- In a spec-chat repo, `*.spec.html` files are canonical under the repo's
  declared spec root, with one sentence per prose line, stable `data-anchor`
  attributes on every meaningful block, and pretty-printed semantic-island
  JSON for visual state.
- The shared `.viz/` runtime and vendored libraries are committed for offline
  rendering, `*.review/` spools are ignored, and shaping includes the
  serve/annotate/hand-off/drain/edit/reply review loop before readiness.
- Agents must follow the target repo's declared format and must not generate a
  Markdown counterpart for a spec-chat canonical document.

## Local Workflow

- Do not add a CLI, daemon, polling service, or runtime stack for v1.
- Keep templates inside the relevant skill `assets/` directory.
- Keep always-loaded guidance in `profile/AGENTS.md` short.
- Do not copy octo-lite skills, agents, or templates into target repos.

## Validation

- Check Markdown and TOML syntax after edits.
- Verify skill symlinks point at this source repo when installing locally.

## Conventions

- Prefer concise skills with progressive disclosure.
- Use target repo `AGENTS.md` files only for target repo conventions.
- Use skills for reusable octo-lite procedure.
