import {
  acceptCodeReview,
  acceptImplementation,
  acceptPublication,
  acceptQaReview,
  assertAdmission,
  assertContainment,
  assertLaunchReadback,
  assertLaunchRevision,
  assertReadyEnvelope,
  assertWorkerAckEcho,
  evidenceMode,
  launchRevision,
} from './lib/gates.mjs'

export const meta = {
  name: 'octo-loop-qa',
  description: 'Native workflow-subagent delivery loop: gate, spawn, and bind one fresh exact-head worker pass per invocation',
  whenToUse: 'Shaped or Todo Linear work with a clear exact-head shaping verdict, journalled bound inputs, and a per-pass brief',
  phases: [
    { title: 'Implement' },
    { title: 'Code Review' },
    { title: 'Fix' },
    { title: 'QA Capture' },
    { title: 'QA Review' },
    { title: 'Publication Readback' },
  ],
}

// Decision 109 (operating-model decision-109-workflow-native and decision-109-binding;
// role-runtime launch-correctness-path and role-worker-migration): this Workflow spawns
// every worker role pass natively as a fresh subagent. The retired CLI pass launcher
// and its completed-pass result consumption model are gone. Worker binding proof is
// the workflow journal entry for the spawn plus the schema-forced acknowledgment echo
// of the exact bound inputs, verified before any mutation-phase advance. No worker
// TOML receipt exists. An OpenAI review role runs through a codex relay subagent brief;
// the spawn primitive is the same. Roles resolve through roles.toml; raw adapter files
// are never spawn inputs.

const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const mode = A.mode ?? 'implement'

const PROOF_SCHEMA = {
  type: 'object',
  required: ['command', 'exit_status', 'outcome', 'artifact'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    outcome: { type: 'string' },
    artifact: { type: 'string' },
  },
}

// Schema-forced acknowledgment echo of the exact journalled bound inputs
// (role-runtime launch-identity, launch-receipt; operating-model decision-109-binding).
const ACK_SCHEMA = {
  type: 'object',
  required: ['role', 'repo', 'issue', 'pr', 'starting_head', 'spec_blobs', 'contract_hash'],
  properties: {
    role: { type: 'string' },
    repo: { type: 'string' },
    issue: { type: 'string' },
    pr: { type: 'string' },
    starting_head: { type: 'string' },
    spec_blobs: { type: 'array', items: { type: 'string' } },
    contract_hash: { type: 'string' },
  },
}

const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: [
    'ack', 'issue', 'pr_url', 'branch', 'head', 'handoff_url', 'red', 'green',
    'validation', 'blocked',
  ],
  properties: {
    ack: ACK_SCHEMA,
    issue: { type: 'string' },
    pr_url: { type: 'string' },
    branch: { type: 'string' },
    head: { type: 'string' },
    handoff_url: { type: 'string' },
    red: PROOF_SCHEMA,
    green: PROOF_SCHEMA,
    validation: { type: 'string' },
    summary: { type: 'string' },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'verdict', 'findings', 'comment_url'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    comment_url: { type: 'string' },
  },
}

const CAPTURE_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'plan', 'manifest', 'artifacts', 'blocked'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    plan: { type: 'array', items: { type: 'object' } },
    manifest: { type: 'string' },
    artifacts: { type: 'array', items: { type: 'string' } },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
  },
}

const CRITERION_SCHEMA = {
  type: 'object',
  required: ['criterion', 'status', 'observation'],
  properties: {
    criterion: { type: 'string' },
    status: { enum: ['pass', 'fail', 'not_evidenced'] },
    observation: { type: 'string' },
    artifact: { type: 'string' },
    fix: { type: 'string' },
  },
}

const QA_REVIEW_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'verdict', 'issue', 'pr', 'manifest', 'criteria', 'packet_url'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    verdict: { enum: ['satisfied', 'blocking', 'ambiguous'] },
    issue: { type: 'string' },
    pr: { type: 'string' },
    manifest: { type: 'string' },
    criteria: { type: 'array', items: CRITERION_SCHEMA },
    packet_url: { type: 'string' },
  },
}

const FIRE_SCHEMA = {
  type: 'object',
  required: ['command', 'exit_status', 'readback_state'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    readback_state: { type: 'string' },
  },
}

function required(value, label) {
  if (value === undefined || value === null || value === '') throw new Error(`${label} required`)
  return value
}

function cycle() {
  const value = Number(A.cycle ?? 1)
  if (!Number.isInteger(value) || value < 1 || value > 3) throw new Error('cycle must be 1 through 3')
  return value
}

function specBlobs() {
  if (!Array.isArray(A.spec_blobs) || A.spec_blobs.length === 0) throw new Error('spec blobs required')
  return A.spec_blobs
}

// The exact bound inputs for one worker pass. The workflow journal records this
// object at spawn time; the worker must echo it verbatim in its structured result.
function journalledBoundInputs(role, startingHead) {
  return {
    role,
    repo: required(A.repo, 'repo'),
    issue: required(A.issue, 'issue'),
    pr: required(A.pr, 'pr'),
    starting_head: required(startingHead, 'starting head'),
    spec_blobs: specBlobs(),
    contract_hash: required(A.contract_hash, 'contract hash'),
  }
}

// Shared native spawn path for every worker pass: the admission matrix plus
// Linear-state gate, worktree containment, and launch-revision revalidation run
// before the subagent spawns, the journal records the exact bound inputs, and the
// schema-forced acknowledgment echo plus launch-revision revalidation are verified
// before any mutation-phase advance. Every pass is a fresh subagent; a worker
// session is never resumed.
async function spawnWorker(role, phaseTitle, startingHead, schema) {
  assertAdmission({ purpose: 'delivery', role, linearState: required(A.linear_state, 'linear state') })
  // Containment at admission (launch-containment).
  const worktree = assertContainment(
    required(A.worktree_root, 'worktree root'),
    required(A.worktree, 'worker worktree'),
  )
  const bound = journalledBoundInputs(role, startingHead)
  // Launch-revision revalidation before spawn (launch-entrypoint-revalidation):
  // a journalled revision that mismatches the exact bound inputs spawns nothing.
  const revision = A.launch_revision ?? launchRevision(bound)
  assertLaunchRevision(revision, bound)
  log(`journal spawn ${role} ${bound.issue} ${bound.pr} ${bound.starting_head} ${bound.contract_hash} ${revision}`)
  const brief = required(A.brief, 'pass brief')
  const prompt = [
    `You are a fresh octo-lite ${role}. One pass only. Never reuse a worker session.`,
    'BOUND INPUTS: verify each against your own reads, echo them verbatim as the ack',
    'object in your structured result, and stop before any mutation on any mismatch:',
    JSON.stringify(bound, null, 2),
    brief,
  ].join('\n\n')
  // Containment again at child subagent spawn (launch-containment).
  assertContainment(A.worktree_root, worktree)
  const result = await agent(prompt, { label: `${role}:${bound.issue}`, phase: phaseTitle, schema })
  if (result === null) throw new Error(`${role} pass returned no result`)
  assertWorkerAckEcho(bound, result.ack)
  // Launch-revision revalidation again before any mutation-phase advance.
  assertLaunchRevision(revision, bound)
  return result
}

// Loop fire (delivery-lifecycle linear-loop-fire-transition, delivery-entry-gate):
// the one mechanical Shaped -> Todo transition, performed by this loop through
// octo-control linear-transition before any delivery worker spawns. The runner is
// the owning orchestrator's mechanical helper invocation, not a worker role pass,
// so the role-purpose admission matrix and ack echo do not apply; octo-control
// itself verifies caller authority with compare, mutate, readback, notify.
async function loopFire() {
  const issue = required(A.issue, 'issue')
  const controlArgs = required(A.loop_fire_args, 'loop fire control args')
  const fire = await agent([
    'Run exactly this command from the owning orchestrator context, then report it:',
    `octo-control linear-transition ${issue} --expected Shaped --target Todo ${controlArgs}`,
    'Return command, exit_status, and readback_state (the Linear state read back).',
    'Never substitute a different transition, target, or issue.',
  ].join('\n'), { label: `loop-fire:${issue}`, phase: 'Implement', schema: FIRE_SCHEMA, effort: 'low' })
  if (fire === null || fire.exit_status !== 0) {
    throw new Error('delivery spawn at Shaped rejected: Shaped -> Todo loop fire failed')
  }
  return fire
}

if (mode === 'implement') {
  assertReadyEnvelope(A)
  // Final exact Linear and PR readback before dispatch (launch-readback): fresh reads
  // taken immediately before this invocation are explicit arguments, so a stale
  // self-consistent envelope disagreeing with them never spawns.
  assertLaunchReadback(A, required(A.fresh_reads, 'fresh reads'))
  // Delivery entry: at Shaped this loop performs the Shaped -> Todo loop fire and
  // verifies the Todo readback before the implementer spawns; there is no path to a
  // delivery worker spawn at Shaped without that prior fire. The single ruling-15
  // orchestrator-performed manual Shaped -> Todo for TUR-447 is the one recorded
  // non-recurring exception; every later member fires through this gate.
  if (A.linear_state === 'Shaped') {
    const fired = await loopFire()
    if (fired.readback_state !== 'Todo') {
      throw new Error('delivery spawn at Shaped rejected: Todo readback missing after loop fire')
    }
  }
  const implementation = await spawnWorker('implementer', 'Implement', A.shaping_head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'implement', implementation }
  acceptImplementation(A.shaping_head, implementation, true)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: implementation.head,
    cycle: 1, implementation,
  }
}

if (mode === 'code-review') {
  const head = required(A.head, 'head')
  const reviewCycle = cycle()
  // An OpenAI code reviewer runs through the codex relay subagent brief
  // (role-runtime role-openai-relay); the native spawn and gates are identical.
  const review = await spawnWorker('code-reviewer', 'Code Review', head, REVIEW_SCHEMA)
  if (review.verdict === 'ambiguous') {
    return { stage: 'return-to-shaping', issue: A.issue, head, review }
  }
  const gate = acceptCodeReview(head, A.pr, review)
  if (gate.advance) {
    return { stage: 'code-clear', issue: A.issue, pr: A.pr, head, review, next: evidenceMode(A.user_facing !== false) }
  }
  if (reviewCycle === 3) return { stage: 'return-to-shaping', issue: A.issue, head, review }
  return { stage: 'fix-required', issue: A.issue, head, cycle: reviewCycle, findings: gate.findings }
}

if (mode === 'fix') {
  const head = required(A.head, 'head')
  const reviewCycle = cycle()
  if (reviewCycle >= 3) return { stage: 'return-to-shaping', issue: A.issue, head }
  if (!Array.isArray(A.findings) || A.findings.length === 0) throw new Error('blocking findings required')
  const implementation = await spawnWorker('implementer', 'Fix', head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'fix', implementation }
  acceptImplementation(head, implementation, true)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: implementation.head,
    cycle: reviewCycle + 1, implementation,
  }
}

if (mode === 'evidence') {
  const head = required(A.head, 'head')
  if (!A.code_review || A.code_review.verdict !== 'clear' || A.code_review.head !== head) {
    throw new Error('clear exact-head code review required')
  }
  if (A.user_facing === false) {
    return {
      stage: 'backend-publication-required', issue: A.issue, head,
      required: ['code_review', 'validation', 'story_ids', 'spec_criteria', 'contract_checks'],
      next: 'Publish and read back the exact backend card, then run qa-review.',
    }
  }
  const capture = await spawnWorker('qa-capture', 'QA Capture', head, CAPTURE_SCHEMA)
  if (capture.blocked) return { stage: 'blocked', gate: 'qa-capture', capture }
  if (capture.head !== head) throw new Error('QA capture head mismatch')
  return {
    stage: 'visual-publication-required', issue: A.issue, head, capture,
    next: 'Publish and read back the exact visual card, then run qa-review.',
  }
}

if (mode === 'qa-review') {
  const head = required(A.head, 'head')
  if (
    !A.publication?.readback || A.publication.head !== head
    || !A.publication.packet_url || !A.publication.manifest
  ) {
    throw new Error('exact served publication readback required')
  }
  const qaReview = await spawnWorker('qa-reviewer', 'QA Review', head, QA_REVIEW_SCHEMA)
  if (qaReview.verdict === 'ambiguous') return { stage: 'return-to-shaping', issue: A.issue, head, qa_review: qaReview }
  const gate = acceptQaReview(head, { issue: A.issue, pr: A.pr, manifest: A.publication.manifest }, qaReview)
  return gate.advance
    ? {
        stage: 'verdict-publication-required', issue: A.issue, head, qa_review: qaReview,
        next: 'Publish verdict, read back card, then operator may accept.',
      }
    : { stage: 'fix-required', trigger: 'qa-review', issue: A.issue, head, cycle: cycle(), findings: gate.findings }
}

if (mode === 'publication-readback') {
  const accepted = acceptPublication(
    {
      issue: A.issue, pr: A.pr, head: A.head, story_ids: A.story_ids ?? [],
      acceptance_criteria: A.acceptance_criteria,
    },
    A.publication,
  )
  return {
    stage: 'awaiting-operator-acceptance', issue: A.issue, head: A.head,
    packet_url: accepted.packet_url,
    next: 'Operator may accept or reject. No agent may infer acceptance.',
  }
}

throw new Error(`unknown mode: ${mode}`)
