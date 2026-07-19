import {
  acceptCodeReview,
  acceptPublication,
  acceptQaReview,
  assertReadyEnvelope,
  evidenceMode,
} from './lib/gates.mjs'

export const meta = {
  name: 'octo-loop-qa',
  description: 'Fresh, exact-head implement, review, QA, and acceptance gates',
  whenToUse: 'Shaped Linear work. Pass a resolver-produced envelope. No target policy here.',
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
const mode = A.mode ?? 'delivery'

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

if (mode === 'delivery') {
  assertReadyEnvelope(A)
  phase('Implement')
  let implementation = await agent(
    `Execute the canonical implementer role. Resolve all detail from this exact envelope and its pinned sources. Spec-driven TDD required. Continue the same draft PR. Never merge or change acceptance state. Return only the schema.\n${sourceEnvelope({ starting_head: A.shaping_head, role_receipt: A.role_receipts.implementer })}`,
    {
      agentType: 'implementer',
      phase: 'Implement',
      schema: IMPLEMENT_SCHEMA,
    },
  )
  if (!implementation || implementation.blocked) {
    return { stage: 'blocked', gate: 'implement', implementation }
  }

  let currentHead = implementation.head
  let review = null
  for (let cycle = 1; cycle <= 3; cycle += 1) {
    phase('Code Review')
    review = await agent(
      `Execute the canonical code-reviewer role as a fresh instance. Review exact HEAD. Publish the deterministic verdict comment through the named helper. Never approve or merge. Return only the schema.\n${sourceEnvelope({ expected_head: currentHead, implementation, cycle, role_receipt: A.role_receipts.code_reviewer })}`,
      {
        agentType: 'code-reviewer',
        phase: 'Code Review',
        schema: REVIEW_SCHEMA,
      },
    )
    const gate = acceptCodeReview(currentHead, review)
    if (gate.advance) {
      return {
        stage: 'code-clear',
        issue: A.issue,
        pr: A.pr,
        head: currentHead,
        implementation,
        review,
        next: evidenceMode(A.user_facing !== false),
      }
    }
    if (cycle === 3) {
      return { stage: 'return-to-shaping', issue: A.issue, head: currentHead, review }
    }

    phase('Fix')
    const previousHead = currentHead
    implementation = await agent(
      `Execute the canonical implementer role as a fresh fix instance. Fix only blocking findings on the same draft PR. Add a spec-derived regression red, then green. Return only the schema.\n${sourceEnvelope({ previous_head: previousHead, findings: gate.findings, cycle, role_receipt: A.role_receipts.implementer })}`,
      {
        agentType: 'implementer',
        phase: 'Fix',
        schema: IMPLEMENT_SCHEMA,
      },
    )
    if (!implementation || implementation.blocked) {
      return { stage: 'blocked', gate: 'fix', implementation }
    }
    if (!implementation.head || implementation.head === previousHead) {
      throw new Error('fix must return a new exact HEAD')
    }
    currentHead = implementation.head
  }
}

if (mode === 'evidence') {
  if (!A.code_review || A.code_review.verdict !== 'clear') {
    throw new Error('clear code review required')
  }
  if (A.code_review.head !== A.head) throw new Error('code review HEAD mismatch')
  if (A.user_facing === false) {
    return {
      stage: 'backend-publication-required',
      issue: A.issue,
      head: A.head,
      required: ['code_review', 'validation', 'story_ids', 'spec_criteria', 'contract_checks'],
      next: 'Run target publication helper, read back exact card, then mode=qa-review.',
    }
  }

  phase('QA Capture')
  const capture = await agent(
    `Execute the canonical qa-capture role as a fresh instance. Plan minimum honest proof per criterion. Screenshots default. Video only when stills cannot prove the behavior. Do not publish or mutate any dashboard or tracker. Return only the schema.\n${sourceEnvelope({ expected_head: A.head, code_review: A.code_review, qa_brief: A.qa_brief, role_receipt: A.role_receipts.qa_capture })}`,
    {
      agentType: 'qa-capture',
      phase: 'QA Capture',
      schema: CAPTURE_SCHEMA,
    },
  )
  if (!capture || capture.blocked) return { stage: 'blocked', gate: 'qa-capture', capture }
  if (capture.head !== A.head) throw new Error('QA capture HEAD mismatch')
  return {
    stage: 'visual-publication-required',
    issue: A.issue,
    head: A.head,
    capture,
    next: 'Run target publication helper, read back exact card, then mode=qa-review.',
  }
}

if (mode === 'qa-review') {
  if (!A.publication?.readback || A.publication.head !== A.head || !A.publication.packet_url) {
    throw new Error('exact served publication readback required')
  }
  phase('QA Review')
  const qaReview = await agent(
    `Execute the canonical qa-reviewer role as a fresh instance. Inspect the served packet and every artifact. Grade each criterion. Backend packets receive the same evidence-sufficiency gate. Never mutate Linear, publish, accept, or merge. Return only the schema.\n${sourceEnvelope({ expected_head: A.head, publication: A.publication, role_receipt: A.role_receipts.qa_reviewer })}`,
    {
      agentType: 'qa-reviewer',
      phase: 'QA Review',
      schema: QA_REVIEW_SCHEMA,
    },
  )
  const gate = acceptQaReview(A.head, qaReview)
  return gate.advance
    ? {
        stage: 'verdict-publication-required',
        issue: A.issue,
        head: A.head,
        qa_review: qaReview,
        next: 'Publish verdict, read back card, then operator may accept.',
      }
    : { stage: 'qa-fix-required', issue: A.issue, head: A.head, findings: gate.findings }
}

if (mode === 'publication-readback') {
  const accepted = acceptPublication(
    {
      issue: A.issue,
      pr: A.pr,
      head: A.head,
      story_ids: A.story_ids ?? [],
      acceptance_criteria: A.acceptance_criteria,
    },
    A.publication,
  )
  return {
    stage: 'awaiting-operator-acceptance',
    issue: A.issue,
    head: A.head,
    packet_url: accepted.packet_url,
    next: 'Operator may accept or reject. No agent may infer acceptance.',
  }
}

throw new Error(`unknown mode: ${mode}`)
