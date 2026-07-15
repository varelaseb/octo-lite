// Claude Code Workflow implementation of the octo-lite loop with QA stages
// (see skills/octo-lite-loop/SKILL.md). Install: copy into ~/.claude/workflows/.
// The CONVENTIONS and QA_APP blocks below are per-target configuration
// (currently Turbo-Outreach: repo paths, base branch, demo logins, QA app
// topology) — rewrite them when pointing the loop at a different target repo;
// the phases, schemas, and loop logic are target-agnostic.
export const meta = {
  name: 'octo-loop-qa',
  description: 'Default octo-lite loop with QA: implement → code review → QA video/artifacts → Opus QA review vs user story + AC → fix loop → concise operator report',
  whenToUse: 'Default loop for shaped+ready Linear issues in Turbo-Outreach. args: {issue, branch, base?, pr?, mode: "full"|"qa-only", user_facing?: bool, user_story, acceptance_criteria: [], qa_flows: [], context, artifacts_dir}. user_facing defaults true; pass false for backend-only / not UI-visible issues — QA capture + visual review are SKIPPED (operator convention 2026-07-12), the gate is code review + validation, and the calling session moves the issue to Awaiting Accept when it posts the packet. In sequential batches pass base = the PREVIOUS loop\'s branch head (stacked branches, zero sibling conflicts); omit base only for the first loop or genuinely independent work.',
  phases: [
    { title: 'Implement' },
    { title: 'Code Review' },
    { title: 'QA Capture' },
    { title: 'QA Review', detail: 'Opus judges artifacts vs user story + AC' },
    { title: 'Fix' },
  ],
}

// ---------- args (parsed early: conventions interpolate the branch base) ----------
const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const TRUNK = 'main' // collapse 2026-07-04: main is the only trunk (tur-50 deleted)
const BASE = A.base ?? TRUNK

// ---------- shared conventions ----------
const CONVENTIONS = `
REPO: /root/Turbo-Outreach-staging (PRs target origin/${TRUNK}, NOT main).
BRANCH BASE: fork your branch from origin/${BASE}${BASE !== TRUNK ? ' (STACKED batch base — the previous loop\'s head; your diff builds on it conflict-free. PRs still target the trunk; the PR diff shrinks as predecessors merge in stack order)' : ''}.
WORKTREE (never touch the main tree): git -C /root/Turbo-Outreach-staging worktree add --detach <WT> origin/<branch-or-base>
  Backend deps: ln -s /root/Turbo-Outreach-staging/tools/prospect-report/node_modules <WT>/tools/prospect-report/node_modules
  Client deps:  ln -s /root/Turbo-Outreach-staging/tools/prospect-report/client/node_modules <WT>/tools/prospect-report/client/node_modules
  Env: cp /root/Turbo-Outreach-staging/tools/prospect-report/.env <WT>/tools/prospect-report/.env
Validation: client vitest run + tsc -p client/tsconfig.json --noEmit; backend node --test for touched suites; scripts/lint-architecture.js when boundaries move.
COMMITS end with:
Co-Authored-By: GPT-5.6 Luna (Codex) <noreply@openai.com>
PR body references the Linear key ("Tracks <ISSUE>"). Do NOT merge — the operator watches the QA evidence videos (see EVIDENCE SITE) and the merge happens only after that human acceptance plus the merge-gate checks.
SPECS are law: read the relevant spec/domains/*.md decision logs before changing behavior. Return ONLY the structured result.
LINEAR STATES are lifecycle-only (operator convention 2026-07-04, 6-state consolidation 2026-07-15): the six TUR states are Backlog, Todo, In Progress, Awaiting Accept, Done, Canceled. The loop moves the issue Todo -> In Progress when implementation starts (linear issue update <ISSUE> -s "In Progress"); the QA reviewer moves it to "Awaiting Accept" when a satisfied evidence packet lands in the operator queue (that is the review-queue state for team TUR). NEVER set Done and NEVER invent states like "Accepted" — Done is reserved for the post-acceptance merge routine (acceptance ledger entry + merge = Done, in that step only).`

const QA_APP = `
QA ENV (ISOLATED PER QA PASS — never rely on a shared app stack; loops must be able to capture in parallel):
- Provision YOUR OWN env: worktree of the PR branch (see WORKTREE conventions: deps symlinks + .env copy), then pick two FREE ports (check ss -tln; e.g. vite 5200-5999, api 3200-3999) and start your own stack from <WT>/tools/prospect-report: API via PORT=<api_port> nohup node server.js > /tmp/qa-api-<issue>.log 2>&1 &, client via its dev server on <vite_port> with the API proxy pointed at YOUR api port (env override or a one-off vite config wrapper — the isolation is the requirement; record the exact mechanics in the manifest). Verify http://127.0.0.1:<api_port>/api/health then http://127.0.0.1:<vite_port> before capturing. Record app_url + ports + worktree path in manifest.json.
- TEARDOWN when done: kill only YOUR two processes (record PIDs at launch), git worktree remove YOUR worktree. NEVER kill other processes on 5173/3000 and never touch /tmp/qa2-wt — that is the operator's demo stack, not yours.
- DB is the shared Docker Postgres (turbo-outreach-postgres / prospect_report): use DEDICATED fixture users for consumable flows; never run migrations, truncations, or resets of global/other-loops' state from a QA pass. If the issue genuinely needs exclusive DB state, say so in issues_hit and stop rather than assuming exclusivity.
- Demo login: client@local.test / LocalDevPass123! (post-first-run user, role=client). Pre-first-run logins (verify first-run chrome): qa-topicfinder-full-20260630b@local.test or ...c@local.test / LocalDevPass123!. These fixtures are CONSUMABLE — completing onboarding/first-run burns them (qa-topicfinder-full-20260630d is already burned, completed 2026-07-01). Verify state first: SELECT current_step, completed_at FROM topicfinder_onboarding_progress (docker exec turbo-outreach-postgres psql -U postgres -d prospect_report).
- Playwright is installed at /tmp/qa-evidence-playwright (import { chromium, webkit, devices } from 'playwright'; launch args ['--no-sandbox']). Record video via context recordVideo + convert webm→mp4 with ffmpeg (-c:v libx264 -pix_fmt yuv420p -movflags +faststart). Full-page screenshots for key states. Desktop = 1440x1000 (chromium). MOBILE BASELINE = modern iPhone: webkit.launch() + devices['iPhone 15'] (393x852, real WebKit + touch) — this is the primary mobile target; Android (chromium + devices['Pixel 7']) is secondary, capture it when the issue calls out Android or the flow is input/navigation-heavy (e.g. back-button behavior).
- EVIDENCE SITE: python3 -m http.server 8080 serves /root/codex-uploads/topicfinder-FINAL-20260701 at http://147.182.226.89:8080. Symlink the issue's artifacts dir into that root (ln -sfn <artifacts_dir> /root/codex-uploads/topicfinder-FINAL-20260701/<basename>), then REBUILD THE GALLERY: python3 /root/codex-uploads/build-evidence-index.py (regenerates index.html + video posters; the operator browses the gallery, not raw listings). The operator reviews videos at these URLs BEFORE any merge — human acceptance of the artifacts is part of the merge gate. Include the URLs in the returned artifact list.
- QA VERDICT ARTIFACT: the QA reviewer writes its structured verdict to <artifacts_dir>/round-N/qa-verdict.json AND the canonical /root/codex-uploads/qa-verdicts/<ISSUE>.json. The merge gate requires this file — no verdict artifact, no merge.
- REVIEW PACKET CONTRACT (the returned report IS the operator's acceptance packet): it MUST lead with the browsable evidence-site URL for this round (symlink + rebuild the gallery FIRST; a local path is a contract violation), give per-AC status each pointing at a POSITIVE artifact, and leave NO paid/live leg as a "disclosed residual" when a budget-capped micro-run (cents) can prove it live — run the micro-proof before returning. Recurrence guard: 2026-07-04 TUR-127 packet shipped with local paths + unproven paid legs; operator escalated.
- UPON MERGE (operator's agent, after acceptance): drop a Linear comment on the issue with the evidence-site link and the report packet (per-AC proof, edge cases/regressions checked, merge commit). Link video URLs; do not upload video files to Linear. In the SAME step, transition the Linear issue to Done — acceptance + merge = Done, no separate sweep (operator convention 2026-07-04). Exception: leave the issue open only when it carries explicitly-deferred remaining scope, and say why in the merge comment. Then regenerate BOTH downstream artifacts — STOP-AND-SURFACE if either errors (a silent failure here is how the catalog drifted 82 commits behind on 2026-07-04): (1) gallery — python3 /root/codex-uploads/build-evidence-index.py ; (2) user-story catalog — python3 /root/codex-uploads/build-story-catalog.py --publish-notion (publishes the Notion page), then BUNDLE the repo twin INTO THIS FEATURE'S MERGE: copy /root/codex-uploads/story-catalog.md to spec/user-stories.md on the FEATURE branch, commit it there ("docs: refresh user-story catalog through <ISSUE>"), and merge the PR only after — so the catalog refresh ships inside the feature's own merge. There is NO standing catalog branch (PR #70 retired 2026-07-04); spec/user-stories.md lives on main and every acceptance refreshes it. Generator canonical source is octo-lite/workflows/lib/build-story-catalog.py (codex-uploads path is a symlink); it regenerates the WHOLE file from every satisfied verdict, so it MUST run on every acceptance or the catalog silently falls behind.`

// ---------- schemas ----------
const IMPL_SCHEMA = { type: 'object', required: ['pr_url', 'branch', 'validation', 'blocked'], properties: {
  pr_url: { type: 'string' }, branch: { type: 'string' }, head: { type: 'string' },
  validation: { type: 'string' }, summary: { type: 'string' }, blocked: { type: 'boolean' }, blocker: { type: 'string' } } }
const REVIEW_SCHEMA = { type: 'object', required: ['verdict', 'findings'], properties: {
  verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
  findings: { type: 'array', items: { type: 'object', required: ['severity', 'title', 'detail'], properties: {
    severity: { enum: ['blocking', 'important', 'nit'] }, title: { type: 'string' }, detail: { type: 'string' } } } },
  review_url: { type: 'string' } } }
const CAPTURE_SCHEMA = { type: 'object', required: ['artifacts', 'flows_covered', 'issues_hit'], properties: {
  artifacts: { type: 'array', items: { type: 'object', required: ['path', 'kind', 'covers'], properties: {
    path: { type: 'string' }, kind: { enum: ['video', 'screenshot', 'manifest', 'other'] }, covers: { type: 'string' } } } },
  flows_covered: { type: 'array', items: { type: 'string' } },
  issues_hit: { type: 'array', items: { type: 'string' } },
  app_state_note: { type: 'string' } } }
const QA_VERDICT_SCHEMA = { type: 'object', required: ['satisfied', 'ac_results', 'summary'], properties: {
  satisfied: { type: 'boolean' },
  ac_results: { type: 'array', items: { type: 'object', required: ['criterion', 'status', 'artifact', 'observed', 'evidence'], properties: {
    criterion: { type: 'string' }, status: { enum: ['pass', 'fail', 'not_evidenced'] },
    // artifact = the exact operator-visible file (screenshot/video-frame path) this verdict rests on.
    // observed = what that artifact LITERALLY shows, described from the pixels (e.g. "lightbox with a
    //   playing <video>, controls at 0:06" vs "lightbox showing a 'Source unavailable' pill"). Writing
    //   this is the forcing function: you cannot grade without having looked. A pass whose `observed`
    //   contradicts the criterion is invalid — code/API/log re-runs are corroboration, never a substitute
    //   for the artifact the operator will see.
    artifact: { type: 'string' }, observed: { type: 'string' },
    evidence: { type: 'string' }, fix_instruction: { type: 'string' } } } },
  edge_cases_checked: { type: 'array', items: { type: 'string' } },
  regressions_checked: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } } }

// ---------- args (A parsed above conventions) ----------
const issue = A.issue
const mode = A.mode ?? 'full'
// QA capture/visual review run ONLY for user-facing / UI-visible issues
// (operator convention 2026-07-12): backend-only work gains nothing from
// browser videos — its gate is code review + validation.
const userFacing = A.user_facing !== false
const userStory = A.user_story ?? '(none provided)'
const ac = Array.isArray(A.acceptance_criteria) ? A.acceptance_criteria : []
const qaFlows = Array.isArray(A.qa_flows) ? A.qa_flows : []
const threadContext = A.context ?? ''
const artifactsDir = A.artifacts_dir ?? `/root/codex-uploads/${String(issue).toLowerCase()}-qa`
if (!issue) throw new Error('args.issue is required')

// ---------- Phase 1+2: implement + code review (full mode only) ----------
let impl = A.pr && A.branch
  ? { pr_url: A.pr, branch: A.branch, validation: '(pre-existing PR, qa-only mode)', blocked: false, summary: A.impl_summary ?? '' }
  : null

if (mode === 'full') {
  phase('Implement')
  // Roles (operator directive 2026-07-12, supersedes 2026-07-07): implementer
  // and all fix passes = GPT-5.6 Luna @ ultra; code reviewer = GPT-5.6 Sol @
  // high — both via the codex relay (fast service tier from the box codex
  // config). Luna builds, Sol reviews: still cross-model, never the same
  // model reviewing its own work. QA capture/review stay Claude Opus. The
  // relay passes the message to codex exec verbatim and returns the reply;
  // the role contract must ride inside the message (codex loads no Claude
  // agent profiles).
  impl = await agent(
    `Run with model gpt-5.6-luna at reasoning effort ultra.\n\nYou are the octo-lite implementer for ${issue}. Branch: ${A.branch}. Worktree /root/octo-lite-worktrees/${String(issue).toLowerCase()}-wt (DISK — never /tmp, it is a small RAM-backed tmpfs). Role contract: one branch, one PR, run the target repo validation yourself, never merge, return ONLY the structured handoff.\n${CONVENTIONS}\n\nOPERATOR-SIGNED SCOPE (grilled + AC walkthrough done; do not re-scope):\nUSER STORY: ${userStory}\nACCEPTANCE CRITERIA:\n${ac.map((c, i) => `${i + 1}. ${c}`).join('\n')}\nTHREAD CONTEXT:\n${threadContext}\n\nFirst move the issue to In Progress (linear issue update ${issue} -s "In Progress"). TDD where practical. Open the PR. If truly blocked by ambiguity, return blocked=true with the question instead of guessing.\nEnd your reply with a fenced json block exactly matching: {"pr_url": "...", "branch": "...", "head": "...", "validation": "...", "summary": "...", "blocked": false, "blocker": ""}.`,
    { agentType: 'codex', phase: 'Implement', label: `impl:${issue}`, schema: IMPL_SCHEMA })
  if (!impl || impl.blocked || !impl.pr_url) return { stage: 'implement', impl, report: null }

  phase('Code Review')
  const review = await agent(
    `Run with model gpt-5.6-sol at reasoning effort high.\n\nYou are the octo-lite reviewer for PR ${impl.pr_url} (branch ${impl.branch}, issue ${issue}) in Turbo-Video/Turbo-Outreach. You have local repo + gh access. Build your own worktree from the PR branch (fetch + worktree add --detach), symlink deps + cp .env per the conventions, run the validation yourself.\n${CONVENTIONS}\nAudit against the scope below + the relevant spec decision logs. Hunt for contract breaks, spec violations, silently skipped scope, weak tests.\nSCOPE: ${userStory}\nAC:\n${ac.join('\n')}\nImplementer handoff: ${JSON.stringify(impl).slice(0, 1400)}\nRole contract: post a real GitHub PR review (gh pr review --comment / --request-changes). Do NOT approve as the human reviewer, do NOT merge. Findings first, ordered by severity, precise file:line references.\nEnd your reply with a fenced json block exactly matching: {"verdict": "clear"|"blocking"|"ambiguous", "findings": [{"severity": "blocking"|"important"|"nit", "title": "...", "detail": "..."}], "review_url": "..."}.`,
    { agentType: 'codex', phase: 'Code Review', label: `review:${issue}`, schema: REVIEW_SCHEMA })

  if (review && review.verdict === 'blocking') {
    phase('Fix')
    const blocking = (review.findings || []).filter(f => f.severity === 'blocking')
    const fix = await agent(
      `Run with model gpt-5.6-luna at reasoning effort ultra.\n\nContinue ${issue} on existing branch ${impl.branch} (PR ${impl.pr_url}). Fix the reviewer's BLOCKING findings on the SAME branch, push, re-validate.\n${CONVENTIONS}\nBLOCKING FINDINGS:\n${JSON.stringify(blocking, null, 1)}\nEnd your reply with a fenced json block exactly matching: {"pr_url": "...", "branch": "...", "head": "...", "validation": "...", "summary": "...", "blocked": false, "blocker": ""}.`,
      { agentType: 'codex', phase: 'Fix', label: `fix:${issue}`, schema: IMPL_SCHEMA })
    if (fix?.pr_url) impl = fix
  }
}

// ---------- Phase 3+4: QA capture → Opus QA review → fix loop ----------
let capture = null
let qaVerdict = null
const MAX_QA_ROUNDS = 2
if (!userFacing) log(`${issue} is backend-only (user_facing=false) — skipping QA capture + visual review; gate = code review + validation. Calling session sets Awaiting Accept with the packet.`)
for (let round = 1; userFacing && round <= MAX_QA_ROUNDS; round += 1) {
  phase('QA Capture')
  capture = await agent(
    `You are the QA-evidence agent for ${issue} (PR ${impl.pr_url}, branch ${impl.branch}). Capture browser evidence of the ACTUAL running app on this branch.\nLEAN CAPTURE (operator convention 2026-07-12): the shortest video per story that proves its ACs — no filler navigation, no flows that no AC or qa_flow references, screenshots only for AC-relevant key states. Lean means fewer/shorter artifacts, never skipped viewports or unproven ACs.\n${QA_APP}\nArtifacts go under ${artifactsDir}/round-${round}/ : at least one narrated-by-action VIDEO (mp4) walking the user story end to end, full-page SCREENSHOTS of each key state, and a manifest.json (url, viewport, flows, artifact list). Name files by what they show — include 'mobile' in mobile artifact filenames. BOTH VIEWPORTS ARE MANDATORY for any UI-touching issue: capture desktop (1440x1000) AND mobile (390x844) for every user-visible flow — a flow without mobile evidence cannot pass its render/regression criteria. Also write ${artifactsDir}/story-map.json: [{story, videos: [relative paths], acs: [numbers], viewports?: ["desktop","mobile"]}] — every video addresses ONE explicitly stated user-voiced story (a video may serve multiple entries), and EVERY STORY carries proof on BOTH viewports (desktop + mobile videos in its list); declare "viewports": ["mobile"] (or ["desktop"]) only for stories inherently single-viewport (e.g. bottom tab bar). The evidence site renders one card per story with a slot per viewport — a missing slot shows an amber "no proof yet" placeholder, so gaps are visible, never hidden. If this round RE-CAPTURES flows from an earlier round (fix round), write a SUPERSEDED file into the earlier round's dir (glob patterns, one per line, '#' comments) matching the redone artifacts — the evidence site's default view must show exactly one current video per use case, covering ALL of them side by side.\nUSER STORY: ${userStory}\nACCEPTANCE CRITERIA (capture evidence FOR EACH):\n${ac.map((c, i) => `${i + 1}. ${c}`).join('\n')}\nQA FLOWS TO EXERCISE:\n${qaFlows.map((f, i) => `${i + 1}. ${f}`).join('\n')}\nBe honest in issues_hit — anything broken, odd, or uncapturable goes there, not papered over. Return the structured result with every artifact path.`,
    { agentType: 'general-purpose', model: 'opus', effort: 'high', phase: 'QA Capture', label: `qa-capture:${issue} r${round}`, schema: CAPTURE_SCHEMA })
  if (!capture) return { stage: 'qa-capture', impl, report: null }

  phase('QA Review')
  qaVerdict = await agent(
    `You are the QA REVIEWER for ${issue}. Judge whether the shipped work satisfies the user story and EVERY acceptance criterion. Your PRIMARY evidence is the pixels the OPERATOR will see: for EACH criterion you must open the specific screenshot (Read it) or extract and Read video frames (ffmpeg -i <mp4> -vf fps=1 <dir>/f%03d.png), then in the verdict's per-AC 'observed' field write what that artifact LITERALLY shows — describe the actual visible content, not what it "should" show. If the visible content contradicts the criterion (e.g. the criterion is "stored reel plays" but the frame shows a "Source unavailable" panel), the status is fail/not_evidenced — no exceptions, no rationalizing from logs. Re-running the API/code or reading state JSON is corroboration ONLY; it can never substitute for looking at the artifact, because a misconfigured harness can make code pass while the operator-visible artifact shows the feature broken (this is exactly how TUR-127 round-1 slipped: the reviewer trusted logs and passed a "Source unavailable" screenshot). You may also open the PR diff (gh pr diff ${impl.pr_url}) and the running app (use the app_url/ports recorded in the capture manifest — each QA pass runs its own isolated env; if it was torn down, provision your own per the QA ENV conventions) to verify claims — but the ARTIFACTS must stand on their own as proof for the operator.\n\nTHREAD CONTEXT (from the operator's session — goals and decisions):\n${threadContext}\nUSER STORY: ${userStory}\nACCEPTANCE CRITERIA:\n${ac.map((c, i) => `${i + 1}. ${c}`).join('\n')}\nCAPTURE RESULT: ${JSON.stringify(capture).slice(0, 3000)}\n\nFor each criterion: pass / fail / not_evidenced (missing evidence = NOT a pass). List the edge cases and regressions you actively checked (e.g. role gating, mobile, empty states, existing flows still intact). If ANY criterion fails or lacks evidence, satisfied=false with a concrete fix_instruction per failure. Be strict — a plausible screenshot is not proof if the flow wasn't exercised. Before returning, WRITE your full verdict JSON to ${artifactsDir}/round-${round}/qa-verdict.json and /root/codex-uploads/qa-verdicts/${issue}.json (mkdir -p first) — the merge gate requires these files. If your verdict is satisfied=true, also move the issue to Awaiting Accept (linear issue update ${issue} -s "Awaiting Accept") — the packet is now in the operator's queue; do NOT set any other state.`,
    { model: 'opus', effort: 'high', phase: 'QA Review', label: `qa-review:${issue} r${round}`, schema: QA_VERDICT_SCHEMA })
  if (!qaVerdict) return { stage: 'qa-review', impl, capture, report: null }
  if (qaVerdict.satisfied) break

  if (round < MAX_QA_ROUNDS) {
    phase('Fix')
    const failures = (qaVerdict.ac_results || []).filter(r => r.status !== 'pass')
    const fix = await agent(
      `Run with model gpt-5.6-luna at reasoning effort ultra.\n\nContinue ${issue} on existing branch ${impl.branch} (PR ${impl.pr_url}). The QA reviewer rejected the work — fix these on the SAME branch, push, re-validate:\n${JSON.stringify(failures, null, 1)}\n${CONVENTIONS}\nEnd your reply with a fenced json block exactly matching: {"pr_url": "...", "branch": "...", "head": "...", "validation": "...", "summary": "...", "blocked": false, "blocker": ""}.`,
      { agentType: 'codex', phase: 'Fix', label: `qa-fix:${issue}`, schema: IMPL_SCHEMA })
    if (fix?.pr_url) impl = fix
  }
}

// ---------- concise operator report ----------
return {
  issue,
  pr: impl.pr_url,
  branch: impl.branch,
  qa_mode: userFacing ? 'visual' : 'skipped-backend-only',
  qa_satisfied: userFacing ? (qaVerdict?.satisfied ?? false) : null,
  report: {
    goals: userStory,
    built: impl.summary,
    proof: (qaVerdict?.ac_results || []).map(r => `${r.status.toUpperCase()}: ${r.criterion} — ${r.evidence}`),
    edge_cases_checked: qaVerdict?.edge_cases_checked ?? [],
    regressions_checked: qaVerdict?.regressions_checked ?? [],
    qa_summary: qaVerdict?.summary ?? '',
  },
  artifacts: (capture?.artifacts || []).map(a => a.path),
  capture_issues: capture?.issues_hit ?? [],
}
