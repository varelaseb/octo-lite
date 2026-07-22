import test from 'node:test'
import assert from 'node:assert/strict'

import {
  acceptCodeReview,
  acceptOpenaiReviewRelay,
  acceptShapingReviewRelay,
  assertReviewWorktreeImmutable,
  assertAdmission,
  acceptQaReview,
  assertCommittedImplementation,
  assertBoundTest,
  assertIndependentGitRead,
  assertWorkerClaimCrossCheck,
  assertWorkerBoundTestCrossCheck,
  INDEPENDENT_GIT_READ_SOURCE,
  assertHostJournalledCommits,
  assertObservedCommittedStates,
  assertLiveRemotePushReadback,
  INDEPENDENT_OBSERVER_SOURCE,
  acceptPublication,
  assertContainment,
  assertLaunchReadback,
  assertLaunchRevision,
  assertManifestShape,
  assertReadOnlyAckPhase,
  assertReadOnlyFirstBootstrap,
  assertReadyEnvelope,
  assertResumeSandboxConfig,
  assertWorkerAckEcho,
  assertPrePushReadback,
  assertWorkerLivenessEcho,
  evidenceMode,
  launchRevision,
  verifyAckThenUpgrade,
  verifyRelayVerbatim,
  assertProvisionedWorkspaceBinding,
  assertLiveWorktreeIdentity,
  assertHostTrustedIdentity,
  HOST_PROVISION_SOURCE,
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

test('delivery admits only implementer, code-reviewer, qa-capture, qa-reviewer, and the Read-restricted tdd-observer', () => {
  for (const role of ['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer']) {
    assert.deepEqual(assertAdmission({ purpose: 'delivery', role, linearState: 'Todo' }), { purpose: 'delivery', role })
  }
  // The tdd-observer is admitted for delivery only as a Read-restricted subagent
  // (role-runtime role-tdd-observer, launch-purpose-delivery-roles).
  assert.deepEqual(
    assertAdmission({ purpose: 'delivery', role: 'tdd-observer', readRestricted: true, linearState: 'Todo' }),
    { purpose: 'delivery', role: 'tdd-observer' },
  )
  assert.throws(
    () => assertAdmission({ purpose: 'delivery', role: 'tdd-observer', readRestricted: false, linearState: 'Todo' }),
    /Read-restricted/,
  )
  assert.throws(
    () => assertAdmission({ purpose: 'delivery', role: 'tdd-observer', linearState: 'Todo' }),
    /Read-restricted/,
  )
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
  // TUR-447 ruling-56 cycle3 slug-identity-bound: readiness requires the canonical owner/repo slug, a
  // contained host worktree, and the PR as a NUMBER (never a URL).
  repo_slug: 'varelaseb/octo-lite',
  worktree_root: '/root',
  worktree: 'repo',
  pr: 1,
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

// TUR-447 D1 reshaped delivery loop. The implementer COMMITS a real failing red then a green on an
// isolated delivery branch and NEVER pushes; the committed result carries distinct red/green/final
// commit ids and the bound test by path+content digest. The independent tdd-observer replay of the
// committed states, consumed separately, is the sole proof.
const START = 'abc'
const RED = 'red111'
const GREEN = 'grn222'
const FINAL = 'fin333'
const CMD = 'python3 -m unittest tests.test_launch'
const BTEST = { path: 'tests/test_launch.py', digest: 'sha256:bt' }

function proof(overrides = {}) {
  return {
    command: CMD, exit_status: 1, outcome: 'FAILED (errors=1)',
    artifact: 'https://example.test/pr/1#issuecomment-1', head: RED, scenario: 'delivery-entry-gate',
    ...overrides,
  }
}

function greenProof(overrides = {}) {
  return {
    command: CMD, exit_status: 0, outcome: 'OK', artifact: 'https://example.test/pr/1#issuecomment-2',
    head: FINAL, scenario: 'delivery-entry-gate', ...overrides,
  }
}

function implFixture(overrides = {}) {
  return {
    head: FINAL, validation: 'suite', blocked: false, committed: true, pushed: false,
    red: proof(), green: greenProof(),
    red_commit: RED, green_commit: GREEN, final_commit: FINAL, bound_test: { ...BTEST },
    ...overrides,
  }
}

function bindingFixture(overrides = {}) {
  return {
    branch: 'octo-lite/tur-443-operating-model',
    red_commit: RED, green_commit: GREEN, final_commit: FINAL, command: CMD, ...overrides,
  }
}

// The INDEPENDENT tdd-observer replay of the committed states. Distinct from the mutating worker
// (source stamped independent-tdd-observer, observed_by not the worker); it checked out each
// host-journalled commit and the final HEAD in an isolated worktree, ran the host-sourced command,
// and saw red fail, green pass, final HEAD pass, with the bound test unchanged at each.
function observationFixture(overrides = {}) {
  return {
    source: INDEPENDENT_OBSERVER_SOURCE, observed_by: 'observer-1', mutating_worker: 'implementer-1',
    isolated_worktree: '/root/octo-lite-observer-wt', command: CMD,
    red_commit: RED, red_exit: 1, red_output: 'FAILED (errors=1)', red_test: { ...BTEST },
    green_commit: GREEN, green_exit: 0, green_output: 'OK', green_test: { ...BTEST },
    final_commit: FINAL, final_exit: 0, final_output: 'OK', final_test: { ...BTEST },
    ...overrides,
  }
}

test('assertCommittedImplementation requires a committed unpushed red then green on the isolated branch', () => {
  const result = implFixture()
  const accepted = assertCommittedImplementation(START, result)
  assert.deepEqual(accepted, { redCommit: RED, greenCommit: GREEN, finalCommit: FINAL, boundTest: BTEST })
  // A worker that did not commit is rejected.
  assert.throws(() => assertCommittedImplementation(START, { ...result, committed: false }), /must commit the red then green/)
  // A worker that pushed is rejected.
  assert.throws(() => assertCommittedImplementation(START, { ...result, pushed: true }), /must not push/)
  // Red and green must be distinct commits.
  assert.throws(() => assertCommittedImplementation(START, { ...result, green_commit: RED }), /distinct commits/)
  // The red commit must move off the unchanged starting HEAD.
  assert.throws(() => assertCommittedImplementation(START, { ...result, red_commit: START }), /move off the unchanged starting HEAD/)
  // The red must fail and the green must pass the named test.
  assert.throws(() => assertCommittedImplementation(START, { ...result, red: proof({ exit_status: 0 }) }), /red must fail the named test/)
  assert.throws(() => assertCommittedImplementation(START, { ...result, green: greenProof({ exit_status: 1 }) }), /green must pass the same named test/)
  // Green and red must prove the same scenario.
  assert.throws(() => assertCommittedImplementation(START, { ...result, green: greenProof({ scenario: 'other' }) }), /same scenario as red/)
  // A blocked result is rejected.
  assert.throws(() => assertCommittedImplementation(START, { ...result, blocked: true }), /blocked/)
})

test('assertBoundTest binds the failing test by path AND content digest', () => {
  assert.deepEqual(assertBoundTest(BTEST), { path: BTEST.path, digest: BTEST.digest })
  assert.throws(() => assertBoundTest({ path: 'p' }), /content digest/)
  assert.throws(() => assertBoundTest({ digest: 'd' }), /path/)
})

// TUR-447 D1 cycle2 independent git-read trust root. The host-controlled Read-restricted git reader is
// given ONLY the branch + expected starting HEAD and reads the ACTUAL red/green/final shas from git.
function gitReadFixture(overrides = {}) {
  return {
    source: INDEPENDENT_GIT_READ_SOURCE, read_by: 'git-reader-1', mutating_worker: 'implementer-1',
    isolated_worktree: '/root/octo-lite-git-read-wt', branch: 'octo-lite/tur-443-operating-model', base_head: START,
    red_commit: RED, green_commit: GREEN, final_commit: FINAL,
    ancestry: [RED, GREEN, FINAL],
    red_diff_kind: 'test-only', red_named_test_exit: 1, red_test: { ...BTEST },
    green_diff_kind: 'production-only', green_named_test_exit: 0, green_test: { ...BTEST },
    final_named_test_exit: 0, final_test: { ...BTEST },
    ...overrides,
  }
}

test('assertIndependentGitRead establishes the trust root shas from the independent git read, not any worker claim', () => {
  const branch = 'octo-lite/tur-443-operating-model'
  // TUR-447 D1 cycle3: the bound-test identity is DISCOVERED by the reader (its red_test), not supplied. The
  // expectation carries only { branch, expectedStartingHead }; the gate returns the discovered boundTest.
  const expected = { branch, expectedStartingHead: START }
  assert.deepEqual(
    assertIndependentGitRead(gitReadFixture(), expected),
    { red_commit: RED, green_commit: GREEN, final_commit: FINAL, branch, boundTest: BTEST },
  )
  // Provenance: a read NOT stamped by the independent git reader is rejected (a worker cannot masquerade).
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ source: 'implementer-1' }), expected), /not from the independent git reader/)
  // The reader cannot be the mutating worker.
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ read_by: 'implementer-1' }), expected), /the reader cannot be the mutating worker/)
  // The read must run in an isolated worktree over the exact committed branch.
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ isolated_worktree: '' }), expected), /isolated worktree/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ branch: 'other' }), expected), /a branch other than the committed delivery branch/)
  // The branch base must be the expected starting HEAD.
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ base_head: 'wrong' }), expected), /branch base is not the expected starting HEAD/)
  // Red and green cannot collapse; red must move off the base.
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ green_commit: RED, ancestry: [RED, FINAL] }), expected), /red and green collapse to one commit/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ red_commit: START }), expected), /red commit does not move off the expected starting HEAD/)
  // Linear ancestry red -> green -> final.
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ ancestry: [GREEN, RED, FINAL] }), expected), /ancestry does not start at the red commit/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ ancestry: [RED, GREEN] }), expected), /ancestry does not end at the final HEAD/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ ancestry: [RED, FINAL] }), expected), /green commit not on the ancestry chain/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ ancestry: [GREEN, RED, FINAL], green_commit: GREEN }), expected), /ancestry does not start at the red commit/)
  // Red test-only + fails; green production-only + passes; final passes.
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ red_diff_kind: 'production-only' }), expected), /red commit diff is not test-only/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ red_named_test_exit: 0 }), expected), /the red commit did not fail the named test/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ green_diff_kind: 'test-only' }), expected), /green commit diff is not production-only/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ green_named_test_exit: 1 }), expected), /the green commit did not pass the named test/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ final_named_test_exit: 1 }), expected), /the final HEAD did not pass the named test/)
  // Bound-test identity is DISCOVERED from the red commit's diff (the reader's red_test) and must be present
  // unchanged by path AND digest at green and final. A red_test that names a different file than green/final
  // surfaces at the green commit (the discovered identity diverges from what green carries).
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ red_test: { path: 'other', digest: BTEST.digest } }), expected), /path absent or changed at the green commit/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ green_test: { path: BTEST.path, digest: 'weak' } }), expected), /content digest differs at the green commit/)
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ final_test: { path: 'other', digest: BTEST.digest } }), expected), /path absent or changed at the final commit/)
  // A missing/empty discovered bound test (no test file found in the red diff) is rejected.
  assert.throws(() => assertIndependentGitRead(gitReadFixture({ red_test: { path: '', digest: BTEST.digest } }), expected), /bound test path/)
})

test('assertWorkerClaimCrossCheck rejects a worker claim that differs from the independent git read', () => {
  const trust = { red_commit: RED, green_commit: GREEN, final_commit: FINAL, branch: 'b' }
  assert.deepEqual(
    assertWorkerClaimCrossCheck(trust, { redCommit: RED, greenCommit: GREEN, finalCommit: FINAL }),
    { redCommit: RED, greenCommit: GREEN, finalCommit: FINAL },
  )
  // A forged/cherry-picked worker sha is rejected: the observer never sees a worker-pointed commit.
  assert.throws(() => assertWorkerClaimCrossCheck(trust, { redCommit: 'forged', greenCommit: GREEN, finalCommit: FINAL }), /claimed red commit differs from the independent git read/)
  assert.throws(() => assertWorkerClaimCrossCheck(trust, { redCommit: RED, greenCommit: 'forged', finalCommit: FINAL }), /claimed green commit differs from the independent git read/)
  assert.throws(() => assertWorkerClaimCrossCheck(trust, { redCommit: RED, greenCommit: GREEN, finalCommit: 'forged' }), /claimed final commit differs from the independent git read/)
})

test('assertWorkerBoundTestCrossCheck rejects a worker bound-test claim that differs from the independently discovered one', () => {
  // The trust root carries the INDEPENDENTLY DISCOVERED bound test (the reader's red_test); the worker's
  // CLAIMED path/digest is used ONLY here, post-hoc, never as a reader input.
  const trust = { red_commit: RED, green_commit: GREEN, final_commit: FINAL, branch: 'b', boundTest: { ...BTEST } }
  assert.deepEqual(assertWorkerBoundTestCrossCheck(trust, { ...BTEST }), BTEST)
  // A worker that RELABELS the bound test path is rejected.
  assert.throws(() => assertWorkerBoundTestCrossCheck(trust, { path: 'tests/impostor.py', digest: BTEST.digest }), /claimed test path differs from the independently discovered bound test/)
  // A worker that MIS-DIGESTS the bound test is rejected.
  assert.throws(() => assertWorkerBoundTestCrossCheck(trust, { path: BTEST.path, digest: 'sha256:forged' }), /claimed test digest differs from the independently discovered bound test/)
})

test('assertHostJournalledCommits binds the host journal to the accepted committed ids and host-sourced command', () => {
  const accepted = { redCommit: RED, greenCommit: GREEN, finalCommit: FINAL, boundTest: BTEST }
  const branch = 'octo-lite/tur-443-operating-model'
  assert.deepEqual(
    assertHostJournalledCommits(bindingFixture(), accepted, CMD, branch),
    { red_commit: RED, green_commit: GREEN, final_commit: FINAL, command: CMD, branch },
  )
  // A journalled commit differing from the accepted committed id is rejected (worker-claimed id never enters).
  assert.throws(() => assertHostJournalledCommits(bindingFixture({ red_commit: 'other' }), accepted, CMD, branch), /journalled red commit differs/)
  // A worker-authored command differing from the host-sourced command is rejected.
  assert.throws(() => assertHostJournalledCommits(bindingFixture({ command: 'bad' }), accepted, CMD, branch), /journalled command differs/)
  // A journalled branch differing from the committed delivery branch is rejected.
  assert.throws(() => assertHostJournalledCommits(bindingFixture({ branch: 'other' }), accepted, CMD, branch), /journalled branch differs/)
})

test('assertObservedCommittedStates consumes the observer replay, not any worker string', () => {
  const journalled = { red_commit: RED, green_commit: GREEN, final_commit: FINAL, command: CMD, branch: 'b' }
  assert.deepEqual(assertObservedCommittedStates(observationFixture(), journalled, BTEST), observationFixture())
  // No observation is rejected.
  assert.throws(() => assertObservedCommittedStates(undefined, journalled, BTEST), /independent observer replay/)
  // A forged observation (source not the independent observer) is rejected.
  assert.throws(() => assertObservedCommittedStates(observationFixture({ source: 'implementer-1' }), journalled, BTEST), /not from the independent tdd-observer/)
  // The observer cannot be the mutating worker.
  assert.throws(() => assertObservedCommittedStates(observationFixture({ observed_by: 'implementer-1' }), journalled, BTEST), /the observer cannot be the mutating worker/)
  // The replay must run in an isolated worktree.
  assert.throws(() => assertObservedCommittedStates(observationFixture({ isolated_worktree: '' }), journalled, BTEST), /isolated worktree/)
  // The observer must check out EXACTLY the host-journalled commits.
  assert.throws(() => assertObservedCommittedStates(observationFixture({ red_commit: 'wrong' }), journalled, BTEST), /red commit checked out is not the host-journalled/)
  assert.throws(() => assertObservedCommittedStates(observationFixture({ green_commit: 'wrong' }), journalled, BTEST), /green commit checked out is not the host-journalled/)
  assert.throws(() => assertObservedCommittedStates(observationFixture({ final_commit: 'wrong' }), journalled, BTEST), /final HEAD checked out is not the host-journalled/)
  // The observer must run the host-sourced command.
  assert.throws(() => assertObservedCommittedStates(observationFixture({ command: 'worker-cmd' }), journalled, BTEST), /command run is not the host-sourced/)
  // Red fail, green pass, final green.
  assert.throws(() => assertObservedCommittedStates(observationFixture({ red_exit: 0 }), journalled, BTEST), /red commit did not fail/)
  assert.throws(() => assertObservedCommittedStates(observationFixture({ green_exit: 1 }), journalled, BTEST), /green commit did not pass/)
  assert.throws(() => assertObservedCommittedStates(observationFixture({ final_exit: 1 }), journalled, BTEST), /final pushed HEAD is not green/)
  // Bound-test identity present unchanged by path AND digest at each committed state.
  assert.throws(() => assertObservedCommittedStates(observationFixture({ green_test: { path: BTEST.path, digest: 'weak' } }), journalled, BTEST), /content digest differs at the green commit/)
  assert.throws(() => assertObservedCommittedStates(observationFixture({ final_test: { path: 'other', digest: BTEST.digest } }), journalled, BTEST), /path absent or changed at the final commit/)
  assert.throws(() => assertObservedCommittedStates(observationFixture({ red_test: { path: 'other', digest: BTEST.digest } }), journalled, BTEST), /path absent or changed at the red commit/)
})

test('assertLiveRemotePushReadback requires a live remote read (gh api or git ls-remote), not a local tracking ref', () => {
  assert.deepEqual(
    assertLiveRemotePushReadback({ remote_head: FINAL, remote_source: 'gh-api' }, FINAL),
    { remote_head: FINAL, remote_source: 'gh-api' },
  )
  assert.deepEqual(
    assertLiveRemotePushReadback({ remote_head: FINAL, remote_source: 'git-ls-remote' }, FINAL),
    { remote_head: FINAL, remote_source: 'git-ls-remote' },
  )
  // A local tracking ref source is rejected.
  assert.throws(() => assertLiveRemotePushReadback({ remote_head: FINAL, remote_source: 'local-tracking-ref' }, FINAL), /must be confirmed by a live remote read/)
  // A remote head differing from the expected final HEAD is rejected.
  assert.throws(() => assertLiveRemotePushReadback({ remote_head: 'other', remote_source: 'gh-api' }, FINAL), /does not match the expected pushed final HEAD/)
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
// TUR-447 ruling-59 item 5 numeric-PR QA fix: acceptQaReview now compares pr number-safe, so the QA
// fixtures bind the canonical PR NUMBER (integer), not the code-review comment-URL constant. PR 6 (the
// TUR-447 PR) is the anti-regression: a numeric PR must pass QA review.
const QA_PR = 6

function criterion(overrides = {}) {
  return { criterion: 'loads', status: 'pass', observation: 'renders as expected', ...overrides }
}

function qaExpected(overrides = {}) {
  return { issue: 'TUR-1', pr: QA_PR, manifest: MANIFEST, ...overrides }
}

function qaFixture(overrides = {}) {
  return {
    head: 'abc', verdict: 'satisfied', packet_url: 'https://evidence.test/1',
    issue: 'TUR-1', pr: QA_PR, manifest: MANIFEST, criteria: [criterion()],
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

// TUR-447 ruling-59 item 5 numeric-PR QA regression: a numeric PR 6 (the TUR-447 PR) must PASS QA
// review, and a numeric/string PR compare equal, while a genuinely different PR still REJECTS.
test('qa review: a numeric PR (6) passes and a numeric/string PR compare equal, a different PR rejects', () => {
  assert.deepEqual(
    acceptQaReview('abc', qaExpected({ pr: 6 }), qaFixture({ pr: 6 })),
    { advance: true, packet_url: 'https://evidence.test/1' },
  )
  // Number 6 and string '6' are the same PR.
  assert.doesNotThrow(() => acceptQaReview('abc', qaExpected({ pr: 6 }), qaFixture({ pr: '6' })))
  assert.doesNotThrow(() => acceptQaReview('abc', qaExpected({ pr: '6' }), qaFixture({ pr: 6 })))
  // A genuinely different PR still rejects.
  assert.throws(() => acceptQaReview('abc', qaExpected({ pr: 6 }), qaFixture({ pr: 7 })), /PR mismatch/)
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
    // TUR-447 ruling-56 cycle3 slug-identity-bound: repo_slug and worktree are part of the bound-input
    // echo set, and the PR is the canonical NUMBER (never a URL).
    repo_slug: 'varelaseb/octo-lite',
    worktree: '/root/octo-lite',
    issue: 'TUR-1',
    pr: 1,
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
    ['repo_slug', 'attacker/other'],
    ['worktree', '/root/foreign-lane-wt'],
    ['issue', 'TUR-9'],
    ['pr', 9],
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
    ['repo_slug', 'attacker/other'],
    ['worktree', '/root/foreign-lane-wt'],
    ['issue', 'TUR-9'],
    ['pr', 9],
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
    // TUR-447 ruling-56 cycle3 slug-identity-bound: repo_slug and worktree are in the fingerprint too.
    ['repo_slug', 'attacker/other'],
    ['worktree', '/root/foreign-lane-wt'],
    ['issue', 'TUR-9'],
    ['pr', 9],
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

// TUR-447 cycle2 pass1 stale-read-race pre-push readback (role-runtime launch-readback).
test('pre-push readback rejects any live field that changed since bind, and requires git HEAD', () => {
  const bound = {
    linear_state: 'Todo', linear_fingerprint: 'fp-todo', pr_head: 'aaa',
    branch: 'octo-lite/tur-1', git_head: 'aaa',
  }
  const fresh = { ...bound }
  assert.deepEqual(assertPrePushReadback(bound, fresh), fresh)
  const drift = [
    ['linear_state', 'In Progress'],
    ['linear_fingerprint', 'fp-moved'],
    ['pr_head', 'bbb'],
    ['branch', 'octo-lite/tur-9'],
    ['git_head', 'ccc'],
  ]
  for (const [field, changed] of drift) {
    assert.throws(
      () => assertPrePushReadback(bound, { ...fresh, [field]: changed }),
      /pre-push readback: .* changed since bind/,
    )
  }
  // git HEAD is part of the pre-push read; a missing field is rejected.
  for (const field of ['linear_state', 'linear_fingerprint', 'pr_head', 'branch', 'git_head']) {
    const partial = { ...fresh }
    delete partial[field]
    assert.throws(() => assertPrePushReadback(bound, partial), /required/)
  }
  assert.throws(() => assertPrePushReadback(bound, undefined), /pre-push fresh reads required/)
})

// TUR-447 cycle2 pass1 stale-read-race worker liveness echo (role-runtime launch-readback).
test('worker liveness echo must match the bound ground truth for state, fingerprint, and branch', () => {
  const bound = { linear_state: 'Todo', linear_fingerprint: 'fp-todo', branch: 'octo-lite/tur-1' }
  const result = { linear_state: 'Todo', linear_fingerprint: 'fp-todo', branch: 'octo-lite/tur-1' }
  assert.equal(assertWorkerLivenessEcho(bound, result), result)
  assert.throws(
    () => assertWorkerLivenessEcho(bound, { ...result, linear_state: 'In Progress' }),
    /worker liveness Linear state disagrees/,
  )
  assert.throws(
    () => assertWorkerLivenessEcho(bound, { ...result, linear_fingerprint: 'fp-other' }),
    /worker liveness Linear fingerprint disagrees/,
  )
  assert.throws(
    () => assertWorkerLivenessEcho(bound, { ...result, branch: 'octo-lite/tur-9' }),
    /worker liveness branch disagrees/,
  )
  // A worker that omits a liveness field is rejected.
  assert.throws(() => assertWorkerLivenessEcho(bound, { linear_state: 'Todo', linear_fingerprint: 'fp-todo' }), /required/)
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

// TUR-447 F2a Unit C. Spec: role-runtime role-openai-relay, role-openai-fail-closed,
// launch-correctness-path, launch-review-sandbox-integrity, launch-resume-sandbox-config
// (blob spec/domains/role-runtime.spec.html:e1265b3c5d0a464ed416de283e11069e4796b01a);
// operating-model ADR decision-identity-source, decision-fail-closed-identity
// (blob spec/adr/0001-operating-model-boundaries.spec.html). The relay-verbatim gate is a
// PURE function over data the caller fetches independently (the loop cannot read the
// codex rollout file): it proves effective provider/model/effort FROM the rollout record
// and rejects any relay payload that is not the rollout-derived final message.
const EXPECTED_RUNTIME = { provider: 'openai', model: 'gpt-5.4-codex', effort: 'high' }
const SESSION_ID = '01998888-4444-7abc-8def-0123456789ab'
const RELAY_MESSAGE = 'BLOCKING: line 42 dereferences a possibly-null handle.'

function rolloutRecord(overrides = {}) {
  return {
    provider: 'openai',
    model: 'gpt-5.4-codex',
    effort: 'high',
    final_message: RELAY_MESSAGE,
    ...overrides,
  }
}

test('relay-verbatim accepts a payload byte-identical to the rollout record final message', () => {
  assert.deepEqual(
    verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, rolloutRecord()),
    { provider: 'openai', model: 'gpt-5.4-codex', effort: 'high', final_message: RELAY_MESSAGE },
  )
  // A session-keyed map of independently fetched records resolves the exact session.
  assert.deepEqual(
    verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, { [SESSION_ID]: rolloutRecord() }),
    { provider: 'openai', model: 'gpt-5.4-codex', effort: 'high', final_message: RELAY_MESSAGE },
  )
})

// Red (a): edited payload. The relay-returned payload differs from the rollout-derived
// final message, so a relay that authors or edits prose fails.
test('relay-verbatim rejects a relay payload that edits the rollout final message', () => {
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, `${RELAY_MESSAGE} (softened by relay)`, rolloutRecord()),
    /payload mismatch with rollout record/,
  )
})

// Red (b): absent rollout record for the claimed session id fails closed.
test('relay-verbatim fails closed when no rollout record resolves for the claimed session', () => {
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, undefined),
    /no rollout record for session/,
  )
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, { 'other-session': rolloutRecord() }),
    /no rollout record for session/,
  )
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, { session_id: 'other-session', ...rolloutRecord() }),
    /no rollout record for session/,
  )
  // A record present but carrying no final assistant message is insufficient.
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, rolloutRecord({ final_message: '' })),
    /no final assistant message/,
  )
})

// Red (c): model mismatch proven from the rollout record.
test('relay-verbatim rejects a model that disagrees with the expected role runtime', () => {
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, rolloutRecord({ model: 'gpt-5.4' })),
    /effective identity mismatch: model/,
  )
})

// Red (d): effort mismatch proven from the rollout record.
test('relay-verbatim rejects an effort that disagrees with the expected role runtime', () => {
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, rolloutRecord({ effort: 'medium' })),
    /effective identity mismatch: effort/,
  )
})

// Red (e): provider substitution. A rollout record from any provider other than the exact
// expected OpenAI runtime is rejected.
test('relay-verbatim rejects a non-OpenAI provider substitution', () => {
  assert.throws(
    () => verifyRelayVerbatim(EXPECTED_RUNTIME, SESSION_ID, RELAY_MESSAGE, rolloutRecord({ provider: 'anthropic' })),
    /provider substitution: anthropic/,
  )
})

test('relay-verbatim requires the expected runtime fields and a claimed session id', () => {
  assert.throws(() => verifyRelayVerbatim(undefined, SESSION_ID, RELAY_MESSAGE, rolloutRecord()), /expected role runtime required/)
  assert.throws(() => verifyRelayVerbatim({ model: 'x', effort: 'high' }, SESSION_ID, RELAY_MESSAGE, rolloutRecord()), /expected provider required/)
  assert.throws(() => verifyRelayVerbatim(EXPECTED_RUNTIME, '', RELAY_MESSAGE, rolloutRecord()), /relay session id required/)
})

// Sandbox-law predicates (launch-review-sandbox-integrity, launch-resume-sandbox-config).
const READ_ONLY_RESUME = ['codex', 'exec', 'resume', '--json', '-c', 'sandbox_mode="read-only"', 'SID', '-']
const LIVE_READ_RESUME = [
  'codex', 'exec', 'resume', '--json',
  '-c', 'sandbox_mode="workspace-write"', '-c', 'sandbox_workspace_write.network_access=true', 'SID', '-',
]

test('resume sandbox is selected through -c config and rejects the top-level -s flag', () => {
  assert.deepEqual(assertResumeSandboxConfig(READ_ONLY_RESUME), { sandbox_mode: 'read-only', needsLiveReads: false })
  assert.deepEqual(
    assertResumeSandboxConfig(LIVE_READ_RESUME, { needsLiveReads: true }),
    { sandbox_mode: 'workspace-write', needsLiveReads: true },
  )
  // A resume that uses the top-level -s flag is rejected: the installed CLI resume
  // subcommand rejects -s.
  assert.throws(
    () => assertResumeSandboxConfig(['codex', 'exec', 'resume', '--json', '-s', 'read-only', 'SID', '-']),
    /top-level -s flag prohibited on resume/,
  )
})

test('a workspace-write plus network resume must declare both through -c config', () => {
  assert.throws(
    () => assertResumeSandboxConfig(READ_ONLY_RESUME, { needsLiveReads: true }),
    /sandbox_mode=workspace-write/,
  )
  assert.throws(
    () => assertResumeSandboxConfig(
      ['codex', 'exec', 'resume', '--json', '-c', 'sandbox_mode="workspace-write"', 'SID', '-'],
      { needsLiveReads: true },
    ),
    /network_access=true/,
  )
  // A non-live-read resume must stay read-only, never silently workspace-write.
  assert.throws(
    () => assertResumeSandboxConfig(LIVE_READ_RESUME),
    /must stay sandbox_mode=read-only/,
  )
  assert.throws(
    () => assertResumeSandboxConfig(['codex', 'exec', 'resume', '--json', 'SID', '-']),
    /exactly one -c sandbox_mode config required/,
  )
})

test('an OpenAI review-pass bootstrap must be read-only-first', () => {
  assert.deepEqual(
    assertReadOnlyFirstBootstrap(['codex', 'exec', '--json', '-C', '/wt', '-m', 'gpt-5.4-codex', '-s', 'read-only', '-']),
    { sandbox_mode: 'read-only' },
  )
  assert.throws(
    () => assertReadOnlyFirstBootstrap(['codex', 'exec', '--json', '-C', '/wt', '-m', 'gpt-5.4-codex', '-s', 'workspace-write', '-']),
    /must be read-only-first/,
  )
  assert.throws(
    () => assertReadOnlyFirstBootstrap(['codex', 'exec', '--json', '-C', '/wt', '-m', 'gpt-5.4-codex', '-']),
    /must be read-only-first/,
  )
})

// TUR-447 F2b Unit G. Spec: role-runtime role-openai-relay, role-openai-fail-closed,
// launch-correctness-path, launch-review-sandbox-integrity, launch-resume-sandbox-config,
// launch-role-purpose-capability (blob spec/domains/role-runtime.spec.html). The composite
// OpenAI-reviewer relay gate ties the whole review pass into one deterministic acceptance:
// resolved-from-roles.toml runtime, independent rollout provenance, sandbox law, worktree
// immutability, and relay-verbatim verification. A verdict admitted through the generic
// native agent() path (no relay), with relay-supplied rollout, or with a mutated worktree
// is rejected.
const RESOLVED_REVIEWER_RUNTIME = { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', service_tier: 'default' }
const REVIEW_BOOTSTRAP = ['codex', 'exec', '--json', '-C', '/wt', '-m', 'gpt-5.6-sol', '-s', 'read-only', '-']
const REVIEW_RESUME = [
  'codex', 'exec', 'resume', '--json',
  '-c', 'sandbox_mode="workspace-write"', '-c', 'sandbox_workspace_write.network_access=true', SESSION_ID, '-',
]

function reviewerRolloutRecord(overrides = {}) {
  return { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', final_message: RELAY_MESSAGE, ...overrides }
}

function reviewerRelay(overrides = {}) {
  return {
    claimed_session_id: SESSION_ID,
    payload: RELAY_MESSAGE,
    bootstrap_argv: REVIEW_BOOTSTRAP,
    resume_argv: REVIEW_RESUME,
    needs_live_reads: true,
    worktree_before: { head: 'abc123', status: '' },
    worktree_after: { head: 'abc123', status: '' },
    ...overrides,
  }
}

function independentRollout(overrides = {}) {
  return { source: 'independent-rollout-subagent', data: reviewerRolloutRecord(overrides.record), ...overrides }
}

test('review worktree immutability accepts an unchanged HEAD and empty status', () => {
  assert.deepEqual(
    assertReviewWorktreeImmutable({ head: 'abc123', status: '' }, { head: 'abc123', status: '' }),
    { head: 'abc123', status: '' },
  )
})

test('review worktree immutability rejects a changed HEAD or a dirty status', () => {
  assert.throws(
    () => assertReviewWorktreeImmutable({ head: 'abc123', status: '' }, { head: 'def456', status: '' }),
    /worktree HEAD changed/,
  )
  assert.throws(
    () => assertReviewWorktreeImmutable({ head: 'abc123', status: '' }, { head: 'abc123', status: ' M file' }),
    /worktree status changed/,
  )
})

test('OpenAI-reviewer relay gate accepts a fully verified code-reviewer relay pass', () => {
  const accepted = acceptOpenaiReviewRelay(
    'code-reviewer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(), independentRollout(),
  )
  assert.equal(accepted.verdict_payload, RELAY_MESSAGE)
  assert.equal(accepted.session_id, SESSION_ID)
})

// Red: a reviewer pass that uses the generic native agent() path supplies no relay session,
// no bootstrap/resume argv, and no rollout provenance, so it cannot pass the composite gate.
test('OpenAI-reviewer relay gate rejects a generic native agent() reviewer pass (no relay)', () => {
  assert.throws(
    () => acceptOpenaiReviewRelay('code-reviewer', RESOLVED_REVIEWER_RUNTIME, { payload: RELAY_MESSAGE }, independentRollout()),
    /relay claimed session id required/,
  )
})

// Red: rollout data supplied by the relay itself (or stamped as coming from the relay) is
// rejected before verification; only the independent read-only subagent may supply it.
test('OpenAI-reviewer relay gate rejects rollout data supplied by the relay', () => {
  assert.throws(
    () => acceptOpenaiReviewRelay(
      'code-reviewer', RESOLVED_REVIEWER_RUNTIME,
      reviewerRelay({ rollout: reviewerRolloutRecord() }), independentRollout(),
    ),
    /relay must not supply the rollout record/,
  )
  assert.throws(
    () => acceptOpenaiReviewRelay(
      'code-reviewer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(),
      { source: 'relay', data: reviewerRolloutRecord() },
    ),
    /not from the independent read-only subagent/,
  )
})

// Red: relay payload differs from the independently fetched rollout final message.
test('OpenAI-reviewer relay gate rejects a relay payload that edits the rollout final message', () => {
  assert.throws(
    () => acceptOpenaiReviewRelay(
      'qa-reviewer', RESOLVED_REVIEWER_RUNTIME,
      reviewerRelay({ payload: `${RELAY_MESSAGE} (softened)` }), independentRollout(),
    ),
    /payload mismatch with rollout record/,
  )
})

// Red: a resume that uses the top-level -s flag instead of -c sandbox_mode config.
test('OpenAI-reviewer relay gate rejects a resume using the top-level -s flag', () => {
  assert.throws(
    () => acceptOpenaiReviewRelay(
      'code-reviewer', RESOLVED_REVIEWER_RUNTIME,
      reviewerRelay({ resume_argv: ['codex', 'exec', 'resume', '--json', '-s', 'workspace-write', SESSION_ID, '-'] }),
      independentRollout(),
    ),
    /top-level -s flag prohibited on resume/,
  )
})

// Red: a mutated review worktree HEAD found after the resumed pass.
test('OpenAI-reviewer relay gate rejects a review pass that mutated its worktree', () => {
  assert.throws(
    () => acceptOpenaiReviewRelay(
      'code-reviewer', RESOLVED_REVIEWER_RUNTIME,
      reviewerRelay({ worktree_after: { head: 'def456', status: '' } }), independentRollout(),
    ),
    /worktree HEAD changed/,
  )
})

// Red: effective identity proven from the rollout must match the roles.toml-resolved runtime.
test('OpenAI-reviewer relay gate rejects a rollout model that disagrees with resolved runtime', () => {
  assert.throws(
    () => acceptOpenaiReviewRelay(
      'code-reviewer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(),
      independentRollout({ record: { model: 'gpt-5.4' } }),
    ),
    /effective identity mismatch: model/,
  )
})

// Red: a non-reviewer role must never enter the OpenAI relay acceptance gate.
test('OpenAI-reviewer relay gate rejects a non-reviewer role', () => {
  assert.throws(
    () => acceptOpenaiReviewRelay('implementer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(), independentRollout()),
    /not an OpenAI reviewer role/,
  )
})

// TUR-447 cycle1 pass2 P0: shaping-reviewer has a real cutover relay execution path with the
// SAME fail-closed independent-rollout provenance and sandbox law the code/qa reviewers use
// (role-runtime launch-purpose-shaping-roles, role-openai-relay, role-openai-fail-closed).
test('shaping-review relay gate accepts a fully verified shaping-reviewer relay pass', () => {
  const accepted = acceptShapingReviewRelay(
    'shaping-reviewer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(), independentRollout(),
  )
  assert.equal(accepted.verdict_payload, RELAY_MESSAGE)
  assert.equal(accepted.session_id, SESSION_ID)
})

// Red: the shaping relay path must NOT admit a code/qa reviewer or any non-shaping role, and
// the code/qa gate must NOT admit shaping-reviewer; each purpose keeps its own admitted set.
test('shaping-review relay gate rejects a non-shaping role and the reviewer gate rejects shaping-reviewer', () => {
  assert.throws(
    () => acceptShapingReviewRelay('code-reviewer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(), independentRollout()),
    /not a shaping-review relay role/,
  )
  assert.throws(
    () => acceptOpenaiReviewRelay('shaping-reviewer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(), independentRollout()),
    /not an OpenAI reviewer role/,
  )
})

// Red: the shaping relay is genuinely fail-closed: a relay-supplied rollout is rejected before
// verification exactly as at the reviewer gate.
test('shaping-review relay gate rejects rollout data not from the independent read-only subagent', () => {
  assert.throws(
    () => acceptShapingReviewRelay(
      'shaping-reviewer', RESOLVED_REVIEWER_RUNTIME, reviewerRelay(),
      { source: 'relay', data: reviewerRolloutRecord() },
    ),
    /not from the independent read-only subagent/,
  )
})

// === gh#8 integration: provisioning-trust identity (Anchor A retired as trust source) ==============
// TUR-447 gh#8: the identity TRUST ROOT is now the host-provisioned per-lane worktree, proven by the
// out-of-tree provision record (source host-provisioned-worktree, schema_version 1, resolver_root ==
// worktree) cross-checked against the frozen launch env a child cannot forge (cwd == OCTO_WORKTREE).
// assertReceiptWorkspaceBinding (Anchor A = a receipt.toml at $OCTO_RECEIPT) is RETIRED as the trust
// source and REPLACED by assertProvisionedWorkspaceBinding(envelope, provision, env). Anchor B
// (assertLiveWorktreeIdentity) stays as a cheap defense-in-depth reality check, no longer the root.
const PROV_REPO = '/root/octo-lite'
const PROV_SLUG = 'varelaseb/octo-lite'
const PROV_WORKTREE = '/root/octo-lite/.wt/tur-447'
const PROV_ROOT = '/root/octo-lite/.wt'
const PROV_BRANCH = 'octo-lite/tur-447-gh8-integration'
const PROV_HEAD = '3696e1abadc0ffee00000000000000000000abcd'

function provEnvelope(overrides = {}) {
  return {
    repo: PROV_REPO, repo_slug: PROV_SLUG, worktree: PROV_WORKTREE,
    branch: PROV_BRANCH, starting_head: PROV_HEAD, ...overrides,
  }
}
// The host-authored, out-of-tree provision record (gh#8 launch-provision-record).
function provRecord(overrides = {}) {
  return {
    schema_version: 1, source: HOST_PROVISION_SOURCE, lane: 'tur-447',
    control_repo: PROV_REPO, worktree: PROV_WORKTREE, worktree_root: PROV_ROOT,
    repo_slug: PROV_SLUG, branch: PROV_BRANCH, starting_head: PROV_HEAD,
    resolver_root: PROV_WORKTREE, install_check: 'clean',
    provisioned_at: '2026-07-22T04:00:00Z', ...overrides,
  }
}
// The frozen launch env the host set into the loop process; a child cannot forge its own launch env,
// and cwd == OCTO_WORKTREE is the anchor. The reader resolves these itself and returns them.
function provEnv(overrides = {}) {
  return {
    OCTO_WORKTREE: PROV_WORKTREE, OCTO_WORKTREE_ROOT: PROV_ROOT,
    OCTO_CONTROL_REPO: PROV_REPO, OCTO_REPO_SLUG: PROV_SLUG,
    OCTO_STARTING_HEAD: PROV_HEAD, OCTO_LANE: 'tur-447', ...overrides,
  }
}
function provLive(overrides = {}) {
  return {
    source: 'host-receipt-pinned-worktree-read', read_worktree: PROV_WORKTREE,
    head: PROV_HEAD, branch: PROV_BRANCH, repo_slug: PROV_SLUG, ...overrides,
  }
}

test('provision-binding: accepts identity when provision record + resolved env agree with the envelope (source host-provisioned-worktree)', () => {
  assert.doesNotThrow(() => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord(), provEnv()))
})

test('provision-binding: rejects when OCTO_PROVISION_RECORD/env is missing (fail closed, no fabricated identity)', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(provEnvelope(), null, provEnv()), /provision/)
  assert.throws(() => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord(), null), /env|provision/)
  const noWt = provEnv(); delete noWt.OCTO_WORKTREE
  assert.throws(() => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord(), noWt), /OCTO_WORKTREE/)
})

test('provision-binding: rejects when the source is not host-provisioned-worktree', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord({ source: 'host-provisioned-receipt' }), provEnv()),
    /host-provisioned-worktree|provision record source/,
  )
})

test('provision-binding: rejects when schema_version is not 1', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord({ schema_version: 2 }), provEnv()),
    /schema_version/,
  )
})

test('provision-binding: rejects when resolver_root != worktree (INV5)', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord({ resolver_root: '/root/octo-lite/.wt/other' }), provEnv()),
    /resolver_root|resolver root/,
  )
})

test('provision-binding: rejects when the envelope worktree disagrees with the provision record (accidental misrouting)', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope({ worktree: '/root/foreign-lane-wt' }), provRecord(), provEnv()),
    /worktree/,
  )
})

test('provision-binding: rejects when the envelope repo_slug disagrees with the provision record', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope({ repo_slug: 'attacker/other' }), provRecord(), provEnv()),
    /repo_slug|slug/,
  )
})

test('provision-binding: rejects when the envelope starting_head disagrees with the provision record', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope({ starting_head: 'deadbeef' }), provRecord(), provEnv()),
    /starting|head/i,
  )
})

test('provision-binding: rejects when the envelope branch disagrees with the provision record', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope({ branch: 'someone-elses/lane' }), provRecord(), provEnv()),
    /branch/,
  )
})

test('provision-binding: rejects when the resolved env OCTO_WORKTREE disagrees with the provision record (env vs record cross-check)', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord(), provEnv({ OCTO_WORKTREE: '/root/foreign-lane-wt' })),
    /OCTO_WORKTREE|worktree/,
  )
})

test('provision-binding: rejects when the resolved env OCTO_REPO_SLUG disagrees with the provision record', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord(), provEnv({ OCTO_REPO_SLUG: 'attacker/other' })),
    /OCTO_REPO_SLUG|slug/,
  )
})

test('provision-binding: rejects when env OCTO_CONTROL_REPO/OCTO_WORKTREE_ROOT is inconsistent with the record (INV2)', () => {
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord(), provEnv({ OCTO_CONTROL_REPO: '/root/other-repo' })),
    /OCTO_CONTROL_REPO|control_repo/,
  )
  assert.throws(
    () => assertProvisionedWorkspaceBinding(provEnvelope(), provRecord(), provEnv({ OCTO_WORKTREE_ROOT: '/root/other' })),
    /OCTO_WORKTREE_ROOT|worktree_root/,
  )
})

test('host-trusted-identity: now composes provisioning-binding + the live-read Anchor B (defense-in-depth)', () => {
  // BOTH pass for a genuine matching triple: provision record + env + live read all agree.
  assert.doesNotThrow(() => assertHostTrustedIdentity(provEnvelope(), provRecord(), provLive(), provEnv()))
})

test('anchor-b-defense-in-depth: the live read STILL rejects a foreign branch/remote, and its role does NOT restore Anchor A (receipt) as the trust root', () => {
  // Anchor B (live-read) still catches the tur-456 foreign-branch shape as a cheap reality check.
  assert.throws(
    () => assertHostTrustedIdentity(provEnvelope(), provRecord(), provLive({ branch: 'someone-elses/lane' }), provEnv()),
    /foreign branch/,
  )
  assert.throws(
    () => assertHostTrustedIdentity(provEnvelope(), provRecord(), provLive({ repo_slug: 'attacker/other' }), provEnv()),
    /foreign remote/,
  )
  // The provisioning source constant is the new trust-root stamp.
  assert.equal(typeof HOST_PROVISION_SOURCE, 'string')
  assert.equal(HOST_PROVISION_SOURCE, 'host-provisioned-worktree')
})
