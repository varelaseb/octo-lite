# Agent Instructions

## Repository Role

This repository is the source for the local octo-lite Codex personalization.
octo-lite installs into the user's Codex profile and operates on separate
target repositories.

## Durable Sources

- `README.md` explains the product and install shape.
- `profile/AGENTS.md` is the global user-profile guidance to install.
- `skills/` contains reusable octo-lite skills and their bundled templates.
- `agents/` contains custom Codex subagent profiles.

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

