import {
  acceptCodeReview,
  acceptImplementation,
  acceptPublication,
  acceptQaReview,
  assertPassReceipt,
  assertReadyEnvelope,
  evidenceMode,
} from './lib/gates.mjs'

export const meta = {
  name: 'octo-loop-qa',
  description: 'One fresh exact-head delivery pass per invocation',
  whenToUse: 'Shaped Linear work with a resolver-produced pass receipt',
  phases: [
    { title: 'Implement' },
    { title: 'Code Review' },
    { title: 'Fix' },
    { title: 'QA Capture' },
    { title: 'QA Review' },
    { title: 'Publication Readback' },
  ],
}

const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const mode = A.mode ?? 'implement'

const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: [
    'issue', 'pr_url', 'branch', 'head', 'handoff_url', 'red', 'green',
    'validation', 'blocked', 'receipt',
  ],
  properties: {
    issue: { type: 'string' },
    pr_url: { type: 'string' },
    branch: { type: 'string' },
    head: { type: 'string' },
    handoff_url: { type: 'string' },
    red: { type: 'string' },
    green: { type: 'string' },
    validation: { type: 'string' },
    summary: { type: 'string' },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
    receipt: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['head', 'verdict', 'findings', 'receipt', 'comment_url'],
  properties: {
    head: { type: 'string' },
    verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    receipt: { type: 'string' },
    comment_url: { type: 'string' },
  },
}

const CAPTURE_SCHEMA = {
  type: 'object',
  required: ['head', 'plan', 'manifest', 'artifacts', 'receipt', 'blocked'],
  properties: {
    head: { type: 'string' },
    plan: { type: 'array', items: { type: 'object' } },
    manifest: { type: 'string' },
    artifacts: { type: 'array', items: { type: 'string' } },
    receipt: { type: 'string' },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
  },
}

const QA_REVIEW_SCHEMA = {
  type: 'object',
  required: ['head', 'verdict', 'findings', 'receipt', 'packet_url'],
  properties: {
    head: { type: 'string' },
    verdict: { enum: ['satisfied', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    receipt: { type: 'string' },
    packet_url: { type: 'string' },
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

function passReceipt(role, head) {
  return assertPassReceipt(A.role_receipt, role, head)
}

function sourceEnvelope(extra = {}) {
  return JSON.stringify({
    issue: A.issue,
    repo: A.repo,
    pr: A.pr,
    branch: A.branch,
    linear_revision: A.linear_revision,
    spec_revision: A.spec_revision,
    target_instructions_revision: A.target_instructions_revision,
    topology_revision: A.topology_revision,
    acceptance_criteria: A.acceptance_criteria,
    story_ids: A.story_ids ?? [],
    ...extra,
  })
}

if (mode === 'implement') {
  assertReadyEnvelope(A)
  const receipt = passReceipt('implementer', A.shaping_head)
  phase('Implement')
  const implementation = await agent(
    `Implement one pass from the verified receipt. Spec-driven red, green, refactor required. Continue the same draft PR. Never merge or change acceptance state. Return only the schema.\n${sourceEnvelope({ starting_head: A.shaping_head, receipt: receipt.spawn_id })}`,
    { agentType: 'implementer', phase: 'Implement', schema: IMPLEMENT_SCHEMA },
  )
  if (!implementation || implementation.blocked) return { stage: 'blocked', gate: 'implement', implementation }
  acceptImplementation(A.shaping_head, implementation, receipt.spawn_id, true)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: implementation.head,
    cycle: 1, implementation,
  }
}

if (mode === 'code-review') {
  const head = required(A.head, 'head')
  const reviewCycle = cycle()
  const receipt = passReceipt('code-reviewer', head)
  phase('Code Review')
  const review = await agent(
    `Review exact HEAD from the verified receipt. Publish the deterministic verdict comment. Never approve or merge. Return only the schema.\n${sourceEnvelope({ expected_head: head, cycle: reviewCycle, receipt: receipt.spawn_id })}`,
    { agentType: 'code-reviewer', phase: 'Code Review', schema: REVIEW_SCHEMA },
  )
  if (review?.receipt !== receipt.spawn_id) throw new Error('code review receipt mismatch')
  if (review?.verdict === 'ambiguous') {
    return { stage: 'return-to-shaping', issue: A.issue, head, review }
  }
  const gate = acceptCodeReview(head, review)
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
  const receipt = passReceipt('implementer', head)
  phase('Fix')
  const implementation = await agent(
    `Fix only the bound findings on the same draft PR. Start with a spec-derived regression red, then green and refactor. Return only the schema.\n${sourceEnvelope({ previous_head: head, findings: A.findings, trigger: A.trigger ?? 'code-review', receipt: receipt.spawn_id })}`,
    { agentType: 'implementer', phase: 'Fix', schema: IMPLEMENT_SCHEMA },
  )
  if (!implementation || implementation.blocked) return { stage: 'blocked', gate: 'fix', implementation }
  acceptImplementation(head, implementation, receipt.spawn_id, true)
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
  const receipt = passReceipt('qa-capture', head)
  phase('QA Capture')
  const capture = await agent(
    `Capture minimum honest proof per criterion from the verified receipt. Screenshots default. Video only when stills cannot prove behavior. Never publish or mutate tracker state. Return only the schema.\n${sourceEnvelope({ expected_head: head, qa_brief: A.qa_brief, receipt: receipt.spawn_id })}`,
    { agentType: 'qa-capture', phase: 'QA Capture', schema: CAPTURE_SCHEMA },
  )
  if (!capture || capture.blocked) return { stage: 'blocked', gate: 'qa-capture', capture }
  if (capture.head !== head || capture.receipt !== receipt.spawn_id) throw new Error('QA capture binding mismatch')
  return {
    stage: 'visual-publication-required', issue: A.issue, head, capture,
    next: 'Publish and read back the exact visual card, then run qa-review.',
  }
}

if (mode === 'qa-review') {
  const head = required(A.head, 'head')
  if (!A.publication?.readback || A.publication.head !== head || !A.publication.packet_url) {
    throw new Error('exact served publication readback required')
  }
  const receipt = passReceipt('qa-reviewer', head)
  phase('QA Review')
  const qaReview = await agent(
    `Inspect the served packet and every artifact from the verified receipt. Grade each criterion. Backend packets use the same sufficiency gate. Never publish, accept, merge, or mutate Linear. Return only the schema.\n${sourceEnvelope({ expected_head: head, publication: A.publication, receipt: receipt.spawn_id })}`,
    { agentType: 'qa-reviewer', phase: 'QA Review', schema: QA_REVIEW_SCHEMA },
  )
  if (qaReview?.receipt !== receipt.spawn_id) throw new Error('QA review receipt mismatch')
  if (qaReview?.verdict === 'ambiguous') return { stage: 'return-to-shaping', issue: A.issue, head, qa_review: qaReview }
  const gate = acceptQaReview(head, qaReview)
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
