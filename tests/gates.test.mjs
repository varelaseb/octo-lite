import test from 'node:test'
import assert from 'node:assert/strict'

import {
  acceptCodeReview,
  assertAdmission,
  acceptQaReview,
  acceptImplementation,
  acceptPublication,
  assertBoundPassResult,
  assertPassReceipt,
  assertReadyEnvelope,
  assertSchema,
  assertWorkerAckEcho,
  evidenceMode,
  exactFingerprint,
} from '../workflows/lib/gates.mjs'

// Spec: role-runtime launch-role-purpose-capability, launch-purpose-shaping-roles,
// launch-purpose-delivery-roles, launch-purpose-reconcile, launch-gates-workflow-layer
// (blob spec/domains/role-runtime.spec.html:e1265b3c5d0a464ed416de283e11069e4796b01a).
test('shaping-review admits only shaping-reviewer or orchestrator with resolved shaping capability', () => {
  assert.deepEqual(
    assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer' }),
    { purpose: 'shaping-review', role: 'shaping-reviewer' },
  )
  assert.deepEqual(
    assertAdmission({ purpose: 'shaping-review', role: 'orchestrator', capabilities: ['shaping', 'grill'] }),
    { purpose: 'shaping-review', role: 'orchestrator' },
  )
  assert.throws(
    () => assertAdmission({ purpose: 'shaping-review', role: 'orchestrator', capabilities: ['grill'] }),
    /shaping-review/,
  )
  assert.throws(
    () => assertAdmission({ purpose: 'shaping-review', role: 'orchestrator' }),
    /shaping-review/,
  )
  for (const role of ['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer', 'reconciler', 'meta-operator']) {
    assert.throws(
      () => assertAdmission({ purpose: 'shaping-review', role, capabilities: ['shaping'] }),
      /shaping-review/,
    )
  }
})

test('delivery admits only implementer, code-reviewer, qa-capture, and qa-reviewer', () => {
  for (const role of ['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer']) {
    assert.deepEqual(assertAdmission({ purpose: 'delivery', role }), { purpose: 'delivery', role })
  }
  for (const role of ['shaping-reviewer', 'orchestrator', 'reconciler', 'meta-operator']) {
    assert.throws(
      () => assertAdmission({ purpose: 'delivery', role, capabilities: ['shaping'] }),
      /delivery/,
    )
  }
})

test('reconcile admits only reconciler as a Read-restricted subagent', () => {
  assert.deepEqual(
    assertAdmission({ purpose: 'reconcile', role: 'reconciler', readRestricted: true }),
    { purpose: 'reconcile', role: 'reconciler' },
  )
  assert.throws(
    () => assertAdmission({ purpose: 'reconcile', role: 'reconciler', readRestricted: false }),
    /Read-restricted/,
  )
  assert.throws(
    () => assertAdmission({ purpose: 'reconcile', role: 'reconciler' }),
    /Read-restricted/,
  )
  for (const role of ['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer', 'shaping-reviewer', 'orchestrator', 'meta-operator']) {
    assert.throws(
      () => assertAdmission({ purpose: 'reconcile', role, readRestricted: true }),
      /reconcile/,
    )
  }
})

test('admission fails closed on any purpose outside the matrix and on missing identity', () => {
  assert.throws(() => assertAdmission({ purpose: 'merge', role: 'implementer' }), /purpose/)
  assert.throws(() => assertAdmission({ purpose: '', role: 'implementer' }), /purpose/)
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: '' }), /role/)
})

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
  conversation_log_references: ['session.jsonl:1-6824'],
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
  assert.throws(
    () => assertReadyEnvelope({ ...ready, conversation_log_references: [] }),
    /conversation log references/,
  )
})

function fullReceipt() {
  return {
    spawn_id: 'spawn-1',
    parent: 'issue-orchestrator',
    reply_route: 'herdr:issue-orchestrator',
    ready: true,
    purpose: 'delivery',
    launch_revision: 'rev-1',
    role: { name: 'implementer', contract_blob: 'blob-1', mapping_revision: 'map-1' },
    runtime: { provider: 'anthropic', model: 'claude-sonnet-5' },
    skills: { resolved: ['tdd', 'commit'], blobs: ['sblob-1', 'sblob-2'] },
    workspace: { starting_head: 'abc', repo: '/repo', instructions_blob: 'iblob-1' },
    issue: { identifier: 'TUR-1', fingerprint: 'fp-1' },
    spec: { revision: 'spec-1', blobs: ['spec/domain.spec.html:spec-1'] },
    pull_request: { url: 'https://example.test/pr/1', head: 'abc' },
    topology: { revision: 2 },
    prior_gates: { shaping_verdict: 'clear', acceptance_criteria: ['works'] },
    access: { execution_location: 'remote', operator_loopback: false },
    resources: { branch: 'feature' },
    bootstrap: { verified: true, provider_session_id: 'provider-session-1' },
  }
}

test('pass receipt binds fresh role and exact starting head', () => {
  const receipt = fullReceipt()
  assert.deepEqual(assertPassReceipt(receipt, 'implementer', 'abc'), receipt)
  assert.throws(() => assertPassReceipt(receipt, 'code-reviewer', 'abc'), /role/)
  assert.throws(() => assertPassReceipt(receipt, 'implementer', 'old'), /starting HEAD/)
  assert.throws(
    () => assertPassReceipt({ ...receipt, bootstrap: { verified: false } }, 'implementer', 'abc'),
    /bootstrap/,
  )
})

test('an exact registry-resolved empty skill set is a valid qa-reviewer receipt, not a gate failure', () => {
  const receipt = { ...fullReceipt(), role: { name: 'qa-reviewer', contract_blob: 'blob-1', mapping_revision: 'map-1' }, skills: { resolved: [], blobs: [] } }
  assert.deepEqual(assertPassReceipt(receipt, 'qa-reviewer', 'abc'), receipt)
})

test('a nonempty skill list still requires exactly one blob per resolved skill', () => {
  const receipt = { ...fullReceipt(), skills: { resolved: ['tdd'], blobs: [] } }
  assert.throws(() => assertPassReceipt(receipt, 'implementer', 'abc'), /skill blobs/)
  const missingField = { ...fullReceipt(), skills: {} }
  assert.throws(() => assertPassReceipt(missingField, 'implementer', 'abc'), /resolved skills/)
})

test('pass receipt requires the complete bound-input set, not a decorative subset', () => {
  const receipt = fullReceipt()
  assert.throws(
    () => assertPassReceipt({ ...receipt, bootstrap: { verified: true, provider_session_id: '' } }, 'implementer', 'abc'),
    /provider session/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, skills: { resolved: ['tdd'], blobs: [] } }, 'implementer', 'abc'),
    /skill blobs/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, issue: {} }, 'implementer', 'abc'),
    /issue/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, spec: { revision: '', blobs: [] } }, 'implementer', 'abc'),
    /spec/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, pull_request: { url: '', head: 'abc' } }, 'implementer', 'abc'),
    /pull request/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, topology: {} }, 'implementer', 'abc'),
    /topology/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, prior_gates: {} }, 'implementer', 'abc'),
    /prior gates/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, access: {} }, 'implementer', 'abc'),
    /access/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, resources: {} }, 'implementer', 'abc'),
    /resources/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, launch_revision: '' }, 'implementer', 'abc'),
    /launch revision/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, parent: '' }, 'implementer', 'abc'),
    /parent/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, reply_route: '' }, 'implementer', 'abc'),
    /reply route/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, workspace: { starting_head: 'abc', repo: '/repo', instructions_blob: '' } }, 'implementer', 'abc'),
    /instructions blob/,
  )
  assert.throws(
    () => assertPassReceipt({ ...receipt, role: { name: 'implementer', contract_blob: '', mapping_revision: 'map-1' } }, 'implementer', 'abc'),
    /contract blob/,
  )
})

const BINDING = 'a'.repeat(64)

function proof(overrides = {}) {
  return {
    command: 'python3 -m unittest tests.test_launch',
    exit_status: 1,
    outcome: 'ModuleNotFoundError: no module named octo_lite.launch',
    artifact: 'https://example.test/pr/1#issuecomment-1',
    ...overrides,
  }
}

test('implementation requires TDD evidence, exact receipt, new fix head, and exact output binding', () => {
  const result = {
    head: 'def', receipt: 'spawn-1', validation: 'suite', blocked: false,
    red: proof(),
    green: proof({ exit_status: 0, outcome: 'OK', artifact: 'https://example.test/pr/1#issuecomment-2' }),
    result_binding: BINDING,
  }
  assert.deepEqual(acceptImplementation('abc', result, 'spawn-1', true), result)
  assert.throws(() => acceptImplementation('abc', { ...result, red: null }, 'spawn-1', true), /red/)
  assert.throws(
    () => acceptImplementation('abc', { ...result, red: proof({ command: '' }) }, 'spawn-1', true),
    /red/,
  )
  assert.throws(
    () => acceptImplementation('abc', { ...result, red: proof({ exit_status: 0 }) }, 'spawn-1', true),
    /red must fail/,
  )
  assert.throws(
    () => acceptImplementation('abc', { ...result, green: proof({ exit_status: 1 }) }, 'spawn-1', true),
    /green must pass/,
  )
  assert.throws(() => acceptImplementation('abc', { ...result, receipt: 'old' }, 'spawn-1', true), /receipt/)
  assert.throws(() => acceptImplementation('abc', { ...result, head: 'abc' }, 'spawn-1', true), /new HEAD/)
  assert.throws(
    () => acceptImplementation('abc', { ...result, result_binding: 'not-a-hash' }, 'spawn-1', true),
    /result binding/,
  )
})

const PR = 'https://example.test/pr/1'

function reviewFixture(overrides = {}) {
  return {
    head: 'abc', verdict: 'clear', receipt: 'x', comment_url: `${PR}#issuecomment-1`,
    bound_inputs: ['spec:blob1', 'implementer-receipt:spawn-1'], result_binding: BINDING,
    ...overrides,
  }
}

test('code review rejects wrong head, ambiguous, missing receipt, and unbound output', () => {
  assert.throws(() => acceptCodeReview('abc', PR, reviewFixture({ head: 'old' })), /HEAD/)
  assert.throws(() => acceptCodeReview('abc', PR, reviewFixture({ verdict: 'ambiguous' })), /ambiguous/)
  assert.throws(() => acceptCodeReview('abc', PR, reviewFixture({ receipt: undefined })), /receipt/)
  assert.throws(
    () => acceptCodeReview('abc', PR, reviewFixture({ result_binding: undefined })),
    /result binding/,
  )
  assert.throws(
    () => acceptCodeReview('abc', PR, reviewFixture({ bound_inputs: [] })),
    /bound inputs/,
  )
  assert.throws(
    () => acceptCodeReview('abc', PR, reviewFixture({ comment_url: 'https://example.test/pr/9#issuecomment-1' })),
    /comment URL/,
  )
})

test('blocking review never advances', () => {
  assert.deepEqual(
    acceptCodeReview('abc', PR, reviewFixture({ verdict: 'blocking', findings: ['fix'] })),
    { advance: false, findings: ['fix'] },
  )
})

const MANIFEST = 'https://evidence.test/manifest-1'

function criterion(overrides = {}) {
  return { criterion: 'loads', status: 'pass', observation: 'renders as expected', ...overrides }
}

function qaExpected(overrides = {}) {
  return { issue: 'TUR-1', pr: PR, manifest: MANIFEST, ...overrides }
}

function qaFixture(overrides = {}) {
  return {
    head: 'abc', verdict: 'satisfied', receipt: 'qa-1', packet_url: 'https://evidence.test/1',
    issue: 'TUR-1', pr: PR, manifest: MANIFEST, criteria: [criterion()], result_binding: BINDING,
    ...overrides,
  }
}

test('qa-reviewer pass with the exact registry-declared empty skill set grades end to end', () => {
  const passResult = qaFixture()
  const { result_binding, ...unbound } = passResult
  const binding = exactFingerprint(unbound)
  const bound = { ...unbound, result_binding: binding }
  const receipt = {
    ...fullReceipt(),
    role: { name: 'qa-reviewer', contract_blob: 'blob-qa', mapping_revision: 'map-1' },
    skills: { resolved: [], blobs: [] },
    result: { bound: true, binding },
  }
  assertPassReceipt(receipt, 'qa-reviewer', 'abc')
  assertBoundPassResult(receipt, bound)
  assert.deepEqual(acceptQaReview('abc', qaExpected(), bound), { advance: true, packet_url: 'https://evidence.test/1' })
})

test('backend work still requires fresh qa review', () => {
  assert.equal(evidenceMode(false), 'nonvisual')
  assert.deepEqual(
    acceptQaReview('abc', qaExpected(), qaFixture()),
    { advance: true, packet_url: 'https://evidence.test/1' },
  )
})

test('qa review rejects wrong head, missing served packet, and unbound output', () => {
  assert.throws(() => acceptQaReview('abc', qaExpected(), qaFixture({ head: 'old' })), /HEAD/)
  assert.throws(() => acceptQaReview('abc', qaExpected(), qaFixture({ packet_url: undefined })), /served packet/)
  assert.throws(
    () => acceptQaReview('abc', qaExpected(), qaFixture({ result_binding: undefined })),
    /result binding/,
  )
  assert.throws(() => acceptQaReview('abc', qaExpected(), qaFixture({ issue: 'TUR-9' })), /issue/)
  assert.throws(() => acceptQaReview('abc', qaExpected(), qaFixture({ manifest: 'other' })), /manifest/)
})

test('qa review requires structured per-criterion proof and only all-pass advances', () => {
  assert.throws(() => acceptQaReview('abc', qaExpected(), qaFixture({ criteria: [] })), /criteria/)
  assert.throws(
    () => acceptQaReview('abc', qaExpected(), qaFixture({ criteria: [criterion({ status: 'fail' })] })),
    /artifact/,
  )
  assert.throws(
    () => acceptQaReview('abc', qaExpected(), qaFixture({
      criteria: [criterion({ status: 'fail', artifact: 'https://evidence.test/1#shot2' })],
    })),
    /fix/,
  )
  const failing = qaFixture({
    verdict: 'blocking',
    criteria: [criterion({ status: 'fail', artifact: 'https://evidence.test/1#shot2', fix: 'add retry' })],
  })
  const gate = acceptQaReview('abc', qaExpected(), failing)
  assert.deepEqual(gate, { advance: false, findings: [failing.criteria[0]] })
  assert.throws(
    () => acceptQaReview('abc', qaExpected(), qaFixture({
      verdict: 'satisfied',
      criteria: [criterion({ status: 'fail', artifact: 'https://evidence.test/1#shot2', fix: 'add retry' })],
    })),
    /verdict does not match/,
  )
})

test('final publication readback binds the complete acceptance card', () => {
  const publication = {
    readable: true,
    issue: 'TUR-1',
    pr: 'https://example.test/pr/1',
    head: 'abc',
    verdict: 'satisfied',
    story_ids: ['US-1-01'],
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

test('exact fingerprint matches octo_lite.runtime.exact_fingerprint for the same payload', () => {
  // Cross-checked against python3 -c "from octo_lite.runtime import exact_fingerprint; print(exact_fingerprint(...))"
  assert.equal(
    exactFingerprint({ a: 1, b: [1, 2, 3], c: { z: 'y', a: 'b' } }),
    'c36bd36cb7d15bf8bc503f812c71ed02f9340466699c0b55a449c8a39a5c48aa',
  )
  assert.equal(
    exactFingerprint({ command: 'pytest', exit_status: 0, outcome: 'pass', artifact: 'a/b.txt' }),
    '3800bd8b93cc5789beecf634f9627d9c370a8132c9b3f2ef3b0ff475b8e2e5db',
  )
})

test('the workflow independently recomputes and cross-checks the launcher-owned binding', () => {
  const passResult = { head: 'def', receipt: 'spawn-1' }
  const binding = exactFingerprint(passResult)
  const bound = { ...passResult, result_binding: binding }
  const receipt = { result: { bound: true, binding } }
  assert.equal(assertBoundPassResult(receipt, bound), binding)

  // A role cannot self-author its own binding: a claim that does not match its own content fails.
  assert.throws(
    () => assertBoundPassResult(receipt, { ...bound, result_binding: 'f'.repeat(64) }),
    /does not match its own content/,
  )
  // The receipt itself must record the launcher's binding as bound.
  assert.throws(
    () => assertBoundPassResult({ result: { bound: false, binding } }, bound),
    /receipt result not bound/,
  )
  // A tampered field after binding fails self-consistency immediately (the claimed
  // binding no longer matches the tampered content).
  assert.throws(
    () => assertBoundPassResult(receipt, { ...bound, head: 'tampered' }),
    /does not match its own content/,
  )
  // A self-consistent result bound to a different receipt's stored binding is rejected:
  // the launcher bound this receipt to a different pass result.
  const otherReceipt = { result: { bound: true, binding: exactFingerprint({ head: 'other' }) } }
  assert.throws(
    () => assertBoundPassResult(otherReceipt, bound),
    /does not match receipt/,
  )
})

// Spec: role-runtime launch-identity, launch-receipt, launch-gates-workflow-layer
// (blob spec/domains/role-runtime.spec.html:e1265b3c5d0a464ed416de283e11069e4796b01a);
// operating-model decision-109-binding
// (blob spec/domains/operating-model.spec.html:30c64f92a7085bd85609f238f7ed3891fe729b1a).
// Worker binding proof is the workflow journal plus a schema-forced acknowledgment echo
// of the exact bound inputs the orchestrator verifies before any mutation phase.
const CONTRACT_HASH = 'c'.repeat(64)

function journalledBoundInputs() {
  return {
    role: 'implementer',
    repo: 'varelaseb/octo-lite',
    issue: 'TUR-1',
    pr: PR,
    starting_head: 'abc',
    spec_blobs: [
      'spec/domains/role-runtime.spec.html:spec-1',
      'spec/domains/operating-model.spec.html:spec-2',
    ],
    contract_hash: CONTRACT_HASH,
  }
}

test('worker ack echo of the exact journalled bound inputs is accepted', () => {
  const journalled = journalledBoundInputs()
  const ack = journalledBoundInputs()
  assert.deepEqual(assertWorkerAckEcho(journalled, ack), ack)
})

test('a role, repo, issue, or PR substitution fails the echo exactly as a HEAD mismatch does', () => {
  const journalled = journalledBoundInputs()
  const headError = (() => {
    try {
      assertWorkerAckEcho(journalled, { ...journalledBoundInputs(), starting_head: 'other' })
    } catch (error) {
      return error
    }
    throw new Error('HEAD mismatch must be rejected')
  })()
  assert.equal(headError.constructor, Error)
  assert.match(headError.message, /mismatch$/)
  const substitutions = [
    ['role', 'code-reviewer'],
    ['repo', 'varelaseb/other-repo'],
    ['issue', 'TUR-9'],
    ['pr', 'https://example.test/pr/9'],
  ]
  for (const [field, substituted] of substitutions) {
    const error = (() => {
      try {
        assertWorkerAckEcho(journalled, { ...journalledBoundInputs(), [field]: substituted })
      } catch (caught) {
        return caught
      }
      throw new Error(`${field} substitution must be rejected`)
    })()
    assert.equal(error.constructor, headError.constructor)
    assert.match(error.message, /mismatch$/)
  }
})

test('worker ack echo requires exact spec blobs and exact contract hash', () => {
  const journalled = journalledBoundInputs()
  assert.throws(
    () => assertWorkerAckEcho(journalled, { ...journalledBoundInputs(), contract_hash: 'd'.repeat(64) }),
    /contract hash mismatch/,
  )
  assert.throws(
    () => assertWorkerAckEcho(journalled, { ...journalledBoundInputs(), spec_blobs: ['spec/domains/role-runtime.spec.html:spec-1'] }),
    /spec blobs mismatch/,
  )
  assert.throws(
    () => assertWorkerAckEcho(journalled, {
      ...journalledBoundInputs(),
      spec_blobs: [
        'spec/domains/operating-model.spec.html:spec-2',
        'spec/domains/role-runtime.spec.html:spec-1',
      ],
    }),
    /spec blobs mismatch/,
  )
  assert.throws(
    () => assertWorkerAckEcho(journalled, {
      ...journalledBoundInputs(),
      spec_blobs: [
        'spec/domains/role-runtime.spec.html:spec-1',
        'spec/domains/operating-model.spec.html:tampered',
      ],
    }),
    /spec blobs mismatch/,
  )
})

test('a missing bound input in the worker ack echo is rejected before any mutation phase', () => {
  const journalled = journalledBoundInputs()
  for (const field of ['role', 'repo', 'issue', 'pr', 'starting_head', 'contract_hash']) {
    const ack = journalledBoundInputs()
    delete ack[field]
    assert.throws(() => assertWorkerAckEcho(journalled, ack), /required/)
  }
  const noBlobs = journalledBoundInputs()
  delete noBlobs.spec_blobs
  assert.throws(() => assertWorkerAckEcho(journalled, noBlobs), /spec blobs required/)
  assert.throws(() => assertWorkerAckEcho(journalled, undefined), /required/)
})

test('schema assertion enforces required fields, types, enums, and nested items', () => {
  const schema = {
    type: 'object',
    required: ['head', 'verdict'],
    properties: {
      head: { type: 'string' },
      verdict: { enum: ['clear', 'blocking'] },
      findings: { type: 'array', items: { type: 'string' } },
    },
  }
  assert.deepEqual(assertSchema(schema, { head: 'abc', verdict: 'clear', findings: ['x'] }, 'result'), {
    head: 'abc', verdict: 'clear', findings: ['x'],
  })
  assert.throws(() => assertSchema(schema, { verdict: 'clear' }, 'result'), /result\.head required/)
  assert.throws(() => assertSchema(schema, { head: 'abc', verdict: 'maybe' }, 'result'), /must be one of/)
  assert.throws(
    () => assertSchema(schema, { head: 'abc', verdict: 'clear', findings: [1] }, 'result'),
    /result\.findings\[0\] must be string/,
  )
})
