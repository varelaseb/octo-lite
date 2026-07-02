// Claude Code Workflow implementation of the octo-lite loop with QA stages
// (see skills/octo-lite-loop/SKILL.md). Install: copy into ~/.claude/workflows/.
// The CONVENTIONS and QA_APP blocks below are per-target configuration
// (currently Turbo-Outreach: repo paths, base branch, demo logins, QA app
// topology) — rewrite them when pointing the loop at a different target repo;
// the phases, schemas, and loop logic are target-agnostic.
export const meta = {
  name: 'octo-loop-qa',
  description: 'Default octo-lite loop with QA: implement → code review → QA video/artifacts → Fable QA review vs user story + AC → fix loop → concise operator report',
  whenToUse: 'Default loop for shaped+ready Linear issues in Turbo-Outreach. args: {issue, branch, pr?, mode: "full"|"qa-only", user_story, acceptance_criteria: [], qa_flows: [], context, artifacts_dir}',
  phases: [
    { title: 'Implement' },
    { title: 'Code Review' },
    { title: 'QA Capture' },
    { title: 'QA Review', detail: 'Fable judges artifacts vs user story + AC' },
    { title: 'Fix' },
  ],
}

// ---------- shared conventions ----------
const CONVENTIONS = `
REPO: /root/Turbo-Outreach-staging (base branch: origin/tur-50-topicfinder-alpha-video-remix-golden-path — PRs target it, NOT main).
WORKTREE (never touch the main tree): git -C /root/Turbo-Outreach-staging worktree add --detach <WT> origin/<branch-or-base>
  Backend deps: ln -s /root/Turbo-Outreach-staging/tools/prospect-report/node_modules <WT>/tools/prospect-report/node_modules
  Client deps:  ln -s /tmp/qa2-wt/tools/prospect-report/client/node_modules <WT>/tools/prospect-report/client/node_modules
  Env: cp /root/Turbo-Outreach-staging/tools/prospect-report/.env <WT>/tools/prospect-report/.env
Validation: client vitest run + tsc -p client/tsconfig.json --noEmit; backend node --test for touched suites; scripts/lint-architecture.js when boundaries move.
COMMITS end with:
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
PR body references the Linear key ("Tracks <ISSUE>"). Do NOT merge — the operator watches the QA evidence videos (see EVIDENCE SITE) and the merge happens only after that human acceptance plus the merge-gate checks.
SPECS are law: read the relevant spec/domains/*.md decision logs before changing behavior. Return ONLY the structured result.`

const QA_APP = `
QA APP (shared demo stack — reuse it, do not build a parallel one):
- Worktree /tmp/qa2-wt serves the app: Vite dev on :5173 (live-reloads on checkout), API on :3000.
- To QA a PR branch: git -C /tmp/qa2-wt fetch origin <branch> && git -C /tmp/qa2-wt checkout -f -B qa-under-test origin/<branch>. Vite picks it up live. If backend files changed, restart the API: find it (ss -tlnp | grep :3000), kill it, then from /tmp/qa2-wt/tools/prospect-report run: nohup node src/index.js > /tmp/qa-api.log 2>&1 & (env loads from its .env). Verify http://127.0.0.1:3000/api/health then http://127.0.0.1:5173.
- AFTER QA: leave the branch checked out (the operator's agent restores tur-50 after merge).
- Demo login: client@local.test / LocalDevPass123! (post-first-run user, role=client). Pre-first-run logins (verify first-run chrome): qa-topicfinder-full-20260630b@local.test or ...c@local.test / LocalDevPass123!. These fixtures are CONSUMABLE — completing onboarding/first-run burns them (qa-topicfinder-full-20260630d is already burned, completed 2026-07-01). Verify state first: SELECT current_step, completed_at FROM topicfinder_onboarding_progress (docker exec turbo-outreach-postgres psql -U postgres -d prospect_report).
- Playwright is installed at /tmp/qa-evidence-playwright (import { chromium } from 'playwright'; launch args ['--no-sandbox']). Record video via context recordVideo + convert webm→mp4 with ffmpeg (-c:v libx264 -pix_fmt yuv420p -movflags +faststart). Full-page screenshots for key states; mobile = viewport 390x844, desktop = 1440x1000.
- EVIDENCE SITE: python3 -m http.server 8080 serves /root/codex-uploads/topicfinder-FINAL-20260701 at http://147.182.226.89:8080. Symlink the issue's artifacts dir into that root (ln -sfn <artifacts_dir> /root/codex-uploads/topicfinder-FINAL-20260701/<basename>), then REBUILD THE GALLERY: python3 /root/codex-uploads/build-evidence-index.py (regenerates index.html + video posters; the operator browses the gallery, not raw listings). The operator reviews videos at these URLs BEFORE any merge — human acceptance of the artifacts is part of the merge gate. Include the URLs in the returned artifact list.
- UPON MERGE (operator's agent, after acceptance): drop a Linear comment on the issue with the evidence-site link and the report packet (per-AC proof, edge cases/regressions checked, merge commit). Link video URLs; do not upload video files to Linear.`

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
  ac_results: { type: 'array', items: { type: 'object', required: ['criterion', 'status', 'evidence'], properties: {
    criterion: { type: 'string' }, status: { enum: ['pass', 'fail', 'not_evidenced'] },
    evidence: { type: 'string' }, fix_instruction: { type: 'string' } } } },
  edge_cases_checked: { type: 'array', items: { type: 'string' } },
  regressions_checked: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } } }

// ---------- args ----------
const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const issue = A.issue
const mode = A.mode ?? 'full'
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
  impl = await agent(
    `You are the octo-lite implementer for ${issue}. Branch: ${A.branch}. Worktree /tmp/${String(issue).toLowerCase()}-wt.\n${CONVENTIONS}\n\nOPERATOR-SIGNED SCOPE (grilled + AC walkthrough done; do not re-scope):\nUSER STORY: ${userStory}\nACCEPTANCE CRITERIA:\n${ac.map((c, i) => `${i + 1}. ${c}`).join('\n')}\nTHREAD CONTEXT:\n${threadContext}\n\nTDD where practical. Open the PR. If truly blocked by ambiguity, return blocked=true with the question instead of guessing.`,
    { agentType: 'octo-lite-implementer', model: 'opus', effort: 'high', phase: 'Implement', label: `impl:${issue}`, schema: IMPL_SCHEMA })
  if (!impl || impl.blocked || !impl.pr_url) return { stage: 'implement', impl, report: null }

  phase('Code Review')
  const review = await agent(
    `You are the octo-lite reviewer. Audit PR ${impl.pr_url} (branch ${impl.branch}) for ${issue} in Turbo-Video/Turbo-Outreach. Build your own worktree from the PR branch (fetch + worktree add --detach), symlink deps + cp .env per the conventions, run the validation yourself.\n${CONVENTIONS}\nAudit against the scope below + the relevant spec decision logs. Hunt for contract breaks, spec violations, silently skipped scope, weak tests.\nSCOPE: ${userStory}\nAC:\n${ac.join('\n')}\nImplementer handoff: ${JSON.stringify(impl).slice(0, 1400)}\nPost a real GitHub PR review (gh pr review --comment / --request-changes). Do NOT approve as the human reviewer, do NOT merge. Return the structured verdict.`,
    { agentType: 'octo-lite-reviewer', model: 'opus', effort: 'xhigh', phase: 'Code Review', label: `review:${issue}`, schema: REVIEW_SCHEMA })

  if (review && review.verdict === 'blocking') {
    phase('Fix')
    const blocking = (review.findings || []).filter(f => f.severity === 'blocking')
    const fix = await agent(
      `Continue ${issue} on existing branch ${impl.branch} (PR ${impl.pr_url}). Fix the reviewer's BLOCKING findings on the SAME branch, push, re-validate.\n${CONVENTIONS}\nBLOCKING FINDINGS:\n${JSON.stringify(blocking, null, 1)}`,
      { agentType: 'octo-lite-implementer', model: 'opus', effort: 'high', phase: 'Fix', label: `fix:${issue}`, schema: IMPL_SCHEMA })
    if (fix?.pr_url) impl = fix
  }
}

// ---------- Phase 3+4: QA capture → Fable QA review → fix loop ----------
let capture = null
let qaVerdict = null
const MAX_QA_ROUNDS = 2
for (let round = 1; round <= MAX_QA_ROUNDS; round += 1) {
  phase('QA Capture')
  capture = await agent(
    `You are the QA-evidence agent for ${issue} (PR ${impl.pr_url}, branch ${impl.branch}). Capture browser evidence of the ACTUAL running app on this branch.\n${QA_APP}\nArtifacts go under ${artifactsDir}/round-${round}/ : at least one narrated-by-action VIDEO (mp4) walking the user story end to end, full-page SCREENSHOTS of each key state (desktop AND mobile where UI changed), and a manifest.json (url, viewport, flows, artifact list). Name files by what they show. If this round RE-CAPTURES flows from an earlier round (fix round), write a SUPERSEDED file into the earlier round's dir (glob patterns, one per line, '#' comments) matching the redone artifacts — the evidence site's default view must show exactly one current video per use case, covering ALL of them side by side.\nUSER STORY: ${userStory}\nACCEPTANCE CRITERIA (capture evidence FOR EACH):\n${ac.map((c, i) => `${i + 1}. ${c}`).join('\n')}\nQA FLOWS TO EXERCISE:\n${qaFlows.map((f, i) => `${i + 1}. ${f}`).join('\n')}\nBe honest in issues_hit — anything broken, odd, or uncapturable goes there, not papered over. Return the structured result with every artifact path.`,
    { agentType: 'general-purpose', model: 'opus', effort: 'high', phase: 'QA Capture', label: `qa-capture:${issue} r${round}`, schema: CAPTURE_SCHEMA })
  if (!capture) return { stage: 'qa-capture', impl, report: null }

  phase('QA Review')
  qaVerdict = await agent(
    `You are the QA REVIEWER for ${issue}. Judge whether the shipped work satisfies the user story and EVERY acceptance criterion, using the QA artifacts as primary evidence (Read the screenshots; for videos, extract frames with ffmpeg -i <mp4> -vf fps=1 <dir>/f%03d.png and Read those). You may also open the PR diff (gh pr diff ${impl.pr_url}) and the running app (${'http://127.0.0.1:5173'}) to verify claims — but the ARTIFACTS must stand on their own as proof for the operator.\n\nTHREAD CONTEXT (from the operator's session — goals and decisions):\n${threadContext}\nUSER STORY: ${userStory}\nACCEPTANCE CRITERIA:\n${ac.map((c, i) => `${i + 1}. ${c}`).join('\n')}\nCAPTURE RESULT: ${JSON.stringify(capture).slice(0, 3000)}\n\nFor each criterion: pass / fail / not_evidenced (missing evidence = NOT a pass). List the edge cases and regressions you actively checked (e.g. role gating, mobile, empty states, existing flows still intact). If ANY criterion fails or lacks evidence, satisfied=false with a concrete fix_instruction per failure. Be strict — a plausible screenshot is not proof if the flow wasn't exercised.`,
    { model: 'fable', effort: 'high', phase: 'QA Review', label: `qa-review:${issue} r${round}`, schema: QA_VERDICT_SCHEMA })
  if (!qaVerdict) return { stage: 'qa-review', impl, capture, report: null }
  if (qaVerdict.satisfied) break

  if (round < MAX_QA_ROUNDS) {
    phase('Fix')
    const failures = (qaVerdict.ac_results || []).filter(r => r.status !== 'pass')
    const fix = await agent(
      `Continue ${issue} on existing branch ${impl.branch} (PR ${impl.pr_url}). The QA reviewer rejected the work — fix these on the SAME branch, push, re-validate:\n${JSON.stringify(failures, null, 1)}\n${CONVENTIONS}`,
      { agentType: 'octo-lite-implementer', model: 'opus', effort: 'high', phase: 'Fix', label: `qa-fix:${issue}`, schema: IMPL_SCHEMA })
    if (fix?.pr_url) impl = fix
  }
}

// ---------- concise operator report ----------
return {
  issue,
  pr: impl.pr_url,
  branch: impl.branch,
  qa_satisfied: qaVerdict?.satisfied ?? false,
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
