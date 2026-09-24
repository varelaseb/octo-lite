# Agent Instructions

## Repository Role

This repository is the source for the local octo-lite Codex personalization.
octo-lite installs into the user's Codex profile and operates on separate
target repositories.

## Design Frame (operator ruling 2026-07-27)

Every octo-lite issue STARTS from the elegant-lean frame: build the smallest
mechanism that makes the failure visible or the behavior correct. No machinery
for hypothetical edge cases - an edge case earns code only with a failing test
that proves real cost. Prefer deletion over guard. One bound over layered
bounds. Derivation over declaration. Recorded-not-implemented is the default
disposition for reviewer findings beyond the elegant minimum. Precedents:
gh#28 (-380 lines deletion-only), gh#34 (envelope deleted, not simplified),
gh#31 (one age bound, dropped lock/TOCTOU armor).

## Worker lifecycle

Every worker starts one concrete `/goal` before work, naming its narrow
outcome, source or ticket pointers, and observable done condition. Keep it
active while working. A worker that is blocked, stalled, interrupted, or unable
to finish messages its owner or operator before idling with current state,
evidence, blocker, and concrete next need. It does not report completion or go
idle without that handoff. A transient failure or normal human gate is
reported, but is not itself a blocked goal.

## Durable Sources

- `README.md` explains the product and install shape.
- `agents/*.md` are the sole canonical role contracts. They are hand-written,
  and pin no model so each CLI applies its own default.
- `skills/implement-spec/` owns post-shaping delivery. Its Herdr workers run
  under the `implementer` and `code-reviewer` contracts, which declare the
  skills available to them, so no prose list has to be kept in step by hand.
- `profile/AGENTS.md` is the global user-profile guidance to install.
- `skills/` contains reusable octo-lite skills authored locally and their
  bundled templates.
- `Skillfile`, `Skillfile.lock`, and `.skillfile/patches/` are the skillfile
  (eljulians/skillfile) manifest, lockfile, and pinned patches that manage
  skills per ADR 0002: they pin tdd and authoritative Spec Chat skills at exact
  SHAs and carry the single tdd seam-gate patch across upstream updates.
- `agents/` contains the hand-written Claude role contracts plus the managed
  skillfile install target `agents/skills/`. Never hand-edit `agents/skills/`; it is
  materialized by skillfile from the `Skillfile`, and `scripts/install-octo-lite
  --check` verifies every managed skill there resolves identically from
  `.claude/skills` and `.codex/skills`. OpenAI roles use a direct `codex exec`
  relay with no generated Codex custom-agent file.

## Target Spec Format Capability

- Spec format: spec-chat
- Canonical spec paths: spec/domains/operating-model.spec.html, spec/domains/delivery-lifecycle.spec.html, spec/domains/role-runtime.spec.html, spec/domains/operator-control.spec.html
- Canonical ADR paths: spec/adr/0001-operating-model-boundaries.spec.html, spec/adr/0002-tdd-skill-vendoring.spec.html, spec/adr/0003-drop-loop-trust-root.spec.html, spec/adr/0004-derive-delivery-entry.spec.html, spec/adr/0005-herdr-ticket-graph-delivery.spec.html
- octo-lite's own canonical specifications and ADRs use native spec-chat
  `*.spec.html` documents under `spec/`.
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
- Install profile, role contracts, skills, and helpers by symlink.

## Validation

- Check Markdown and TOML syntax after edits.
- Run `python3 -m unittest tests.test_herdr` after changing the Herdr wrappers.
- Verify skill symlinks point at this source repo when installing locally.
- Run `scripts/install-octo-lite --check` after installed-surface changes.

## Conventions

- Prefer concise skills with progressive disclosure.
- Use target repo `AGENTS.md` files only for target repo conventions.
- Use skills for reusable octo-lite procedure.
