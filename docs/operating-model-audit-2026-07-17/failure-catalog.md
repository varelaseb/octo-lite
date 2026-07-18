# Failure Catalog

Status: historical audit evidence with reconciled fix directions. The
canonical operating-model spec and Decisions 1 through 102 win on any conflict.

## How to read this catalog

`Systemic` means the mechanism is present on every applicable path.
`Recurring` means multiple recent sessions or durable incident notes describe
the same class.
`Observed` means the audit found a concrete instance but does not claim a
stable rate.

The catalog describes failure classes, not blame.
Many agents recovered correctly after detecting the problem.
The operating-model gap is that recovery depended on vigilance rather than a
hard gate.

Fix directions are reconciled to the canonical operating-model spec through
Decision 102. Incident mechanisms and counts remain historical evidence.

## Instruction and prompt failures

| ID | Failure mode | Incidence | Mechanism | Consequence | Durable fix direction |
| --- | --- | --- | --- | --- | --- |
| I-01 | Codex relay starts outside target repo | Systemic on sampled Claude-to-Codex workflow relays | `codex exec` inherits a Claude scratch cwd, so only global Codex instructions auto-load | Turbo repo law, spec format, validation, and branch rules become optional discovery | Provision worktree first; invoke `codex exec -C <worktree>`; require instruction-manifest acknowledgment |
| I-02 | Short role summary replaces role profile | Systemic in `octo-loop-qa` implement/review/fix prompts | Workflow hand-maintains a few role sentences instead of composing the versioned role profile | Role skills, source precedence, ambiguity stops, and handoff requirements drift | Generate prompt envelopes from one role-contract source |
| I-03 | Repo instructions are present but stale | Recurring across worktrees | Worktrees contain branch-era copies of `AGENTS.md`; five variants are registered | Agents follow old state, spec, or workflow rules with confidence | Pin and report target instruction blob; define policy for branch-local versus current-baseline instructions |
| I-04 | `AGENTS.md` and `CLAUDE.md` duplicate policy | Systemic in Turbo-Outreach | The same workflow/spec/plan rules are maintained twice | Cross-runtime divergence and contradictory pause behavior | Make root `AGENTS.md` the sole Turbo instruction source and root `CLAUDE.md` a tracked relative symlink to it |
| I-05 | Ready-loop work is told to stop and ask for plan review | Systemic in current Turbo instructions | Generic "when asked to implement" steps do not distinguish unshaped work from operator-signed loop work | A ready issue can be re-planned or unnecessarily paused | Add explicit shaped-loop exception and authority boundary |
| I-06 | Generic profile carries TopicFinder policy | Systemic | TopicFinder Notion and target lifecycle details live in the global octo-lite profile | Other repos inherit client-specific behavior; target updates require generic releases | Move standing target policy exclusively to Turbo root `AGENTS.md`; keep product behavior in Turbo specs/ADRs |
| I-07 | Source and installed prompts drift | Observed and structurally guaranteed | Claude workflow is copied and locally rewritten rather than symlinked/generated | Live behavior cannot be reconstructed from git; fixes disappear or remain unreviewed | Install canonical generic roles, skills, and workflows by symlink or deterministic build with a drift check |
| I-08 | Model/effort policy is prose, not executable wiring | Recurring | Role profiles do not pin model/effort; native agents inherit global defaults | An implementer can run on the reviewer model, defeating cross-model review | Pin executable model config per role and report actual model from runtime metadata |
| I-09 | Relay resumes `--last`, not its exact session | Systemic under concurrent relay reuse | Global last-session selection is unrelated to relay scratch isolation | Follow-up can enter another lane's context | Capture and resume exact Codex session ID |
| I-10 | Platform-specific prompt copies diverge | Recurring | TOML, Claude Markdown, workflow literals, memories, and handoff prompts restate roles | A fix reaches one surface but not another | One canonical role contract with thin generated adapters |
| I-11 | Orchestrator and QA roles are not in the role-skill map | Systemic | `role-skills.json` defines only shaper, implementer, and reviewer while live prompts add several implicit roles | Role boundaries and allowed skills are unenforceable for most of the delivery path | Add the nine canonical LLM roles to `roles.toml`; keep acceptance, merge, publication, transitions, promotion, and traffic shift as deterministic helpers |
| I-12 | Orchestrator bypasses issue-shaper entry contract | Recurring | The same session writes detailed scope, labels it shaped, and launches the loop without a readiness artifact | Self-written scope is presented as operator-signed work | Require issue-shaper activation, operator grill, and a clear exact-input shaping verdict comment on the evolving draft PR before `Shaped` |
| I-13 | Spawned stream orchestrator is not guaranteed to enter auto mode | 11 of 51 recent Claude `herdr-spawn` command lines omitted an explicit permissive mode; systemic helper gap | `herdr-spawn` passes arbitrary argv and merely shows an auto-mode example; the meta prompt does not require or verify the child orchestrator's permission mode | A long-lived orchestrator stalls on routine approvals and has to be babysat or manually cycled to auto | Role-aware spawn command pins Claude `--permission-mode auto`; bootstrap reports and verifies runtime mode without expanding authority |

## Workflow gate failures

| ID | Failure mode | Incidence | Mechanism | Consequence | Durable fix direction |
| --- | --- | --- | --- | --- | --- |
| G-01 | Fix is not re-reviewed | Systemic whenever first review blocks | Workflow performs review → one fix → QA | QA may validate a head no reviewer cleared | Loop review until clear/ambiguous/max cycles; bind verdict to exact head |
| G-02 | Missing or ambiguous review falls through | Systemic code path | Only `blocking` has explicit handling | Downstream QA can start without a valid code-review gate | Fail closed on null, schema error, ambiguous, stale head, or non-clear verdict |
| G-03 | Fresh worker instances receive incomplete handoffs | Recurring | Fixes and follow-ups correctly use new instances, but prompts assume context held by the prior worker | Findings are reinterpreted, repo law is missed, or work is repeated; attempts to compensate with `--last` can cross lanes | Require a complete durable input envelope for every new pass; never resume worker sessions or use `--last` |
| G-04 | PR base changes under the lane | Recurring and heavily documented | Generic reviewer/PR conventions assume `main`; live work uses integration branches | Reviews demand retargeting; automation silently flips bases; diffs and merge order change | Make required PR base a signed input; assert after every push/review |
| G-05 | QA head differs from reviewed or PR head | Recurring incident class | No exact-head chain links code review, capture, verdict, and PR | Evidence can prove an obsolete commit | Put HEAD in every gate artifact and reject mismatches |
| G-06 | Empty or placeholder scope is accepted | Systemic code path | Workflow defaults to `(none provided)` story and empty AC/flows | A loop can execute unshaped work despite ready-gate doctrine | Schema preflight: nonempty signed story, observable AC, readiness identity |
| G-07 | State update silently fails | Recurring | CLI invocations can return without changing Linear; no read-back gate | Board and orchestration disagree about current state | Treat transition as compare-and-set with read-back evidence |
| G-08 | Acceptance, merge, and deployment semantics conflict | Recurring; `TUR-437` reproduced it on 2026-07-17 | Routines use “merge = staging” without distinguishing `main` from `next-candidate` or another integration branch | Issues merged only to an integration branch are falsely labeled deployed | `In Staging` only after merge to `main` (the staging-deploy boundary); integration-branch acceptance remains separately represented |
| G-09 | Backend-only path lacks equivalent durable acceptance packet | Recurring; reproduced by `TUR-437` on 2026-07-17 | `user_facing=false` skips both browser QA and creation of the nonvisual verdict/gallery packet; the calling orchestrator owns an undocumented manual repair | Backend work is called ready while absent from the acceptance surface; evidence is authored after acceptance from prose | Workflow must emit a typed nonvisual verdict and gallery card before `Awaiting Accept`; publication read-back is part of the gate |
| G-10 | Workflow status is not a reliable business status | Recurring | Completed workflow can still have unresolved product, base, evidence, or deployment work | Operator sees "done" while outcome is pending | Separate process completion from issue outcome and gate state |
| G-11 | `Shaped` is an unverified assertion | Recurring | Linear state carries no grill, AC-walkthrough, approver, issue-revision, or spec-revision proof | Changed or ungrilled scope can enter implementation | Make `Shaped` depend on the exact-input shaping verdict comment on the evolving draft PR; launch refetches and compares all bound sources |
| G-12 | Spec-driven TDD is optional prose | Systemic current policy | TDD activates only on explicit request and the workflow weakens this to `where practical` | Tests may be retrospective and no red/green proof survives | Make behavior-first TDD the default; require recorded red/green evidence or a signed narrow waiver |
| G-13 | Linear transition is not tied to observable lifecycle fact | Recurring | State names are used as orchestration commands and integration-branch position is conflated with deployment | Linear ceases to be reliable product/dev truth | Define state evidence and sole owner; compare-and-set with read-back |
| G-14 | Reviewer cannot request changes with its GitHub identity | Recurring; 82 Codex session files | Reviewer authenticates as the PR-owning identity, and GitHub rejects request-changes on one's own PR | Required durable review operation fails and degrades to comments | Use one deterministic exact-HEAD PR verdict comment as the canonical gate; do not depend on formal review identity |
| G-15 | QA requires video even when still evidence is sufficient | Systemic in current workflow prompt | Every user-facing story is told to produce narrated video plus screenshots | Capture is slower and noisier than the acceptance criterion requires | Choose evidence type per AC; screenshots default, video only for motion/sequence/timing/playback/interaction proof |
| G-16 | “Ready for accept” is declared before the evidence site proves visibility | Recurring; operator-confirmed and reproduced by `TUR-437` | Lane/meta packet checks cover branch, HEAD, review, validation, and CI but omit a read-back from the operator's actual acceptance surface | Operator is asked to accept an item they cannot inspect; emergency artifact repair races with merge | Before declaring ready, the accountable orchestrator must confirm the issue card is present and reviewable on the served page; defer cryptographic receipts unless this simpler gate still fails |

## Orchestration and communication failures

| ID | Failure mode | Incidence | Mechanism | Consequence | Durable fix direction |
| --- | --- | --- | --- | --- | --- |
| O-01 | Text is visible in TUI but not submitted | Recurring; operator-confirmed | Paste and Enter are separate, unacknowledged operations | Sender assumes work started; recipient remains idle | `herdr-say` distinguishes queued from submitted; required control messages need explicit acknowledgment and completion needs the named outcome |
| O-02 | Raw injection can answer a human modal | Recurring historical incident | Bare Enter is sent while a trust/question dialog is active | Agent selects an answer without operator authority | Dialog-aware delivery; never inject or submit while a modal is active and never infer approval from TUI text |
| O-03 | Ghost/suggestion text is mistaken for operator input | Recurring historical incident | TUI suggestion text resembles typed human text | False acceptance or action authority | Only structured user events or explicitly acknowledged control messages grant authority |
| O-04 | A recipient has no return route | Recurring | Cross-agent prose appears in a pane without sender identity/ack address | Reply is written locally and never reaches the owner | Herdr messages carry sender and reply route; control messages also identify the expected acknowledgment and outcome |
| O-05 | Spawn readiness is inferred from a prompt glyph | Systemic in current helper | Visible REPL is treated as successful startup | Folder trust, launch prompt, or bootstrap may still be unaccepted | Require a compact bootstrap acknowledgment bound to the launch receipt |
| O-06 | Fresh session starts in wrong cwd | Recurring historical incident | Tab cwd and agent cwd differ; some launch paths bypass helper | Wrong repo instructions and project memory load | One spawn primitive, explicit cwd, target remote check, bootstrap ack |
| O-07 | Session ownership and lifecycle drift | Recurring | Long-lived sessions accumulate unrelated work; finished lanes remain active | Context rot, credit waste, ambiguous ownership | One bounded stream per session; kill when done; durable replacement brief |
| O-08 | Multiple agents relay conflicting operator rulings | Recurring | Decisions travel as free-form chat without revision or supersession | Work starts from an obsolete ruling | Parent-owned authority briefs plus compact material ruling revisions; avoid a flat decision ID requirement for routine relays |
| O-09 | Operator status is issue-number/process-centric | Operator-confirmed | Tabs and packets emphasize issue/PR/run IDs instead of outcomes, owner, stage, and epic | Human cannot quickly see what is happening or why it matters | Outcome-first control view with owner, gate, epic, blocker, and next operator action |
| O-10 | Notifications do not guarantee accountable wake-up | Recurring risk | Watcher/polling may record state without reactivating an owner | Work silently stalls after external completion | Every monitor records a tested wake path and accountable owner |
| O-11 | One stale resumed-session auth failure is promoted to a fleet outage | Observed in `TUR-429`; the error remained buried for 62 minutes | A resumed Codex session returned `token_revoked`, but no fresh-session auth probe ran before the lane escalated and the meta-operator repeated the conclusion | Healthy fleet capacity is unnecessarily stopped; completed on-disk work is at risk of being discarded | Surface auth errors immediately; inspect the worktree; probe a fresh exact-model session; classify lane/session/provider scope before broadcasting; never use `resume --last` |

## Workspace and resource failures

| ID | Failure mode | Incidence | Mechanism | Consequence | Durable fix direction |
| --- | --- | --- | --- | --- | --- |
| R-01 | Stale coordination checkout is treated as canonical | Systemic current configuration | Workflow uses `/root/Turbo-Outreach-staging`, 826 commits behind `origin/main` | Wrong source, instructions, dependencies, and branch assumptions | Clean control clone/bare repo; never use a mutable working tree as registry |
| R-02 | Worktree fleet grows without lifecycle owner | Recurring; hundreds registered | Creation is automated; teardown is best-effort and per-agent | Disk pressure, stale instruction variants, branch confusion | Remove each completed worker worktree after durable handoff, commit, and push; dirty worktrees stop for owner inspection |
| R-03 | Disk exhaustion blocks deployment/validation | Observed in recent sessions | Worktrees, dependencies, artifacts, and repeated installs accumulate | `ENOSPC`, failed `npm ci`, abandoned runs | Check disk/inodes before spawn, reuse native immutable download caches, and clean completed worker worktrees |
| R-04 | OOM/529 overload causes kill-and-pivot loops | Recurring | Many expensive workflows and relays start without global capacity control | Hours lost, context resets, orphaned state | Lightweight pre-spawn provider and host overload check; unsafe work waits without a scheduler service |
| R-05 | Parallel sessions share a checkout | Recurring incident | Separate agents mutate the same branch/worktree | HEAD swaps, overwritten changes, nondeterministic validation | Exactly one writer per worktree; file territory plus integration owner |
| R-06 | Shared database fixtures are consumed or collide | Recurring | QA flows mutate reusable first-run users and shared DB state | Later evidence is invalid or irreproducible | Verify starting state, avoid another lane's fixture, record the fixture, and create a unique local fixture only where already cheap |
| R-07 | Ports and processes leak across QA passes | Recurring | Agents start local stacks and tear down by convention | Port collision, wrong app captured, unrelated process killed | Record owned ports and PIDs in the pass manifest, verify app identity, and perform scoped teardown without a process registry |
| R-08 | Staging mutation lease is orphaned | Observed and documented | Killed job does not release a shared lease | Other deployments are blocked | Target runbook names the owner, release trap, inspection, and safe recovery command; add no heartbeat service |
| R-09 | Evidence lives under ephemeral session state | Recurring | Artifacts/symlinks point into scratch or session directories | Evidence disappears when the session is killed | Durable artifact root allocated before run; immutable manifest |
| R-10 | Evidence/catalog builders have multiple writers | Recurring | Each lane can rebuild shared indexes or update acceptance ledger | Races, stale cards, overwritten state | One deterministic publication helper performs atomic generation and exact-card readback; QA workers never write the shared index |

## Repo and validation gotchas

| ID | Failure mode | Incidence | Mechanism | Consequence | Durable fix direction |
| --- | --- | --- | --- | --- | --- |
| V-01 | Workflow says Markdown specs while repo is spec-chat | Systemic source conflict | Generic prompt hard-codes `spec/domains/*.md` | Agents may ignore canonical HTML specs | Discover the spec-format signal from target `AGENTS.md`, then bind the matching index and relevant spec blobs |
| V-02 | DB-gated tests skip silently | Recurring | Required test database is absent | Green output hides unexecuted integration coverage | Validation manifest records executed/skipped counts and required env |
| V-03 | Local typecheck differs from CI | Recurring | Local TypeScript target allows constructs CI rejects | Repeated CI-only failures | One canonical validation command/container matching CI |
| V-04 | Diff-scoped review misses shared untouched behavior | Recurring | Review examines only changed lines | Shared CSS/components or host behavior regress | Risk-triggered full-tree checks and browser evidence |
| V-05 | Runtime/deployed ref is inferred from cwd | Recurring | Stale worktree is used to explain production | Incorrect mechanism and line references | Every operational claim carries source ref/image digest/deployment identity |
| V-06 | Repeated verification adds latency without confidence | Operator-confirmed | Multiple lanes rerun already-owned gates | Compute and wall-clock waste | One owner per claim; consume the exact-HEAD gate artifact unless its bound inputs change |
| V-07 | One-time operations are embedded in repeatable deploy paths | Observed | Seeding/migration/corpus work is not separated from promotion | Accidental long reruns and risky data mutation | Idempotent explicit ops commands; promotion path excludes completed migrations/seeding by default |
| V-08 | Environment assumptions are encoded as mutable paths | Recurring | Workflow copies env/deps from a dirty stale checkout | Broken symlinks and inconsistent runs | Resolve versioned repo facts and the signed brief at launch, use native immutable cache roots, and inject secrets separately |
| V-09 | Reviewer/worker worktree lacks dependencies | Recurring; `Cannot find module` in 109 Codex files | Worktrees are created without a repo-owned, verified bootstrap | Reviews/tests fail for environment reasons or silently narrow coverage | One fail-fast Turbo worktree bootstrap command with dependency, env, tool, DB, and disk checks |
| V-10 | Evidence publication is a slow non-atomic whole-corpus rebuild | Systemic gallery architecture; successful recent builds took 404–1,538 seconds and several were killed; live hotfix reduced the normal path to 20.079 seconds | Every trigger rescans/re-renders the full archive; formerly it also made ~139 serial Linear detail calls plus serial GitHub reads; triggers coalesce while Linear state and artifacts are read at different moments | New cards can miss the build snapshot, remain invisible for tens of minutes, or appear only after acceptance/merge | Keep the cache/parallel-read hotfix; move toward atomic per-issue manifests/cards plus an incremental index update and immediate served-card readback, without a queue service |

## Failure clusters

The catalog collapses into five root causes:

1. **No canonical instruction assembly.**
2. **No fail-closed, exact-head gate state machine.**
3. **No acknowledged inter-agent control channel.**
4. **No resource, worktree, and shared-state ownership layer.**
5. **No clean separation between generic workflow mechanics, target repo law,
   and ephemeral operating state.**
