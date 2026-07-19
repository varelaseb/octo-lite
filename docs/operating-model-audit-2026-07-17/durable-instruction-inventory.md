# Durable instruction inventory

Snapshot: live tracked files in octo-lite and Turbo TUR-450 worktrees on 2026-07-19.

Purpose: exact review map for agent instructions, role and skill loading, prompts, specs, durable operating prose, historical context, wiring, and adjacent tests.

## Boundary

Included:

- Tracked files that can direct an agent, model, operator, reviewer, or implementation.
- Canonical behavior sources and durable context likely to influence work.
- Code that builds prompts or selects instruction text.
- Machine files that select roles, skills, prompt versions, or instruction-loading paths.
- Tests that directly exercise those contracts.

Excluded:

- Product source with only ordinary UI copy.
- Pure customer, prospect, marketing seed, email, fixture, snapshot, or generated report content.
- Vendored renderer code and binaries.
- Ignored local drafts, review spools, traces, runtime state, and evidence output.
- Tests unrelated to prompt or operating-model conformance.

Example exclusions in Turbo:

- spike/output/danmartell-report.md is generated prospect content.
- tools/prospect-report/scripts/seed-for-articles.js is customer-facing seed copy.
- tools/prospect-report/email-templates/** is customer email copy.
- tools/prospect-report/test/snapshots/email-renders/** is rendered customer copy.
- tools/prospect-report/test-fixtures/topicfinder-pinned-source/** is product fixture source.

Runtime-injected examples are included even when they resemble customer copy. tools/prospect-report/eval/golden-samples.txt enters the quality-judge prompt.

Paths below are repository-relative.

## Authority and precedence

### octo-lite

1. Provider and product system policy.
2. Installed profile/AGENTS.md for generic workflow.
3. roles.toml for runtime, model, mode, session, tools, and skill mapping.
4. roles/*.md for canonical role prose.
5. Required skill SKILL.md files for role procedure.
6. Target root AGENTS.md for target-specific commands, architecture, validation, and deployment.
7. Linear for issue identity and high-level scope. Canonical spec for detailed behavior. One draft PR for implementation and review state.

Generated agents/* adapters have no independent authority. They must match roles.toml and roles/*.md.

### Turbo

1. Root AGENTS.md is the sole standing Turbo-specific agent instruction source.
2. Root CLAUDE.md is the same bytes through a relative symlink.
3. .cursor/rules/*.mdc are optional pointers only.
4. Linear owns issue identity and high-level decisions.
5. spec/*.spec.html owns detailed product and technical behavior.
6. For TopicFinder presentation, the presentation spec precedes DESIGN.md. AGENTS.md records the exact rule.
7. GitHub PRs carry implementation, validation, and exact-head review state.
8. Runtime product prompts come from the active prompt_versions database row. A prompts/*.txt file is only the first-run seed unless no active row exists.

Historical plans, audits, worklogs, and reports are context. They never override current Linear, spec, AGENTS.md, or active prompt state.

## Counts

Counts are distinct paths inside each repository.

| Repository | Category | Count |
| --- | --- | ---: |
| octo-lite | Standing authority and loading | 4 |
| octo-lite | Canonical role contracts | 8 |
| octo-lite | Generated launch adapters | 16 |
| octo-lite | Skill contracts | 17 |
| octo-lite | Skill discovery descriptors | 4 |
| octo-lite | Skill assets, templates, and launch prompts | 14 |
| octo-lite | Canonical specs | 2 |
| octo-lite | Product docs and audit context | 13 |
| octo-lite | Runtime wiring and prompt builders | 14 |
| octo-lite | Conformance tests and fixtures | 14 |
| octo-lite | Total | 106 |
| Turbo | Standing authority and loading | 5 |
| Turbo | Canonical specs | 24 |
| Turbo | Repo skill and skill lock | 2 |
| Turbo | Prompt seeds and runtime prompt corpora | 22 |
| Turbo | Prompt builders and composers | 26 |
| Turbo | Migration-pinned prompt copies | 2 |
| Turbo | Prompt and instruction wiring | 6 |
| Turbo | Current operating and reference docs | 33 |
| Turbo | Historical audit and decision docs | 11 |
| Turbo | Historical implementation plans | 120 |
| Turbo | Prompt-adjacent conformance tests | 24 |
| Turbo | Evidence operating-model tests | 7 |
| Turbo | Total | 282 |

## octo-lite inventory

### Standing authority and loading, 4

- AGENTS.md
- CLAUDE.md
- profile/AGENTS.md
- roles.toml

CLAUDE.md is a tracked relative symlink to AGENTS.md.

### Canonical role contracts, 8

- roles/code-reviewer.md
- roles/implementer.md
- roles/meta-operator.md
- roles/orchestrator.md
- roles/qa-capture.md
- roles/qa-reviewer.md
- roles/reconciler.md
- roles/shaping-reviewer.md

### Generated launch adapters, 16

- agents/code-reviewer.md
- agents/code-reviewer.toml
- agents/implementer.md
- agents/implementer.toml
- agents/meta-operator.md
- agents/meta-operator.toml
- agents/orchestrator.md
- agents/orchestrator.toml
- agents/qa-capture.md
- agents/qa-capture.toml
- agents/qa-reviewer.md
- agents/qa-reviewer.toml
- agents/reconciler.md
- agents/reconciler.toml
- agents/shaping-reviewer.md
- agents/shaping-reviewer.toml

### Skill contracts, 17

- skills/commit/SKILL.md
- skills/frontend-design/SKILL.md
- skills/grill-with-docs/SKILL.md
- skills/herdr-comms/SKILL.md
- skills/launch-meta-operator/SKILL.md
- skills/nodejs/SKILL.md
- skills/octo-lite-debug/SKILL.md
- skills/octo-lite-github/SKILL.md
- skills/octo-lite-issue-shaper/SKILL.md
- skills/octo-lite-loop/SKILL.md
- skills/pnpm-patching/SKILL.md
- skills/pnpm/SKILL.md
- skills/pull/SKILL.md
- skills/push/SKILL.md
- skills/python/SKILL.md
- skills/tdd/SKILL.md
- skills/typescript/SKILL.md

### Skill discovery descriptors, 4

- skills/grill-with-docs/agents/openai.yaml
- skills/launch-meta-operator/agents/openai.yaml
- skills/octo-lite-issue-shaper/agents/openai.yaml
- skills/octo-lite-loop/agents/openai.yaml

### Skill assets, templates, and launch prompts, 14

- skills/herdr-comms/assets/herdr-ack
- skills/herdr-comms/assets/herdr-drain
- skills/herdr-comms/assets/herdr-say
- skills/herdr-comms/assets/herdr-spawn
- skills/herdr-comms/assets/operator-say
- skills/launch-meta-operator/scripts/launch-meta-operator.sh
- skills/octo-lite-issue-shaper/assets/adr.md
- skills/octo-lite-issue-shaper/assets/github-issue.md
- skills/octo-lite-issue-shaper/assets/gitignore-entry.txt
- skills/octo-lite-issue-shaper/assets/readme.md
- skills/octo-lite-issue-shaper/assets/repo-agents.md
- skills/octo-lite-issue-shaper/assets/spec-domain.md
- skills/octo-lite-issue-shaper/assets/spec-index.md
- skills/octo-lite-loop/assets/handoff.md

### Canonical specs, 2

- spec/index.spec.html
- spec/domains/operating-model.spec.html

### Product docs and audit context, 13

- README.md
- docs/operating-model-audit-2026-07-17/README.md
- docs/operating-model-audit-2026-07-17/durable-instruction-inventory.md
- docs/operating-model-audit-2026-07-17/evidence-builder-performance.md
- docs/operating-model-audit-2026-07-17/evidence-index.md
- docs/operating-model-audit-2026-07-17/failure-catalog.md
- docs/operating-model-audit-2026-07-17/gap-backlog.md
- docs/operating-model-audit-2026-07-17/instruction-and-prompt-architecture.md
- docs/operating-model-audit-2026-07-17/operating-model-draft.md
- docs/operating-model-audit-2026-07-17/optimal-model-grill.md
- docs/operating-model-audit-2026-07-17/role-linear-spec-tdd-compliance.md
- docs/operating-model-audit-2026-07-17/symphony-assessment.md
- docs/operating-model-audit-2026-07-17/target-promotion-map.md

### Runtime wiring and prompt builders, 14

- .github/workflows/role-contracts.yml
- octo_lite/__init__.py
- octo_lite/launch.py
- octo_lite/runtime.py
- scripts/check-traces
- scripts/install-octo-lite
- scripts/octo-control
- scripts/octo-launch
- scripts/octo-probe
- scripts/operator-sweep
- scripts/operator-timer
- workflows/lib/gates.mjs
- workflows/lib/role_resolver.py
- workflows/octo-loop-qa.js

### Conformance tests and fixtures, 14

- tests/fixtures/traces/failure.jsonl
- tests/fixtures/traces/happy.jsonl
- tests/fixtures/traces/invalid.jsonl
- tests/fixtures/traces/retry.jsonl
- tests/gates.test.mjs
- tests/test_conformance.py
- tests/test_herdr.py
- tests/test_launch.py
- tests/test_launch_meta_operator.py
- tests/test_operator_control.py
- tests/test_provider_probe.py
- tests/test_role_resolver.py
- tests/test_runtime.py
- tests/test_trace_contract.py

## Turbo inventory

### Standing authority and loading, 5

- AGENTS.md
- CLAUDE.md
- .claude/settings.json
- .cursor/rules/commits.mdc
- .cursor/rules/worklog.mdc

CLAUDE.md is a tracked relative symlink to AGENTS.md. Cursor files declare alwaysApply false and point to AGENTS.md.

### Canonical specs, 24

- spec/index.spec.html
- spec/adr/0001-topicfinder-typescript-island.spec.html
- spec/adr/0002-analytics-layering-ledger-plus-posthog.spec.html
- spec/adr/0003-spec-chat-html-canonical-specs.spec.html
- spec/adr/0004-niche-anchored-topic-taxonomy.spec.html
- spec/domains/account-credential-recovery.spec.html
- spec/domains/devops-cicd-runtime-config.spec.html
- spec/domains/hosting-domains.spec.html
- spec/domains/topicfinder-active-scope.spec.html
- spec/domains/topicfinder-alpha.spec.html
- spec/domains/topicfinder-content-migration.spec.html
- spec/domains/topicfinder-create-workspace.spec.html
- spec/domains/topicfinder-delivery-operations.spec.html
- spec/domains/topicfinder-discovery.spec.html
- spec/domains/topicfinder-media-storage.spec.html
- spec/domains/topicfinder-observability-evals.spec.html
- spec/domains/topicfinder-presentation.spec.html
- spec/domains/topicfinder-script-authoring.spec.html
- spec/domains/topicfinder-script-management.spec.html
- spec/domains/topicfinder-staging-readiness.spec.html
- spec/domains/topicfinder-topic-taxonomy.spec.html
- spec/domains/topicfinder-user-stories.spec.html
- spec/domains/topicfinder-waitlist.spec.html
- spec/domains/video-performance-history.spec.html

### Repo skill and skill lock, 2

- tools/prospect-report/.agents/skills/neon-postgres/SKILL.md
- tools/prospect-report/skills-lock.json

### Prompt seeds and runtime prompt corpora, 22

- tools/prospect-report/eval/golden-samples.txt
- tools/prospect-report/prompts/category-assignment.txt
- tools/prospect-report/prompts/category-interpretation.txt
- tools/prospect-report/prompts/custom-topic-brief.txt
- tools/prospect-report/prompts/location-inference.txt
- tools/prospect-report/prompts/reel-analysis.txt
- tools/prospect-report/prompts/reel-remix-brief.txt
- tools/prospect-report/prompts/script-generation.txt
- tools/prospect-report/prompts/script-quality-judge.txt
- tools/prospect-report/prompts/source-dna.txt
- tools/prospect-report/prompts/topicfinder-critic.txt
- tools/prospect-report/prompts/topicfinder-hooks.txt
- tools/prospect-report/prompts/topicfinder-onboarding-scan.txt
- tools/prospect-report/prompts/topicfinder-rewrite.txt
- tools/prospect-report/prompts/topicfinder-section.txt
- tools/prospect-report/prompts/transcript-enrichment.txt
- tools/prospect-report/prompts/v1-content-brief.txt
- tools/prospect-report/prompts/v1-creator-profile.txt
- tools/prospect-report/prompts/v1-signal-match.txt
- tools/prospect-report/prompts/v2-content-brief.txt
- tools/prospect-report/prompts/voice-generate.txt
- tools/prospect-report/prompts/voice-suggestions.txt

### Prompt builders and composers, 26

- tools/prospect-report/pipeline/src/backfill-voice-blueprints.js
- tools/prospect-report/pipeline/src/category-runner.js
- tools/prospect-report/pipeline/src/shared/discoveryFormatClassifier.js
- tools/prospect-report/pipeline/src/shared/discoveryStyleClassifier.js
- tools/prospect-report/pipeline/src/shared/prompts.js
- tools/prospect-report/pipeline/src/shared/script-generator.js
- tools/prospect-report/pipeline/src/shared/sourceDnaGate.js
- tools/prospect-report/pipeline/src/shared/transcribe-reels.js
- tools/prospect-report/pipeline/src/stages/2-profile.js
- tools/prospect-report/pipeline/src/stages/4-match.js
- tools/prospect-report/pipeline/src/stages/5-briefs.js
- tools/prospect-report/services/reportPipeline.js
- tools/prospect-report/src/routes/creators.js
- tools/prospect-report/src/routes/recommendations.js
- tools/prospect-report/src/routes/voice.js
- tools/prospect-report/src/services/customBriefGeneration.js
- tools/prospect-report/src/services/promptTester.js
- tools/prospect-report/src/services/reelRemixService.js
- tools/prospect-report/src/services/scriptGenerationContent.js
- tools/prospect-report/src/services/scriptQualityJudge.js
- tools/prospect-report/src/services/scriptRunner.js
- tools/prospect-report/src/services/sourceDna.js
- tools/prospect-report/src/services/topicSearch.js
- tools/prospect-report/src/services/topicfinderOnboardingScanService.js
- tools/prospect-report/src/services/topicfinderScriptAiClient.js
- tools/prospect-report/src/services/topicfinderScriptBuilderService.js

### Migration-pinned prompt copies, 2

- tools/prospect-report/db/migrations/047_activate_script_generation_v2_prompt.sql
- tools/prospect-report/db/migrations/106_activate_topicfinder_hooks_v2.sql

### Prompt and instruction wiring, 6

- .github/workflows/pr-checks.yml
- tools/prospect-report/db/migrations/001_initial_schema.sql
- tools/prospect-report/db/migrations/021_prompt_versioning.sql
- tools/prospect-report/db/migrations/030_prompt_versions_single_active.sql
- tools/prospect-report/db/queries/prompt_versions.js
- tools/prospect-report/src/routes/prompts.js

### Current operating and reference docs, 33

- DESIGN.md
- README.md
- docs/app-overview.md
- docs/backfill-runbook.md
- docs/ci-cd.md
- docs/deploy-production.md
- docs/marketing-features.md
- docs/pipeline-stages.md
- docs/qa-test-account-matrix.md
- docs/reconciliation/README.md
- docs/roadmap.html
- docs/roadmap.md
- docs/unattended-ops-auth.md
- docs/user-flip-runbook.md
- docs/worklog.md
- tools/evidence-site/EVIDENCE-REVIEW-ACTIONS.md
- tools/evidence-site/README.md
- tools/prospect-report/BRIEF_STRUCTURE.md
- tools/prospect-report/COMMANDS.md
- tools/prospect-report/README.md
- tools/prospect-report/client/README.md
- tools/prospect-report/client/TESTING.md
- tools/prospect-report/client/src/features/topicfinder/presentation/ORIGIN.md
- tools/prospect-report/client/src/features/topicfinder/presentation/parity/fixtures/README.md
- tools/prospect-report/client/src/status-messages/README.md
- tools/prospect-report/docs/API.md
- tools/prospect-report/docs/GCLOUD.md
- tools/prospect-report/docs/TOPICFINDER_CLIENT_ENABLEMENT.md
- tools/prospect-report/docs/TOPICFINDER_LOCAL_DEV.md
- tools/prospect-report/docs/postmark-templates.md
- tools/prospect-report/docs/tf-corpus-quality-ops.md
- tools/prospect-report/docs/waitlist-cutover-runbook.md
- tools/prospect-report/scripts/admin-scope-proof/README.md

### Historical audit and decision docs, 11

- docs/architecture/remediation-plan-2026-04-13.md
- docs/architecture/system-audit-2026-04-13.md
- docs/architecture/topicfinder-integration-plan.md
- docs/spec-chat-conversion-report.md
- docs/spec-chat-round-trip.md
- docs/tf-delta-audit-2026-07.md
- spec/audits/tf-supabase-discover-audit-20260703.md
- spike/output/go-nogo-summary.md
- spike/output/outlier-annotations-legend.txt
- tools/prospect-report/docs/projects/HELP_CENTER.md
- tools/prospect-report/docs/topicfinder-topic-taxonomy-analysis.md

### Historical implementation plans, 120

Projects, 12:

- Projects/Turbo-Video-Sprint-5-Plan.md
- Projects/feedback-improvements-plan.md
- Projects/prospect-report-pipeline-sprint.md
- Projects/prospect-report-sprint-3.md
- Projects/prospect-report-sprint-4.md
- Projects/sprint-0-linear-tasks.md
- Projects/sprint-1-prospect-report-tool.md
- Projects/sprint-2-pipeline-improvements.md
- Projects/sprint-4-shared-signal-pool.md
- Projects/sprint-5b-creator-page-tabs.md
- Projects/sprint-5c-share-model.md
- Projects/sprint-5d-feedback-infrastructure.md

Root plans, 106:

- plans/2026-04-30-test-coverage-review.md
- plans/category-schema-v2.md
- plans/handle-voice-setup-dialog.md
- plans/teleprompter-recording-quality.md
- plans/teleprompter-scroll-speed-controls.md
- plans/thin-pages-scale-readiness-refactor.md
- plans/topicfinder-completion-handoff-alignment.md
- plans/topicfinder-first-run-discovery.md
- plans/topicfinder-home-route.md
- plans/topicfinder-onboarding-orientation.md
- plans/topicfinder-preprod-bug-fixes.md
- plans/topicfinder-route-shell-progress-backbone.md
- plans/topicfinder-scripts-surface.md
- plans/tur-135-client-config-degradation.md
- plans/tur-209-shell-navigation.md
- plans/tur-210-evidence-policy-closure.md
- plans/tur-210-presentation-foundation.md
- plans/tur-212-discovery-fix.md
- plans/tur-212-launch-correction.md
- plans/tur-212-media-exec-safety.md
- plans/tur-212-media-sharding.md
- plans/tur-212-neon-branch-guard.md
- plans/tur-212-onboarding-fix.md
- plans/tur-212-preprod-live-regressions.md
- plans/tur-212-rehearsal-guard.md
- plans/tur-213-visual-completion-pass.md
- plans/tur-214-onboarding-presentation.md
- plans/tur-217-213-core-journey.md
- plans/tur-217-visual-completion.md
- plans/tur-222-build-speed.md
- plans/tur-223-preprod-corpus-reuse.md
- plans/tur-224-launch-polish.md
- plans/tur-225-remove-preprod.md
- plans/tur-226-topicfinder-corpus-enrichment.md
- plans/tur-231-spec-chat-adoption.md
- plans/tur-234-topic-taxonomy.md
- plans/tur-235-video-metric-observation-ledger.md
- plans/tur-238-launch-hotfix-a.md
- plans/tur-239-launch-hotfix-b.md
- plans/tur-244-corpus-quality.md
- plans/tur-245-swipe-deck-performance.md
- plans/tur-246-brand-blue-token.md
- plans/tur-247-email-templates.md
- plans/tur-248-staging-backfill-clamp.md
- plans/tur-254-brand-host-polish.md
- plans/tur-255-onboarding-scan-failure-ux.md
- plans/tur-256-video-polish.md
- plans/tur-258-corpus-viz.md
- plans/tur-260-global-onboarding-gate.md
- plans/tur-261-sweep-robustness.md
- plans/tur-264-tf-host-token-routes.md
- plans/tur-268-tf-invite-accept-experience.md
- plans/tur-275-scan-latency-stuckstate.md
- plans/tur-277-discover-onboarding-ux.md
- plans/tur-278-onboarding-record-gate.md
- plans/tur-282-native-password-reset.md
- plans/tur-289-handle-claim-recovery.md
- plans/tur-292-brand-host-root-login-redirect.md
- plans/tur-296-accept-invite-native.md
- plans/tur-315-taxonomy-sweep-incremental.md
- plans/tur-318-onboarding-topic-supply-gate.md
- plans/tur-334-cloud-run-jobs.md
- plans/tur-337-client-scope-picker.md
- plans/tur-339-scope-query-user-keying.md
- plans/tur-346-switched-scope-thumbnails.md
- plans/tur-350-stepnav-below-content.md
- plans/tur-351-tf-hover-cursor.md
- plans/tur-352-discover-infinite-scroll.md
- plans/tur-357-admin-onboarding-exempt.md
- plans/tur-358-legacy-home.md
- plans/tur-360-legacy-visual-fidelity.md
- plans/tur-361-boot-path-refreeze.md
- plans/tur-362-admin-reset-ttl.md
- plans/tur-364-onboarding-nav-normalization.md
- plans/tur-366-reels-active-scope.md
- plans/tur-370-record-from-final-review.md
- plans/tur-375-topic-filter-multiselect.md
- plans/tur-376-logo-discover.md
- plans/tur-377-hook-screen-ux.md
- plans/tur-379-follower-counts.md
- plans/tur-394-multimember-silent-join.md
- plans/tur-395-client-creator-switcher.md
- plans/tur-397-azure-sweep.md
- plans/tur-398-scripts-drag-hint.md
- plans/tur-403-posthog-creator-host-stamp.md
- plans/tur-404-posthog-activation-events.md
- plans/tur-405-posthog-scripted-insights.md
- plans/tur-406-explorer-folders.md
- plans/tur-408-heit-hook-visibility.md
- plans/tur-411-seeded-topic-selection.md
- plans/tur-412-one-shot-generation.md
- plans/tur-413-topic-typeahead.md
- plans/tur-414-script-review-cleanup.md
- plans/tur-416-posthog-dau-wau-insights.md
- plans/tur-417-record-funnel-trap.md
- plans/tur-418-no-shared-brief-write.md
- plans/tur-421-enrichment-admin-surface.md
- plans/tur-422-discover-typeahead-sentinels.md
- plans/tur-427-hook-yours-card-fix.md
- plans/tur-429-folder-containment.md
- plans/tur-432-server-forward-posthog.md
- plans/tur-433-api-events-ingest.md
- plans/tur-436-deploy-hygiene.md
- plans/tur-437-discovery-search-logging.md
- plans/tur378-saved-videos-revamp.md
- plans/tur401-supply-funnel-drill.md

Nested tool plans, 2:

- tools/prospect-report/plans/tur-177-nocreator-onboarding.md
- tools/prospect-report/plans/tur-318-reversal-full-list-gated-first.md

### Prompt-adjacent conformance tests, 24

- tools/prospect-report/test/classificationCatchup.test.js
- tools/prospect-report/test/creatorsRoutes.test.js
- tools/prospect-report/test/creatorsRoutesPhase4.test.js
- tools/prospect-report/test/customBriefGeneration.test.js
- tools/prospect-report/test/customScriptAndCache.test.js
- tools/prospect-report/test/discoveryFormatClassifier.test.js
- tools/prospect-report/test/observability.test.js
- tools/prospect-report/test/profileStage.test.js
- tools/prospect-report/test/reelRemixService.test.js
- tools/prospect-report/test/retryFailedClassificationsDrain.test.js
- tools/prospect-report/test/scriptGeneratorVoice.test.js
- tools/prospect-report/test/scriptQualityJudge.test.js
- tools/prospect-report/test/scriptRunner.test.js
- tools/prospect-report/test/sourceDna.test.js
- tools/prospect-report/test/sourceReadyAnalysis.test.js
- tools/prospect-report/test/sourceReadyBackfill.test.js
- tools/prospect-report/test/topicSearch.test.js
- tools/prospect-report/test/topicSearchService.test.js
- tools/prospect-report/test/topicfinderHookPromptActivation.test.js
- tools/prospect-report/test/topicfinderOnboardingScanService.test.js
- tools/prospect-report/test/topicfinderScriptAiClient.test.js
- tools/prospect-report/test/topicfinderScriptBuilderService.test.js
- tools/prospect-report/test/transcribeMissingReels.test.js
- tools/prospect-report/test/tur148Metering.test.js

### Evidence operating-model tests, 7

- tools/evidence-site/test/byteIdentity.test.js
- tools/evidence-site/test/deployState.test.js
- tools/evidence-site/test/operatingModelContracts.test.js
- tools/evidence-site/test/pathDecoding.test.js
- tools/evidence-site/test/publishEvidenceCard.test.js
- tools/evidence-site/test/specSourceGuard.test.js
- tools/evidence-site/test/syncProcedure.test.js

## Ambiguity and drift flags

1. Turbo production prompt text is not fully reviewable from git. The active prompt_versions database row wins after first seed. Review active rows and hashes for any production prompt audit.
2. Turbo has 21 seed prompts, 2 migration-pinned copies, and 26 embedded composers. Copies can diverge. No single checked-in prompt manifest binds seed, active version, composer, model, and tests.
3. Turbo prompt tests are uneven. Deterministic tests cover many schemas and call shapes. They do not replace fresh-model evaluations for judgment quality.
4. Turbo keeps 120 historical plan files. They are useful context but easy for an agent to mistake for current scope. AGENTS.md now explicitly lowers their authority: tracked plans, project notes, audits, worklogs, memories, and session logs are dated context only and never override AGENTS.md, current Linear state, canonical specs or ADRs, or the active PR.
5. octo-lite roles/*.md are canonical while agents/* duplicates their content as generated adapters. Resolver checks are the drift guard. Direct adapter edits remain a failure mode.
6. octo-lite install correctness is external state. Repository tests can validate link targets and manifests, but each installed Claude or Codex profile still needs scripts/install-octo-lite --check.
7. Provider model aliases and availability are external. roles.toml pins intent, not provider reachability.
8. Audit docs in both repos can preserve rejected or superseded proposals. Treat them as evidence and context, never standing instruction.
9. Turbo deliberately does not depend on octo-lite. Generic role and skill loading therefore depends on the operator's installed octo-lite profile. Turbo AGENTS.md supplies only repo-specific policy.
10. A prior revision recomputed every octo-lite count and path against its final tree. `octo_lite/__init__.py` was a real prior omission from Runtime wiring and prompt builders; it was included from that point on. The Turbo worktree at `/root/Turbo-Outreach-tur450-operating-model` (`29b929e`) had a different agent's concurrent uncommitted work at that validation time; that pass spot-checked canonical specs, historical plans, and evidence tests by exact count and left the Turbo section unchanged since all three matched.
11. This revision reconciled both repos against pushed Turbo worktree HEAD `83b6b507b6ff1490576947388bd9682e784e2847` (Turbo fix pass 4, superseding note 10's `29b929e`) and this fix pass's final octo-lite tree. Turbo fix pass 4 added `tools/evidence-site/test/deployState.test.js` and `tools/evidence-site/test/pathDecoding.test.js`, raising Evidence operating-model tests from 5 to 7 and the Turbo total from 280 to 282; no other Turbo category changed and the 120 historical plan count is exact. This fix pass added `tests/test_launch_meta_operator.py` to octo-lite Conformance tests and fixtures, raising it from 13 to 14 and the octo-lite total from 108 to 109. Every listed path in both repositories was verified to exist at its exact head, with no duplicates and category sums matching declared totals.
12. This revision (PR 6 fix pass 4) reconciled the pinned Turbo head to `c0c27be9f3661a0007aeef49e9dd06f663b1e4ee` (tree `c85d86616fbad1b6302484b566b520ecfd2fae75`), the exact commit named by the operator as final for this inventory. Diffed against note 11's `83b6b507` pin: zero files added or removed, only content edits inside five already-listed `tools/evidence-site/*` files; every Turbo category and the 282 total are unchanged. octo-lite removed the separately persistent `issue-shaper` role and its two generated adapters (`roles/issue-shaper.md`, `agents/issue-shaper.md`, `agents/issue-shaper.toml`): the one issue orchestrator now resolves the `octo-lite-issue-shaper` skill conditionally in shaping mode instead of a second persistent role, per the one-dedicated-Opus contract. Canonical role contracts moved 9 to 8, Generated launch adapters 18 to 16, octo-lite total 109 to 106. Every listed path in both repositories was verified to exist at its exact head, with no duplicates and category sums matching declared totals.

## Review focus

1. Read octo-lite profile/AGENTS.md, roles.toml, all roles/*.md, then the required SKILL.md files.
2. Compare every generated agents/* adapter through the role resolver. Do not review it as a second source.
3. Read Turbo AGENTS.md through the CLAUDE.md symlink path once.
4. Review Turbo canonical specs before historical plans.
5. For product prompt changes, inspect the seed, composer, migration copy if any, active database row, model selection, and exact tests together.
6. Treat missing fresh-model red and green evidence as a prompt TDD gap, even when deterministic CI is green.
