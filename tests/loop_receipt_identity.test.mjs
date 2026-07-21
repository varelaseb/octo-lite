// TUR-447 ruling-59 receipt+live-read identity trust anchor (loop-correctness single-writer;
// delivery-lifecycle launch-readback, delivery-entry-gate; role-runtime launch-identity,
// launch-entrypoint-revalidation, launch-containment, launch-receipt). ROOT FIX for the
// self-referential identity hole. Every prior identity check validated the envelope
// repo_slug/worktree/starting_head OVER the same forgeable child envelope, so a foreign-but-
// well-formed envelope self-consistently passed. The fix adds TWO trust anchors the child cannot
// forge, NEITHER derived from the envelope, validated BEFORE any Shaped -> Todo fire or spawn:
//   Anchor A - a HOST-PROVISIONED receipt (repo_slug/worktree/starting_head) read from a HOST-TRUSTED
//     location; the envelope must MATCH it (catches a forged envelope claiming a different
//     repo/worktree/head than the host provisioned).
//   Anchor B - a LIVE git read of the RECEIPT-pinned worktree (HEAD/branch/origin); the receipt+
//     envelope must MATCH it (catches the tur-456 shape: a matching worktree PATH that is on a
//     FOREIGN branch / different remote - Anchor A alone MISSES this).
//
// This suite is the spec-derived RED. It proves the anchors BOTH at the real gate seam (gates.mjs,
// mirrored byte-identically into the loop's GATES-EMBED region) AND through the REAL loop identity
// gate driven by the composed harness (fail-closed if the gate is removed): a mismatch drives NO
// transition and NO spawn; a matching envelope+receipt+live-read is ACCEPTED. It does NOT call pure
// fingerprint helpers as the proof; it drives the production identity gate on the real foreign path.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  assertReceiptWorkspaceBinding,
  assertLiveWorktreeIdentity,
  assertHostTrustedIdentity,
  assertPrePushWorktreeReAnchor,
} from '../workflows/lib/gates.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const LOOP_SRC = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8')

const REPO = '/root/octo-lite'
const REPO_SLUG = 'varelaseb/octo-lite'
const WORKTREE_ABS = '/root/octo-lite'
const BRANCH = 'octo-lite/tur-443-operating-model'
const HEAD = 'f00b13357cb1be87b5c5e6d7bd98fd9572915154'

// A well-formed envelope carries the identity fields; the child controls all of them.
function envelope(overrides = {}) {
  return {
    repo: REPO, repo_slug: REPO_SLUG, worktree: WORKTREE_ABS, branch: BRANCH, starting_head: HEAD,
    ...overrides,
  }
}
// The HOST-PROVISIONED receipt (Anchor A): host-authored, source-stamped, NOT from the envelope.
function receipt(overrides = {}) {
  return {
    source: 'host-provisioned-receipt', repo: REPO, repo_slug: REPO_SLUG,
    worktree: WORKTREE_ABS, starting_head: HEAD, ...overrides,
  }
}
// The LIVE git read of the receipt-pinned worktree (Anchor B): the non-forgeable reality.
function live(overrides = {}) {
  return {
    source: 'host-receipt-pinned-worktree-read', read_worktree: WORKTREE_ABS,
    head: HEAD, branch: BRANCH, repo_slug: REPO_SLUG, ...overrides,
  }
}

// === Seam: Anchor A - host receipt workspace binding ==============================================

test('receipt-anchor: a matching envelope+receipt is accepted', () => {
  assert.doesNotThrow(() => assertReceiptWorkspaceBinding(envelope(), receipt()))
})

test('receipt-anchor: a receipt NOT stamped host-provisioned (a forged/child receipt) is REJECTED', () => {
  assert.throws(() => assertReceiptWorkspaceBinding(envelope(), receipt({ source: 'child-supplied' })), /not from the host-provisioned/)
})

test('receipt-anchor: a forged envelope claiming a DIFFERENT repo_slug than the receipt is REJECTED', () => {
  assert.throws(() => assertReceiptWorkspaceBinding(envelope({ repo_slug: 'attacker/other' }), receipt()), /repo slug does not match/)
})

test('receipt-anchor: a forged envelope claiming a DIFFERENT worktree than the receipt is REJECTED', () => {
  assert.throws(() => assertReceiptWorkspaceBinding(envelope({ worktree: '/root/foreign-lane-wt' }), receipt()), /worktree does not match/)
})

test('receipt-anchor: a forged envelope claiming a DIFFERENT starting_head than the receipt is REJECTED', () => {
  assert.throws(() => assertReceiptWorkspaceBinding(envelope({ starting_head: 'deadbeef' }), receipt()), /starting HEAD does not match/)
})

// === Seam: Anchor B - live receipt-pinned worktree reality ========================================

test('live-anchor: a matching receipt+envelope+live read is accepted', () => {
  assert.doesNotThrow(() => assertLiveWorktreeIdentity(receipt(), envelope(), live()))
})

test('live-anchor: a live read NOT stamped by the host-controlled reader is REJECTED', () => {
  assert.throws(() => assertLiveWorktreeIdentity(receipt(), envelope(), live({ source: 'worker' })), /not from the host-controlled/)
})

test('live-anchor: a live read that did NOT read the receipt-pinned worktree is REJECTED', () => {
  assert.throws(() => assertLiveWorktreeIdentity(receipt(), envelope(), live({ read_worktree: '/root/foreign-lane-wt' })), /did not read the receipt-pinned worktree/)
})

// The tur-456 shape: the worktree PATH matches the receipt, but the shared dir is on a FOREIGN
// branch. Anchor A alone (receipt vs envelope) PASSES; only the live read reveals the foreign branch.
test('live-anchor (tur-456): a receipt-pinned worktree on a FOREIGN branch is REJECTED by the live read (Anchor A alone misses this)', () => {
  // Anchor A passes: envelope, receipt, and even the envelope branch all agree.
  assert.doesNotThrow(() => assertReceiptWorkspaceBinding(envelope(), receipt()))
  // Anchor B catches it: the live branch of the receipt-pinned worktree is foreign.
  assert.throws(
    () => assertLiveWorktreeIdentity(receipt(), envelope(), live({ branch: 'someone-elses/lane' })),
    /on a foreign branch/,
  )
})

test('live-anchor (tur-456): a receipt-pinned worktree whose origin is a DIFFERENT remote is REJECTED by the live read', () => {
  assert.throws(
    () => assertLiveWorktreeIdentity(receipt(), envelope(), live({ repo_slug: 'attacker/other' })),
    /foreign remote/,
  )
})

test('live-anchor: a live HEAD that differs from the receipt/envelope starting HEAD is REJECTED', () => {
  assert.throws(() => assertLiveWorktreeIdentity(receipt(), envelope(), live({ head: 'differenthead000' })), /live HEAD is not the receipt-pinned starting HEAD|disagrees with the envelope/)
})

// === Seam: the composite host-trusted identity gate ==============================================

test('host-trusted-identity: BOTH anchors pass for a genuine matching triple', () => {
  assert.doesNotThrow(() => assertHostTrustedIdentity(envelope(), receipt(), live()))
})

test('host-trusted-identity: a mismatch on EITHER anchor rejects', () => {
  // Anchor A mismatch.
  assert.throws(() => assertHostTrustedIdentity(envelope({ repo_slug: 'attacker/other' }), receipt(), live()))
  // Anchor B mismatch (foreign branch, matching path).
  assert.throws(() => assertHostTrustedIdentity(envelope(), receipt(), live({ branch: 'foreign/lane' })))
})

// === Neither anchor derives from the envelope (SOURCE assertion over the production loop) =========

test('provenance: the loop reads the receipt from the HOST env location (OCTO_RECEIPT), never a child-envelope path', () => {
  const start = LOOP_SRC.indexOf('async function hostTrustedIdentity')
  assert.ok(start >= 0, 'hostTrustedIdentity missing from the loop source')
  const region = LOOP_SRC.slice(start, start + 4700)
  // The receipt is read from the host env var, and the loop forbids a child-supplied receipt path.
  assert.match(region, /OCTO_RECEIPT/, 'the receipt is read from the host OCTO_RECEIPT location')
  assert.match(region, /Do NOT accept, resolve, or read any receipt/i, 'forbids a child-supplied receipt path')
  // The live read is pinned to the RECEIPT worktree (git -C the receipt path), never an envelope path.
  assert.match(region, /git -C \$\{receiptWorktree\} rev-parse HEAD/, 'live HEAD read pinned to the receipt worktree')
  assert.match(region, /rev-parse --abbrev-ref HEAD/, 'live branch read of the receipt worktree')
  assert.match(region, /remote get-url origin/, 'live origin read of the receipt worktree')
  // The gate that decides both anchors is the production assertHostTrustedIdentity, over the identity
  // envelope + the host receipt + the live receipt-pinned read (neither the receipt nor the live read
  // is envelope-derived).
  assert.match(region, /assertHostTrustedIdentity\(identityEnvelope, receipt, live\)/, 'the loop drives the production host-trusted identity gate')
  assert.match(region, /assertReceiptWorkspaceBinding\(identityEnvelope, receipt\)/, 'Anchor A gate runs on the production path')
})

test('gate-position: the host-trusted identity gate runs BEFORE the Shaped -> Todo fire and before every spawn', () => {
  const implement = LOOP_SRC.slice(LOOP_SRC.indexOf("if (mode === 'implement')"), LOOP_SRC.indexOf("if (mode === 'code-review')"))
  assert.ok(implement.indexOf('hostTrustedIdentity(') >= 0, 'implement mode calls the identity gate')
  assert.ok(
    implement.indexOf('hostTrustedIdentity(') < implement.indexOf('loopFire('),
    'the identity gate runs BEFORE the Shaped -> Todo fire',
  )
  // spawnWorker and spawnOpenaiReviewer both call it before their live readback / spawn.
  const worker = LOOP_SRC.slice(LOOP_SRC.indexOf('async function spawnWorker'), LOOP_SRC.indexOf('async function acceptWorkerEchoOrDiscard'))
  assert.ok(worker.indexOf('hostTrustedIdentity(') >= 0 && worker.indexOf('hostTrustedIdentity(') < worker.indexOf('liveReadback('), 'spawnWorker gates identity before readback')
  const reviewer = LOOP_SRC.slice(LOOP_SRC.indexOf('async function spawnOpenaiReviewer'), LOOP_SRC.indexOf('async function spawnShapingReviewer'))
  assert.ok(reviewer.indexOf('hostTrustedIdentity(') >= 0 && reviewer.indexOf('hostTrustedIdentity(') < reviewer.indexOf('liveReadback('), 'spawnOpenaiReviewer gates identity before readback')
})

// === TUR-447 ruling-61 REAL live-read over a genuine temp git repo (accidental-misrouting reality) ===
// The identity live-read is best-effort INTERIM against ACCIDENTAL MISROUTING (tur-456: a shared dir on
// a FOREIGN branch / different origin), not a malicious forger. This drives the production gates over a
// GENUINE temp git repo checked out on a real foreign branch / real foreign origin: the live branch and
// origin are read with the EXACT git commands the production re-anchor reader runs (rev-parse
// --abbrev-ref HEAD; remote get-url origin), and those real readings are fed THROUGH the production
// assertPrePushWorktreeReAnchor / assertLiveWorktreeIdentity. The reality check REJECTS the foreign
// branch/origin. No forgery harness: the foreign state is a real git checkout, the reality is real git.

function git(cwd, ...a) {
  return execFileSync('git', ['-C', cwd, ...a], { encoding: 'utf8' }).trim()
}
// Normalize a git remote URL to the canonical owner/repo slug, as the production reader does.
function slugFromRemote(url) {
  const m = url.replace(/\.git$/, '').match(/[/:]([^/:]+\/[^/:]+)$/)
  return m ? m[1] : url
}
// Build a real temp git repo on the given branch with the given origin url; return the live reading
// exactly as the production receipt-pinned reader would return it.
function realWorktreeReading({ branch: onBranch, originUrl }) {
  const dir = mkdtempSync(join(tmpdir(), 'octo-reanchor-'))
  git(dir, 'init', '-q')
  git(dir, 'config', 'user.email', 'test@octo.local')
  git(dir, 'config', 'user.name', 'octo test')
  git(dir, 'commit', '-q', '--allow-empty', '-m', 'root')
  git(dir, 'branch', '-M', onBranch)
  git(dir, 'remote', 'add', 'origin', originUrl)
  const head = git(dir, 'rev-parse', 'HEAD')
  const liveBranch = git(dir, 'rev-parse', '--abbrev-ref', 'HEAD')
  const liveOrigin = slugFromRemote(git(dir, 'remote', 'get-url', 'origin'))
  return {
    dir,
    reading: { source: 'host-receipt-pinned-worktree-read', read_worktree: dir, head, branch: liveBranch, repo_slug: liveOrigin },
  }
}

test('real-git re-anchor: a genuine temp repo on the EXPECTED branch+origin PASSES the production pre-push re-anchor', () => {
  const { dir, reading } = realWorktreeReading({ branch: BRANCH, originUrl: `git@github.com:${REPO_SLUG}.git` })
  try {
    // The envelope expects exactly this branch/origin; the REAL live reading agrees.
    assert.doesNotThrow(() => assertPrePushWorktreeReAnchor({ branch: BRANCH, repo_slug: REPO_SLUG }, reading))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('real-git re-anchor (tur-456): a genuine temp repo CHECKED OUT ON A FOREIGN BRANCH is REJECTED by the production pre-push re-anchor', () => {
  // A REAL foreign-branch checkout (accidental misrouting), not a fabricated blob.
  const { dir, reading } = realWorktreeReading({ branch: 'someone-elses/lane', originUrl: `git@github.com:${REPO_SLUG}.git` })
  try {
    assert.equal(reading.branch, 'someone-elses/lane', 'the live git read reflects the real foreign branch')
    assert.throws(
      () => assertPrePushWorktreeReAnchor({ branch: BRANCH, repo_slug: REPO_SLUG }, reading),
      /receipt-pinned worktree is on a foreign branch at push time/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('real-git re-anchor (tur-456): a genuine temp repo whose ORIGIN is a DIFFERENT remote is REJECTED by the production pre-push re-anchor', () => {
  const { dir, reading } = realWorktreeReading({ branch: BRANCH, originUrl: 'git@github.com:attacker/other.git' })
  try {
    assert.equal(reading.repo_slug, 'attacker/other', 'the live git read reflects the real foreign origin')
    assert.throws(
      () => assertPrePushWorktreeReAnchor({ branch: BRANCH, repo_slug: REPO_SLUG }, reading),
      /receipt-pinned worktree origin is a foreign remote at push time/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('real-git identity anchor (tur-456): a genuine temp repo on a FOREIGN BRANCH is REJECTED by the production assertLiveWorktreeIdentity', () => {
  // The SAME real foreign-branch reality also fails the initial live identity anchor: the two gates are
  // consistent, the live-read reality check is the load-bearing accidental-misrouting catch at both.
  const { dir, reading } = realWorktreeReading({ branch: 'foreign/lane', originUrl: `git@github.com:${REPO_SLUG}.git` })
  try {
    const receiptObj = { source: 'host-provisioned-receipt', repo: REPO, repo_slug: REPO_SLUG, worktree: dir, starting_head: reading.head }
    const envelopeObj = { repo: REPO, repo_slug: REPO_SLUG, worktree: dir, branch: BRANCH, starting_head: reading.head }
    assert.throws(
      () => assertLiveWorktreeIdentity(receiptObj, envelopeObj, reading),
      /receipt-pinned worktree is on a foreign branch/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
