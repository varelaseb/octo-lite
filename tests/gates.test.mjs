import test from 'node:test'
import assert from 'node:assert/strict'

import {
  acceptCodeReview,
  acceptQaReview,
  acceptImplementation,
  acceptPublication,
  assertPassReceipt,
  assertReadyEnvelope,
  evidenceMode,
} from '../workflows/lib/gates.mjs'

const ready = {
  issue: 'TUR-1',
  repo: '/repo',
  pr: 'https://example.test/pr/1',
  branch: 'octo-lite/tur-1',
  shaping_head: 'aaa',
  spec_revision: 'spec-1',
  linear_revision: 'linear-1',
  linear_fingerprint: 'lfp-1',
  linear_state: 'Shaped',
  pr_head: 'aaa',
  pr_base: 'main',
  topology_revision: 2,
  shaping_verdict: 'clear',
  shaping_verdict_head: 'aaa',
  shaping_verdict_inputs: ['linear:lfp-1', 'spec:spec-1', 'log:6824'],
  shaping_reviewer_receipt: 'review-session-1',
  spec_blobs: ['spec/domains/operating-model.spec.html:spec-1'],
  adr_blobs: [],
  conversation_cutoff: 'session.jsonl:6824',
  role_receipts: { implementer: 'r1', code_reviewer: 'r2', qa_reviewer: 'r3' },
  acceptance_criteria: ['works'],
}

test('ready envelope rejects stale shaping head', () => {
  assert.throws(
    () => assertReadyEnvelope({ ...ready, shaping_verdict_head: 'old' }),
    /shaping verdict head/,
  )
})

test('ready envelope rejects wrong lifecycle and incomplete bindings', () => {
  assert.throws(() => assertReadyEnvelope({ ...ready, linear_state: 'Ideas' }), /Linear state/)
  assert.throws(() => assertReadyEnvelope({ ...ready, spec_blobs: [] }), /spec blobs/)
  assert.throws(() => assertReadyEnvelope({ ...ready, pr_head: 'old' }), /PR head/)
})

test('pass receipt binds fresh role and exact starting head', () => {
  const receipt = {
    spawn_id: 'spawn-1',
    ready: true,
    role: { name: 'implementer' },
    workspace: { starting_head: 'abc' },
    bootstrap: { verified: true },
  }
  assert.deepEqual(assertPassReceipt(receipt, 'implementer', 'abc'), receipt)
  assert.throws(() => assertPassReceipt(receipt, 'code-reviewer', 'abc'), /role/)
  assert.throws(() => assertPassReceipt(receipt, 'implementer', 'old'), /starting HEAD/)
  assert.throws(
    () => assertPassReceipt({ ...receipt, bootstrap: { verified: false } }, 'implementer', 'abc'),
    /bootstrap/,
  )
})

test('implementation requires TDD evidence, exact receipt, and new fix head', () => {
  const result = {
    head: 'def', receipt: 'spawn-1', red: 'fails', green: 'passes', validation: 'suite', blocked: false,
  }
  assert.deepEqual(acceptImplementation('abc', result, 'spawn-1', true), result)
  assert.throws(() => acceptImplementation('abc', { ...result, red: '' }, 'spawn-1', true), /red/)
  assert.throws(() => acceptImplementation('abc', { ...result, receipt: 'old' }, 'spawn-1', true), /receipt/)
  assert.throws(() => acceptImplementation('abc', { ...result, head: 'abc' }, 'spawn-1', true), /new HEAD/)
})

test('code review rejects wrong head, ambiguous, and missing receipt', () => {
  assert.throws(
    () => acceptCodeReview('abc', { head: 'old', verdict: 'clear', receipt: 'x', comment_url: 'u' }),
    /HEAD/,
  )
  assert.throws(
    () => acceptCodeReview('abc', { head: 'abc', verdict: 'ambiguous', receipt: 'x', comment_url: 'u' }),
    /ambiguous/,
  )
  assert.throws(
    () => acceptCodeReview('abc', { head: 'abc', verdict: 'clear', comment_url: 'u' }),
    /receipt/,
  )
})

test('blocking review never advances', () => {
  assert.deepEqual(
    acceptCodeReview('abc', {
      head: 'abc', verdict: 'blocking', receipt: 'x', comment_url: 'u', findings: ['fix'],
    }),
    { advance: false, findings: ['fix'] },
  )
})

test('backend work still requires fresh qa review', () => {
  assert.equal(evidenceMode(false), 'nonvisual')
  assert.deepEqual(
    acceptQaReview('abc', {
      head: 'abc', verdict: 'satisfied', receipt: 'qa-1', packet_url: 'https://evidence.test/1',
    }),
    { advance: true, packet_url: 'https://evidence.test/1' },
  )
})

test('qa review rejects wrong head and missing served packet', () => {
  assert.throws(
    () => acceptQaReview('abc', { head: 'old', verdict: 'satisfied', receipt: 'x', packet_url: 'u' }),
    /HEAD/,
  )
  assert.throws(
    () => acceptQaReview('abc', { head: 'abc', verdict: 'satisfied', receipt: 'x' }),
    /served packet/,
  )
})

test('final publication readback binds the complete acceptance card', () => {
  const publication = {
    readable: true,
    issue: 'TUR-1',
    pr: 'https://example.test/pr/1',
    head: 'abc',
    verdict: 'satisfied',
    story_ids: ['TF-US-1-01'],
    criteria_covered: ['works'],
    packet_url: 'https://evidence.test/1',
  }
  assert.deepEqual(
    acceptPublication({ issue: 'TUR-1', pr: publication.pr, head: 'abc', story_ids: publication.story_ids, acceptance_criteria: ['works'] }, publication),
    { packet_url: publication.packet_url },
  )
  assert.throws(
    () => acceptPublication({ issue: 'TUR-1', pr: publication.pr, head: 'abc', story_ids: publication.story_ids, acceptance_criteria: ['works', 'missing'] }, publication),
    /criterion coverage/,
  )
})
