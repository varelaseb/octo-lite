// Unit tests for the canonical delivery-loop gate module (workflows/lib/gates.mjs). ADR 0003
// (drop-loop-trust-root) removed the loop-entry trust root, the independent observer, the ack-echo
// two-phase gate, the launch-revision revalidation, and the pre-push readback; the retained set is the
// admission matrix, containment, the code/QA review acceptance gates, the acceptance-package
// builder, and the OpenAI reviewer relay-provenance gate (role-runtime role-openai-relay,
// role-openai-fail-closed).
import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

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

// Containment is a git-LINKAGE property (role-runtime launch-containment-integrity), not path-prefix
// nesting. assertContainment admits the repository's own top-level working tree and any linked worktree
// whose .git file resolves bidirectionally into that repository's worktrees set, and rejects only a path
// whose git linkage does not belong to the repository. The linkage reader is injectable so the pure
// predicate is testable without a real filesystem; it defaults to the real-fs reader.
test('assertContainment admits by git linkage (top-level and bidirectional sibling) and rejects a foreign linkage', () => {
  // Equal repo-root: <resolved>/.git is a directory -> the repository top-level working tree.
  const topLevel = (p) => (p === '/repo/.git' ? { type: 'dir' } : { type: 'missing' })
  assert.equal(assertContainment('/repo', '.', topLevel), '/repo')
  // Sibling: <resolved>/.git is a `gitdir:` file into worktrees/<name>, whose gitdir points back.
  const linked = (p) => {
    if (p === '/root/sib/.git') return { type: 'file', content: 'gitdir: /root/repo/.git/worktrees/sib\n' }
    if (p === '/root/repo/.git/worktrees/sib/gitdir') return { type: 'file', content: '/root/sib/.git\n' }
    return { type: 'missing' }
  }
  assert.equal(assertContainment('/root/repo', '../sib', linked), '/root/sib')
  // Escape: a forged .git whose worktrees entry points back to a DIFFERENT worktree, so the
  // bidirectional linkage does not hold and the path does not belong to the repository.
  const forged = (p) => {
    if (p === '/root/evil/.git') return { type: 'file', content: 'gitdir: /root/repo/.git/worktrees/sib\n' }
    if (p === '/root/repo/.git/worktrees/sib/gitdir') return { type: 'file', content: '/root/sib/.git\n' }
    return { type: 'missing' }
  }
  assert.throws(() => assertContainment('/root', 'evil', forged), /escapes/)
})

// Real-repo git-worktree linkage classes (self-validating bidirectional linkage created with git):
// <repo>/.git/worktrees/<name>/gitdir reads back to the linked worktree's .git file. These exercise the
// default real-fs linkage reader end to end.
function git(cwd, ...args) {
  execFileSync('git', args, { cwd, stdio: 'pipe' })
}

function makeRepo() {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), 'octo-containment-')))
  const repo = join(dir, 'repo')
  mkdirSync(repo)
  git(repo, 'init', '-q')
  git(repo, 'config', 'user.email', 't@t')
  git(repo, 'config', 'user.name', 't')
  writeFileSync(join(repo, 'f'), 'x')
  git(repo, 'add', 'f')
  git(repo, 'commit', '-qm', 'init')
  return { dir, repo }
}

test('assertContainment admits a real sibling git worktree by bidirectional linkage', () => {
  const { dir, repo } = makeRepo()
  try {
    git(repo, 'worktree', 'add', '-q', join(dir, 'sib'))
    // `git worktree add ../sib` is a sibling of the repo, never path-nested under it.
    assert.equal(assertContainment(repo, '../sib'), join(dir, 'sib'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('assertContainment admits the repository top-level working tree (equal repo-root path)', () => {
  const { dir, repo } = makeRepo()
  try {
    // Equal: the resolved worktree IS the repository top-level working tree; its .git is a directory.
    assert.equal(assertContainment(repo, '.'), repo)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('assertContainment rejects a path whose git linkage does not belong to the repository', () => {
  const { dir, repo } = makeRepo()
  try {
    git(repo, 'worktree', 'add', '-q', join(dir, 'sib'))
    // A path-NESTED directory (the retired prefix check admitted it) whose forged .git steals the
    // sibling's worktrees entry; that entry's gitdir points back to `sib`, not here, so the
    // bidirectional linkage fails and the path is an escape.
    const evil = join(repo, 'evil')
    mkdirSync(evil)
    writeFileSync(join(evil, '.git'), `gitdir: ${join(repo, '.git', 'worktrees', 'sib')}\n`)
    assert.throws(() => assertContainment(repo, 'evil'), /escapes/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
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
    resume_argv: ['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="workspace-write"', '-c', 'sandbox_workspace_write.network_access=true'],
    needs_live_reads: true,
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

test('sandbox-law predicates enforce read-only bootstrap and -c sandbox_mode resume', () => {
  assert.deepEqual(assertReadOnlyFirstBootstrap(['codex', 'exec', '-s', 'read-only']), { sandbox_mode: 'read-only' })
  assert.throws(() => assertReadOnlyFirstBootstrap(['codex', 'exec', '-s', 'workspace-write']), /read-only-first/)
  assert.throws(() => assertResumeSandboxConfig(['codex', 'resume', '-s', 'workspace-write'], { needsLiveReads: true }), /-s flag prohibited/)
  assert.deepEqual(
    assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="workspace-write"', '-c', 'sandbox_workspace_write.network_access=true'], { needsLiveReads: true }),
    { sandbox_mode: 'workspace-write', needsLiveReads: true },
  )
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
