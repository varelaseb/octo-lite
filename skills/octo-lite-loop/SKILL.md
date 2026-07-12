---
name: octo-lite-loop
description: Run the native octo-lite implementer-reviewer subagent loop for shaped Linear-first work or an explicitly GitHub-first issue. Use when the user asks to execute shaped work, spawn implementer/reviewer agents, or run the implementer -> reviewer -> implementer cycle.
---

# octo-lite Loop

Use this skill after an issue has been shaped and marked ready.

In Linear-first repos, start from the Linear issue key and specs; do not require
or create GitHub issue mirrors. In GitHub-first repos, the existing
`octo-lite:ready` GitHub issue label remains the readiness gate.
This skill orchestrates Codex subagents. It is not a daemon, CLI, polling loop,
or background service.

## Inputs

- Linear issue key or explicitly GitHub-first issue number/URL.
- Optional existing PR number or URL.
- Optional max cycle override. Default max is 3 reviewer fix cycles.

## Required Preflight

Run:

```bash
gh auth status
gh repo view
gh issue view <issue> --json number,title,labels,url,body
```

For GitHub-first issues, refuse to proceed unless the issue has
`octo-lite:ready`, unless the operator explicitly overrides this guard. For
Linear-first work, require the parent/operator to confirm the Linear issue is
ready and use Linear/specs as scope.

Ready means grilled: the issue passed `$grill-with-docs` (or equivalent
operator-led grilling) and the operator walked through the user story and
acceptance criteria and signed them off. Do not start implementation from a
self-written or ungrilled scope — a body the agent wrote itself is not shaped
work. If the grill or AC walkthrough has not happened, stop and route back to
`$octo-lite-issue-shaper`. Ready also means the issue carries a feature-level,
user-voiced user story — loops never invent or repair stories.

Read target repo `AGENTS.md`, `spec/index.md`, relevant specs, and ADRs before
spawning agents when they are needed to build the initial task prompt.

## Agent Roles

Role-model policy (operator directive 2026-07-12, supersedes 2026-07-07):

- **Implementer: always OpenAI GPT-5.6 Luna at `ultra` reasoning effort, fast
  service tier, via the `codex` relay** (`codex exec -m gpt-5.6-luna -c
  model_reasoning_effort="ultra"`; `service_tier = "fast"` comes from the box
  codex config). State model and effort in the relayed message. The relay does
  not load role profiles, so INCLUDE the implementer role contract from the
  `octo-lite-implementer` profile in the message: one branch, one PR, run the
  target repo validation, post the octo-lite handoff, never merge.
- **Reviewer: always OpenAI GPT-5.6 Sol at `high` reasoning effort, fast
  service tier, via the `codex` relay** (`codex exec -m gpt-5.6-sol -c
  model_reasoning_effort="high"`) — a different model than the implementer
  (Luna builds, Sol reviews; never the same model reviewing its own work).
  INCLUDE the reviewer role instructions from the `octo-lite-reviewer` profile
  verbatim in the relayed message: post a real `gh pr review`, verdict
  `blocking`/`clear`/`ambiguous` as the first word of the reply, never
  approve, never merge. Give it absolute repo/worktree paths — Codex runs on
  the local box with repo + gh access. Continue the SAME codex session via
  SendMessage for re-review cycles so it keeps its findings context.
- QA capture and QA review stages stay Claude (Opus, per octo-loop-qa) — this
  policy covers the implementer and code-reviewer roles.
- `octo-lite-implementer`/`octo-lite-reviewer` remain the role-instruction
  sources, and the Claude-agent spawn is the fallback ONLY when the codex
  CLI/subagent is unavailable — note that deviation in the operator report.

On the Codex surface the role profiles are the installed `agents/*.toml`
profiles (configure gpt-5.6-luna/ultra for the implementer and
gpt-5.6-sol/high for the reviewer in the Codex profile). On the Claude Code
surface the relay path above applies; the installed `~/.claude/agents/*.md`
subagents are the fallback.

If a required agent name is unavailable in the current surface, fall back to a
generic worker (Codex `worker`/`default`, or Claude `general-purpose`) for that
role, include the corresponding role instructions from the installed agent
profile in the prompt, and keep the role-model policy above.

## Role Skill Expectations

Use `role-skills.json` as the role-skill source of truth.

Implementer agents may load or follow only these implementer role skills during
normal loop execution:

- `$commit`
- `$frontend-design`
- `$octo-lite-github`
- `$nodejs`
- `$pnpm`
- `$pnpm-patching`
- `$pull`
- `$push`
- `$python`
- `$tdd`
- `$typescript`

Reviewer agents may load or follow only these reviewer role skills during
normal loop execution:

- `$octo-lite-debug`
- `$octo-lite-github`
- `$pull`

When using fallback agents, include the appropriate list above and tell the
agent not to use Issue Shaper or opposite-role skills unless the loop stops and
routes back to the operator.

## Loop

Use at most 3 reviewer fix cycles by default.

1. Spawn `octo-lite-implementer` with the issue number, repo path, branch
   convention, PR convention, implementer role skill expectations, and any
   latest reviewer findings.
2. Wait for the implementer to finish.
3. Require the implementer to report PR URL/number, branch, HEAD, validation,
   and whether any ambiguity blocked implementation.
4. If implementation is blocked by ambiguity, env/config, or conflicting
   durable sources, stop and route back to `$octo-lite-issue-shaper`.
5. Spawn `octo-lite-reviewer` with the issue number, PR number, repo path,
   reviewer role skill expectations, and expected review outcome format.
6. Wait for the reviewer to finish.
7. Require the reviewer to post a real GitHub PR review and return one of:
   `blocking`, `clear`, or `ambiguous`.
8. If `clear`, stop and report that the PR is ready for human review.
9. If `ambiguous`, stop and route back to `$octo-lite-issue-shaper`.
10. If `blocking`, send the blocking findings back to the implementer and start
    the next cycle.

Do not merge. Do not approve as the human reviewer.

## Durable Loop Surface

Use the PR as the durable loop surface:

- Implementer opens or updates one PR linked to the issue.
- Implementer posts a compact `## octo-lite handoff` PR comment.
- Reviewer posts a GitHub PR review directly.
- Fix cycles update the same branch and PR.

Use `assets/handoff.md` for the implementer handoff shape.

## QA Stages (default on surfaces that support them)

When the target repo has a runnable app and the surface can drive a browser,
the loop extends past the code review with two QA stages; on Claude Code this
is the default loop, implemented as `workflows/octo-loop-qa.js` (installed at
`~/.claude/workflows/octo-loop-qa.js`, invoked as the `octo-loop-qa` workflow).

1. **QA capture** — after the code-review verdict is clear, a QA-evidence
   agent exercises the operator-signed QA flows against the ACTUAL running
   app on the PR branch and records durable artifacts: at least one video
   walking the user story end to end, full-page screenshots of each key
   state, and a manifest. BOTH viewports are mandatory for UI work — every
   user-visible flow is captured on desktop AND mobile; missing mobile
   evidence means the render/regression criteria are not_evidenced, never
   waved through. Each artifact addresses ONE explicitly stated user-voiced
   story, recorded in `story-map.json` ({story, videos, acs} entries) so the
   evidence site can lay each story out next to its video. Broken or
   uncapturable flows are reported honestly, never papered over.
2. **QA review** — a strict judge (Fable) evaluates the artifacts against the
   user story and EVERY acceptance criterion: `pass` / `fail` /
   `not_evidenced`, where missing evidence is not a pass. Any failure sends
   concrete fix instructions back to the implementer on the same branch and
   PR (bounded fix rounds), then QA repeats.

The loop ends with a concise operator report: what was built, per-AC proof
with evidence, edge cases and regressions actively checked, and artifact
paths INCLUDING browsable evidence-site URLs for every video (the operator
reviews in a browser, not on the box). Human acceptance of the artifacts is
part of the merge gate: the operator watches the evidence before the PR
merges. Neither the loop nor the operator's agent merges ahead of that
acceptance.

The QA verdict MUST be produced by a spawned QA-review agent that visually
judges the artifacts (reads screenshots, extracts and reads video frames) —
never by the orchestrator or the operator's agent reviewing inline. A manual
review is not a verdict. If a loop dies after capture but before review
(killed workflow, session end), re-enter the loop in qa-only mode or spawn
the QA reviewer directly with the same prompt and artifacts before anything
else happens. The reviewer writes its structured verdict to
`<artifacts_dir>/round-N/qa-verdict.json`; the merge gate takes that file as
a REQUIRED input — no verdict artifact, no merge, regardless of what a
handoff says.

Upon merging, drop a comment on the tracker issue (Linear for Linear-first
work) containing the evidence-site link and the report packet (per-AC proof,
edge cases/regressions checked, merge commit). Link video URLs rather than
uploading video files to the tracker.

Operator acceptance is a DURABLE LEDGER, not a chat vibe: accepted issues
live in `qa-verdicts/accepted.json` ({issue: {accepted_at, by, note}}),
written by the operator's agent on an explicit chat accept ("accept TUR-XX" /
"flag TUR-XX: reason" — flags route back into the loop). The evidence site
splits on it: "Needs your review (n)" queue first (ordered by epic rank in
the roadmap, then verdict age — NEVER by capture recency), accepted archive
below, plus a generated `review.html` story-mode (one pending issue per
screen, arrow-key navigation) for one-sitting review sessions.

Evidence-site hierarchy is coverage-first: the default view of an issue shows
exactly one current video per use case — all of them side by side — never a
"latest run only" view that hides use cases, and never a stale video for a
flow that was redone. When a fix round re-captures a flow, mark the older
round's redone artifacts in a SUPERSEDED glob file so they collapse out of
the default view.

The evidence-site gallery (Turbo target: `/root/codex-uploads/
build-evidence-index.py`) is issue-aware, VERDICT-FIRST, and operator-facing.
Each issue section is structured around the operator's acceptance flow:
(1) verdict pill + per-AC checklist from `qa-verdicts/<ISSUE>.json` (each row
expands to its evidence and fix instruction), (2) "Watch the proof" — the
current video per use case, human-labeled, side by side, (3) screenshots
collapsed, (4) "Capture details & history" collapsed (rounds, capture notes,
check badges, superseded/deprecated). Rounds never structure the default
view — they are forensic plumbing. Plus: light product theme,
mobile-optimized, Linear-linked titles, context chips (epic/related/token
spend), Desktop/Mobile tabs, lightbox arrows, and a right rail with the
Linear roadmap grouped by epic (progress bars, in-flight/up-next, done
collapsed). Linear metadata is fetched at build time and cached for offline
rebuilds. A header hint spells out the review flow: verdict → AC checklist →
videos → accept in the CLI to merge.

QA verdicts are durable, per-issue artifacts: the reviewer writes
`/root/codex-uploads/qa-verdicts/<ISSUE>.json` (canonical) in addition to the
round-level copy. Issues that shipped before this process get BACKFILLED
verdicts: spawn the same visual QA reviewer over their existing artifacts so
every shipped story has an evidence-graded verdict on file.

Downstream (design agreed 2026-07-03, generator to be built): a user-story
catalog is GENERATED from Linear stories/AC joined with the qa-verdicts —
QA-proven stories only, organized by app surface — and published from one
generator run to BOTH Notion (business agents) and the target repo's `spec/`
dir (dev agents). Neither copy is hand-edited; regeneration happens as part
of the post-acceptance merge routine (the same operator-agent step that
merges and drops the tracker comment).

Linear state model (operator convention 2026-07-04): states are LIFECYCLE
ONLY — `Todo → In Progress → In Review → Done` — and no state may duplicate
the meaning of another artifact. Concretely:

- The loop moves the issue to In Progress when implementation starts, and to
  In Review when a satisfied evidence packet lands in the operator's queue.
- Evidence acceptance is NOT a state. It is the operator's chat-accept,
  recorded in the acceptance ledger (`qa-verdicts/accepted.json`) — an audit
  log and site index, never a second source of truth. Do not create an
  "Accepted" workflow state or label; two states describing the same fact
  make the tracker feel wrong (operator, verbatim intent).
- Done is GATED, not granted: the post-acceptance merge routine — and only
  it — transitions the issue to Done, in the same step as the merge and the
  evidence-link comment. No ledger entry, no merge, no Done; and never a
  separate state-sweep later.
- No half-open issues: an accepted issue never stays open to carry remaining
  scope. TRANSFER the remainder to the issue that will build it (comments on
  both sides recording the hand-off), then close the accepted issue Done —
  operator rule 2026-07-04, set when TUR-81 straddled a shipped slice and an
  unshipped deliverable and broke the accepted/Done reconciliation.
- Invariant: accepted ⇒ merged ⇒ Done, always; the ledger, the tracker, and
  the evidence site must reconcile exactly (packets without Linear identity
  are counted apart, never blended into issue counts).

QA fixture hygiene: onboarding/first-run demo users are consumable — a QA run
that completes onboarding burns the fixture. Verify fixture state (e.g. the
progress row in the database) before trusting a first-run flow's result, and
prefer re-verifying with a genuinely fresh user over re-using a named login.

The workflow script's conventions blocks (repo paths, base branch, demo
logins, QA app topology) are per-target configuration — see the header
comment in `workflows/octo-loop-qa.js`.

## Batch Execution (multiple shaped issues)

Two rules exist because their absence created an avoidable merge-conflict
train and a pointlessly serialized night (operator correction 2026-07-03):

- **Stack sequential batches.** When loops run in a dictated order, loop N+1's
  branch forks from loop N's final head (pass `base` in the workflow args),
  never as siblings off one shared base commit. Review flags are fix-forward
  on the same branch in this workflow — nothing is ever reverted out of the
  line — so stacking costs nothing at review time and eliminates the
  cross-PR conflict surface entirely. PRs still target the trunk; merge them
  in stack order and each PR's diff collapses to its own work. If a loop is
  skipped or blocked mid-batch, continue the stack from the last good head
  and note the gap in the operator report.
- **Cluster same-file issues.** If two shaped issues edit the same files,
  prefer one loop carrying both AC sets (with operator sign-off at intake)
  over two loops that will collide.
- **Parallelize only disjoint work.** Issues with no file overlap and no
  exclusive-DB-state needs may run as parallel loops — safe because every QA
  pass provisions its own isolated env (own worktree + ports; see the QA ENV
  conventions in the workflow). The genuinely shared budgets to watch are the
  Postgres fixture supply and external API spend (e.g. scraping/AI credits),
  not the app stack.

## Stop Conditions

Stop and summarize when:

- reviewer reports no blocking findings;
- 3 reviewer fix cycles have completed;
- implementer or reviewer finds ambiguous requirements;
- env/config needed for acceptance is missing;
- issue, specs, ADRs, or repo instructions conflict;
- validation cannot run and the missing validation affects acceptance.

Final summary should include:

- issue link;
- PR link;
- latest reviewer outcome;
- validation status;
- reason for stopping;
- recommended next action.

## Boundaries

- Do not create new GitHub workflow labels. Do not create or update GitHub
  issue mirrors for Linear-first work unless the operator explicitly asks.
- Do not create extra PRs for the same issue.
- Do not continue past ambiguity by guessing.
- Do not run issue shaping inside the loop except to recommend returning to the
  Issue Shaper.
