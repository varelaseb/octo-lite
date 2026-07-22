# Target Promotion Map

Status: shaping handoff. This file preserves approved target-specific decisions
that must be promoted in the target repo, not implemented in generic octo-lite.

## Turbo-Outreach

Shape these together against current Turbo instructions, specs, code, Linear,
and the evolving Turbo draft PR:

- Decisions 17 and 36: move the TopicFinder evidence and operator-site
  implementation into Turbo. Routine issue-card publication must be
  incremental and complete within 5 seconds; explicit full-archive repair must
  complete within 60 seconds. Keep the exact-card and linked-artifact readback.
- Decisions 34 and 46 through 49: the TopicFinder-dev operation view becomes
  primary only when it accurately shows outcomes, hierarchy, owners, gates,
  dependencies, blockers, and next actions. Fable remains its sole reconciled
  writer; hosted views remain read-only.
- Decisions 37 through 40: Turbo has no product dependency on octo-lite,
  spec-chat, or the control panel. Root `AGENTS.md` contains only Turbo law and
  is the sole target instruction source. Root `CLAUDE.md` is a tracked relative
  symlink. Worktree-local instructions remain versioned with each branch.
- Decision 57: Turbo bootstrap and cache details stay in Turbo, including its
  nested npm lockfiles, native download caches, compatible browser downloads,
  and worktree-local mutable dependencies.
- Decisions 72 and 74 through 81: promote the TopicFinder user-story and QA
  contracts into Turbo specs. The initial catalog path is
  `spec/domains/topicfinder-user-stories.spec.html`; IDs use
  `TF-US-<origin Linear number>-<two-digit ordinal>`. Curate the legacy catalog,
  remove the Notion mirror, and keep QA evidence separate from story truth.
- Decisions 90 and 92: evidence hosting remains Turbo operations. Publish no
  known secrets, perform the exact served-card readback, add no new
  access/redaction/retention subsystem, and create no control-panel adapter
  unless a later shaped non-derivable presentation need proves one necessary.
- Deployment lifecycle mapping (TUR-443 cutover, `linear-deployment-target-owned`):
  the concrete meaning of `In Staging` (merged to `main`), `In Preprod`
  (verified candidate at zero percent live traffic), and `Live` (operator
  traffic shift) is Turbo's own Linear state mapping. Promote it into Turbo
  `AGENTS.md` or spec; generic octo-lite defines only that such states are
  durable, operator-authorized, and evidence-backed.

## Boundary

The generic operating-model spec may define the reusable contract behind these
features. It must not contain Turbo paths, credentials, fixture identities,
hosts, lifecycle presentation, story prefixes, or product behavior. This map
does not authorize Turbo code, tracker, or deployment mutations.
