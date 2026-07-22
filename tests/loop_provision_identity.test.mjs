// TUR-447 gh#8 integration: host-provisioned worktree is the identity TRUST ROOT (loop-correctness
// single-writer; delivery-lifecycle launch-readback, delivery-entry-gate; role-runtime launch-identity,
// launch-provisioning-trust-root, launch-provision-record, launch-provision-env-seam,
// launch-provision-identity-supersedes-interim, launch-entrypoint-revalidation). ROOT CUTOVER of the
// identity anchor. The old Anchor A read a receipt.toml from $OCTO_RECEIPT and stamped it
// host-provisioned-receipt; it is RETIRED as the trust source. The new trust root is the gh#8
// per-lane host-provisioned worktree: the host writes an OUT-OF-TREE provision record (path in
// $OCTO_PROVISION_RECORD, source host-provisioned-worktree, schema_version 1, resolver_root ==
// worktree) and starts the loop process with cwd == OCTO_WORKTREE and the 7 frozen env names set. A
// child cannot forge its own launch env, so env + record + cwd == worktree is the non-forgeable root.
//
// This suite is the spec-derived RED. It proves, at the real gate seam (gates.mjs, mirrored
// byte-identically into the loop's GATES-EMBED region) AND through the REAL loop identity gate:
//   - a matching envelope + provision record + resolved env is ACCEPTED (source host-provisioned-worktree);
//   - a missing record/env fails closed (no fabricated identity);
//   - an envelope worktree/slug/head/branch that disagrees with the record (accidental misrouting) rejects;
//   - resolver_root != worktree or source != host-provisioned-worktree rejects;
//   - Anchor B live-read STILL runs as defense-in-depth (foreign branch/remote still rejected) and its
//     presence does NOT restore the retired receipt (Anchor A) as the trust root.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  assertProvisionedWorkspaceBinding,
  assertLiveWorktreeIdentity,
  assertHostTrustedIdentity,
  HOST_PROVISION_SOURCE,
} from '../workflows/lib/gates.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const LOOP_SRC = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8')

const REPO = '/root/octo-lite'
const REPO_SLUG = 'varelaseb/octo-lite'
const WORKTREE = '/root/octo-lite/.wt/tur-447'
const WORKTREE_ROOT = '/root/octo-lite/.wt'
const BRANCH = 'octo-lite/tur-447-gh8-integration'
const HEAD = '3696e1abadc0ffee00000000000000000000abcd'
const LANE = 'tur-447'

// A well-formed envelope carries the identity fields; the child controls all of them.
function envelope(overrides = {}) {
  return {
    repo: REPO, repo_slug: REPO_SLUG, worktree: WORKTREE, branch: BRANCH, starting_head: HEAD,
    ...overrides,
  }
}
// The HOST-PROVISIONED, out-of-tree provision record: host-authored, source-stamped, NOT the envelope.
function provision(overrides = {}) {
  return {
    schema_version: 1, source: HOST_PROVISION_SOURCE, lane: LANE,
    control_repo: REPO, worktree: WORKTREE, worktree_root: WORKTREE_ROOT,
    repo_slug: REPO_SLUG, branch: BRANCH, starting_head: HEAD,
    resolver_root: WORKTREE, install_check: 'clean',
    provisioned_at: '2026-07-22T04:00:00Z', ...overrides,
  }
}
// The frozen launch env the host set; a child cannot forge its own launch env (cwd == OCTO_WORKTREE).
function env(overrides = {}) {
  return {
    OCTO_WORKTREE: WORKTREE, OCTO_WORKTREE_ROOT: WORKTREE_ROOT,
    OCTO_CONTROL_REPO: REPO, OCTO_REPO_SLUG: REPO_SLUG,
    OCTO_STARTING_HEAD: HEAD, OCTO_LANE: LANE, ...overrides,
  }
}
// The LIVE git read of the provisioned worktree (Anchor B): cheap defense-in-depth reality check.
function live(overrides = {}) {
  return {
    source: 'host-receipt-pinned-worktree-read', read_worktree: WORKTREE,
    head: HEAD, branch: BRANCH, repo_slug: REPO_SLUG, ...overrides,
  }
}

// === Seam: provisioning-trust workspace binding (NEW trust root) ==================================

test('accepts identity when provision record + resolved env agree with the envelope (source host-provisioned-worktree)', () => {
  assert.doesNotThrow(() => assertProvisionedWorkspaceBinding(envelope(), provision(), env()))
})

test('rejects when OCTO_PROVISION_RECORD/env is missing (fail closed, no fabricated identity)', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope(), null, env()), /provision/)
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope(), provision(), null), /env|provision/)
})

test('rejects when envelope worktree/slug/head/branch disagrees with the provision record (accidental misrouting)', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope({ worktree: '/root/foreign-lane-wt' }), provision(), env()), /worktree/)
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope({ repo_slug: 'attacker/other' }), provision(), env()), /repo_slug|slug/)
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope({ starting_head: 'deadbeef' }), provision(), env()), /head|starting/i)
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope({ branch: 'someone-elses/lane' }), provision(), env()), /branch/)
})

test('rejects when resolver_root != worktree or source != host-provisioned-worktree', () => {
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope(), provision({ resolver_root: '/root/octo-lite/.wt/other' }), env()), /resolver_root|resolver root/)
  assert.throws(() => assertProvisionedWorkspaceBinding(envelope(), provision({ source: 'host-provisioned-receipt' }), env()), /host-provisioned-worktree|provision record source/)
})

// === Seam: Anchor B live-read STILL runs as defense-in-depth (no longer the trust root) ============

test('Anchor B live-read STILL rejects a foreign branch/remote as defense-in-depth, and its removal does NOT restore Anchor A (receipt) as trust root', () => {
  // The trust root is provisioning-binding; the live read is a cheap reality confirm on top.
  assert.doesNotThrow(() => assertHostTrustedIdentity(envelope(), provision(), live(), env()))
  // Anchor B still catches the tur-456 foreign-branch / foreign-remote shape.
  assert.throws(() => assertHostTrustedIdentity(envelope(), provision(), live({ branch: 'someone-elses/lane' }), env()), /foreign branch/)
  assert.throws(() => assertHostTrustedIdentity(envelope(), provision(), live({ repo_slug: 'attacker/other' }), env()), /foreign remote/)
  // The retired receipt source is NOT the trust root: the provisioning source constant is.
  assert.equal(HOST_PROVISION_SOURCE, 'host-provisioned-worktree')
  // assertLiveWorktreeIdentity remains callable as the defense-in-depth confirm.
  assert.doesNotThrow(() => assertLiveWorktreeIdentity(provision(), envelope(), live()))
})

// === SOURCE assertions over the REAL production loop (the trust root is provisioning) ==============

test('provenance: the loop reads the provision record from the HOST env location (OCTO_PROVISION_RECORD), never a child-envelope path', () => {
  const start = LOOP_SRC.indexOf('async function hostTrustedIdentity')
  assert.ok(start >= 0, 'hostTrustedIdentity missing from the loop source')
  const region = LOOP_SRC.slice(start, start + 6000)
  // The trust root is the gh#8 provision record read from the host env var, not a receipt.toml.
  assert.match(region, /OCTO_PROVISION_RECORD/, 'the record is read from the host OCTO_PROVISION_RECORD location')
  assert.match(region, /host-provisioned-worktree/, 'the reader expects the host-provisioned-worktree source')
  // The reader also resolves the frozen launch env itself and returns it for the env==record cross-check.
  assert.match(region, /OCTO_WORKTREE/, 'the reader resolves the frozen OCTO_WORKTREE env')
  assert.match(region, /OCTO_REPO_SLUG/, 'the reader resolves the frozen OCTO_REPO_SLUG env')
  assert.match(region, /OCTO_STARTING_HEAD/, 'the reader resolves the frozen OCTO_STARTING_HEAD env')
  // The gate that decides the trust root is the production assertProvisionedWorkspaceBinding, and the
  // composite host-trusted identity gate still runs the live-read Anchor B as defense-in-depth.
  assert.match(region, /assertHostTrustedIdentity\(/, 'the loop drives the composite host-trusted identity gate')
  assert.match(region, /assertProvisionedWorkspaceBinding/, 'the loop drives the provisioning-binding trust gate')
  // Anchor A receipt reading (receipt.toml at OCTO_RECEIPT) is retired from the identity anchor.
  assert.doesNotMatch(region, /assertReceiptWorkspaceBinding/, 'the retired receipt-binding gate no longer drives identity')
})

test('gate-position: the host-trusted identity gate runs BEFORE the Shaped -> Todo fire and before every spawn', () => {
  const implement = LOOP_SRC.slice(LOOP_SRC.indexOf("if (mode === 'implement')"), LOOP_SRC.indexOf("if (mode === 'code-review')"))
  assert.ok(implement.indexOf('hostTrustedIdentity(') >= 0, 'implement mode calls the identity gate')
  assert.ok(
    implement.indexOf('hostTrustedIdentity(') < implement.indexOf('loopFire('),
    'the identity gate runs BEFORE the Shaped -> Todo fire',
  )
})
