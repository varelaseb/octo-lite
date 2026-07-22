// TUR-447 ruling-56 cycle3 slug-identity-bound (loop-correctness single-writer; delivery-lifecycle
// launch-readback, launch-identity; role-runtime launch-entrypoint-revalidation, launch-containment,
// launch-receipt). The cycle-2 codex gate found the STRUCTURAL ROOT: the canonical GitHub repo slug
// (owner/repo) and the host issue worktree were used ad-hoc but were NOT readiness-validated, NOT in
// the journalled bound-input set, NOT in the worker ack echo, and NOT in the launch-revision
// fingerprint. So a MISSING slug ran the Shaped -> Todo fire before failing, and a FOREIGN slug caused
// no identity mismatch. A related hole: a PR bound as a full URL (not a number) let `gh pr view <URL>
// --repo <slug>` silently select the URL's repository, hiding a foreign repo.
//
// This suite is the spec-derived RED for the fix. It proves, at the real gate seam (gates.mjs, which
// the loop's GATES-EMBED region mirrors byte-identically) and over the real loop source, that:
//   (1) repo_slug and worktree are REQUIRED, shape/containment-validated readiness inputs, so a missing
//       or malformed slug or an escaping worktree is REJECTED at readiness BEFORE any fire/spawn;
//   (2) a PR bound as a URL is REJECTED at readiness (the gh identity is the PR NUMBER + --repo <slug>);
//   (3) repo_slug and worktree are in the WORKER ACK ECHO bound-input set, so a foreign slug or worktree
//       fails assertWorkerAckEcho exactly as a HEAD mismatch does;
//   (4) repo_slug and worktree are in the LAUNCH-REVISION fingerprint, so a foreign slug/worktree
//       diverges launchRevision and the identity gate rejects it before any mutation;
//   (5) the loop's journalledBoundInputs threads repo_slug and worktree into the bound object (so 3+4
//       hold on the production path), and the worker-liveness echo is repo/worktree pinned.

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  assertReadyEnvelope,
  assertWorkerAckEcho,
  launchRevision,
  assertLaunchRevision,
} from '../workflows/lib/gates.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const LOOP_SRC = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8')

const REPO = '/root/octo-lite'
const REPO_SLUG = 'varelaseb/octo-lite'
const ISSUE = 'TUR-447'
const PR = 6
const BRANCH = 'octo-lite/tur-443-operating-model'
const HEAD = 'f00b13357cb1be87b5c5e6d7bd98fd9572915154'
const SPEC_BLOBS = ['spec/domains/role-runtime.spec.html:anchor-1']
const CONTRACT = 'c8b0440cacc5188b2926b626ee6f506ced5368ebbda67dc6b1ed0d542cddc34c'

function readyEnvelope(overrides = {}) {
  const base = {
    mode: 'implement',
    repo: REPO, repo_slug: REPO_SLUG, issue: ISSUE, pr: PR, branch: BRANCH,
    shaping_head: HEAD, pr_head: HEAD, pr_base: 'main',
    spec_revision: 'r1', linear_revision: 'lr1', topology_revision: 't1',
    linear_fingerprint: 'fp-shaped-a1', linear_state: 'Shaped',
    shaping_verdict: 'clear', shaping_verdict_head: HEAD,
    shaping_reviewer_receipt: 'rcpt-1', conversation_cutoff: 'session.jsonl:1',
    conversation_log_references: ['session.jsonl:1-1'],
    spec_blobs: SPEC_BLOBS, adr_blobs: [], shaping_verdict_inputs: ['in-1'],
    acceptance_criteria: ['works'],
    contract_hash: CONTRACT,
    worktree_root: '/root', worktree: 'octo-lite',
  }
  return { ...base, ...overrides }
}

// The exact bound-input set the loop journals for a worker pass, now identity-bound to the canonical
// slug and the host issue worktree.
function boundInputs(overrides = {}) {
  return {
    role: 'implementer', repo: REPO, repo_slug: REPO_SLUG, worktree: '/root/octo-lite',
    issue: ISSUE, pr: PR, starting_head: HEAD, spec_blobs: SPEC_BLOBS, contract_hash: CONTRACT,
    ...overrides,
  }
}

function ackFor(overrides = {}) {
  const b = boundInputs()
  return {
    role: b.role, repo: b.repo, repo_slug: b.repo_slug, worktree: b.worktree,
    issue: b.issue, pr: b.pr, starting_head: b.starting_head,
    spec_blobs: b.spec_blobs, contract_hash: b.contract_hash,
    ...overrides,
  }
}

// === (1) readiness validates repo_slug + worktree as REQUIRED identity-bound inputs ===============

test('slug-ready: a ready envelope carrying a canonical owner/repo slug and a contained worktree is accepted', () => {
  assert.doesNotThrow(() => assertReadyEnvelope(readyEnvelope()))
})

test('slug-ready: a MISSING repo_slug is REJECTED at readiness (before any fire/spawn)', () => {
  const env = readyEnvelope()
  delete env.repo_slug
  assert.throws(() => assertReadyEnvelope(env), /repo_slug/)
})

test('slug-ready: a FOREIGN/malformed repo_slug (not owner/repo shape) is REJECTED at readiness', () => {
  assert.throws(() => assertReadyEnvelope(readyEnvelope({ repo_slug: 'not-a-slug' })), /owner\/repo|repo_slug/)
  assert.throws(() => assertReadyEnvelope(readyEnvelope({ repo_slug: 'https://github.com/x/y' })), /owner\/repo|repo_slug/)
  assert.throws(() => assertReadyEnvelope(readyEnvelope({ repo_slug: 'a/b/c' })), /owner\/repo|repo_slug/)
})

test('slug-ready: a MISSING worktree is REJECTED at readiness', () => {
  const env = readyEnvelope()
  delete env.worktree
  assert.throws(() => assertReadyEnvelope(env), /worktree/)
})

test('slug-ready: a worktree that ESCAPES the worktree root is REJECTED at readiness', () => {
  assert.throws(() => assertReadyEnvelope(readyEnvelope({ worktree: '../elsewhere' })), /worktree|escape/)
})

// === (2) a PR bound as a URL is REJECTED (the gh identity is the PR NUMBER + --repo <slug>) ========

test('pr-number: a PR bound as a full URL is REJECTED at readiness so gh cannot infer a foreign repo from the URL', () => {
  assert.throws(
    () => assertReadyEnvelope(readyEnvelope({ pr: 'https://github.com/x/y/pull/6' })),
    /PR number|pr number|not a URL|URL/i,
  )
})

test('pr-number: a numeric PR is accepted at readiness', () => {
  assert.doesNotThrow(() => assertReadyEnvelope(readyEnvelope({ pr: 6 })))
  assert.doesNotThrow(() => assertReadyEnvelope(readyEnvelope({ pr: '6' })))
})

// === (3) repo_slug + worktree are in the WORKER ACK ECHO bound-input set ===========================

test('ack-echo: a matching ack (slug + worktree echoed) verifies', () => {
  assert.doesNotThrow(() => assertWorkerAckEcho(boundInputs(), ackFor()))
})

test('ack-echo: a FOREIGN repo_slug in the worker ack is REJECTED exactly as a HEAD mismatch is', () => {
  assert.throws(() => assertWorkerAckEcho(boundInputs(), ackFor({ repo_slug: 'attacker/other' })), /repo_slug|slug/)
})

test('ack-echo: a substituted worktree in the worker ack is REJECTED', () => {
  assert.throws(() => assertWorkerAckEcho(boundInputs(), ackFor({ worktree: '/root/foreign-lane-wt' })), /worktree/)
})

test('ack-echo: an OMITTED repo_slug or worktree in the worker ack is REJECTED', () => {
  const noSlug = ackFor(); delete noSlug.repo_slug
  assert.throws(() => assertWorkerAckEcho(boundInputs(), noSlug), /repo_slug|slug/)
  const noWt = ackFor(); delete noWt.worktree
  assert.throws(() => assertWorkerAckEcho(boundInputs(), noWt), /worktree/)
})

// === (4) repo_slug + worktree are in the LAUNCH-REVISION fingerprint ===============================

test('launch-revision: a FOREIGN repo_slug diverges the launch revision (identity mismatch), so it is rejected', () => {
  const canonical = launchRevision(boundInputs())
  const foreign = launchRevision(boundInputs({ repo_slug: 'attacker/other' }))
  assert.notEqual(foreign, canonical, 'a foreign slug must change the launch-revision fingerprint')
  // A caller presenting the canonical revision but a foreign slug fails revalidation.
  assert.throws(() => assertLaunchRevision(canonical, boundInputs({ repo_slug: 'attacker/other' })), /launch revision mismatch/)
})

test('launch-revision: a substituted worktree diverges the launch revision', () => {
  const canonical = launchRevision(boundInputs())
  const foreign = launchRevision(boundInputs({ worktree: '/root/foreign-lane-wt' }))
  assert.notEqual(foreign, canonical, 'a foreign worktree must change the launch-revision fingerprint')
})

// === (5) the loop threads repo_slug + worktree into journalledBoundInputs, and the worker-liveness
// echo is repo/worktree pinned (SOURCE assertions over the real production loop text) ==============

test('bound-inputs-source: journalledBoundInputs threads repo_slug and the contained worktree into the bound object', () => {
  const start = LOOP_SRC.indexOf('function journalledBoundInputs(')
  assert.ok(start >= 0, 'journalledBoundInputs missing from loop source')
  const region = LOOP_SRC.slice(start, start + 600)
  assert.match(region, /repo_slug:/, 'journalledBoundInputs must bind repo_slug')
  assert.match(region, /worktree:/, 'journalledBoundInputs must bind the host issue worktree')
})

test('liveness-pin: the worker-liveness echo reads the live PR via a repo-pinned gh pr view --repo ${slug} and git via git -C ${worktree}', () => {
  const start = LOOP_SRC.indexOf('LIVENESS ECHO: read the live Linear state')
  assert.ok(start >= 0, 'worker-liveness-echo anchor missing from loop source')
  const region = LOOP_SRC.slice(start, start + 900)
  assert.match(region, /gh pr view \$\{pr\} --repo \$\{slug\}/, 'worker-liveness must repo-pin the PR read')
  assert.match(region, /git -C \$\{worktree\}/, 'worker-liveness must pin git reads to the host worktree')
})
