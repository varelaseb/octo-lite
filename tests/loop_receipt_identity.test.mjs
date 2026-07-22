// TUR-447 gh#8 host-provisioned worktree identity trust root (loop-correctness single-writer;
// delivery-lifecycle launch-readback, delivery-entry-gate; role-runtime launch-identity,
// launch-provisioning-trust-root, launch-provision-record, launch-provision-env-seam,
// launch-provision-identity-supersedes-interim, launch-entrypoint-revalidation, launch-containment).
// The old Anchor A (a receipt.toml at $OCTO_RECEIPT) is RETIRED as the identity trust source. The
// trust root is now the gh#8 per-lane host-provisioned worktree, proven by the OUT-OF-TREE provision
// record (source host-provisioned-worktree, schema_version 1, resolver_root == worktree) cross-checked
// against the frozen launch env the reader resolves itself (a child cannot forge its own launch env;
// cwd == OCTO_WORKTREE is the anchor). Anchor B (the live git read of the provisioned worktree) stays
// as a cheap DEFENSE-IN-DEPTH reality confirm (ruling-61C), no longer the trust root.
//
// This suite proves the trust-root gate at the real seam (gates.mjs, mirrored byte-identically into
// the loop's GATES-EMBED region) AND the real-git accidental-misrouting reality checks: the live
// branch/origin of a GENUINE temp git repo, read with the EXACT git commands the production reader
// runs, are fed THROUGH assertPrePushWorktreeReAnchor / assertLiveWorktreeIdentity and rejected on a
// real foreign branch / real foreign origin. No forgery harness: the foreign state is a real git
// checkout, the reality is real git.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  assertProvisionedWorkspaceBinding,
  assertLiveWorktreeIdentity,
  assertHostTrustedIdentity,
  assertPrePushWorktreeReAnchor,
  HOST_PROVISION_SOURCE,
} from '../workflows/lib/gates.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const LOOP_SRC = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8')

const REPO = '/root/octo-lite'
const REPO_SLUG = 'varelaseb/octo-lite'
const WORKTREE_ABS = '/root/octo-lite/.wt/tur-447'
const WORKTREE_ROOT = '/root/octo-lite/.wt'
const BRANCH = 'octo-lite/tur-443-operating-model'
const HEAD = 'f00b13357cb1be87b5c5e6d7bd98fd9572915154'

// A well-formed envelope carries the identity fields; the child controls all of them.
function envelope(overrides = {}) {
  return {
    repo: REPO, repo_slug: REPO_SLUG, worktree: WORKTREE_ABS, branch: BRANCH, starting_head: HEAD,
    ...overrides,
  }
}
// The HOST-PROVISIONED, out-of-tree provision record (the trust root): host-authored, source-stamped.
function provision(overrides = {}) {
  return {
    schema_version: 1, source: HOST_PROVISION_SOURCE, lane: 'tur-447',
    control_repo: REPO, worktree: WORKTREE_ABS, worktree_root: WORKTREE_ROOT,
    repo_slug: REPO_SLUG, branch: BRANCH, starting_head: HEAD,
    resolver_root: WORKTREE_ABS, install_check: 'clean', provisioned_at: '2026-07-22T04:00:00Z',
    ...overrides,
  }
}
// The frozen launch env the host set; a child cannot forge its own launch env (cwd == OCTO_WORKTREE).
function env(overrides = {}) {
  return {
    OCTO_WORKTREE: WORKTREE_ABS, OCTO_WORKTREE_ROOT: WORKTREE_ROOT,
    OCTO_CONTROL_REPO: REPO, OCTO_REPO_SLUG: REPO_SLUG,
    OCTO_STARTING_HEAD: HEAD, OCTO_LANE: 'tur-447', ...overrides,
  }
}
// The LIVE git read of the provisioned worktree (Anchor B): the defense-in-depth reality check.
function live(overrides = {}) {
  return {
    source: 'host-receipt-pinned-worktree-read', read_worktree: WORKTREE_ABS,
    head: HEAD, branch: BRANCH, repo_slug: REPO_SLUG, ...overrides,
  }
}

// === Seam: the provisioning trust root ============================================================

test('provision-anchor: a matching envelope + provision record + resolved env is accepted', () => {
  assert.doesNotThrow(() => assertProvisionedWorkspaceBinding(envelope(), provision(), env()))
})

test('provision-anchor: a record NOT stamped host-provisioned-worktree (a forged record) is REJECTED', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope(), provision({ source: 'child-supplied' }), env()), /host-provisioned-worktree|provision record source/)
})

test('provision-anchor: a forged envelope claiming a DIFFERENT repo_slug than the record is REJECTED', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope({ repo_slug: 'attacker/other' }), provision(), env()), /repo slug does not match|repo_slug/)
})

test('provision-anchor: a forged envelope claiming a DIFFERENT worktree than the record is REJECTED', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope({ worktree: '/root/foreign-lane-wt' }), provision(), env()), /worktree does not match|worktree/)
})

test('provision-anchor: a forged envelope claiming a DIFFERENT starting_head than the record is REJECTED', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope({ starting_head: 'deadbeef' }), provision(), env()), /starting HEAD does not match|head/i)
})

test('provision-anchor: resolver_root != worktree (INV5) is REJECTED', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope(), provision({ resolver_root: '/root/octo-lite/.wt/other' }), env()), /resolver_root|resolver root/)
})

test('provision-anchor: a resolved env that disagrees with the record (env vs record cross-check) is REJECTED', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope(), provision(), env({ OCTO_WORKTREE: '/root/foreign-lane-wt' })), /OCTO_WORKTREE|worktree/)
})

// === Seam: Anchor B - live provisioned-worktree reality (defense-in-depth) ========================

test('live-anchor: a matching provision+envelope+live read is accepted', () => {
  assert.doesNotThrow(() => assertLiveWorktreeIdentity(provision(), envelope(), live()))
})

test('live-anchor: a live read NOT stamped by the host-controlled reader is REJECTED', () => {
  assert.throws(() => assertLiveWorktreeIdentity(provision(), envelope(), live({ source: 'worker' })), /not from the host-controlled/)
})

test('live-anchor: a live read that did NOT read the provisioned worktree is REJECTED', () => {
  assert.throws(() => assertLiveWorktreeIdentity(provision(), envelope(), live({ read_worktree: '/root/foreign-lane-wt' })), /did not read the provisioned worktree/)
})

// The tur-456 shape: the worktree PATH matches the record, but the dir is on a FOREIGN branch. The
// trust-root binding passes; the defense-in-depth live read reveals the foreign branch.
test('live-anchor (tur-456): a provisioned worktree on a FOREIGN branch is REJECTED by the defense-in-depth live read', () => {
  assert.doesNotThrow(() => assertProvisionedWorkspaceBinding(envelope(), provision(), env()))
  assert.throws(
    () => assertLiveWorktreeIdentity(provision(), envelope(), live({ branch: 'someone-elses/lane' })),
    /on a foreign branch/,
  )
})

test('live-anchor (tur-456): a provisioned worktree whose origin is a DIFFERENT remote is REJECTED by the live read', () => {
  assert.throws(
    () => assertLiveWorktreeIdentity(provision(), envelope(), live({ repo_slug: 'attacker/other' })),
    /foreign remote/,
  )
})

test('live-anchor: a live HEAD that differs from the provision/envelope starting HEAD is REJECTED', () => {
  assert.throws(() => assertLiveWorktreeIdentity(provision(), envelope(), live({ head: 'differenthead000' })), /live HEAD is not the provisioned starting HEAD|disagrees with the envelope/)
})

// === Seam: the composite host-trusted identity gate (trust root + defense-in-depth) ===============

test('host-trusted-identity: the trust-root binding AND the defense-in-depth read pass for a genuine matching triple', () => {
  assert.doesNotThrow(() => assertHostTrustedIdentity(envelope(), provision(), live(), env()))
})

test('host-trusted-identity: a mismatch on EITHER the trust root or the defense-in-depth read rejects', () => {
  // Trust-root mismatch.
  assert.throws(() => assertHostTrustedIdentity(envelope({ repo_slug: 'attacker/other' }), provision(), live(), env()))
  // Defense-in-depth mismatch (foreign branch, matching path).
  assert.throws(() => assertHostTrustedIdentity(envelope(), provision(), live({ branch: 'foreign/lane' }), env()))
})

// === Neither the record, env, nor live is envelope-derived (SOURCE assertion over the production loop) ===

test('provenance: the loop reads the provision record from the HOST env location (OCTO_PROVISION_RECORD) and resolves the frozen env, never a child-envelope path', () => {
  const start = LOOP_SRC.indexOf('async function hostTrustedIdentity')
  assert.ok(start >= 0, 'hostTrustedIdentity missing from the loop source')
  const region = LOOP_SRC.slice(start, start + 6000)
  // The record is read from the host env var, and the loop forbids a child-supplied record path.
  assert.match(region, /OCTO_PROVISION_RECORD/, 'the record is read from the host OCTO_PROVISION_RECORD location')
  assert.match(region, /Do NOT accept, resolve, or read any record/i, 'forbids a child-supplied record path')
  // The reader also resolves the frozen launch env itself (a child cannot forge its own launch env).
  assert.match(region, /OCTO_WORKTREE/, 'the reader resolves the frozen OCTO_WORKTREE env')
  assert.match(region, /OCTO_STARTING_HEAD/, 'the reader resolves the frozen OCTO_STARTING_HEAD env')
  // The live read is pinned to the PROVISIONED worktree (git -C the provisioned path), never an envelope path.
  assert.match(region, /git -C \$\{provisionedWorktree\} rev-parse HEAD/, 'live HEAD read pinned to the provisioned worktree')
  assert.match(region, /rev-parse --abbrev-ref HEAD/, 'live branch read of the provisioned worktree')
  assert.match(region, /remote get-url origin/, 'live origin read of the provisioned worktree')
  // The gate that decides the trust root is assertProvisionedWorkspaceBinding, over the identity
  // envelope + the host record + the resolved env; the composite gate still runs the live-read check.
  assert.match(region, /assertHostTrustedIdentity\(identityEnvelope, provision, live, env\)/, 'the loop drives the composite host-trusted identity gate')
  assert.match(region, /assertProvisionedWorkspaceBinding\(identityEnvelope, provision, env\)/, 'the trust-root gate runs on the production path')
  // The retired receipt gate no longer drives identity.
  assert.doesNotMatch(region, /assertReceiptWorkspaceBinding/, 'the retired receipt-binding gate no longer drives identity')
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
// The defense-in-depth live-read is best-effort INTERIM against ACCIDENTAL MISROUTING (tur-456: a
// shared dir on a FOREIGN branch / different origin), not a malicious forger. This drives the
// production gates over a GENUINE temp git repo checked out on a real foreign branch / real foreign
// origin: the live branch and origin are read with the EXACT git commands the production reader runs
// (rev-parse --abbrev-ref HEAD; remote get-url origin), and those real readings are fed THROUGH the
// production assertPrePushWorktreeReAnchor / assertLiveWorktreeIdentity. The reality check REJECTS the
// foreign branch/origin. No forgery harness: the foreign state is a real git checkout, real git.

function git(cwd, ...a) {
  return execFileSync('git', ['-C', cwd, ...a], { encoding: 'utf8' }).trim()
}
// Normalize a git remote URL to the canonical owner/repo slug, as the production reader does.
function slugFromRemote(url) {
  const m = url.replace(/\.git$/, '').match(/[/:]([^/:]+\/[^/:]+)$/)
  return m ? m[1] : url
}
// Build a real temp git repo on the given branch with the given origin url; return the live reading
// exactly as the production provisioned-worktree reader would return it.
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
  // The SAME real foreign-branch reality also fails the defense-in-depth live identity anchor: the two
  // gates are consistent, the live-read reality check is the load-bearing accidental-misrouting catch.
  const { dir, reading } = realWorktreeReading({ branch: 'foreign/lane', originUrl: `git@github.com:${REPO_SLUG}.git` })
  try {
    const provisionObj = { source: HOST_PROVISION_SOURCE, repo: REPO, repo_slug: REPO_SLUG, worktree: dir, starting_head: reading.head }
    const envelopeObj = { repo: REPO, repo_slug: REPO_SLUG, worktree: dir, branch: BRANCH, starting_head: reading.head }
    assert.throws(
      () => assertLiveWorktreeIdentity(provisionObj, envelopeObj, reading),
      /provisioned worktree is on a foreign branch/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
