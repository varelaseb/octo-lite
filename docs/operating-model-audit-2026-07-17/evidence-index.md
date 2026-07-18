# Evidence Index

## Scope and counting notes

The audit window is 2026-07-10 through 2026-07-17 UTC. Counts are corpus
signals, not statistically independent incidents: resumed sessions, forked
workers, and copied prompts can repeat the same history. Live session counts
also grew while this audit was running; the packet uses the subaudit snapshot
where a count is tied to detailed classification.

No raw session transcript, secret, environment value, or credential is copied
into this packet.

## Corpus snapshots

| Corpus | Snapshot |
| --- | ---: |
| Top-level Claude sessions | 147 |
| Claude subordinate/workflow JSONLs | 1,057 |
| Total recent Claude project JSONLs | 1,204 |
| Claude workflow records | 153 |
| Codex rollout files in classified snapshot | 482 |
| Claude memory Markdown files inspected | 101 |
| Linear `TUR` issues created in the window | 228 |

## Versioned contract evidence

| Claim | Primary evidence |
| --- | --- |
| Issue shaper requires exact story sections, debate, docs grill, spec/ADR update, walkthrough, and approval | `skills/octo-lite-issue-shaper/SKILL.md` |
| Loop refuses self-written/ungrilled scope and requires exact roles/re-review | `skills/octo-lite-loop/SKILL.md` |
| TDD requires intended red, green, and durable evidence | `skills/tdd/SKILL.md` |
| Only shaper, implementer, and reviewer are wired | `role-skills.json` |
| Workflow accepts placeholder story/empty AC and performs only one fix without re-review | `workflows/octo-loop-qa.js:90-129` |
| Workflow hard-codes Turbo config and Markdown specs | `workflows/octo-loop-qa.js:26-50` |
| Generic loop unconditionally starts with `gh issue view` | `skills/octo-lite-loop/SKILL.md:37` |
| Generic loop says eight states, lists nine, and calls Backlog dead while defining it | `skills/octo-lite-loop/SKILL.md:254-260` |
| Meta launcher bypasses its mandated spawn helper | `skills/launch-meta-operator/scripts/launch-meta-operator.sh:220-245` |
| Child spawn helper does not enforce auto mode | `skills/herdr-comms/assets/herdr-spawn:18-41` |
| Delivery helper has no ID/ack/completion state | `skills/herdr-comms/assets/herdr-say:34-40` |
| Installed workflow is designed as a copied/re-written file | `README.md:52-55` |

## Codex/OpenAI evidence

The classified Codex snapshot contained 482 rollouts, approximately 838 MB.

| Signal | Result |
| --- | ---: |
| Scratch-directory relays | 172 |
| Scratch relays that later read any `AGENTS.md` | 143 |
| Scratch relays that never read one | 29 |
| Scratch prompts explicitly asking to read `AGENTS.md` | 3 |
| Scratch prompts naming `role-skills.json` or a role profile | 0 |
| Session files hard-coding `spec/domains/*.md` | 280 |
| Files recording missing-Markdown-spec errors | at least 16 |
| Files with real Linear CLI calls | 234 |
| Scratch relays that queried Linear | 87 / 172 |
| Files loading the issue-shaper skill | 23 |
| Files loading the TDD skill | 133 |
| Files posting red/green evidence in a PR comment | 22 |
| Files putting red/green evidence in a PR body/edit | 27 |
| Files with self-review `request changes` errors | 82 |
| Files with `Cannot find module` bootstrap failures | 109 |

Representative rollouts:

- Scratch relay missing automatic repo law, PR #344 / `TUR-394`:
  `/root/.codex/sessions/2026/07/16/rollout-2026-07-16T05-46-21-019f6976-3240-7f12-b1c3-ad1b76c60e7d.jsonl`.
- Stale Markdown-spec routing, `TUR-383`:
  `/root/.codex/sessions/2026/07/16/rollout-2026-07-16T02-30-15-019f68c2-a8f8-7101-a2a7-4d79fa59b522.jsonl`.
- Self-review identity failure, PR #390 / `TUR-422`:
  `/root/.codex/sessions/2026/07/17/rollout-2026-07-17T18-59-38-019f7172-d494-77f0-93e7-7de6fbeb529a.jsonl`.
- Missing reviewer dependency:
  `/root/.codex/sessions/2026/07/13/rollout-2026-07-13T07-23-40-019f5a5c-3648-7fa3-b5b1-37c276ee0c3c.jsonl`.
- Visible/input-buffer collision:
  `/root/.codex/sessions/2026/07/11/rollout-2026-07-11T08-29-34-019f504b-d1c1-7570-ad9e-409398c76d0b.jsonl`.
- Long control-state drift and repeated operator correction:
  `/root/.codex/sessions/2026/07/10/rollout-2026-07-10T07-34-57-019f4af3-78bc-7a41-9851-8a52b9805d92.jsonl`.

## Claude evidence

Top-level session incidence signals:

| Pattern | Sessions | Mentions |
| --- | ---: | ---: |
| Timeout, killed, or stopped work | 53 | 161 |
| PR retarget/base-policing | 25 | 133 |
| Review gaps/re-review/unfixed findings | 30 | 94 |
| 529/provider overload | 14 | 51 |
| TUI unsubmitted/ghost/input-line failures | 8 | 46 |
| Cross-lane or foreign-session replies | 12 | 14 |

Key session references:

- Shared-checkout contamination:
  `/root/.claude/projects/-root-turbo-main-wt/c332b985-10b6-410b-8ac3-59a03360d195.jsonl`.
- `resume --last` attached `TUR-423` to the wrong lane:
  `/root/.claude/projects/-root-turbo-main-wt/2c724244-1ce3-41fc-8f7f-246d3fc37a0e.jsonl`.
- A global process match waited on a foreign lane for roughly 1h46m and the
  `TUR-401` fix/review/QA chain failed:
  `/root/.claude/projects/-root-turbo-main-wt/6a086bc4-9b70-4367-be07-4e82c25a2cf4.jsonl`.
- Raw send plus separate Enter/modal incident:
  `/root/.claude/projects/-root/1a1c71de-ab13-40a7-b395-25b5b260ede2.jsonl`.
- Input glued onto an active command:
  `/root/.claude/projects/-root-turbo-main-wt/17d0ee7c-45ad-44ea-9e77-d29f53b89d72.jsonl`.
- Ghost suggestion mistaken for human input:
  session `2c724244…`.
- User's “wrong place” correction after cross-context input collision:
  `/root/.claude/projects/-root/13bae03f-f3c6-45f3-a9c5-a9355df801fa.jsonl`.
- `TUR-429` stale-session auth incident: the resumed Codex subagent first
  returned `401 token_revoked / refresh_token_invalidated` at
  `2026-07-17T21:15:11.384755Z`, but the lane did not surface it until
  `22:17:39.730Z`. The meta-operator declared a fleet outage at `22:17:59.731Z`
  without a fresh probe. A fresh Sol execution returned `AUTH-OK` at
  `22:19:56.294Z`; the edits made before the stale resume failed were already
  complete on disk. Workflow record:
  `/root/.claude/projects/-root-turbo-main-wt/9bdba04d-afd9-4942-862d-c4cca5fe5d1f/workflows/wf_8120dfff-05c.json`.
  First failing subagent:
  `/root/.claude/projects/-root-turbo-main-wt/9bdba04d-afd9-4942-862d-c4cca5fe5d1f/subagents/workflows/wf_8120dfff-05c/agent-ada687912d72e158a.jsonl`.

The July 13 `herdr-say` mandate appears to have reduced the exact raw-send plus
bare-Enter pattern. The remaining control gap is that exit 0 still proves only
an attempted injection/submission, not recipient acknowledgment or action.

The `TUR-429` incident adds a separate observability gap: workflow-internal
auth errors are not surfaced at occurrence, and orchestrators have no required
fresh-session probe or scope-classification step before declaring provider or
fleet outages.

`TUR-437` reproduced the backend acceptance-surface gap on 2026-07-17. The
backend-only workflow intentionally returned no QA artifact or verdict. The
lane moved the issue to `Awaiting Accept` and the meta-operator declared it
ready after base/HEAD/review/validation/CI checks, but the served `review.html`
had no `TUR-437` card. The gallery watcher noticed the Linear-state change and
coalesced a rebuild, but the in-flight build had started at `22:28:59` before
the state transition. Recent successful whole-gallery builds recorded in
`/root/codex-uploads/.rebuild.log` took 404, 471, 484, 725, 826, 857, 910, and
1,538 seconds, with additional `-9`/`-15` terminations. The operator accepted
and PR #397 merged before the manually reconstructed verdict, `gate.md`, and
uploads link were complete. Primary live artifacts:
`/root/.local/state/octo-lite/qa-artifacts/TUR-437/round-1/qa-verdict.json`,
`/root/.local/state/octo-lite/qa-artifacts/TUR-437/gate.md`, and
`/root/codex-uploads/.serve-evidence.log`.

The immediate performance hotfix and red/green benchmark are recorded in
`evidence-builder-performance.md`. It reduced a normal rebuild to 20.079
seconds by eliminating archive-wide serial Linear detail calls and running
independent GitHub reads concurrently. This resolves the acute latency but not
the source-ownership or full-rebuild architectural gap.

## Memory evidence

| Finding | Evidence |
| --- | --- |
| Memory says not to store live status | `/root/.claude/projects/-root/memory/no-status-snapshots-in-memory.md` |
| Turbo memory stores extensive current issue/PR/run state anyway | `/root/.claude/projects/-root-Turbo-Outreach-staging/memory/tf-remigrate-and-admin-wiring-issues.md` and `posthog-v1-stream-state.md` |
| State model is internally contradictory | `/root/.claude/projects/-root-Turbo-Outreach-staging/memory/MEMORY.md` and `linear-six-state-workflow.md` |
| Review/fix/QA head gap was already known | `/root/.claude/projects/-root-Turbo-Outreach-staging/memory/octo-loop-qa-review-gap.md` |

## Linear and PR sample evidence

The Linear corpus query covered all `TUR` issues created from 2026-07-10
through 2026-07-17. The detailed compliance sample was `TUR-418` through
`TUR-438`; exact results live in
`role-linear-spec-tdd-compliance.md`.

The PR TDD evidence sample covered Turbo-Outreach PRs #388 through #396. None
of their combined public bodies, comments, and reviews contained durable TDD,
test-first, intended-red, or red/green evidence at the audit snapshot. This is
a durable-evidence claim, not a claim about the private order of edits.

## Workspace and instruction evidence

- `/root/Turbo-Outreach-staging` was dirty, on `_review_tur50`, with its upstream
  gone and 826 commits behind `origin/main`, while the workflow used it as repo,
  dependency, environment, and worktree origin.
- The registered Turbo worktree fleet contained five `AGENTS.md` variants.
- The source and installed `octo-loop-qa.js` files had different SHA-256 hashes;
  the installed copy contained a PR-base patch missing from source.
- The installed and source `herdr-spawn` helper hashes matched, confirming that
  the child auto-mode gap is in the canonical helper rather than local drift.
- A command-level scan found 51 weekly Claude `herdr-spawn` lines; 11 omitted an
  explicit auto/bypass permission mode.
