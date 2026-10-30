---
name: implement-spec
description: Dispatch delivery of an accepted spec, or one ticket the existing spec already states, through Herdr workers to one PR. The lane owner's route for every repo change.
disable-model-invocation: false
---

# Implement Spec

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

The owner dispatches; it never edits repo files itself. Deliver the complete
spec or ticket on one branch and leave one PR ready for human review. Workers
load their `agents/*.md` role contracts and use octo-lite skills as guidance.
Workers are the whole mechanism: no role resolver, loop workflow, journal, or
exact-role gate sits on top of them.

## Inputs

Require:

- canonical spec
- spec issue
- target root `AGENTS.md`

A ticket whose behavior the existing spec on main already states needs no
shaping or new acceptance: that spec's commit on main is the spec acceptance
receipt, and the ticket is the spec issue (a spec change goes back to shaping).
The primary issue is the one-node graph: Start step 1 files nothing, and only
filing is skipped. Every worker step still runs: one implementer in its own
worktree, one integrator, one reviewer. The primary issue stays open until merge.

In a repo whose specs are Spec Chat's, a ticket that changes a screen its
spec's mockup set does not draw goes back to shaping, which draws it and
returns the spec to review, before any implementer starts. A screen that must
differ from its accepted mockup goes back the same way before the build
differs (spec `#delivery-mockup`).

A processed human **spec acceptance** (page action **Accept spec**, formerly
called Finish review) permits implementation dispatch under the reviewed
canonical spec. Follow `spec-chat/skill/review-spec/SKILL.md` under
`## Remote hosting lifecycle` for review resource lifetime. It does not accept
the implementation PR, approve a merge, promote to preproduction, or approve
live traffic.

The tickets are a task graph, not ordered steps. The ready frontier contains
every incomplete ticket whose blockers are complete. Keep Linear titles,
descriptions, relations, assignees, and states aligned with reality throughout.
Do not copy ticket or spec prose into agent messages. Send essential absolute
source paths in the message body; artifact metadata alone is insufficient.

The lane owner keeps its lane record current as the lane-record hook in `agents/orchestrator.md` and `spec/domains/octo-lite.spec.html#lane-record` define.

Record the requested handoff in the existing brief. Manual QA readiness means
a usable feature deployment, required dependencies, working account roles and
starting scenarios, with a secure credential pointer and stated limitations.
Do not replace that outcome with exhaustive agent proof. Required spec/target
evidence still applies; human QA, code readiness and acceptance are separate.

## Start

1. After spec acceptance, file the dependency-linked tickets under the spec
   issue as [consent](../octo-lite-github/SKILL.md#consent) allows, else keep
   the graph in the local brief: one outcome each, spec anchors, real blockers
   only. Before filing, read the target's changelog convention (file,
   format, which changes get an entry, by default every change its users can
   see) from its `AGENTS.md` or `CLAUDE.md`, or a rule file one of them points
   to; octo-lite names no changelog path or format. When the lane makes a
   change it logs, give the entry to one ticket (spec `#delivery-changelog`).
2. Read the spec, issue, and enough of the graph to identify the first
   frontier.
3. When exploration would remove duplicated implementation work, spawn one
   optional exploration agent through `herdr-comms`. Give it write access only
   to the lane's notes directory, `$(octo-lite-state)/lanes/<lane record name>-notes/`
   (spec `#delivery-notes`). Its deliverable is concise Markdown notes there,
   linked from the relevant tickets.
4. Continue the draft PR the orchestrator opened while shaping, else create the
   integration branch from the target base and open one draft PR.
   Push, open PRs, and file issues only as
   [consent](../octo-lite-github/SKILL.md#consent) allows; otherwise the lane stays on local
   branches and ends at a local integration head.
   Put `Closes <issue-key>` lines in the PR body for the spec issue and every
   implementation ticket, and one changelog line: `Changelog: <entry title>`,
   or `Changelog: none: <reason>` when the lane makes no change the
   convention logs or the target declares no convention.
5. Before dispatch, run the spec validator, backslash-artifact scan, and
   tag-balance scan. Repo tests run in delivery, never during shaping. Run one short cross-source conflict check: does the spec
   contradict another canonical spec, merged main, or an open PR?

## Herdr workers

Use the verified launch path from `herdr-comms`; inspect help only when that
invocation is unknown or changed. Spawn every exploration,
implementation, merge, review-fix worker through Herdr. Prefer background tabs
and fill available capacity from the current frontier.

Spawn every worker into the owner's space, `--workspace "$HERDR_WORKSPACE_ID"`,
named `<role>-<ticket>` lowercase (`implementer-ann-64`; a lane-wide worker such
as the integrator carries the primary issue key), per spec
`#transport-spawn-name`. Close a worker before reusing its name. Herdr owns
session selection. Spawn Claude workers
(`-- claude`, CLI default model; brief via `herdr-say`); Codex only when the operator
explicitly selects it. Keep the worker-specific nuance: every writer still
gets its own worktree, and only one integrator writes the integration branch.

For each ready ticket:

1. Create a dedicated worktree and branch from the current integration branch.
2. Mark the Linear ticket In Progress only when its worker starts.
3. Spawn a Herdr implementer in that worktree, under the `implementer` role
   contract. Prompt it with pointers to the ticket, spec, target `AGENTS.md`,
   optional research notes, integration branch, and relevant prior commits.
   Name the accepted mockup of each screen the ticket changes: its file in the
   spec's mockup set at the spec acceptance receipt's commit (spec
   `#delivery-mockup`).
   Cite each repo-wide rule the ticket bears on by its marked criterion's spec
   and anchor (spec `#roles-repo-wide-rule`); an `AGENTS.md` line is only a
   pointer to it. The brief of the ticket that owns the changelog entry names
   the convention's file, so its implementer writes the entry in the same PR.
4. The contract declares the skills available to it and the bounds it works in,
   so neither has to be restated here or kept in step by hand. A Claude worker
   loads it with `--agent implementer`; a Codex worker gets it as developer
   instructions from `herdr-spawn --role implementer`.

The worker owns only that ticket, validates it, commits it, and returns the
commit plus terse evidence. It does not merge, push, or update unrelated
tickets.

Use `herdr-say` for commands. It returns only once Herdr has observed the
target change state, so delivery needs no separate acknowledgement. Send each
message that sets a worker to work (brief, resume, repair) with
`herdr-await <name> <message>` instead, by name, on Claude as
`herdr-await --notice` run in the background, never `herdr agent wait`
yourself, and when that wait ends follow the
[wait recipe](../herdr-comms/SKILL.md#wait-on-an-agent) (spec `#roles-goal`,
`#transport-await`). Keep messages sparse. A status pointer or
commit is better than a recap.

## Integrate and advance

When an implementer completes:

1. Spawn an integrator through `herdr-comms` with `--role integrator` in a clean
   integration worktree.
2. Give it the ticket, worker commit, integration branch, and spec pointers.
3. Have it merge or cherry-pick the worker commit, resolve only integration
   conflicts, run proportionate validation, push the integration branch as
   [consent](../octo-lite-github/SKILL.md#consent) allows, and send the
   resulting commit to the owner pane as a [report](../herdr-comms/SKILL.md#send-a-report).
4. Mark the ticket Done only after its change is integrated (and pushed when
   consent allows). If the merge fails or validation is red, reflect that
   truth in Linear and return the ticket to active work.
5. Recompute the frontier and immediately fill newly available capacity.

One integrator writes the integration branch at a time. Implementers may continue
in parallel on independent frontier tickets.
Each writer has a distinct worktree, including the integrator; a separate tab in
the same checkout is not isolation. Read-only explorers may share source only
when they do not install dependencies, change branches or generate files there.

Consume completed results at the next owner wake, before optional status work,
and continue integration or the next ready task in that turn. Keep one integrator
owner for the lane's integration branch. Every worker brief names the owner pane.
The owner waits for the worker's result message, or for its one wait on that
worker to end (`agents/orchestrator.md`).
Record one truthful current state, next action and dependency.
Do not end delivery at startup, dispatch, worker completion or review forwarding.

## Validation and preview setup

Read target `AGENTS.md` and applicable CI commands before broad validation,
including DB isolation, shard/file concurrency, schema and dependencies.
Do not run parallel destructive suites on one shared DB when CI isolates them.
Before a heavy job (full suite, QA capture, build), yours or a worker's, check
box load (`uptime` against `nproc`, `free -m`); when high, run one heavy job at
a time and say so in worker briefs.
On topology failures, stop the owned invalid run and diagnose before retrying.
Reuse passing evidence only for unchanged code and compatible environment
when target rules permit; final-head required checks and integration-sensitive
tests remain required. Repeat or broaden tests only for a change, failure,
unresolved risk or explicit required check, not because a handoff occurred.

Use one preview deployment/fork owner. Its current receipt in existing control
state binds feature SHA, revision, DB fork/schema, scoped access, fixture
namespace and secure credential pointer. A base-only healthy preview is not the
feature. Share the receipt and setup window; do not infer access from another
identity's grants. Before recreation, preserve fixtures/paid progress and agree
closure with affected owners; restore and verify after the new receipt. Keep
rollback and target safety checks. No new receipt framework is required.
Stop watching an operation after its terminal outcome is consumed. Retry a
known deployment/access blocker only after a relevant state change; continue
independent work and report the exact remaining dependency.

## Review and finish

Order, every lane: build only after the spec acceptance receipt; integrate every ticket; code review clear and its notes ended by the finish rule (spec `#delivery-finish`); the target's required validation; any evidence the target's AGENTS.md requires before a merge ask (for example a QA evidence bundle for changes a person can observe); every failed QA criterion triaged by annotateanything's owner triage rule (`docs/specs/jev-capture.spec.html#qa-rules-owner-triage`), a failure carried from an older head first recaptured at the merge ask's head, then ended by the finish rule; then one merge ask that carries the review result, the PR body's Changelog line, that evidence, and its QA call, and goes out with its gate line (`agents/orchestrator.md`, spec `#handoff-kind-gate`), in that contract's merge-ask template: plain summary lines, then the PR link, every detail in the PR body (spec `#delivery-merge-ask`). A merge ask covers its whole issue (spec `#delivery-finish`): in-scope work that cannot be done before merge is named, with why, to the operator pane (`pane` in `$(octo-lite-state)/operator.toml`) as a [report](../herdr-comms/SKILL.md#send-a-report), asking whether to cut it, in place of the merge ask. A merge ask never goes out ahead of a step it needs.

As soon as a capture or recapture of the PR publishes its bundle, run `qa down <owner>/<repo>#<n>` before your next step (spec `#delivery-qa-down`); only a recapture brings an environment back, and it goes down again once that recapture publishes its bundle.

The merge ask lists, in its PR body, each failed criterion as judged at the merge ask's head, never as carried, with the bundle row's `evidence_state`, its `decision_source` and judged head, its triage, its cause or reason, and its outcome, the end the finish rule gives it; one the rule files is also listed under `## Review notes`, tagged with its category and its consequence as a review note is, so the lane closer files it with its Health label. A failure whose `evidence_state` is `complete` is listed as a code fault unless a specific capture cause is named, such as a wrong fixture, a wrong page reached, or the criterion's shape (spec `spec/domains/octo-lite.spec.html#delivery-qa-triage`).

After every ticket is integrated:

1. Spawn a fresh reviewer through `herdr-comms` with `--role code-reviewer`
   and brief it to run `/code-review` on the integration branch, the lane's one
   full review of the integration head, naming each changed screen's accepted
   mockup as the implementer briefs do, then send its verdict to the
   owner pane as a [report](../herdr-comms/SKILL.md#send-a-report), since `/code-review` ends in its own pane. The verdict policy
   is the `agents/code-reviewer.md` contract. If unsupported,
   use the available independent review mechanism with the provided diff, base,
   spec and scope. Verify acknowledgment and actual review work once;
   do not retry an unrecognized slash command or count pasted text as review.
2. Only the verdict's blockers send the PR back, for at most 2 fix rounds
   (spec `#delivery-review`): the first a fix batch, the second a fresh
   step-back pass toward the simplest design that meets the spec, not another
   patch. A round is one fix branch and worktree, one implementer through
   `herdr-comms` briefed with the accepted spec, the current diff, and the
   findings, not the history, and one Herdr integrator; then a fresh reviewer
   reviews only the fix delta (base = the last reviewed head) plus the surface
   it touches; never re-review unchanged code. Blockers the review after round
   2 still finds go, in place of a third round, to the operator pane (`pane`
   in `$(octo-lite-state)/operator.toml`) as a [report](../herdr-comms/SKILL.md#send-a-report), each blocker named,
   asking how to go on. In-scope work the verdict names as not doable before
   merge gets no fix round: it goes to the ask before it is cut, in the Order
   above. Notes marked `Fix in this PR` are fixed before the merge ask, in a
   fix batch already running, which that round's delta review covers, else
   one batch of their own: no fix round, but a fresh reviewer reviews its
   delta the same way. List every other note, tagged as the reviewer
   gave it, in the PR body under `## Review notes`; they are
   filed at lane close by the [filing rule](../repo-health/SKILL.md#filing-rule).
   Never park a confirmed defect or implicitly waive a failed required
   check. If the same attempt makes no progress, diagnose or route the
   concrete unresolved blocker through the repo-approved path while
   independent tasks continue.
3. Run the target repo's required validation.
4. Mark the PR ready for review only when the final review is clear, every
   required validation succeeds, and any required evidence (QA bundle) is
   published. The Human inbox derives its gate from PR draft status
   (ANN-373): ready means the merge ask is out; draft means work is still in
   progress. Otherwise keep it draft and report the blocker. Keep the spec
   issue open until human review or repository automation closes it.
5. Close each consumed worker with
   `herdr-close TAB >> $(octo-lite-state)/lanes/<lane record name>.handoffs.jsonl`,
   which also ends its detached processes and appends its closed line (spec
   `#transport-close-line`). A worker you would keep idle through a long wait (human
   gate, another lane) is parked instead, never a consumed one:
   `herdr-close --park <pane> >> $(octo-lite-state)/lanes/<lane record name>.handoffs.jsonl`;
   `herdr-say <name>` resumes it. Remove every temporary worker worktree only after it is
   clean and its commits are reachable from the integration branch. Never
   force-remove a worktree with uncommitted or unmerged work.

Continue any authorized deployment/seeding/manual-QA handoff after code review
readiness; report its actual state separately. Human acceptance, preproduction
promotion and live traffic shifts still require explicit human instruction.

Return the PR, integrated tickets, validation, review result, and any truthful
remaining blocker.

## Human acceptance callback

Acceptance follows the worklane. If the human explicitly accepts and instructs
this owning worklane to merge the named PR, treat a merge instruction as
acceptance of that exact head unless the human says otherwise. Mechanical
updates onto accepted main (merge main in; never rebase or force-push a pushed branch) do not require renewed acceptance when behavior and
scope are unchanged. Load `octo-lite-github`, verify required checks and exact
head, record acceptance, execute the merge, and verify post-merge Linear sync.
A human statement that this worklane owns the action is sufficient.
Failed required checks still block merge until fixed or durably waived through
a repository-approved path.

The merge completes the worklane: reconcile the PR and worklane state together,
reconcile the primary Linear issue to Done, file the PR's review notes by the
[filing rule](../repo-health/SKILL.md#filing-rule), add to the PR body a permalink
to each report the lane kept outside main, tear down in the close order of
`agents/orchestrator.md` (report permalinks before review rows, review rows before
any worktree, lane record archived last; spec `#roles-teardown`), and stop.
