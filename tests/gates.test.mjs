import test from 'node:test'
import assert from 'node:assert/strict'

import {
  acceptCodeReview,
  assertAdmission,
  acceptQaReview,
  acceptImplementation,
  acceptPublication,
  assertContainment,
  assertLaunchReadback,
  assertLaunchRevision,
  assertManifestShape,
  assertReadOnlyAckPhase,
  assertReadyEnvelope,
  assertWorkerAckEcho,
  evidenceMode,
  launchRevision,
  verifyAckThenUpgrade,
} from '../workflows/lib/gates.mjs'

// Spec: role-runtime launch-role-purpose-capability, launch-purpose-shaping-roles,
// launch-purpose-delivery-roles, launch-purpose-reconcile, launch-gates-workflow-layer
// (blob spec/domains/role-runtime.spec.html:e1265b3c5d0a464ed416de283e11069e4796b01a).
test('shaping-review admits only shaping-reviewer or orchestrator with resolved shaping capability', () => {
  assert.deepEqual(
    assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer', linearState: 'Ideas' }),
    { purpose: 'shaping-review', role: 'shaping-reviewer' },
  )
  assert.deepEqual(
    assertAdmission({ purpose: 'shaping-review', role: 'orchestrator', capabilities: ['shaping', 'grill'], linearState: 'Ideas' }),
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
    assert.deepEqual(assertAdmission({ purpose: 'delivery', role, linearState: 'Todo' }), { purpose: 'delivery', role })
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

function proof(overrides = {}) {
  return {
    command: 'python3 -m unittest tests.test_launch',
    exit_status: 1,
    outcome: 'ModuleNotFoundError: no module named octo_lite.launch',
    artifact: 'https://example.test/pr/1#issuecomment-1',
    ...overrides,
  }
}

test('implementation requires TDD evidence, validation, and a new fix head', () => {
  const result = {
    head: 'def', validation: 'suite', blocked: false,
    red: proof(),
    green: proof({ exit_status: 0, outcome: 'OK', artifact: 'https://example.test/pr/1#issuecomment-2' }),
  }
  assert.deepEqual(acceptImplementation('abc', result, true), result)
  assert.throws(() => acceptImplementation('abc', { ...result, red: null }, true), /red/)
  assert.throws(
    () => acceptImplementation('abc', { ...result, red: proof({ command: '' }) }, true),
    /red/,
  )
  assert.throws(
    () => acceptImplementation('abc', { ...result, red: proof({ exit_status: 0 }) }, true),
    /red must fail/,
  )
  assert.throws(
    () => acceptImplementation('abc', { ...result, green: proof({ exit_status: 1 }) }, true),
    /green must pass/,
  )
  assert.throws(() => acceptImplementation('abc', { ...result, head: 'abc' }, true), /new HEAD/)
  assert.throws(() => acceptImplementation('abc', { ...result, blocked: true }, true), /blocked/)
})

const PR = 'https://example.test/pr/1'

function reviewFixture(overrides = {}) {
  return {
    head: 'abc', verdict: 'clear', comment_url: `${PR}#issuecomment-1`,
    ...overrides,
  }
}

test('code review rejects wrong head, ambiguous verdict, and a foreign comment URL', () => {
  assert.throws(() => acceptCodeReview('abc', PR, reviewFixture({ head: 'old' })), /HEAD/)
  assert.throws(() => acceptCodeReview('abc', PR, reviewFixture({ verdict: 'ambiguous' })), /ambiguous/)
  assert.throws(() => acceptCodeReview('abc', PR, reviewFixture({ comment_url: undefined })), /comment/)
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
    head: 'abc', verdict: 'satisfied', packet_url: 'https://evidence.test/1',
    issue: 'TUR-1', pr: PR, manifest: MANIFEST, criteria: [criterion()],
    ...overrides,
  }
}

test('backend work still requires fresh qa review', () => {
  assert.equal(evidenceMode(false), 'nonvisual')
  assert.deepEqual(
    acceptQaReview('abc', qaExpected(), qaFixture()),
    { advance: true, packet_url: 'https://evidence.test/1' },
  )
})

test('qa review rejects wrong head, missing served packet, and identity mismatch', () => {
  assert.throws(() => acceptQaReview('abc', qaExpected(), qaFixture({ head: 'old' })), /HEAD/)
  assert.throws(() => acceptQaReview('abc', qaExpected(), qaFixture({ packet_url: undefined })), /served packet/)
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

// Unit B (TUR-447 F1). Spec: role-runtime launch-identity, launch-receipt,
// launch-gates-workflow-layer
// (blob spec/domains/role-runtime.spec.html:e1265b3c5d0a464ed416de283e11069e4796b01a);
// operating-model decision-109-binding
// (blob spec/domains/operating-model.spec.html:30c64f92a7085bd85609f238f7ed3891fe729b1a).
// The bound-input echo is verified in an OBSERVABLE read-only acknowledgment phase
// (write tools withheld) that produces ONLY the ack echo; the write-capable mutation
// phase is unreachable until that echo verifies. A worker that would mutate before
// verification cannot, rather than being rejected after a prohibited mutation.

// TUR-447 F1 Unit B correction: write tools are withheld ONLY by a real read-only
// subagent type (agentType: 'Explore'). The gate now asserts the ack phase declares a
// recognized read-only agentType and rejects a default, absent, or write-capable
// agentType. The prior writeCapable:false flag was an invented agent() opt the runtime
// ignored, so it withheld nothing; asserting on it proved nothing.
test('the read-only ack phase must declare a real read-only agentType that withholds write tools', () => {
  const ack = journalledBoundInputs()
  assert.deepEqual(
    assertReadOnlyAckPhase({ agentType: 'Explore', ack }),
    { agentType: 'Explore', ack },
  )
  // A default/absent agentType is rejected: the runtime would retain write tools.
  assert.throws(() => assertReadOnlyAckPhase({ ack }), /read-only/)
  // An unrecognized or write-capable agentType is rejected.
  assert.throws(() => assertReadOnlyAckPhase({ agentType: 'Task', ack }), /read-only/)
  assert.throws(() => assertReadOnlyAckPhase({ agentType: 'general', ack }), /read-only/)
  // The retired invented flag no longer satisfies the gate: it withholds nothing.
  assert.throws(() => assertReadOnlyAckPhase({ writeCapable: false, ack }), /read-only/)
  assert.throws(() => assertReadOnlyAckPhase(undefined), /ack phase required/)
})

test('the write-capable mutation phase is unreachable until the ack echo verifies', () => {
  const journalled = journalledBoundInputs()
  const ack = journalledBoundInputs()
  // A read-only-agentType ack phase whose echo verifies authorizes the write phase.
  assert.deepEqual(
    verifyAckThenUpgrade(journalled, { agentType: 'Explore', ack }),
    { upgrade: 'write-capable' },
  )
  // A non-read-only ack agentType never reaches the upgrade: it could mutate before verify.
  assert.throws(
    () => verifyAckThenUpgrade(journalled, { agentType: 'Task', ack }),
    /read-only/,
  )
  // The retired invented flag is no longer accepted here either.
  assert.throws(
    () => verifyAckThenUpgrade(journalled, { writeCapable: false, ack }),
    /read-only/,
  )
})

test('a substituted bound input blocks the mutation phase exactly as a HEAD mismatch does', () => {
  const journalled = journalledBoundInputs()
  const headError = (() => {
    try {
      verifyAckThenUpgrade(journalled, {
        agentType: 'Explore',
        ack: { ...journalledBoundInputs(), starting_head: 'other' },
      })
    } catch (error) {
      return error
    }
    throw new Error('HEAD mismatch must block the mutation phase')
  })()
  assert.equal(headError.constructor, Error)
  assert.match(headError.message, /mismatch$/)
  // Explicit role, repo, issue, and PR substitution reds: each blocks the write phase
  // exactly as a HEAD mismatch does.
  const substitutions = [
    ['role', 'code-reviewer'],
    ['repo', 'varelaseb/other-repo'],
    ['issue', 'TUR-9'],
    ['pr', 'https://example.test/pr/9'],
  ]
  for (const [field, substituted] of substitutions) {
    const error = (() => {
      try {
        verifyAckThenUpgrade(journalled, {
          agentType: 'Explore',
          ack: { ...journalledBoundInputs(), [field]: substituted },
        })
      } catch (caught) {
        return caught
      }
      throw new Error(`${field} substitution must block the mutation phase`)
    })()
    assert.equal(error.constructor, headError.constructor)
    assert.match(error.message, /mismatch$/)
  }
  // A missing bound input in the ack echo also blocks the mutation phase.
  for (const field of ['role', 'repo', 'issue', 'pr', 'starting_head', 'contract_hash']) {
    const ack = journalledBoundInputs()
    delete ack[field]
    assert.throws(() => verifyAckThenUpgrade(journalled, { agentType: 'Explore', ack }), /required|mismatch/)
  }
})

// Unit H. Spec: role-runtime launch-gates-workflow-layer, launch-linear-state-gate,
// launch-receipt-manifest-shapes, launch-entrypoint-revalidation, launch-readback,
// launch-containment
// (blob spec/domains/role-runtime.spec.html:e1265b3c5d0a464ed416de283e11069e4796b01a).

test('linear-state gate admits shaping-review only from Ideas, Todo, Shaped, or In Progress', () => {
  for (const linearState of ['Ideas', 'Todo', 'Shaped', 'In Progress']) {
    assert.deepEqual(
      assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer', linearState }),
      { purpose: 'shaping-review', role: 'shaping-reviewer' },
    )
  }
  for (const linearState of ['Awaiting Accept', 'Done', 'Canceled', 'Duplicate', 'Backlog', 'nonsense']) {
    assert.throws(
      () => assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer', linearState }),
      /Linear state/,
    )
  }
  assert.throws(
    () => assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer' }),
    /Linear state/,
  )
})

test('linear-state gate admits delivery only from Shaped, Todo, or In Progress', () => {
  for (const linearState of ['Shaped', 'Todo', 'In Progress']) {
    assert.deepEqual(
      assertAdmission({ purpose: 'delivery', role: 'implementer', linearState }),
      { purpose: 'delivery', role: 'implementer' },
    )
  }
  for (const linearState of ['Ideas', 'Awaiting Accept', 'Done', 'Canceled', 'Duplicate', 'nonsense']) {
    assert.throws(
      () => assertAdmission({ purpose: 'delivery', role: 'implementer', linearState }),
      /Linear state/,
    )
  }
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: 'implementer' }), /Linear state/)
})

test('manifest-shape admission keeps exactly one durable persistent receipt shape', () => {
  for (const role of ['meta-operator', 'orchestrator']) {
    assert.deepEqual(assertManifestShape({ shape: 'persistent', role }), { shape: 'persistent', role })
  }
  assert.deepEqual(
    assertManifestShape({ shape: 'worker-journal', role: 'implementer', purpose: 'delivery', linearState: 'Todo' }),
    { shape: 'worker-journal', role: 'implementer', purpose: 'delivery' },
  )
  assert.deepEqual(
    assertManifestShape({ shape: 'worker-journal', role: 'reconciler', purpose: 'reconcile', readRestricted: true }),
    { shape: 'worker-journal', role: 'reconciler', purpose: 'reconcile' },
  )
})

test('a pass purpose injected onto a persistent shape is rejected', () => {
  for (const purpose of ['delivery', 'shaping-review', 'reconcile']) {
    assert.throws(
      () => assertManifestShape({ shape: 'persistent', role: 'meta-operator', purpose }),
      /pass purpose/,
    )
  }
})

test('a role substituted for its manifest shape is rejected', () => {
  for (const role of ['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer', 'shaping-reviewer', 'reconciler']) {
    assert.throws(() => assertManifestShape({ shape: 'persistent', role }), /persistent/)
  }
  assert.throws(
    () => assertManifestShape({ shape: 'worker-journal', role: 'meta-operator', purpose: 'delivery', linearState: 'Todo' }),
    /delivery/,
  )
  assert.throws(
    () => assertManifestShape({ shape: 'worker-journal', role: 'implementer' }),
    /purpose/,
  )
})

test('an unknown manifest shape is rejected', () => {
  for (const shape of ['worker-receipt', 'reconcile-receipt', 'pass', 'nonsense']) {
    assert.throws(
      () => assertManifestShape({ shape, role: 'meta-operator' }),
      /unknown manifest shape/,
    )
  }
  assert.throws(() => assertManifestShape({ role: 'meta-operator' }), /manifest shape required/)
  assert.throws(() => assertManifestShape({ shape: 'persistent' }), /manifest role required/)
})

test('launch revision fingerprints the exact bound inputs deterministically', () => {
  const bound = journalledBoundInputs()
  const revision = launchRevision(bound)
  assert.match(revision, /^[0-9a-f]{64}$/)
  assert.equal(assertLaunchRevision(revision, journalledBoundInputs()), revision)
  const reordered = {}
  for (const key of Object.keys(bound).sort().reverse()) reordered[key] = bound[key]
  assert.equal(launchRevision(reordered), revision)
})

test('a launch-revision mismatch from any altered combination is rejected with no spawn', () => {
  const revision = launchRevision(journalledBoundInputs())
  const alterations = [
    ['role', 'code-reviewer'],
    ['repo', 'varelaseb/other-repo'],
    ['issue', 'TUR-9'],
    ['pr', 'https://example.test/pr/9'],
    ['starting_head', 'other'],
    ['contract_hash', 'd'.repeat(64)],
    ['spec_blobs', ['spec/domains/role-runtime.spec.html:tampered']],
  ]
  for (const [field, altered] of alterations) {
    assert.throws(
      () => assertLaunchRevision(revision, { ...journalledBoundInputs(), [field]: altered }),
      /launch revision mismatch/,
    )
  }
  assert.throws(() => assertLaunchRevision(undefined, journalledBoundInputs()), /launch revision required/)
  assert.throws(() => assertLaunchRevision(revision, undefined), /bound inputs required/)
})

function freshReads(overrides = {}) {
  return {
    linear_state: ready.linear_state,
    linear_fingerprint: ready.linear_fingerprint,
    pr_head: ready.pr_head,
    branch: ready.branch,
    ...overrides,
  }
}

test('launch readback accepts an envelope agreeing with the explicit fresh reads', () => {
  const fresh = freshReads()
  assert.deepEqual(assertLaunchReadback(ready, fresh), fresh)
})

test('a stale self-consistent envelope disagreeing with fresh reads never spawns', () => {
  // The envelope is internally consistent and passes its own shape gate; only the
  // live refetch immediately before dispatch exposes it as stale (launch-readback).
  assertReadyEnvelope(ready)
  const staleness = [
    ['linear_state', 'In Progress'],
    ['linear_fingerprint', 'lfp-2'],
    ['pr_head', 'bbb'],
    ['branch', 'octo-lite/tur-9'],
  ]
  for (const [field, fresh] of staleness) {
    assert.throws(
      () => assertLaunchReadback(ready, freshReads({ [field]: fresh })),
      /stale envelope/,
    )
  }
  for (const field of ['linear_state', 'linear_fingerprint', 'pr_head', 'branch']) {
    const fresh = freshReads()
    delete fresh[field]
    assert.throws(() => assertLaunchReadback(ready, fresh), /required/)
  }
  assert.throws(() => assertLaunchReadback(ready, undefined), /fresh reads required/)
})

test('containment admits only worktrees under the declared worktree root', () => {
  assert.equal(
    assertContainment('/work/worktrees', '/work/worktrees/tur-1'),
    '/work/worktrees/tur-1',
  )
  assert.equal(assertContainment('/work/worktrees', 'tur-1'), '/work/worktrees/tur-1')
  assert.equal(
    assertContainment('/work/worktrees/', '/work/worktrees/tur-1/nested'),
    '/work/worktrees/tur-1/nested',
  )
})

test('an escaping or wrong worktree path never spawns', () => {
  for (const escaping of [
    '../outside',
    'tur-1/../../outside',
    '/etc/passwd',
    '/work/worktrees/../evil',
    '/work/worktrees-evil/tur-1',
    '/work/worktrees',
  ]) {
    assert.throws(() => assertContainment('/work/worktrees', escaping), /escapes/)
  }
  assert.throws(() => assertContainment('', '/work/worktrees/tur-1'), /worktree root required/)
  assert.throws(() => assertContainment('/work/worktrees', ''), /worker worktree required/)
})
