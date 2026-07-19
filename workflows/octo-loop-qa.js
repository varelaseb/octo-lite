import {
  acceptCodeReview,
  acceptImplementation,
  acceptPublication,
  acceptQaReview,
  assertBoundPassResult,
  assertPassReceipt,
  assertReadyEnvelope,
  assertSchema,
  evidenceMode,
} from './lib/gates.mjs'

export const meta = {
  name: 'octo-loop-qa',
  description: 'Deterministic gating for one fresh exact-head delivery pass per invocation',
  whenToUse: 'Shaped Linear work with a resolver-produced pass receipt and a completed octo-launch pass_result',
  phases: [
    { title: 'Implement' },
    { title: 'Code Review' },
    { title: 'Fix' },
    { title: 'QA Capture' },
    { title: 'QA Review' },
    { title: 'Publication Readback' },
  ],
}

// This module performs deterministic gating only. octo-launch launch is the sole LLM
// execution: it bootstraps the exact role, resumes that same verified provider session
// to run the pass, parses the structured result, and binds it to the receipt. The
// caller runs octo-launch first, then invokes this Workflow with the receipt and the
// exact pass_result it printed. This module never spawns a worker session itself.

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

const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: [
    'issue', 'pr_url', 'branch', 'head', 'handoff_url', 'red', 'green',
    'validation', 'blocked', 'receipt', 'launch_revision', 'result_binding',
  ],
  properties: {
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
    receipt: { type: 'string' },
    launch_revision: { type: 'string' },
    result_binding: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: [
    'head', 'verdict', 'findings', 'receipt', 'comment_url', 'bound_inputs',
    'launch_revision', 'result_binding',
  ],
  properties: {
    head: { type: 'string' },
    verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    receipt: { type: 'string' },
    comment_url: { type: 'string' },
    bound_inputs: { type: 'array', items: { type: 'string' } },
    launch_revision: { type: 'string' },
    result_binding: { type: 'string' },
  },
}

const CAPTURE_SCHEMA = {
  type: 'object',
  required: ['head', 'plan', 'manifest', 'artifacts', 'receipt', 'blocked', 'launch_revision', 'result_binding'],
  properties: {
    head: { type: 'string' },
    plan: { type: 'array', items: { type: 'object' } },
    manifest: { type: 'string' },
    artifacts: { type: 'array', items: { type: 'string' } },
    receipt: { type: 'string' },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
    launch_revision: { type: 'string' },
    result_binding: { type: 'string' },
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
  required: [
    'head', 'verdict', 'issue', 'pr', 'manifest', 'criteria', 'receipt', 'packet_url',
    'launch_revision', 'result_binding',
  ],
  properties: {
    head: { type: 'string' },
    verdict: { enum: ['satisfied', 'blocking', 'ambiguous'] },
    issue: { type: 'string' },
    pr: { type: 'string' },
    manifest: { type: 'string' },
    criteria: { type: 'array', items: CRITERION_SCHEMA },
    receipt: { type: 'string' },
    packet_url: { type: 'string' },
    launch_revision: { type: 'string' },
    result_binding: { type: 'string' },
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

// Deterministic gate shared by every mode: validate the fresh-pass receipt, validate
// the mode-specific shape of the already-completed pass_result, independently
// recompute and cross-check its launcher-owned binding, and require the exact
// launch_revision and receipt echo before any per-mode acceptance logic runs.
function boundPass(role, startingHead, schema) {
  const receipt = assertPassReceipt(A.role_receipt, role, startingHead)
  const passResult = assertSchema(schema, required(A.pass_result, 'pass result'), 'pass_result')
  assertBoundPassResult(receipt, passResult)
  if (passResult.launch_revision !== receipt.launch_revision) throw new Error('pass result launch revision mismatch')
  if (passResult.receipt !== receipt.spawn_id) throw new Error('pass result receipt mismatch')
  return { receipt, passResult }
}

if (mode === 'implement') {
  assertReadyEnvelope(A)
  const { receipt, passResult: implementation } = boundPass('implementer', A.shaping_head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'implement', implementation }
  acceptImplementation(A.shaping_head, implementation, receipt.spawn_id, true)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: implementation.head,
    cycle: 1, implementation,
  }
}

if (mode === 'code-review') {
  const head = required(A.head, 'head')
  const reviewCycle = cycle()
  const { receipt, passResult: review } = boundPass('code-reviewer', head, REVIEW_SCHEMA)
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
  const { receipt, passResult: implementation } = boundPass('implementer', head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'fix', implementation }
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
  const { passResult: capture } = boundPass('qa-capture', head, CAPTURE_SCHEMA)
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
  const { passResult: qaReview } = boundPass('qa-reviewer', head, QA_REVIEW_SCHEMA)
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
