// Unit tests for the canonical delivery-loop gate module (workflows/lib/gates.mjs). ADR 0003
// (drop-loop-trust-root) removed the loop-entry trust root, the independent observer, the ack-echo
// two-phase gate, the launch-revision revalidation, and the pre-push readback; the retained set is the
// admission matrix, containment, the code/QA review acceptance gates, the acceptance-package
// builder, and the OpenAI reviewer relay-provenance gate (role-runtime role-openai-relay,
// role-openai-fail-closed).
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  assertAdmission,
  assertManifestShape,
  assertContainment,
  assertRepoSlug,
  requiredPrNumber,
  acceptCodeReview,
  acceptQaReview,
  evidenceMode,
  buildAcceptancePackage,
  verifyRelayVerbatim,
  assertResumeSandboxConfig,
  assertReadOnlyFirstBootstrap,
  assertReviewWorktreeImmutable,
  acceptOpenaiReviewRelay,
  acceptShapingReviewRelay,
} from '../workflows/lib/gates.mjs'

test('assertAdmission admits the four delivery roles from a delivery state', () => {
  for (const role of ['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer']) {
    assert.deepEqual(assertAdmission({ purpose: 'delivery', role, linearState: 'Shaped' }), { purpose: 'delivery', role })
  }
})

test('assertAdmission rejects the retired observer role and non-delivery roles for delivery', () => {
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: 'tdd-observer', linearState: 'Shaped' }), /not admitted/)
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: 'reconciler', linearState: 'Shaped' }), /not admitted/)
})

test('assertAdmission enforces the Linear-state gate for delivery and shaping-review', () => {
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: 'implementer', linearState: 'Awaiting Accept' }), /rejected/)
  assert.throws(() => assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer', linearState: 'Awaiting Accept' }), /rejected/)
  assert.deepEqual(
    assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer', linearState: 'Ideas' }),
    { purpose: 'shaping-review', role: 'shaping-reviewer' },
  )
})

test('assertAdmission admits the reconciler only as a Read-restricted subagent', () => {
  assert.deepEqual(assertAdmission({ purpose: 'reconcile', role: 'reconciler', readRestricted: true }), { purpose: 'reconcile', role: 'reconciler' })
  assert.throws(() => assertAdmission({ purpose: 'reconcile', role: 'reconciler' }), /Read-restricted/)
})

test('assertAdmission rejects an unknown purpose', () => {
  assert.throws(() => assertAdmission({ purpose: 'merge', role: 'implementer' }), /purpose/)
  assert.throws(() => assertAdmission({ purpose: '', role: 'implementer' }), /purpose/)
})

test('assertManifestShape admits the persistent shape and the worker-journal shape', () => {
  assert.deepEqual(assertManifestShape({ shape: 'persistent', role: 'orchestrator' }), { shape: 'persistent', role: 'orchestrator' })
  assert.throws(() => assertManifestShape({ shape: 'persistent', role: 'orchestrator', purpose: 'delivery' }), /pass purpose rejected/)
  assert.deepEqual(
    assertManifestShape({ shape: 'worker-journal', role: 'implementer', purpose: 'delivery', linearState: 'Shaped' }),
    { shape: 'worker-journal', role: 'implementer', purpose: 'delivery' },
  )
})

// Containment is a git-LINKAGE OWNERSHIP property (role-runtime launch-containment-integrity,
// launch-containment-sandbox-safe), not path-prefix nesting: the candidate belongs to the repository iff
// its git-common-dir equals the repository's own git-common-dir. Because the gate runs inside the
// delivery-loop Workflow interpreter (no process, filesystem, or module access), it NEVER reads git
// itself: real git is the linkage authority and the read-only delivery-entry derivation agent
// host-derives BOTH absolute common-dirs and supplies them to the pure gate. assertContainment resolves
// and returns the candidate worktree path and admits iff the two supplied common-dirs are equal. A
// sibling worktree (`git worktree add ../sib`) and the repository's own top-level working tree both
// share the repository's common-dir (admitted); a path whose common-dir belongs to a DIFFERENT
// repository differs (rejected). No filesystem read, no injected reader: that linkage validation is now
// git's job on the host.
test('assertContainment admits equal common-dirs (sibling and repo-root) and rejects a differing common-dir', () => {
  const repoCommon = '/root/repo/.git'
  // Sibling worktree: candidate common-dir equals the repository's own; resolves to the sibling path.
  assert.equal(assertContainment(repoCommon, repoCommon, '/root/repo', '../sib'), '/root/sib')
  // Equal repo-root: the candidate IS the repository top-level working tree; same common-dir.
  assert.equal(assertContainment('/repo/.git', '/repo/.git', '/repo', '.'), '/repo')
  // Escape: the candidate's git-common-dir belongs to a DIFFERENT repository; differs -> rejected.
  assert.throws(() => assertContainment(repoCommon, '/root/other/.git', '/root/repo', '../other'), /escapes/)
})

test('assertRepoSlug and requiredPrNumber reject a URL and a bare name', () => {
  assert.equal(assertRepoSlug('a/b', 'slug'), 'a/b')
  assert.throws(() => assertRepoSlug('bare', 'slug'), /owner\/repo/)
  assert.equal(requiredPrNumber(6, 'pr'), '6')
  assert.equal(requiredPrNumber('6', 'pr'), '6')
  assert.throws(() => requiredPrNumber('https://x/pull/6', 'pr'), /not a URL/)
})

test('acceptCodeReview advances on clear and returns findings on blocking', () => {
  assert.deepEqual(acceptCodeReview('h', 'https://pr', { head: 'h', verdict: 'clear', comment_url: 'https://pr#c' }), { advance: true, findings: [] })
  assert.deepEqual(
    acceptCodeReview('h', 'https://pr', { head: 'h', verdict: 'blocking', findings: ['x'], comment_url: 'https://pr#c' }),
    { advance: false, findings: ['x'] },
  )
})

test('acceptQaReview advances on satisfied all-pass and returns non-pass findings otherwise', () => {
  const base = { head: 'h', issue: 'TUR-13', pr: 21, manifest: 'm' }
  const ok = acceptQaReview('h', base, { ...base, verdict: 'satisfied', packet_url: 'u', criteria: [{ criterion: 'c', status: 'pass', observation: 'o' }] })
  assert.equal(ok.advance, true)
  const bad = acceptQaReview('h', base, {
    ...base, verdict: 'blocking', packet_url: 'u',
    criteria: [{ criterion: 'c', status: 'fail', observation: 'o', artifact: 'a', fix: 'f' }],
  })
  assert.equal(bad.advance, false)
})

test('evidenceMode selects visual or nonvisual', () => {
  assert.equal(evidenceMode(true), 'visual')
  assert.equal(evidenceMode(false), 'nonvisual')
})

test('buildAcceptancePackage builds a complete package and marks self_accepted false', () => {
  const pkg = buildAcceptancePackage({
    issue: 'TUR-13', pr: 21, head: 'h',
    code_review: { verdict: 'clear', head: 'h' },
    qa_review: { verdict: 'satisfied', head: 'h' },
    evidence_card_links: ['https://site/card'],
    linear_state: 'In Progress', summary: 'collapsed the loop',
  })
  assert.equal(pkg.self_accepted, false)
  assert.equal(pkg.code_review_verdict, 'clear')
  assert.equal(pkg.qa_review_verdict, 'satisfied')
  assert.deepEqual(pkg.evidence_card_links, ['https://site/card'])
})

test('buildAcceptancePackage fails closed on a missing card link or an unsatisfied verdict', () => {
  const base = {
    issue: 'TUR-13', pr: 21, head: 'h',
    code_review: { verdict: 'clear', head: 'h' },
    qa_review: { verdict: 'satisfied', head: 'h' },
    evidence_card_links: ['https://site/card'], linear_state: 'In Progress', summary: 's',
  }
  assert.throws(() => buildAcceptancePackage({ ...base, evidence_card_links: [] }), /evidence card links/)
  assert.throws(() => buildAcceptancePackage({ ...base, qa_review: { verdict: 'blocking', head: 'h' } }), /satisfied exact-head/)
  assert.throws(() => buildAcceptancePackage({ ...base, code_review: { verdict: 'clear', head: 'other' } }), /clear exact-head/)
})

const RUNTIME = { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', service_tier: 'default' }
function relay(payload) {
  return {
    claimed_session_id: 's1', payload,
    bootstrap_argv: ['codex', 'exec', '-s', 'read-only'],
    resume_argv: ['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="read-only"'],
    worktree_before: { head: 'h', status: '' },
    worktree_after: { head: 'h', status: '' },
  }
}
function rollout(payload) {
  return { source: 'independent-rollout-subagent', data: { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', final_message: payload } }
}

test('verifyRelayVerbatim proves effective identity from the rollout and rejects a payload edit', () => {
  const verified = verifyRelayVerbatim(RUNTIME, 's1', 'hello', { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', final_message: 'hello' })
  assert.equal(verified.final_message, 'hello')
  assert.throws(() => verifyRelayVerbatim(RUNTIME, 's1', 'edited', { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', final_message: 'hello' }), /payload mismatch/)
  assert.throws(() => verifyRelayVerbatim(RUNTIME, 's1', 'hello', { provider: 'anthropic', model: 'gpt-5.6-sol', effort: 'high', final_message: 'hello' }), /provider substitution/)
})

test('sandbox-law predicates enforce read-only bootstrap and a read-only -c sandbox_mode resume', () => {
  assert.deepEqual(assertReadOnlyFirstBootstrap(['codex', 'exec', '-s', 'read-only']), { sandbox_mode: 'read-only' })
  assert.throws(() => assertReadOnlyFirstBootstrap(['codex', 'exec', '-s', 'workspace-write']), /read-only-first/)
  // Resume admits EXACTLY one read-only -c sandbox_mode config and returns read-only.
  assert.deepEqual(
    assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="read-only"']),
    { sandbox_mode: 'read-only' },
  )
  // A workspace-write resume is rejected.
  assert.throws(() => assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="workspace-write"']), /read-only/)
  // A network-access resume config is rejected even alongside read-only.
  assert.throws(
    () => assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="read-only"', '-c', 'sandbox_workspace_write.network_access=true']),
    /network/,
  )
  // A top-level -s resume is rejected.
  assert.throws(() => assertResumeSandboxConfig(['codex', 'resume', '-s', 'read-only']), /-s flag prohibited/)
})

// launch-review-least-privilege conformance probe (role-runtime launch-review-least-privilege): the
// whole reviewer grant is read-only plus no-network. Fired across the reviewer resume argv space,
// read-only is the ONLY admitted resume config; every workspace-write or network-access resume is
// rejected.
test('launch-review-least-privilege admits read-only-only and rejects workspace-write or network resumes', () => {
  assert.deepEqual(
    assertResumeSandboxConfig(['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="read-only"']),
    { sandbox_mode: 'read-only' },
  )
  const rejected = [
    ['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="workspace-write"'],
    ['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="workspace-write"', '-c', 'sandbox_workspace_write.network_access=true'],
    ['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="danger-full-access"'],
    ['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="read-only"', '-c', 'sandbox_workspace_write.network_access=true'],
    ['codex', 'exec', 'resume', 's1', '-s', 'workspace-write'],
  ]
  for (const argv of rejected) {
    assert.throws(() => assertResumeSandboxConfig(argv), /rejected/)
  }
})

test('assertReviewWorktreeImmutable rejects a mutated review worktree', () => {
  assert.deepEqual(assertReviewWorktreeImmutable({ head: 'h', status: '' }, { head: 'h', status: '' }), { head: 'h', status: '' })
  assert.throws(() => assertReviewWorktreeImmutable({ head: 'h', status: '' }, { head: 'other', status: '' }), /HEAD changed/)
  assert.throws(() => assertReviewWorktreeImmutable({ head: 'h', status: '' }, { head: 'h', status: ' M f' }), /status changed/)
})

test('acceptOpenaiReviewRelay accepts a good reviewer relay and rejects a relay-supplied rollout', () => {
  const accepted = acceptOpenaiReviewRelay('code-reviewer', RUNTIME, relay('verdict'), rollout('verdict'))
  assert.equal(accepted.verdict_payload, 'verdict')
  const tainted = { ...relay('verdict'), rollout_source: 'relay' }
  assert.throws(() => acceptOpenaiReviewRelay('code-reviewer', RUNTIME, tainted, rollout('verdict')), /must not supply the rollout/)
  assert.throws(() => acceptOpenaiReviewRelay('implementer', RUNTIME, relay('v'), rollout('v')), /is not an OpenAI reviewer/)
})

test('acceptShapingReviewRelay admits the shaping-reviewer through the same fail-closed gate', () => {
  const accepted = acceptShapingReviewRelay('shaping-reviewer', RUNTIME, relay('verdict'), rollout('verdict'))
  assert.equal(accepted.verdict_payload, 'verdict')
  assert.throws(() => acceptShapingReviewRelay('code-reviewer', RUNTIME, relay('v'), rollout('v')), /is not a shaping-review/)
})
