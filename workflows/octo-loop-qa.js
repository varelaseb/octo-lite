export const meta = {
  name: 'octo-loop-qa',
  description: 'Native workflow-subagent delivery loop: gate, spawn, and bind one fresh exact-head worker pass per invocation',
  whenToUse: 'Shaped or Todo Linear work with a clear exact-head shaping verdict, journalled bound inputs, and a per-pass brief',
  phases: [
    { title: 'Implement' },
    { title: 'Code Review' },
    { title: 'Fix' },
    { title: 'QA Capture' },
    { title: 'QA Review' },
    { title: 'Publication Readback' },
    { title: 'Reconcile' },
  ],
}

// TUR-488 (role-runtime launch-gates-workflow-layer): the Workflow tool requires
// `export const meta` to be the first statement and runs this script in a sandbox
// with NO Node.js API. That sandbox forbids every module load: no static module
// specifier, no dynamic runtime module load, and no node builtin. So this
// script is fully self-contained. The gate helpers below are embedded inline,
// byte-identical to the node-tested canonical source workflows/lib/gates.mjs with
// only the `export ` keyword stripped. The embedded region is delimited by the two
// stable markers below and is drift-guarded by an automated parity test
// (tests/test_conformance.py) that fails closed if the inline gates ever diverge
// from gates.mjs. gates.mjs remains the canonical, unit-tested source under
// node --test (tests/gates.test.mjs), where module imports are available. No gate
// check is weakened; the inline gates are the same functions.
// GATES-EMBED-BEGIN
// TUR-488 (role-runtime launch-gates-workflow-layer): this module loads inside a
// Workflow sandbox with no Node.js API, so it must not statically import any node
// builtin at module-load time. The two former node dependencies, node:crypto for
// the launch-revision fingerprint hash and node:path for worktree containment, are
// replaced by pure-JS implementations below. No gate check is weakened: the launch
// revision remains an exact SHA-256 over the canonical bound inputs, and containment
// remains an exact under-root resolution with POSIX semantics.

// Pure-JS SHA-256 (FIPS 180-4). Deterministic, no node builtin, identical digest to
// node:crypto createHash('sha256') for the same UTF-8 input. Used only for the
// launch-revision fingerprint; not a general crypto surface.
const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]

function utf8Bytes(text) {
  const out = []
  for (let i = 0; i < text.length; i += 1) {
    let code = text.charCodeAt(i)
    if (code < 0x80) {
      out.push(code)
    } else if (code < 0x800) {
      out.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f))
    } else if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) {
      const low = text.charCodeAt(i + 1)
      code = 0x10000 + ((code - 0xd800) << 10) + (low - 0xdc00)
      i += 1
      out.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      )
    } else {
      out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f))
    }
  }
  return out
}

function sha256Hex(text) {
  const h = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]
  const bytes = utf8Bytes(text)
  const bitLength = bytes.length * 8
  bytes.push(0x80)
  while (bytes.length % 64 !== 56) bytes.push(0)
  // 64-bit big-endian length; message length fits in 32 bits for our inputs, so
  // the high word is always zero.
  for (let i = 0; i < 4; i += 1) bytes.push(0)
  bytes.push((bitLength >>> 24) & 0xff, (bitLength >>> 16) & 0xff, (bitLength >>> 8) & 0xff, bitLength & 0xff)

  const rotr = (value, count) => (value >>> count) | (value << (32 - count))
  const w = new Array(64)
  for (let offset = 0; offset < bytes.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      const j = offset + i * 4
      w[i] = ((bytes[j] << 24) | (bytes[j + 1] << 16) | (bytes[j + 2] << 8) | bytes[j + 3]) >>> 0
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3)
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }
    let [a, b, c, d, e, f, g, hh] = h
    for (let i = 0; i < 64; i += 1) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const t1 = (hh + S1 + ch + SHA256_K[i] + w[i]) >>> 0
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + maj) >>> 0
      hh = g
      g = f
      f = e
      e = (d + t1) >>> 0
      d = c
      c = b
      b = a
      a = (t1 + t2) >>> 0
    }
    h[0] = (h[0] + a) >>> 0
    h[1] = (h[1] + b) >>> 0
    h[2] = (h[2] + c) >>> 0
    h[3] = (h[3] + d) >>> 0
    h[4] = (h[4] + e) >>> 0
    h[5] = (h[5] + f) >>> 0
    h[6] = (h[6] + g) >>> 0
    h[7] = (h[7] + hh) >>> 0
  }
  return h.map((value) => (value >>> 0).toString(16).padStart(8, '0')).join('')
}

// Pure-JS POSIX path resolution, enough for worktree containment. No node:path.
// Resolves `./`, `../`, and repeated separators against an absolute root; relative
// roots resolve against '/', matching node:path resolve semantics for our use where
// the worktree root is always an absolute path.
const POSIX_SEP = '/'

function posixResolve(...segments) {
  let resolved = ''
  let isAbsolute = false
  for (let i = segments.length - 1; i >= -1 && !isAbsolute; i -= 1) {
    const segment = i >= 0 ? segments[i] : '/'
    if (!segment) continue
    resolved = `${segment}/${resolved}`
    isAbsolute = segment.charCodeAt(0) === 47
  }
  const parts = []
  for (const part of resolved.split('/')) {
    if (part === '' || part === '.') continue
    if (part === '..') {
      if (parts.length > 0) parts.pop()
      continue
    }
    parts.push(part)
  }
  return `/${parts.join('/')}`
}

function required(value, label) {
  if (value === undefined || value === null || value === '') {
    throw new Error(`${label} required`)
  }
  return value
}

const DELIVERY_ROLES = new Set(['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer', 'tdd-observer'])
// The tdd-observer runs committed states in an isolated worktree and never mutates,
// so it is admitted for delivery only as a Read-restricted subagent
// (role-runtime role-tdd-observer, launch-purpose-delivery-roles).
const DELIVERY_READ_RESTRICTED_ROLES = new Set(['tdd-observer'])

// Linear-state gate (role-runtime launch-linear-state-gate): shaping-review launches
// only from Ideas, Todo, Shaped, or In Progress; delivery only from Shaped, Todo, or
// In Progress; every other state, including Awaiting Accept and terminal states, is
// rejected for both purposes.
const SHAPING_REVIEW_STATES = new Set(['Ideas', 'Todo', 'Shaped', 'In Progress'])
const DELIVERY_STATES = new Set(['Shaped', 'Todo', 'In Progress'])

function assertLinearState(purpose, linearState, admitted) {
  required(linearState, `${purpose} Linear state`)
  if (!admitted.has(linearState)) {
    throw new Error(`Linear state ${linearState} rejected for ${purpose} purpose`)
  }
}

// Workflow-layer admission matrix plus Linear-state gate (role-runtime
// launch-role-purpose-capability, launch-purpose-shaping-roles,
// launch-purpose-delivery-roles, launch-purpose-reconcile, launch-linear-state-gate,
// launch-gates-workflow-layer). Called before each subagent spawn; an invalid
// combination fails closed with no spawn.
function assertAdmission({ purpose, role, capabilities = [], readRestricted = false, linearState } = {}) {
  required(purpose, 'admission purpose')
  required(role, 'admission role')
  if (purpose === 'shaping-review') {
    const orchestratorWithShaping = role === 'orchestrator' && capabilities.includes('shaping')
    if (role !== 'shaping-reviewer' && !orchestratorWithShaping) {
      throw new Error(`role ${role} not admitted for shaping-review purpose`)
    }
    assertLinearState(purpose, linearState, SHAPING_REVIEW_STATES)
  } else if (purpose === 'delivery') {
    if (!DELIVERY_ROLES.has(role)) throw new Error(`role ${role} not admitted for delivery purpose`)
    if (DELIVERY_READ_RESTRICTED_ROLES.has(role) && readRestricted !== true) {
      throw new Error(`role ${role} admitted for delivery only as a Read-restricted subagent`)
    }
    assertLinearState(purpose, linearState, DELIVERY_STATES)
  } else if (purpose === 'reconcile') {
    if (role !== 'reconciler') throw new Error(`role ${role} not admitted for reconcile purpose`)
    if (readRestricted !== true) {
      throw new Error('reconcile admits reconciler only as a Read-restricted subagent')
    }
  } else {
    throw new Error(`unknown admission purpose ${purpose}`)
  }
  return { purpose, role }
}

// Manifest-shape admission (role-runtime launch-receipt-manifest-shapes,
// launch-receipt-persistent): exactly one durable receipt shape remains, the generic
// persistent launch receipt for role meta-operator or orchestrator carrying no pass
// purpose; every worker pass, including reconcile, binds through the workflow journal
// under the role-purpose-capability matrix. A pass purpose injected onto a persistent
// shape, a role substituted for its shape, or an unknown shape is rejected.
const PERSISTENT_ROLES = new Set(['meta-operator', 'orchestrator'])

function assertManifestShape(manifest = {}) {
  const shape = required(manifest.shape, 'manifest shape')
  const role = required(manifest.role, 'manifest role')
  if (shape === 'persistent') {
    if (manifest.purpose !== undefined && manifest.purpose !== null && manifest.purpose !== '') {
      throw new Error('pass purpose rejected on the persistent receipt shape')
    }
    if (!PERSISTENT_ROLES.has(role)) {
      throw new Error(`role ${role} rejected for the persistent receipt shape`)
    }
    return { shape, role }
  }
  if (shape === 'worker-journal') {
    assertAdmission({
      purpose: manifest.purpose,
      role,
      capabilities: manifest.capabilities ?? [],
      readRestricted: manifest.readRestricted ?? false,
      linearState: manifest.linearState,
    })
    return { shape, role, purpose: manifest.purpose }
  }
  throw new Error(`unknown manifest shape ${shape}`)
}

// Launch-revision revalidation (role-runtime launch-entrypoint-revalidation,
// launch-gates-workflow-layer): the worker equivalent of the persistent receipt
// launch revision is an exact fingerprint of the journalled bound inputs, revalidated
// before spawn and again before any mutation-phase advance, so an altered combination
// or a revision mismatch is rejected with no subagent spawned.
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value !== null && typeof value === 'object') {
    const entries = Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
    return `{${entries.join(',')}}`
  }
  return JSON.stringify(value)
}

function launchRevision(boundInputs) {
  required(boundInputs, 'bound inputs')
  return sha256Hex(canonical(boundInputs))
}

function assertLaunchRevision(revision, boundInputs) {
  required(revision, 'launch revision')
  if (launchRevision(boundInputs) !== revision) throw new Error('launch revision mismatch')
  return revision
}

// Live-refetch readback (role-runtime launch-readback): the workflow takes fresh
// Linear and PR reads immediately before dispatch and passes them here as explicit
// arguments; a stale self-consistent envelope whose bound fields disagree with the
// fresh reads is rejected with no spawn.
const READBACK_FIELDS = [
  ['linear_state', 'Linear state'],
  ['linear_fingerprint', 'Linear fingerprint'],
  ['pr_head', 'PR head'],
  ['branch', 'PR branch'],
]

function assertLaunchReadback(envelope, fresh) {
  required(envelope, 'launch envelope')
  required(fresh, 'fresh reads')
  for (const [field, label] of READBACK_FIELDS) {
    required(fresh[field], `fresh ${label}`)
    if (envelope[field] !== fresh[field]) {
      throw new Error(`stale envelope: ${label} disagrees with fresh read`)
    }
  }
  return fresh
}

// Worktree containment (role-runtime launch-containment): checked exactly at
// admission and at child subagent spawn; a wrong or escaping worktree path never
// spawns.
function assertContainment(worktreeRoot, worktreePath) {
  required(worktreeRoot, 'worktree root')
  required(worktreePath, 'worker worktree')
  const root = posixResolve(worktreeRoot)
  const resolved = posixResolve(root, worktreePath)
  if (!resolved.startsWith(root + POSIX_SEP)) {
    throw new Error(`worktree ${worktreePath} escapes worktree root ${worktreeRoot}`)
  }
  return resolved
}

// TUR-447 ruling-59 receipt+live-read identity trust anchor (loop-correctness single-writer;
// delivery-lifecycle launch-readback, delivery-entry-gate; role-runtime launch-identity,
// launch-entrypoint-revalidation, launch-containment, launch-receipt). ROOT FIX for the
// self-referential identity hole: every prior readiness/ack/launch-revision check validated the
// envelope's repo_slug/worktree/starting_head OVER the same (forgeable) child envelope, so a
// foreign-but-well-formed envelope self-consistently passed. The two anchors below are the
// trusted identity roots the worker/child CANNOT forge, validated BEFORE any Shaped -> Todo fire
// or spawn. NEITHER anchor derives from the child envelope.
//
// Anchor A - host-provisioned RECEIPT workspace binding. The launcher wrote a receipt at spawn
// carrying [workspace] repo, worktree, starting_head; it is host-authored, read from a
// HOST-TRUSTED location (an env var / launch-context path the child cannot influence, NEVER a
// path supplied by the child envelope). assertReceiptWorkspaceBinding rejects unless the envelope
// repo_slug/worktree/starting_head EXACTLY match the receipt, catching a forged envelope claiming
// a different repo/worktree/head than the host provisioned. The receipt fields are validated with
// the same slug/containment shape as readiness so a malformed receipt fails closed too.
const HOST_RECEIPT_SOURCE = 'host-provisioned-receipt'
const HOST_WORKTREE_READ_SOURCE = 'host-receipt-pinned-worktree-read'
const RECEIPT_BINDING_FIELDS = [
  ['repo_slug', 'repo_slug', 'canonical repo slug'],
  ['worktree', 'worktree', 'host issue worktree'],
  ['starting_head', 'starting_head', 'starting HEAD'],
]

function assertReceiptWorkspaceBinding(envelope, receipt) {
  required(envelope, 'launch envelope')
  required(receipt, 'host-provisioned receipt')
  // Provenance: the receipt must be stamped by the host launcher, never the child envelope. A
  // receipt whose source is the child/worker/envelope, or an unstamped receipt, fails closed so
  // the anchor cannot be satisfied by a value the child controls.
  if (receipt.source !== HOST_RECEIPT_SOURCE) {
    throw new Error('receipt binding rejected: receipt not from the host-provisioned launch location')
  }
  // The receipt fields are themselves shape-validated (a canonical slug, a real head, a worktree)
  // so a malformed host receipt fails closed rather than matching a malformed envelope.
  assertRepoSlug(receipt.repo_slug, 'receipt repo_slug')
  requiredNonEmptyString(receipt.worktree, 'receipt worktree')
  requiredNonEmptyString(receipt.starting_head, 'receipt starting HEAD')
  for (const [envField, rcField, label] of RECEIPT_BINDING_FIELDS) {
    requiredNonEmptyString(envelope[envField], `envelope ${label}`)
    if (envelope[envField] !== receipt[rcField]) {
      throw new Error(`receipt binding rejected: envelope ${label} does not match the host-provisioned receipt`)
    }
  }
  return { repo_slug: receipt.repo_slug, worktree: receipt.worktree, starting_head: receipt.starting_head }
}

// Anchor B - LIVE git read of the RECEIPT-pinned worktree (non-forgeable reality). A host-controlled
// subagent runs git -C <receipt.worktree> rev-parse HEAD, rev-parse --abbrev-ref HEAD, and remote
// get-url origin over the RECEIPT worktree (never an envelope path). assertLiveWorktreeIdentity
// rejects unless the live HEAD equals the receipt/envelope starting_head, the live branch equals the
// envelope branch, and the live origin remote resolves to the envelope repo_slug. This catches the
// ACTUAL tur-456 bug that Anchor A alone MISSES: the worktree PATH matches the receipt but the shared
// dir is on a FOREIGN branch / different remote; the live read reveals the foreign branch/repo and
// REJECTS. The receipt is the pinned reality source, so the live read is proven over the host-pinned
// path, never a path the child could redirect.
function assertLiveWorktreeIdentity(receipt, envelope, live) {
  required(receipt, 'host-provisioned receipt')
  required(envelope, 'launch envelope')
  required(live, 'live worktree read')
  // Provenance: the live read must be stamped by the host-controlled reader and must have been
  // pinned (git -C) to the RECEIPT worktree, not any envelope-supplied path.
  if (live.source !== HOST_WORKTREE_READ_SOURCE) {
    throw new Error('live worktree read rejected: not from the host-controlled receipt-pinned reader')
  }
  requiredNonEmptyString(receipt.worktree, 'receipt worktree')
  if (live.read_worktree !== receipt.worktree) {
    throw new Error('live worktree read rejected: reader did not read the receipt-pinned worktree')
  }
  const liveHead = requiredNonEmptyString(live.head, 'live worktree HEAD')
  const liveBranch = requiredNonEmptyString(live.branch, 'live worktree branch')
  const liveSlug = requiredNonEmptyString(live.repo_slug, 'live worktree origin repo slug')
  // The live HEAD is the non-forgeable reality: it must equal the receipt AND envelope starting HEAD.
  if (liveHead !== receipt.starting_head) {
    throw new Error('live worktree read rejected: live HEAD is not the receipt-pinned starting HEAD')
  }
  if (liveHead !== envelope.starting_head) {
    throw new Error('live worktree read rejected: live HEAD disagrees with the envelope starting HEAD')
  }
  // The live branch reveals a FOREIGN branch on a matching path (the tur-456 shape).
  requiredNonEmptyString(envelope.branch, 'envelope branch')
  if (liveBranch !== envelope.branch) {
    throw new Error('live worktree read rejected: receipt-pinned worktree is on a foreign branch')
  }
  // The live origin remote (normalized to owner/repo) reveals a different remote on a matching path.
  assertRepoSlug(liveSlug, 'live origin repo slug')
  if (liveSlug !== envelope.repo_slug) {
    throw new Error('live worktree read rejected: receipt-pinned worktree origin is a foreign remote')
  }
  return { head: liveHead, branch: liveBranch, repo_slug: liveSlug }
}

// The single host-trusted identity gate. Validates the envelope against BOTH anchors before any
// spawn or the Shaped -> Todo fire; a mismatch on either rejects with no transition and no spawn.
// receipt is Anchor A's host-provisioned binding; live is Anchor B's receipt-pinned live git read.
// Neither is derived from the envelope.
function assertHostTrustedIdentity(envelope, receipt, live) {
  const binding = assertReceiptWorkspaceBinding(envelope, receipt)
  const reality = assertLiveWorktreeIdentity(receipt, envelope, live)
  return { binding, reality }
}

function assertReadyEnvelope(envelope) {
  for (const field of [
    'issue',
    'repo',
    'pr',
    'branch',
    'shaping_head',
    'spec_revision',
    'linear_revision',
    'linear_fingerprint',
    'linear_state',
    'pr_head',
    'pr_base',
    'topology_revision',
    'shaping_verdict',
    'shaping_verdict_head',
    'shaping_reviewer_receipt',
    'conversation_cutoff',
  ]) required(envelope[field], field)
  // TUR-447 ruling-56 cycle3 slug-identity-bound: the canonical gh repo slug (owner/repo) and the host
  // issue worktree are REQUIRED, shape/containment-validated readiness inputs, checked BEFORE any
  // Shaped -> Todo fire or spawn, so a missing/malformed slug or an escaping worktree fails closed at
  // readiness rather than after the fire. The PR must be a NUMBER, not a URL, so gh cannot infer a
  // foreign repo from a URL that overrides --repo.
  assertRepoSlug(envelope.repo_slug, 'repo_slug')
  requiredPrNumber(envelope.pr, 'PR')
  assertContainment(required(envelope.worktree_root, 'worktree_root'), required(envelope.worktree, 'worktree'))
  if (!Array.isArray(envelope.conversation_log_references) || envelope.conversation_log_references.length === 0) {
    throw new Error('conversation log references required')
  }
  if (!['Shaped', 'Todo'].includes(envelope.linear_state)) {
    throw new Error('Linear state must be Shaped or Todo')
  }
  if (envelope.shaping_verdict !== 'clear') throw new Error('shaping verdict not clear')
  if (envelope.shaping_verdict_head !== envelope.shaping_head) {
    throw new Error('shaping verdict head mismatch')
  }
  if (envelope.pr_head !== envelope.shaping_head) throw new Error('PR head mismatch')
  if (!Array.isArray(envelope.spec_blobs) || envelope.spec_blobs.length === 0) {
    throw new Error('spec blobs required')
  }
  if (!Array.isArray(envelope.adr_blobs)) throw new Error('ADR blobs required')
  if (!Array.isArray(envelope.shaping_verdict_inputs) || envelope.shaping_verdict_inputs.length === 0) {
    throw new Error('shaping verdict input bindings required')
  }
  if (!Array.isArray(envelope.acceptance_criteria) || envelope.acceptance_criteria.length === 0) {
    throw new Error('acceptance criteria required')
  }
  return envelope
}

function requiredNonEmptyString(value, label) {
  if (typeof value !== 'string' || value === '') throw new Error(`${label} required`)
  return value
}

function requiredNonEmptyArray(value, label) {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`${label} required`)
  return value
}

// TUR-447 ruling-56 cycle3 slug-identity-bound. The canonical gh identity is the PR NUMBER, never a
// URL: `gh pr view <URL> --repo <slug>` lets the URL OVERRIDE --repo and select the URL's repository,
// so a URL-bound PR silently reads a foreign repo. requiredPrNumber accepts an integer or an
// all-digits string and REJECTS a URL (or any non-numeric), returning the canonical string form so a
// numeric 6 and a string '6' compare equal.
function requiredPrNumber(value, label) {
  required(value, label)
  if (typeof value === 'number') {
    if (!Number.isInteger(value) || value <= 0) throw new Error(`${label} must be a positive PR number`)
    return String(value)
  }
  if (typeof value === 'string' && /^[0-9]+$/.test(value)) return value
  throw new Error(`${label} must be a PR number, not a URL`)
}

// The canonical GitHub repo slug is owner/repo (exactly one slash, no scheme, no spaces). A missing or
// malformed slug (a bare name, a URL, or an owner/repo/extra path) is rejected so gh is always pinned to
// the right repository and never infers it from the ambient (foreign lane) cwd.
function assertRepoSlug(value, label) {
  requiredNonEmptyString(value, label)
  if (!/^[^/\s]+\/[^/\s]+$/.test(value)) {
    throw new Error(`${label} must be a canonical owner/repo slug`)
  }
  return value
}

// Worker binding by journal plus schema-forced ack echo (role-runtime launch-identity,
// launch-receipt, launch-gates-workflow-layer; operating-model decision-109-binding).
// A worker pass binds no durable TOML receipt: its binding proof is the workflow journal
// entry for the spawn plus this echo of the exact bound inputs, which the owning
// orchestrator verifies before any mutation phase. A role, repo, issue, or PR
// substitution fails the echo exactly as a HEAD mismatch does.
// TUR-447 ruling-56 cycle3 slug-identity-bound: repo_slug (canonical owner/repo gh identity) and
// worktree (host issue worktree) are now part of the bound-input echo set, so a FOREIGN slug or a
// substituted worktree fails the echo exactly as a HEAD mismatch does. The PR is the canonical PR
// NUMBER (compared number-safe), never a URL.
const WORKER_ACK_FIELDS = [
  ['role', 'worker ack role'],
  ['repo', 'worker ack repo'],
  ['repo_slug', 'worker ack repo slug'],
  ['worktree', 'worker ack worktree'],
  ['issue', 'worker ack issue'],
  ['starting_head', 'worker ack starting HEAD'],
  ['contract_hash', 'worker ack contract hash'],
]

function assertWorkerAckEcho(journalled, ack) {
  required(journalled, 'journalled bound inputs')
  required(ack, 'worker ack')
  for (const [field, label] of WORKER_ACK_FIELDS) {
    requiredNonEmptyString(journalled[field], `journalled ${field}`)
    requiredNonEmptyString(ack[field], label)
    if (ack[field] !== journalled[field]) throw new Error(`${label} mismatch`)
  }
  // The PR is the canonical PR NUMBER, compared number-safe (6 and '6' are the same PR).
  const journalledPr = requiredPrNumber(journalled.pr, 'journalled PR')
  const ackPr = requiredPrNumber(ack.pr, 'worker ack PR')
  if (ackPr !== journalledPr) throw new Error('worker ack PR mismatch')
  requiredNonEmptyArray(journalled.spec_blobs, 'journalled spec_blobs')
  if (!Array.isArray(ack.spec_blobs) || ack.spec_blobs.length === 0) {
    throw new Error('worker ack spec blobs required')
  }
  const exact = ack.spec_blobs.length === journalled.spec_blobs.length &&
    ack.spec_blobs.every((blob, index) => blob === journalled.spec_blobs[index])
  if (!exact) throw new Error('worker ack spec blobs mismatch')
  return ack
}

// Observable read-only acknowledgment phase then capability upgrade (role-runtime
// launch-identity, launch-receipt, launch-gates-workflow-layer; operating-model
// decision-109-binding). A worker first runs in a read-only acknowledgment spawn with
// write tools genuinely withheld that produces ONLY the schema-forced ack echo of the
// exact journalled bound inputs. The owning host verifies that echo against the
// journalled bound inputs and ONLY THEN authorizes the write-capable mutation phase. A
// worker that would mutate before verification cannot, rather than being rejected after
// a prohibited mutation: no write-capable phase exists until the read-only echo
// verifies. A role, repo, issue, or PR substitution blocks the mutation phase exactly as
// a HEAD mismatch does, because the same echo gate decides both.
//
// TUR-447 F1 Unit B correction: write tools are withheld ONLY by spawning the ack phase
// under a real Workflow read-only subagent type (opts.agentType). The prior
// writeCapable/readOnly flags were not real agent() opts, so the runtime ignored them
// and the ack phase silently retained write tools; the old gate only re-checked that
// hardcoded ignored flag, proving nothing. The gate now asserts the ack phase declares a
// recognized READ-ONLY agentType and REJECTS a default, absent, or write-capable
// agentType, which is the only value that genuinely withholds write tools at spawn.
const READ_ONLY_AGENT_TYPES = new Set(['Explore'])

function assertReadOnlyAckPhase(phase) {
  required(phase, 'ack phase')
  if (!READ_ONLY_AGENT_TYPES.has(phase.agentType)) {
    throw new Error(
      'ack phase must run read-only: spawn under a read-only agentType (write tools withheld) until the echo verifies',
    )
  }
  return phase
}

function verifyAckThenUpgrade(journalled, phase) {
  assertReadOnlyAckPhase(phase)
  assertWorkerAckEcho(journalled, phase.ack)
  return { upgrade: 'write-capable' }
}

// TUR-447 TDD-gate fix (delivery-lifecycle prompt-tdd-red, prompt-tdd-green,
// prompt-tdd-no-fabrication; and the spec-derived red-green-refactor contract). A proof
// object must carry not only the command/outcome/artifact/exit-status the caller reports
// but the exact HEAD the proof RAN at and the behavior SCENARIO it exercised, so the
// acceptance gate can bind the red to the unchanged starting HEAD (red-before-mutation)
// and prove the SAME scenario went green. Without the head and scenario an arbitrary
// proof-shaped object could satisfy the gate.
function assertProof(proof, label) {
  if (typeof proof !== 'object' || proof === null) throw new Error(`${label} required`)
  requiredNonEmptyString(proof.command, `${label} command`)
  requiredNonEmptyString(proof.outcome, `${label} outcome`)
  requiredNonEmptyString(proof.artifact, `${label} artifact`)
  if (!Number.isInteger(proof.exit_status)) throw new Error(`${label} exit status required`)
  requiredNonEmptyString(proof.head, `${label} HEAD`)
  requiredNonEmptyString(proof.scenario, `${label} scenario`)
  return proof
}

// TUR-447 D1 reshaped delivery loop (delivery-lifecycle delivery-tdd-committed-red,
// delivery-tdd-committed-red-commit, delivery-tdd-committed-green, delivery-tdd-test-identity-binding,
// delivery-tdd-observer-inputs-host-journal-record; role-runtime role-implementer-host-gated-push,
// launch-identity-delivery-branch). The reshape REVERSES the prior host-gated-uncommitted model: the
// implementer worker now COMMITS a real failing red (a new or changed test plus unchanged production)
// then a GREEN commit (production-only) on an ISOLATED delivery branch, binds the failing test by path
// and content digest unchanged across red, green, and final HEAD, and NEVER pushes. The HOST records the
// worker's committed branch and its red, green, and final commit ids in the journal binding; that
// host-journalled binding, never the worker's claim, is the trust root the observer executes from.
//
// assertCommittedImplementation binds the pre-push worker result. It requires committed:true, pushed:false,
// distinct real red and green commit ids on the isolated delivery branch, a final HEAD (possibly a later
// refactor commit) equal to the reported delivered head, and a bound-test identity (path plus content
// digest) the worker reports unchanged red->green->final. It does NOT trust worker-authored red/green
// verdict strings as proof: the independent tdd-observer replay (assertObservedCommittedStates) is the
// sole proof and is consumed separately by the host. A worker that did not commit, that pushed, or whose
// red and green commit ids collapse is rejected here before any host journal binding.
function assertCommittedImplementation(startingHead, result) {
  required(result, 'implementation result')
  if (result.blocked !== false) throw new Error('implementation blocked')
  required(startingHead, 'starting head')
  // The worker COMMITS on the isolated delivery branch and NEVER pushes (role-implementer-host-gated-push).
  if (result.committed !== true) {
    throw new Error('implementer must commit the red then green on the isolated delivery branch')
  }
  if (result.pushed !== false) {
    throw new Error('implementer must not push: the host pushes only after observer verification')
  }
  // Distinct real red and green commit ids, both moving off the unchanged starting HEAD.
  const redCommit = requiredNonEmptyString(result.red_commit, 'red commit id')
  const greenCommit = requiredNonEmptyString(result.green_commit, 'green commit id')
  const finalCommit = requiredNonEmptyString(result.final_commit ?? result.head, 'final commit id')
  if (redCommit === startingHead) throw new Error('red commit must move off the unchanged starting HEAD')
  if (redCommit === greenCommit) throw new Error('red and green must be distinct commits')
  // The delivered head is the final commit (green or a later refactor), never the starting HEAD.
  if (finalCommit === startingHead) throw new Error('delivered final HEAD must move off the starting HEAD')
  // Red and green proofs describe the same behavior scenario.
  assertProof(result.red, 'implementation red evidence')
  assertProof(result.green, 'implementation green evidence')
  if (result.red.exit_status === 0) throw new Error('red must fail the named test before the production change')
  if (result.green.exit_status !== 0) throw new Error('green must pass the same named test after the production change')
  if (result.green.scenario !== result.red.scenario) {
    throw new Error('green must prove the same scenario as red')
  }
  // Bound-test identity: the failing test is bound by path AND content digest, unchanged across red,
  // green, and the final HEAD (delivery-tdd-test-identity-binding).
  const boundTest = assertBoundTest(result.bound_test)
  return { redCommit, greenCommit, finalCommit, boundTest }
}

// TUR-447 D1 test-identity binding (delivery-lifecycle delivery-tdd-test-identity-binding,
// delivery-tdd-final-head-test-identity). The failing test is bound by path AND content digest, not by
// name alone. The same object is threaded to the observer replay so a green or final HEAD that removes,
// weakens, or edits the bound test by path or digest is rejected even when tests pass.
function assertBoundTest(boundTest) {
  required(boundTest, 'bound test identity')
  requiredNonEmptyString(boundTest.path, 'bound test path')
  requiredNonEmptyString(boundTest.digest, 'bound test content digest')
  return { path: boundTest.path, digest: boundTest.digest }
}

// TUR-447 D1 cycle2 independent git-read trust root (delivery-lifecycle
// delivery-tdd-observer-inputs-host-sourced, delivery-tdd-observer-inputs-host-journal-record,
// delivery-tdd-committed-red-commit, delivery-tdd-committed-green, delivery-tdd-test-identity-binding,
// delivery-tdd-final-head-verification, delivery-tdd-final-head-test-identity; role-runtime
// role-tdd-observer-host-sourced-inputs). The prior host journal COPIED the worker-claimed red/green/final
// commit ids straight into the journal, so a worker-authored commit id became the observer's input,
// masquerading as host-journalled. The real trust root is an INDEPENDENT git read the host does NOT get
// from the worker: a host-controlled Read-restricted subagent is given ONLY the worker's committed BRANCH
// name plus the exact bound expected STARTING HEAD (never the worker's claimed shas), independently reads
// git on that branch in an isolated worktree, and establishes and verifies the red commit (its diff is
// TEST-ONLY and its named test FAILS), the green commit (its diff is PRODUCTION-ONLY and the named test
// PASSES), the final HEAD (named test PASSES, bound test present unchanged by path AND content digest at
// red, green, and final), and a LINEAR red -> green -> ... -> final ancestry rooted at the expected
// starting HEAD. It returns the ACTUAL commit shas and digests it read from git.
//
// assertIndependentGitRead binds THAT read as the sole trust root. `read` is the subagent's report;
// `expected` is { branch, expectedStartingHead } the host supplied (never worker shas OR a worker path or
// digest). The bound-test identity is NOT a host/worker input: it is DISCOVERED by the reader from the RED
// COMMIT'S diff (the single test file the red commit added or changed IS the bound test) and its digest is
// computed from the ACTUAL git blob content the reader read at each commit. The gate takes the reader's
// red_test as the discovered bound-test identity and requires it present unchanged by that same path AND
// digest at the green and final commits. A read not stamped by the independent reader, over the wrong
// branch, whose base is not the expected starting HEAD, whose ancestry is not linear red->green->final,
// whose red diff is not test-only or does not fail, whose green diff is not production-only or does not
// pass, whose final does not pass, or whose discovered bound test is absent/changed by path or digest at
// the green or final commit, is rejected. The returned shas and the discovered bound test are what the host
// journals and cross-checks the worker claim against; no worker path/digest string is ever an input here.
const INDEPENDENT_GIT_READ_SOURCE = 'independent-git-read'

function assertReadStateDigest(observedTest, boundTest, label) {
  required(observedTest, `independent read ${label} bound test`)
  if (observedTest.path !== boundTest.path) {
    throw new Error(`independent git read rejected: bound test path absent or changed at the ${label} commit`)
  }
  if (observedTest.digest !== boundTest.digest) {
    throw new Error(`independent git read rejected: bound test content digest differs at the ${label} commit`)
  }
}

function assertIndependentGitRead(read, expected) {
  required(read, 'independent git read')
  required(expected, 'independent git read expectation')
  const branch = requiredNonEmptyString(expected.branch, 'expected delivery branch')
  const expectedStartingHead = requiredNonEmptyString(expected.expectedStartingHead, 'expected starting HEAD')
  // The bound-test identity is DISCOVERED by the reader from the red commit's diff, not supplied. The gate
  // takes the reader's own red_test as that discovered identity; a worker path/digest is never an input.
  const boundTest = assertBoundTest(read.red_test)
  // Provenance: the read is stamped by the independent git reader, never the mutating worker, and its
  // reader identity is not the worker.
  if (read.source !== INDEPENDENT_GIT_READ_SOURCE) {
    throw new Error('independent git read rejected: not from the independent git reader')
  }
  requiredNonEmptyString(read.read_by, 'independent git reader identity')
  if (read.mutating_worker !== undefined && read.read_by === read.mutating_worker) {
    throw new Error('independent git read rejected: the reader cannot be the mutating worker')
  }
  // The read ran in an isolated worktree over the exact committed branch.
  requiredNonEmptyString(read.isolated_worktree, 'independent git read isolated worktree')
  if (read.branch !== branch) {
    throw new Error('independent git read rejected: read a branch other than the committed delivery branch')
  }
  // The branch base is exactly the bound expected starting HEAD (the red roots off the unchanged HEAD).
  if (read.base_head !== expectedStartingHead) {
    throw new Error('independent git read rejected: branch base is not the expected starting HEAD')
  }
  // The actual shas the reader read from git.
  const red = requiredNonEmptyString(read.red_commit, 'independent read red commit')
  const green = requiredNonEmptyString(read.green_commit, 'independent read green commit')
  const final = requiredNonEmptyString(read.final_commit, 'independent read final commit')
  if (red === green) throw new Error('independent git read rejected: red and green collapse to one commit')
  if (red === expectedStartingHead) {
    throw new Error('independent git read rejected: red commit does not move off the expected starting HEAD')
  }
  // Linear red -> green -> ... -> final ancestry rooted at the expected starting HEAD. ancestry is the
  // ordered commit chain from the base HEAD's child (red) to final inclusive.
  const ancestry = requiredNonEmptyArray(read.ancestry, 'independent read ancestry chain')
  if (ancestry[0] !== red) throw new Error('independent git read rejected: ancestry does not start at the red commit')
  if (ancestry[ancestry.length - 1] !== final) {
    throw new Error('independent git read rejected: ancestry does not end at the final HEAD')
  }
  if (!ancestry.includes(green)) throw new Error('independent git read rejected: green commit not on the ancestry chain')
  if (ancestry.indexOf(green) <= ancestry.indexOf(red)) {
    throw new Error('independent git read rejected: green does not descend from the red commit')
  }
  if (ancestry.indexOf(final) < ancestry.indexOf(green)) {
    throw new Error('independent git read rejected: final HEAD does not descend from the green commit')
  }
  // Red diff is test-only and its named test genuinely FAILS (a missing file/module is not a valid red:
  // the reader records a genuine nonzero exit).
  if (read.red_diff_kind !== 'test-only') {
    throw new Error('independent git read rejected: red commit diff is not test-only')
  }
  if (!Number.isInteger(read.red_named_test_exit)) {
    throw new Error('independent git read rejected: red named-test exit status required')
  }
  if (read.red_named_test_exit === 0) {
    throw new Error('independent git read rejected: the red commit did not fail the named test')
  }
  // Green diff is production-only and its named test PASSES.
  if (read.green_diff_kind !== 'production-only') {
    throw new Error('independent git read rejected: green commit diff is not production-only')
  }
  if (!Number.isInteger(read.green_named_test_exit)) {
    throw new Error('independent git read rejected: green named-test exit status required')
  }
  if (read.green_named_test_exit !== 0) {
    throw new Error('independent git read rejected: the green commit did not pass the named test')
  }
  // Final HEAD named test PASSES.
  if (!Number.isInteger(read.final_named_test_exit)) {
    throw new Error('independent git read rejected: final named-test exit status required')
  }
  if (read.final_named_test_exit !== 0) {
    throw new Error('independent git read rejected: the final HEAD did not pass the named test')
  }
  // The discovered bound test (the reader's red_test) is a valid, non-empty {path, digest} the reader read
  // from the red commit's diff, and it is present unchanged by that same path AND digest at green and final.
  assertReadStateDigest(read.red_test, boundTest, 'red')
  assertReadStateDigest(read.green_test, boundTest, 'green')
  assertReadStateDigest(read.final_test, boundTest, 'final')
  return { red_commit: red, green_commit: green, final_commit: final, branch, boundTest }
}

// TUR-447 D1 cycle2 worker-claim cross-check (delivery-lifecycle delivery-tdd-observer-inputs-host-journal-record,
// delivery-tdd-named-test-commit-inputs-host-journalled; role-runtime role-tdd-observer-host-sourced-inputs).
// The worker's claimed red/green/final commit ids are cross-checked against the shas the INDEPENDENT git
// read actually read from the branch. Any mismatch is rejected, so a worker cannot point the observer at a
// forged or cherry-picked commit: the observer's inputs are the independent-read shas, and the worker claim
// must agree with them or the pass is rejected before any journal binding. independentRead is the trust
// root assertIndependentGitRead returned; workerClaim is { redCommit, greenCommit, finalCommit } from
// assertCommittedImplementation.
function assertWorkerClaimCrossCheck(independentRead, workerClaim) {
  required(independentRead, 'independent git read trust root')
  required(workerClaim, 'worker committed-commit claim')
  requiredNonEmptyString(workerClaim.redCommit, 'worker claimed red commit')
  requiredNonEmptyString(workerClaim.greenCommit, 'worker claimed green commit')
  requiredNonEmptyString(workerClaim.finalCommit, 'worker claimed final commit')
  if (workerClaim.redCommit !== independentRead.red_commit) {
    throw new Error('worker claim cross-check rejected: claimed red commit differs from the independent git read')
  }
  if (workerClaim.greenCommit !== independentRead.green_commit) {
    throw new Error('worker claim cross-check rejected: claimed green commit differs from the independent git read')
  }
  if (workerClaim.finalCommit !== independentRead.final_commit) {
    throw new Error('worker claim cross-check rejected: claimed final commit differs from the independent git read')
  }
  return {
    redCommit: independentRead.red_commit,
    greenCommit: independentRead.green_commit,
    finalCommit: independentRead.final_commit,
  }
}

// TUR-447 D1 cycle3 independent bound-test cross-check (delivery-lifecycle delivery-tdd-test-identity-binding,
// delivery-tdd-observer-inputs-host-journal-record; role-runtime role-tdd-observer-host-sourced-inputs). The
// worker's CLAIMED bound-test {path, digest} is used ONLY here, as a post-hoc cross-check against the bound
// test the INDEPENDENT reader DISCOVERED from the red commit's diff and hashed from git blob content. It is
// never an input to the reader. A worker claim that names a different test path or a different digest than
// the independently-discovered one is rejected, so a worker cannot relabel or mis-digest the bound test.
// independentRead is the trust root assertIndependentGitRead returned (it carries boundTest); workerBoundTest
// is the worker-reported { path, digest } from assertCommittedImplementation.
function assertWorkerBoundTestCrossCheck(independentRead, workerBoundTest) {
  required(independentRead, 'independent git read trust root')
  const discovered = assertBoundTest(independentRead.boundTest)
  const claimed = assertBoundTest(workerBoundTest)
  if (claimed.path !== discovered.path) {
    throw new Error('worker bound-test cross-check rejected: claimed test path differs from the independently discovered bound test')
  }
  if (claimed.digest !== discovered.digest) {
    throw new Error('worker bound-test cross-check rejected: claimed test digest differs from the independently discovered bound test')
  }
  return discovered
}

// TUR-447 D1 host-journalled commit binding (delivery-lifecycle delivery-tdd-observer-inputs-host-sourced,
// delivery-tdd-observer-inputs-host-journal-record; role-runtime role-tdd-observer-host-sourced-inputs).
// The HOST records the committed delivery branch, its red, green, and final commit ids, and the canonical
// validation command from the target AGENTS.md in the journal binding. That binding is the trust root: the
// observer checks out exactly these host-journalled commits and runs exactly this host-sourced command,
// never a worker-authored commit id or command string. The commit ids bound here are the INDEPENDENT
// git-read shas (cross-checked against the worker claim), never a raw worker claim; a divergent commit id
// or a worker-authored command is rejected. acceptedCommits is the { redCommit, greenCommit, finalCommit }
// trust root (the independent read cross-checked against the worker claim); command is the host's canonical
// validation command (never worker authored); branch is the committed delivery branch.
function assertHostJournalledCommits(binding, acceptedCommits, command, branch) {
  required(binding, 'host journal commit binding')
  requiredNonEmptyString(command, 'host-sourced validation command')
  requiredNonEmptyString(branch, 'committed delivery branch')
  const red = requiredNonEmptyString(binding.red_commit, 'journalled red commit')
  const green = requiredNonEmptyString(binding.green_commit, 'journalled green commit')
  const final = requiredNonEmptyString(binding.final_commit, 'journalled final commit')
  if (binding.branch !== branch) throw new Error('journalled branch differs from the committed delivery branch')
  // The journalled commit ids are exactly the accepted worker-committed ids; a divergent worker-claimed
  // commit id never enters the journal binding.
  if (red !== acceptedCommits.redCommit) throw new Error('journalled red commit differs from the committed red')
  if (green !== acceptedCommits.greenCommit) throw new Error('journalled green commit differs from the committed green')
  if (final !== acceptedCommits.finalCommit) throw new Error('journalled final commit differs from the committed final')
  // The command is the host-supplied canonical validation command, never a worker-authored string.
  if (binding.command !== command) throw new Error('journalled command differs from the host-sourced validation command')
  return { red_commit: red, green_commit: green, final_commit: final, command, branch }
}

// TUR-447 D1 independent observer replay of the committed states (delivery-lifecycle
// delivery-tdd-independent-observer, delivery-tdd-independent-observer-isolated,
// delivery-tdd-trusted-command-source, delivery-tdd-observer-inputs-host-sourced,
// delivery-tdd-final-head-verification, delivery-tdd-final-head-test-identity,
// delivery-tdd-no-forgeable-attestation; role-runtime role-tdd-observer, role-tdd-observer-trusted-source,
// role-tdd-observer-host-sourced-inputs). The dedicated Read-restricted tdd-observer, NEVER the mutating
// worker, checked out each HOST-JOURNALLED committed state and the final HEAD in an ISOLATED worktree and
// ran the host-trusted invocation. The host consumes THIS observation, not any worker string.
//
// The observation is fail-closed unless: it is stamped by the independent observer (never the worker);
// the exact commit ids it checked out equal the HOST-JOURNALLED red/green/final commits (a worker-claimed
// commit id never sources what the observer ran); the command it ran equals the host-sourced canonical
// validation command; the red commit FAILED, the green commit PASSED, and the final HEAD PASSED; and the
// bound test is present unchanged by path AND content digest at the red, green, and final commits, so a
// refactor that weakened, edited, or removed the bound test is rejected even when tests pass.
const INDEPENDENT_OBSERVER_SOURCE = 'independent-tdd-observer'

function assertObservedStateDigest(observedTest, boundTest, label) {
  required(observedTest, `observed ${label} bound test`)
  if (observedTest.path !== boundTest.path) {
    throw new Error(`observer replay rejected: bound test path absent or changed at the ${label} commit`)
  }
  if (observedTest.digest !== boundTest.digest) {
    throw new Error(`observer replay rejected: bound test content digest differs at the ${label} commit`)
  }
}

function assertObservedCommittedStates(observation, journalled, boundTest) {
  required(observation, 'independent observer replay')
  required(journalled, 'host-journalled commit binding')
  required(boundTest, 'bound test identity')
  // Provenance: the replay is stamped by the independent observer, never the mutating worker.
  if (observation.source !== INDEPENDENT_OBSERVER_SOURCE) {
    throw new Error('observer replay rejected: not from the independent tdd-observer')
  }
  requiredNonEmptyString(observation.observed_by, 'observer identity')
  if (observation.mutating_worker !== undefined && observation.observed_by === observation.mutating_worker) {
    throw new Error('observer replay rejected: the observer cannot be the mutating worker')
  }
  // Isolated worktree: the replay ran in an isolated worktree, never the worker branch, main, or the
  // live repository working directory.
  requiredNonEmptyString(observation.isolated_worktree, 'observer isolated worktree')
  // The observer checked out EXACTLY the host-journalled commits; a worker-claimed commit id never
  // sources what the observer executed.
  if (observation.red_commit !== journalled.red_commit) {
    throw new Error('observer replay rejected: red commit checked out is not the host-journalled red commit')
  }
  if (observation.green_commit !== journalled.green_commit) {
    throw new Error('observer replay rejected: green commit checked out is not the host-journalled green commit')
  }
  if (observation.final_commit !== journalled.final_commit) {
    throw new Error('observer replay rejected: final HEAD checked out is not the host-journalled final commit')
  }
  // The observer ran the host-sourced canonical validation command, never a worker-authored command.
  if (observation.command !== journalled.command) {
    throw new Error('observer replay rejected: command run is not the host-sourced validation command')
  }
  // Red commit FAILED (a missing file, module, export, or script is not a valid red: the observer must
  // record a genuine nonzero test exit with captured output, not an unrunnable invocation).
  if (!Number.isInteger(observation.red_exit)) throw new Error('observer replay rejected: red exit status required')
  if (observation.red_exit === 0) {
    throw new Error('observer replay rejected: the red commit did not fail the named test')
  }
  requiredNonEmptyString(observation.red_output, 'observed red output')
  // Green commit PASSED and final HEAD PASSED.
  if (!Number.isInteger(observation.green_exit)) throw new Error('observer replay rejected: green exit status required')
  if (observation.green_exit !== 0) {
    throw new Error('observer replay rejected: the green commit did not pass the named test')
  }
  requiredNonEmptyString(observation.green_output, 'observed green output')
  if (!Number.isInteger(observation.final_exit)) throw new Error('observer replay rejected: final HEAD exit status required')
  if (observation.final_exit !== 0) {
    throw new Error('observer replay rejected: the final pushed HEAD is not green')
  }
  requiredNonEmptyString(observation.final_output, 'observed final HEAD output')
  // Bound-test identity present unchanged by path AND content digest at the red, green, and final commits.
  assertObservedStateDigest(observation.red_test, boundTest, 'red')
  assertObservedStateDigest(observation.green_test, boundTest, 'green')
  assertObservedStateDigest(observation.final_test, boundTest, 'final')
  return observation
}

// TUR-447 cycle2 pass1 stale-read-race pre-push readback (role-runtime launch-readback,
// launch-gates-workflow-layer; delivery-lifecycle delivery-entry-gate). liveReadback runs at
// spawn start, BEFORE the resolver, ack, and mutation passes. A live change during those
// intervening passes was undetected before commit/push. The host takes a FRESH readback
// immediately BEFORE it commits/pushes and rejects if the live Linear state, Linear
// fingerprint, PR head, branch, or git HEAD changed since bind. bound is the post-fire
// reconciled envelope (the ground truth the pass bound); freshAfter is the pre-push live read.
const PRE_PUSH_FIELDS = [
  ['linear_state', 'Linear state'],
  ['linear_fingerprint', 'Linear fingerprint'],
  ['pr_head', 'PR head'],
  ['branch', 'PR branch'],
  ['git_head', 'git HEAD'],
]

function assertPrePushReadback(bound, freshAfter) {
  required(bound, 'bound envelope')
  required(freshAfter, 'pre-push fresh reads')
  for (const [field, label] of PRE_PUSH_FIELDS) {
    requiredNonEmptyString(freshAfter[field], `pre-push ${label}`)
    if (bound[field] !== freshAfter[field]) {
      throw new Error(`pre-push readback: ${label} changed since bind`)
    }
  }
  return freshAfter
}

// TUR-447 cycle2 pass1 stale-read-race worker liveness echo (role-runtime launch-readback,
// launch-identity). The mutating worker's bound echo previously omitted Linear state,
// fingerprint, and branch, so a change during the intervening passes was undetected before
// commit/push. The worker must now echo linear_state, linear_fingerprint, and branch as it read
// them, and the host asserts they equal the bound (post-fire reconciled) ground truth. This is
// paired with assertPrePushReadback, which then reconfirms those same fields live immediately
// before the host commit; together they close the window between spawn-start readback and push.
const LIVENESS_FIELDS = [
  ['linear_state', 'worker liveness Linear state'],
  ['linear_fingerprint', 'worker liveness Linear fingerprint'],
  ['branch', 'worker liveness branch'],
]

function assertWorkerLivenessEcho(bound, result) {
  required(bound, 'bound envelope')
  required(result, 'worker result')
  for (const [field, label] of LIVENESS_FIELDS) {
    requiredNonEmptyString(bound[field], `bound ${field}`)
    requiredNonEmptyString(result[field], label)
    if (result[field] !== bound[field]) {
      throw new Error(`${label} disagrees with the bound ground truth`)
    }
  }
  return result
}

// TUR-447 D1 live-remote push readback (delivery-lifecycle delivery-tdd-host-gated-push,
// delivery-tdd-named-test-live-remote-readback; role-runtime launch-readback). After the host pushes the
// verified branch, the pushed HEAD is confirmed by a LIVE REMOTE read, gh api or git ls-remote, NOT a
// local tracking ref, so a stale local ref can never falsely confirm an advance. readback carries the
// live remote head and its read source; the source must be one of the live-remote reads and the remote
// head must equal the expected pushed final HEAD.
const LIVE_REMOTE_SOURCES = new Set(['gh-api', 'git-ls-remote'])

function assertLiveRemotePushReadback(readback, expectedFinalHead) {
  required(readback, 'push readback')
  requiredNonEmptyString(expectedFinalHead, 'expected final HEAD')
  const source = requiredNonEmptyString(readback.remote_source, 'push readback remote source')
  if (!LIVE_REMOTE_SOURCES.has(source)) {
    throw new Error('push readback rejected: pushed HEAD must be confirmed by a live remote read (gh api or git ls-remote), not a local tracking ref')
  }
  const remoteHead = requiredNonEmptyString(readback.remote_head, 'push readback remote HEAD')
  if (remoteHead !== expectedFinalHead) {
    throw new Error('push readback rejected: live remote HEAD does not match the expected pushed final HEAD')
  }
  return { remote_head: remoteHead, remote_source: source }
}

function acceptCodeReview(expectedHead, expectedPr, review) {
  required(review, 'code review')
  if (review.head !== expectedHead) throw new Error('code review HEAD mismatch')
  requiredNonEmptyString(review.comment_url, 'code review comment')
  if (!review.comment_url.startsWith(expectedPr)) {
    throw new Error('code review comment URL does not match reviewed PR')
  }
  if (review.verdict === 'ambiguous') throw new Error('code review ambiguous')
  if (review.verdict === 'blocking') {
    if (!Array.isArray(review.findings) || review.findings.length === 0) {
      throw new Error('blocking findings required')
    }
    return { advance: false, findings: review.findings }
  }
  if (review.verdict !== 'clear') throw new Error('invalid code review verdict')
  return { advance: true, findings: [] }
}

function evidenceMode(userFacing) {
  return userFacing ? 'visual' : 'nonvisual'
}

const CRITERION_STATUSES = new Set(['pass', 'fail', 'not_evidenced'])

function assertCriteria(criteria) {
  requiredNonEmptyArray(criteria, 'QA criteria')
  for (const item of criteria) {
    requiredNonEmptyString(item?.criterion, 'QA criterion name')
    requiredNonEmptyString(item?.observation, 'QA criterion observation')
    if (!CRITERION_STATUSES.has(item?.status)) throw new Error('QA criterion status invalid')
    if (item.status !== 'pass') {
      requiredNonEmptyString(item.artifact, 'QA non-pass artifact')
      requiredNonEmptyString(item.fix, 'QA non-pass fix')
    }
  }
  return criteria
}

function acceptQaReview(expectedHead, expected, review) {
  required(review, 'qa review')
  if (review.head !== expectedHead) throw new Error('QA review HEAD mismatch')
  required(review.packet_url, 'served packet')
  if (review.issue !== expected.issue) throw new Error('QA review issue mismatch')
  // TUR-447 ruling-59 item 5: the PR is the canonical PR NUMBER, compared number-safe (6 and '6'
  // are the same PR). QA_REVIEW_SCHEMA previously forced review.pr to a string while this compared
  // strictly against the numeric envelope A.pr, so a numeric PR 6 could never pass; normalize both.
  if (requiredPrNumber(review.pr, 'QA review PR') !== requiredPrNumber(expected.pr, 'expected QA review PR')) {
    throw new Error('QA review PR mismatch')
  }
  if (review.manifest !== expected.manifest) throw new Error('QA review manifest mismatch')
  if (review.verdict === 'ambiguous') throw new Error('QA review ambiguous')
  const criteria = assertCriteria(review.criteria)
  const allPass = criteria.every((item) => item.status === 'pass')
  if (review.verdict === 'satisfied' && !allPass) {
    throw new Error('QA verdict does not match per-criterion results')
  }
  if (!allPass) {
    return { advance: false, findings: criteria.filter((item) => item.status !== 'pass') }
  }
  if (review.verdict !== 'satisfied') throw new Error('invalid QA verdict')
  return { advance: true, packet_url: review.packet_url }
}

function sameValues(left, right) {
  return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort())
}

function acceptPublication(expected, publication) {
  required(publication, 'publication readback')
  if (publication.readable !== true) throw new Error('served card not readable')
  if (publication.issue !== expected.issue) throw new Error('publication issue mismatch')
  if (publication.pr !== expected.pr) throw new Error('publication PR mismatch')
  if (publication.head !== expected.head) throw new Error('publication HEAD mismatch')
  if (publication.verdict !== 'satisfied') throw new Error('publication verdict mismatch')
  required(publication.packet_url, 'publication packet URL')
  if (!sameValues(publication.story_ids ?? [], expected.story_ids ?? [])) {
    throw new Error('publication story IDs mismatch')
  }
  if (!sameValues(publication.criteria_covered ?? [], expected.acceptance_criteria ?? [])) {
    throw new Error('publication criterion coverage mismatch')
  }
  return { packet_url: publication.packet_url }
}

// TUR-447 F2a Unit C. Pure relay-verbatim verification gate (role-runtime
// role-openai-relay, role-openai-fail-closed, launch-correctness-path; operating-model
// ADR decision-identity-source, decision-fail-closed-identity). This is the workflow-layer
// port of octo_lite/launch.py verify_relay_verbatim. It is a PURE function over data
// passed in: the loop cannot read files, sessions, or the network, so the caller resolves
// the OpenAI rollout record through a separate read-only subagent and passes the record
// here. The relay itself never supplies the record; a relay-persisted artifact alone is
// explicitly insufficient. The record shape mirrors the codex rollout file fields the
// launcher extracts: { provider, model, effort, final_message }.
//
// rolloutLookup is the INDEPENDENTLY-fetched rollout data, either the single record for
// the claimed session id or a map of session id to record. Resolution requires a record
// for the exact claimed session id; a session id without a rollout record is rejected
// (fail closed). Effective provider, model, and effort are proven FROM the record, not
// from the relay. The final assistant message is extracted FROM the record and must equal
// the relay-returned payload, so a relay that authors or edits prose fails.
function resolveRolloutRecord(rolloutLookup, claimedSessionId) {
  required(claimedSessionId, 'relay session id')
  if (rolloutLookup === undefined || rolloutLookup === null) {
    throw new Error(`relay verbatim rejected: no rollout record for session ${claimedSessionId}`)
  }
  let record = rolloutLookup
  const looksLikeMap =
    typeof rolloutLookup === 'object' &&
    !Array.isArray(rolloutLookup) &&
    rolloutLookup.provider === undefined &&
    rolloutLookup.session_id === undefined
  if (looksLikeMap) {
    record = rolloutLookup[claimedSessionId]
  } else if (rolloutLookup.session_id !== undefined && rolloutLookup.session_id !== claimedSessionId) {
    throw new Error(`relay verbatim rejected: no rollout record for session ${claimedSessionId}`)
  }
  if (record === undefined || record === null || typeof record !== 'object') {
    throw new Error(`relay verbatim rejected: no rollout record for session ${claimedSessionId}`)
  }
  return record
}

function verifyRelayVerbatim(expectedRuntime, claimedSessionId, relayPayload, rolloutLookup) {
  required(expectedRuntime, 'expected role runtime')
  const expectedProvider = required(expectedRuntime.provider, 'expected provider')
  const expectedModel = required(expectedRuntime.model, 'expected model')
  const expectedEffort = required(expectedRuntime.effort, 'expected effort')
  const record = resolveRolloutRecord(rolloutLookup, claimedSessionId)
  const provider = record.provider
  if (provider !== expectedProvider) {
    throw new Error(`relay verbatim rejected: provider substitution: ${provider}`)
  }
  const mismatches = []
  if (record.model !== expectedModel) mismatches.push('model')
  if (record.effort !== expectedEffort) mismatches.push('effort')
  if (mismatches.length > 0) {
    throw new Error(`relay verbatim rejected: effective identity mismatch: ${mismatches.join(', ')}`)
  }
  const finalMessage = record.final_message
  if (typeof finalMessage !== 'string' || finalMessage === '') {
    throw new Error(`relay verbatim rejected: no final assistant message in rollout record for ${claimedSessionId}`)
  }
  if (relayPayload !== finalMessage) {
    throw new Error('relay verbatim rejected: payload mismatch with rollout record')
  }
  return { provider, model: record.model, effort: record.effort, final_message: finalMessage }
}

// TUR-447 F2a Unit C sandbox-law predicates (role-runtime launch-review-sandbox-integrity,
// launch-resume-sandbox-config). Pure predicate gates over the resume/bootstrap argv the
// relay would execute. Port of the sandbox-selection rules in octo_lite/launch.py
// _provider_argv. F2b wires the actual relay execution and HEAD/status immutability; this
// pass provides the gates F2b calls.
//
// Every OpenAI resume selects its sandbox through -c sandbox_mode=... config, never the
// top-level -s flag, because the installed CLI resume subcommand rejects -s while the exec
// bootstrap still accepts it. A workspace-write plus network resume must declare both the
// workspace-write sandbox_mode and network access through -c config.
function hasTopLevelSandboxFlag(argv) {
  return argv.some((token, index) => token === '-s' && index + 1 < argv.length)
}

function configValues(argv, key) {
  const values = []
  for (let i = 0; i + 1 < argv.length; i += 1) {
    if (argv[i] === '-c' && typeof argv[i + 1] === 'string' && argv[i + 1].startsWith(`${key}=`)) {
      values.push(argv[i + 1].slice(key.length + 1))
    }
  }
  return values
}

function assertResumeSandboxConfig(resumeArgv, { needsLiveReads = false } = {}) {
  requiredNonEmptyArray(resumeArgv, 'resume argv')
  if (hasTopLevelSandboxFlag(resumeArgv)) {
    throw new Error('resume sandbox rejected: top-level -s flag prohibited on resume, use -c sandbox_mode config')
  }
  const modes = configValues(resumeArgv, 'sandbox_mode')
  if (modes.length !== 1) {
    throw new Error('resume sandbox rejected: exactly one -c sandbox_mode config required')
  }
  const mode = modes[0].replace(/^"|"$/g, '')
  if (needsLiveReads) {
    if (mode !== 'workspace-write') {
      throw new Error('resume sandbox rejected: live-read resume requires sandbox_mode=workspace-write')
    }
    const network = configValues(resumeArgv, 'sandbox_workspace_write.network_access')
    if (network.length !== 1 || network[0] !== 'true') {
      throw new Error('resume sandbox rejected: workspace-write resume requires network_access=true')
    }
  } else if (mode !== 'read-only') {
    throw new Error('resume sandbox rejected: non-live-read resume must stay sandbox_mode=read-only')
  }
  return { sandbox_mode: mode, needsLiveReads }
}

// A review-pass bootstrap must be read-only-first: the exec bootstrap selects the
// read-only sandbox before any workspace-write resume. A bootstrap that is not read-only
// is rejected.
function assertReadOnlyFirstBootstrap(bootstrapArgv) {
  requiredNonEmptyArray(bootstrapArgv, 'bootstrap argv')
  let sandbox = ''
  for (let i = 0; i + 1 < bootstrapArgv.length; i += 1) {
    if (bootstrapArgv[i] === '-s') sandbox = bootstrapArgv[i + 1]
  }
  if (sandbox !== 'read-only') {
    throw new Error('bootstrap rejected: OpenAI review-pass bootstrap must be read-only-first')
  }
  return { sandbox_mode: 'read-only' }
}

// TUR-447 F2b Unit G. Review-worktree immutability gate (role-runtime
// launch-review-sandbox-integrity): an OpenAI review pass must not mutate its worktree.
// The loop captures the review worktree HEAD and git status once before the read-only
// bootstrap and again after the resumed pass, and passes both snapshots here. A HEAD or
// status change across the review pass is rejected, whether it appears after the read-only
// bootstrap or after the workspace-write resume. status is the exact `git status
// --porcelain` output, which is empty for an unchanged worktree.
function assertReviewWorktreeImmutable(before, after) {
  required(before, 'review worktree before snapshot')
  required(after, 'review worktree after snapshot')
  requiredNonEmptyString(before.head, 'review worktree before HEAD')
  requiredNonEmptyString(after.head, 'review worktree after HEAD')
  if (before.head !== after.head) {
    throw new Error('review sandbox rejected: review-pass worktree HEAD changed')
  }
  const beforeStatus = before.status ?? ''
  const afterStatus = after.status ?? ''
  if (typeof beforeStatus !== 'string' || typeof afterStatus !== 'string') {
    throw new Error('review sandbox rejected: worktree status must be a string')
  }
  if (beforeStatus !== afterStatus || afterStatus !== '') {
    throw new Error('review sandbox rejected: review-pass worktree status changed')
  }
  return { head: after.head, status: afterStatus }
}

// TUR-447 F2b Unit G. Composite OpenAI-reviewer relay acceptance (role-runtime
// role-openai-relay, role-openai-fail-closed, launch-correctness-path,
// launch-review-sandbox-integrity, launch-resume-sandbox-config, launch-role-purpose-capability;
// operating-model decision-109-workflow-native). This is the single deterministic gate the
// loop calls to accept an OpenAI code-reviewer or qa-reviewer verdict produced through the
// codex relay. It fails closed unless EVERY provenance and sandbox law holds, so an OpenAI
// reviewer verdict can never be admitted through the generic native agent() path or with
// relay-supplied rollout data.
//
// Inputs, each produced by a DISTINCT spawned subagent so no single subagent both authors
// prose and vouches for its own effective identity:
//   resolvedRuntime  - { provider:'openai', model, effort, service_tier } resolved FROM
//                       roles.toml by a resolver subagent; the loop never hardcodes it.
//   relay            - { claimed_session_id, payload, bootstrap_argv, resume_argv,
//                        needs_live_reads, worktree_before, worktree_after,
//                        rollout_source } returned by the codex-exec relay subagent.
//   rollout          - { data, source } returned by a SEPARATE read-only Explore subagent
//                       that read the codex rollout record under CODEX_HOME/sessions; data
//                       is the independently fetched rollout record (or session-keyed map),
//                       source marks who fetched it.
//
// Provenance law: the rollout MUST come from the independent read-only reader, never the
// relay. A rollout whose source is the relay, or a relay that itself supplies rollout data,
// is rejected before verifyRelayVerbatim runs, so the fail-closed independent-read-back is
// structurally required, not merely conventional.
const INDEPENDENT_ROLLOUT_SOURCE = 'independent-rollout-subagent'
const OPENAI_REVIEWER_ROLES = new Set(['code-reviewer', 'qa-reviewer'])
// TUR-447 cycle1 pass2 P0 (role-runtime launch-purpose-shaping-roles, role-openai-relay,
// role-openai-fail-closed, role-machine-map, role-worker-migration): roles.toml declares
// shaping-reviewer as an OpenAI Workflow relay (provider=openai, gpt-5.6-sol, provenance
// relay-verbatim-rollout), so the shaping flow needs a cutover relay path that spawns it
// with the SAME rollout-record provenance and sandbox law as the code/qa reviewers. The
// sole OpenAI-reviewer relay set admitted only code-reviewer and qa-reviewer, so
// shaping-reviewer had no execution path at all. This admits it through an identical
// fail-closed relay acceptance keyed on its own admitted-role set.
const SHAPING_REVIEWER_ROLES = new Set(['shaping-reviewer'])

// Shared fail-closed relay verdict acceptance for every OpenAI relay role
// (role-runtime role-openai-relay, role-openai-fail-closed, launch-correctness-path,
// launch-review-sandbox-integrity, launch-resume-sandbox-config). admittedRoles is the
// exact role set the calling purpose admits; roleError names the purpose in the rejection.
// The body is the single deterministic gate: role admission, resolved-OpenAI-runtime shape,
// relay/rollout provenance (rollout MUST come from the independent read-only reader, never
// the relay), sandbox law over the exact argv, worktree immutability, and relay-verbatim
// effective identity proven FROM the independently fetched rollout record.
function acceptRelayVerdict(admittedRoles, roleError, role, resolvedRuntime, relay, rollout) {
  required(role, 'relay role')
  if (!admittedRoles.has(role)) {
    throw new Error(`relay verbatim rejected: ${role} is not ${roleError}`)
  }
  required(resolvedRuntime, 'resolved reviewer runtime')
  if (resolvedRuntime.provider !== 'openai') {
    throw new Error('relay verbatim rejected: reviewer runtime provider must be openai')
  }
  required(resolvedRuntime.model, 'resolved reviewer model')
  required(resolvedRuntime.effort, 'resolved reviewer effort')
  required(relay, 'relay result')
  const claimedSessionId = requiredNonEmptyString(relay.claimed_session_id, 'relay claimed session id')
  requiredNonEmptyString(relay.payload, 'relay payload')
  required(rollout, 'independent rollout result')
  // Provenance: the relay must not carry rollout data of its own, and the rollout must be
  // stamped by the independent read-only reader. Either violation fails closed.
  if (relay.rollout_source !== undefined && relay.rollout_source !== null) {
    throw new Error('relay verbatim rejected: relay must not supply the rollout record')
  }
  if (relay.rollout !== undefined && relay.rollout !== null) {
    throw new Error('relay verbatim rejected: relay must not supply the rollout record')
  }
  if (rollout.source !== INDEPENDENT_ROLLOUT_SOURCE) {
    throw new Error('relay verbatim rejected: rollout record not from the independent read-only subagent')
  }
  // Sandbox law over the exact argv the relay executed.
  assertReadOnlyFirstBootstrap(relay.bootstrap_argv)
  assertResumeSandboxConfig(relay.resume_argv, { needsLiveReads: relay.needs_live_reads === true })
  // Worktree immutability across the whole review pass.
  assertReviewWorktreeImmutable(relay.worktree_before, relay.worktree_after)
  // Effective identity proven FROM the independently fetched rollout record, and the relay
  // payload must equal that record's final assistant message verbatim.
  const verified = verifyRelayVerbatim(resolvedRuntime, claimedSessionId, relay.payload, rollout.data)
  return { verdict_payload: verified.final_message, session_id: claimedSessionId, runtime: verified }
}

function acceptOpenaiReviewRelay(role, resolvedRuntime, relay, rollout) {
  return acceptRelayVerdict(
    OPENAI_REVIEWER_ROLES, 'an OpenAI reviewer role', role, resolvedRuntime, relay, rollout,
  )
}

// TUR-447 cycle1 pass2 P0 shaping-reviewer cutover (role-runtime launch-purpose-shaping-roles,
// role-openai-relay, role-openai-fail-closed, launch-correctness-path). The shaping-review
// purpose admits role shaping-reviewer through the identical fail-closed relay acceptance the
// code/qa reviewers use: same independent rollout-record provenance, same sandbox law, same
// relay-verbatim effective-identity read-back. This is the workflow-layer acceptance the
// shaping relay spawn path calls so shaping-reviewer has a real cutover execution path rather
// than none. A non-shaping-review role rejects here exactly as a non-reviewer role does at the
// OpenAI-reviewer gate.
function acceptShapingReviewRelay(role, resolvedRuntime, relay, rollout) {
  return acceptRelayVerdict(
    SHAPING_REVIEWER_ROLES, 'a shaping-review relay role', role, resolvedRuntime, relay, rollout,
  )
}
// GATES-EMBED-END

// Decision 109 (operating-model decision-109-workflow-native and decision-109-binding;
// role-runtime launch-correctness-path and role-worker-migration): this Workflow spawns
// every worker role pass natively as a fresh subagent. The retired CLI pass launcher
// and its completed-pass result consumption model are gone. Worker binding proof is
// the workflow journal entry for the spawn plus the schema-forced acknowledgment echo
// of the exact bound inputs, verified before any mutation-phase advance. No worker
// TOML receipt exists. An OpenAI review role runs through a codex relay subagent brief;
// the spawn primitive is the same. Roles resolve through roles.toml; raw adapter files
// are never spawn inputs.

const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const mode = A.mode ?? 'implement'
// TUR-447 D1: red/green proofs are schema-forced to carry the exact HEAD the proof ran at and the
// behavior scenario it exercised. Under the reshaped committed model the implementer commits the red
// then green on an isolated branch, so the independent tdd-observer replay of the committed states,
// not a proof-shaped object, is the sole proof; the schema still forces head and scenario.
const PROOF_SCHEMA = {
  type: 'object',
  required: ['command', 'exit_status', 'outcome', 'artifact', 'head', 'scenario'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    outcome: { type: 'string' },
    artifact: { type: 'string' },
    head: { type: 'string' },
    scenario: { type: 'string' },
  },
}

// TUR-447 D1 reshaped delivery loop: the implementer COMMITS the red then green on an isolated
// delivery branch, so the red and green proofs describe the committed states the independent observer
// re-runs. Both proofs are the same PROOF_SCHEMA shape (command/exit_status/outcome/artifact/head/
// scenario); the observer replay, not a captured worker artifact, is the sole proof.

// Schema-forced acknowledgment echo of the exact journalled bound inputs
// (role-runtime launch-identity, launch-receipt; operating-model decision-109-binding).
// TUR-447 ruling-59 item 5: repo_slug (canonical owner/repo gh identity) and worktree (host issue
// worktree) are DECLARED and REQUIRED in the ack schema, so the schema-forced echo carries the exact
// identity-bound fields assertWorkerAckEcho checks; an ack omitting either is schema-rejected. The PR
// is a NUMBER (Number.isInteger-typed), never a string-only URL, so a numeric PR 6 is schema-valid and
// gh cannot infer a foreign repo from a URL-shaped PR.
const ACK_SCHEMA = {
  type: 'object',
  required: ['role', 'repo', 'repo_slug', 'worktree', 'issue', 'pr', 'starting_head', 'spec_blobs', 'contract_hash'],
  properties: {
    role: { type: 'string' },
    repo: { type: 'string' },
    repo_slug: { type: 'string' },
    worktree: { type: 'string' },
    issue: { type: 'string' },
    pr: { type: 'integer' },
    starting_head: { type: 'string' },
    spec_blobs: { type: 'array', items: { type: 'string' } },
    contract_hash: { type: 'string' },
  },
}

// The read-only acknowledgment phase (Unit B, TUR-447 F1) returns ONLY the ack echo:
// its schema forces the ack object and nothing mutation-related, so the read-only spawn
// cannot smuggle a result that advances work before the echo is host-verified.
const ACK_ONLY_SCHEMA = {
  type: 'object',
  required: ['ack'],
  properties: {
    ack: ACK_SCHEMA,
  },
}

// TUR-447 D1 reshaped delivery loop (delivery-lifecycle delivery-tdd-committed-red,
// delivery-tdd-committed-green, delivery-tdd-test-identity-binding; role-runtime
// role-implementer-host-gated-push). The implementer COMMITS the red then green on an isolated
// delivery branch and reports committed:true, pushed:false with the distinct red, green, and final
// commit ids, plus the failing test bound by path and content digest (bound_test). It still echoes the
// liveness fields it read so the host can reconfirm them live before push. It NEVER pushes.
const BOUND_TEST_SCHEMA = {
  type: 'object',
  required: ['path', 'digest'],
  properties: { path: { type: 'string' }, digest: { type: 'string' } },
}

const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: [
    'ack', 'issue', 'pr_url', 'branch', 'head', 'handoff_url', 'red', 'green',
    'validation', 'blocked', 'committed', 'pushed',
    'red_commit', 'green_commit', 'final_commit', 'bound_test',
    'linear_state', 'linear_fingerprint',
  ],
  properties: {
    ack: ACK_SCHEMA,
    issue: { type: 'string' },
    pr_url: { type: 'string' },
    branch: { type: 'string' },
    head: { type: 'string' },
    handoff_url: { type: 'string' },
    red: PROOF_SCHEMA,
    green: PROOF_SCHEMA,
    validation: { type: 'string' },
    summary: { type: 'string' },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
    // Committed model: the worker committed the red then green on the isolated branch and did NOT push.
    committed: { type: 'boolean' },
    pushed: { type: 'boolean' },
    // The distinct red, green, and final commit ids the host journals for the observer to check out.
    red_commit: { type: 'string' },
    green_commit: { type: 'string' },
    final_commit: { type: 'string' },
    // The failing test bound by path and content digest, unchanged red -> green -> final HEAD.
    bound_test: BOUND_TEST_SCHEMA,
    // Stale-read race: the worker echoes the liveness fields it read so the host asserts them
    // against the bound ground truth and reconfirms them live before push.
    linear_state: { type: 'string' },
    linear_fingerprint: { type: 'string' },
  },
}

// TUR-447 D1 independent observer replay (delivery-lifecycle delivery-tdd-independent-observer,
// delivery-tdd-independent-observer-isolated, delivery-tdd-final-head-verification,
// delivery-tdd-final-head-test-identity). The dedicated Read-restricted tdd-observer checks out each
// HOST-JOURNALLED committed state and the final HEAD in an ISOLATED worktree and runs the host-trusted
// command. It reports the exact commit ids it checked out (must equal the host-journalled red/green/
// final), the command it ran (must equal the host-sourced canonical validation command), the red/green/
// final exit + captured output (red FAIL, green and final PASS), and the bound-test identity it observed
// at each committed state (path + digest unchanged). assertObservedCommittedStates consumes THIS.
const OBSERVED_TEST_SCHEMA = {
  type: 'object',
  required: ['path', 'digest'],
  properties: { path: { type: 'string' }, digest: { type: 'string' } },
}

// TUR-447 D1 cycle2 independent git-read trust root (delivery-lifecycle
// delivery-tdd-observer-inputs-host-sourced, delivery-tdd-observer-inputs-host-journal-record). The
// host-controlled Read-restricted git reader is given ONLY the committed branch name and the expected
// starting HEAD (never the worker's claimed shas). It independently reads git on that branch in an
// isolated worktree and reports the ACTUAL red/green/final shas, the branch base, the linear ancestry
// chain, each commit's diff kind (red test-only, green production-only), each named-test exit (red FAIL,
// green PASS, final PASS), and the bound-test identity (path + digest) it read at each commit.
// assertIndependentGitRead consumes THIS; hostJournalCommits binds its shas, never a worker claim.
const INDEPENDENT_GIT_READ_SCHEMA = {
  type: 'object',
  required: [
    'source', 'read_by', 'isolated_worktree', 'branch', 'base_head',
    'red_commit', 'green_commit', 'final_commit', 'ancestry',
    'red_diff_kind', 'red_named_test_exit', 'red_test',
    'green_diff_kind', 'green_named_test_exit', 'green_test',
    'final_named_test_exit', 'final_test',
  ],
  properties: {
    source: { type: 'string' },
    read_by: { type: 'string' },
    mutating_worker: { type: 'string' },
    isolated_worktree: { type: 'string' },
    branch: { type: 'string' },
    base_head: { type: 'string' },
    red_commit: { type: 'string' },
    green_commit: { type: 'string' },
    final_commit: { type: 'string' },
    ancestry: { type: 'array', items: { type: 'string' } },
    red_diff_kind: { type: 'string' },
    red_named_test_exit: { type: 'integer' },
    red_test: OBSERVED_TEST_SCHEMA,
    green_diff_kind: { type: 'string' },
    green_named_test_exit: { type: 'integer' },
    green_test: OBSERVED_TEST_SCHEMA,
    final_named_test_exit: { type: 'integer' },
    final_test: OBSERVED_TEST_SCHEMA,
  },
}

const OBSERVATION_SCHEMA = {
  type: 'object',
  required: [
    'source', 'observed_by', 'isolated_worktree', 'command',
    'red_commit', 'red_exit', 'red_output', 'red_test',
    'green_commit', 'green_exit', 'green_output', 'green_test',
    'final_commit', 'final_exit', 'final_output', 'final_test',
  ],
  properties: {
    source: { type: 'string' },
    observed_by: { type: 'string' },
    mutating_worker: { type: 'string' },
    isolated_worktree: { type: 'string' },
    command: { type: 'string' },
    red_commit: { type: 'string' },
    red_exit: { type: 'integer' },
    red_output: { type: 'string' },
    red_test: OBSERVED_TEST_SCHEMA,
    green_commit: { type: 'string' },
    green_exit: { type: 'integer' },
    green_output: { type: 'string' },
    green_test: OBSERVED_TEST_SCHEMA,
    final_commit: { type: 'string' },
    final_exit: { type: 'integer' },
    final_output: { type: 'string' },
    final_test: OBSERVED_TEST_SCHEMA,
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'verdict', 'findings', 'comment_url'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    comment_url: { type: 'string' },
  },
}

// TUR-447 cycle1 pass2 P0 shaping-review verdict (role-runtime launch-purpose-shaping-roles,
// role-openai-relay). The OpenAI shaping-reviewer binds an exact-head shaping verdict from the
// verbatim relay payload: clear, blocking, or ambiguous, with findings and the review artifact.
const SHAPING_REVIEW_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'verdict', 'findings', 'comment_url'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    comment_url: { type: 'string' },
  },
}

const CAPTURE_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'plan', 'manifest', 'artifacts', 'blocked'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    plan: { type: 'array', items: { type: 'object' } },
    manifest: { type: 'string' },
    artifacts: { type: 'array', items: { type: 'string' } },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
  },
}

const CRITERION_SCHEMA = {
  type: 'object',
  required: ['criterion', 'status', 'observation'],
  properties: {
    criterion: { type: 'string' },
    status: { enum: ['pass', 'fail', 'not_evidenced'] },
    observation: { type: 'string' },
    artifact: { type: 'string' },
    fix: { type: 'string' },
  },
}

// TUR-447 ruling-59 item 5 numeric-PR QA fix: the QA reviewer's echoed pr is the canonical PR NUMBER
// (integer), never a string-only value, so it matches the numeric envelope A.pr; acceptQaReview
// compares them number-safe. The prior string-only pr could never equal the numeric A.pr, so PR 6
// could not pass QA review.
const QA_REVIEW_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'verdict', 'issue', 'pr', 'manifest', 'criteria', 'packet_url'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    verdict: { enum: ['satisfied', 'blocking', 'ambiguous'] },
    issue: { type: 'string' },
    pr: { type: 'integer' },
    manifest: { type: 'string' },
    criteria: { type: 'array', items: CRITERION_SCHEMA },
    packet_url: { type: 'string' },
  },
}

const FIRE_SCHEMA = {
  type: 'object',
  required: ['command', 'exit_status', 'readback_state', 'readback_fingerprint'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    readback_state: { type: 'string' },
    // TUR-447 cycle2 pass1 P0 fingerprint fix: the fire's own fresh readback returns the
    // POST-FIRE Linear content fingerprint too, so the loop reconciles the bound envelope to
    // BOTH the post-fire state AND fingerprint. The fingerprint is a function of the issue
    // state, so a Shaped fingerprint differs from a Todo fingerprint; reconciling only the
    // state left the stale Shaped fingerprint and self-rejected at assertLaunchReadback.
    readback_fingerprint: { type: 'string' },
  },
}

// Live-readback result shape (role-runtime launch-readback, launch-gates-workflow-layer).
// The fresh reads are the exact fields assertLaunchReadback compares the caller envelope
// against: the live Linear state and fingerprint, the live PR head, and the live branch.
// The reader also returns the live git HEAD so the caller starting HEAD is proven live too.
const FRESH_READS_SCHEMA = {
  type: 'object',
  required: ['linear_state', 'linear_fingerprint', 'pr_head', 'branch', 'git_head'],
  properties: {
    linear_state: { type: 'string' },
    linear_fingerprint: { type: 'string' },
    pr_head: { type: 'string' },
    branch: { type: 'string' },
    git_head: { type: 'string' },
  },
}

// TUR-447 F4b-A Unit I (role-runtime role-worker-migration, role-claude-native,
// role-reconciler-bootstrap-snapshot-proof; operating-model decision-109-workflow-native).
// The reconciler subagent's read-only acknowledgment echo carries the journal-bound
// snapshot path and digest it proved by opening the exact bound snapshot file and hashing
// its bytes, plus the bound identity fields. The owning host verifies this echo against the
// durable journal binding (octo_lite.launch verify_reconcile_workflow_ack) before any
// classification is bound; a missing or digest-mismatched snapshot fails closed.
const RECONCILE_ACK_SCHEMA = {
  type: 'object',
  required: [
    'schema_version', 'spawn_id', 'launch_revision', 'role', 'worktree',
    'starting_head', 'snapshot_path', 'snapshot_digest', 'ready', 'blocker',
  ],
  properties: {
    schema_version: { type: 'integer' },
    spawn_id: { type: 'string' },
    launch_revision: { type: 'string' },
    role: { type: 'string' },
    worktree: { type: 'string' },
    starting_head: { type: 'string' },
    snapshot_path: { type: 'string' },
    snapshot_digest: { type: 'string' },
    ready: { type: 'boolean' },
    blocker: { type: 'string' },
  },
}

// The reconciler's read-only classification result (role-runtime role-reconciler-input,
// role-reconciler-authority, role-reconciler-escalation). Sonnet classifies deltas as
// changed, missing, stale, contradictory, or needs_fable and never mutates a source;
// missing, unparseable, or ambiguous input escalates with needs_fable so Fable judges.
const RECONCILE_RESULT_SCHEMA = {
  type: 'object',
  required: ['ack', 'classification', 'needs_fable', 'deltas'],
  properties: {
    ack: RECONCILE_ACK_SCHEMA,
    classification: { enum: ['changed', 'missing', 'stale', 'contradictory', 'needs_fable', 'unchanged'] },
    needs_fable: { type: 'boolean' },
    deltas: { type: 'array', items: { type: 'string' } },
  },
}

// `required` is the embedded gates.mjs helper above (GATES-EMBED region), the
// single source shared by the inline gates and this loop. A Workflow script is one
// flat top-level scope, so re-declaring it here would be a duplicate top-level
// declaration SyntaxError at load. The loop uses the embedded canonical `required`.
function cycle() {
  const value = Number(A.cycle ?? 1)
  if (!Number.isInteger(value) || value < 1 || value > 3) throw new Error('cycle must be 1 through 3')
  return value
}

function specBlobs() {
  if (!Array.isArray(A.spec_blobs) || A.spec_blobs.length === 0) throw new Error('spec blobs required')
  return A.spec_blobs
}

// The exact bound inputs for one worker pass. The workflow journal records this
// object at spawn time; the worker must echo it verbatim in its structured result.
// TUR-447 ruling-56 cycle3 slug-identity-bound: repo_slug (canonical owner/repo gh identity) and the
// contained host issue worktree are part of the journalled bound-input set, so they enter BOTH the
// worker ack echo (assertWorkerAckEcho) AND the launch-revision fingerprint (launchRevision). A missing
// or foreign slug is rejected at readiness (assertReadyEnvelope) before this runs; here they are bound
// so a foreign slug/worktree diverges the launch revision and fails the ack echo. The PR is the
// canonical PR NUMBER, not a URL.
function journalledBoundInputs(role, startingHead) {
  return {
    role,
    repo: required(A.repo, 'repo'),
    repo_slug: assertRepoSlug(A.repo_slug, 'repo_slug'),
    worktree: assertContainment(required(A.worktree_root, 'worktree root'), required(A.worktree, 'worker worktree')),
    issue: required(A.issue, 'issue'),
    // Validate the PR is a NUMBER (never a URL) but bind the caller's exact value so the launch-revision
    // fingerprint matches the caller-computed revision over the same bound-input shape.
    pr: (requiredPrNumber(A.pr, 'pr'), A.pr),
    starting_head: required(startingHead, 'starting head'),
    spec_blobs: specBlobs(),
    contract_hash: required(A.contract_hash, 'contract hash'),
  }
}

// TUR-447 cycle1 pass2 F2 (role-runtime role-machine-map, role-resolver, role-openai-relay).
// The COMPLETE, runnable role-resolver command carrying every required argument from the bound
// inputs. The prior brief had a literal '...' that omitted every required arg, so it was not
// runnable and no runtime was ever resolved. This builds the exact command a resolver subagent
// runs: role plus --spawn-id --parent --reply-route --repo --worktree --execution-location
// --review-delivery, plus --capability for each matched conditional-skill trigger and
// --operator-loopback when the launch context confirms operator loopback. worktreeAbs is the
// contained absolute worktree path (worktree_root + worktree, containment-checked).
function resolverCommand(role, worktreeAbs) {
  const repo = required(A.repo, 'repo')
  const spawnId = A.spawn_id ?? `${role}-${required(A.issue, 'issue')}-${required(A.starting_head ?? A.shaping_head ?? A.head, 'starting head')}`
  const parent = A.parent ?? 'orchestrator'
  const replyRoute = A.reply_route ?? A.pr_url ?? required(A.pr, 'pr')
  const executionLocation = A.execution_location ?? 'local'
  const reviewDelivery = A.review_delivery ?? A.pr_url ?? required(A.pr, 'pr')
  const parts = [
    'python3', 'workflows/lib/role_resolver.py', 'resolve', role,
    '--spawn-id', spawnId,
    '--parent', parent,
    '--reply-route', replyRoute,
    '--repo', repo,
    '--worktree', worktreeAbs,
    '--execution-location', executionLocation,
    '--review-delivery', reviewDelivery,
    // Emit the canonical contract text (as a valid TOML [contract] table) so the relay and the
    // native worker carry the exact contract prose; the durable persistent-launch path omits it.
    '--emit-contract',
  ]
  if (A.operator_loopback === true || A.operator_loopback === false) {
    parts.push('--operator-loopback', String(A.operator_loopback))
  }
  const capabilities = Array.isArray(A.capabilities) ? A.capabilities : []
  for (const capability of capabilities) parts.push('--capability', capability)
  return parts.join(' ')
}

// TUR-447 cycle1 pass2 F2c (role-runtime role-machine-map, role-worker-migration,
// role-openai-relay). Resolve one role's runtime FROM roles.toml through the role resolver in a
// read-only Explore subagent that runs the COMPLETE resolverCommand and returns the exact
// resolved provider, model, effort, service_tier, contract_blob, the canonical contract TEXT,
// and (for native workers) the resolved skill set. The loop cannot read files, so it never
// hardcodes any runtime field; every worker and reviewer pass binds the resolved identity.
async function resolveRuntime(role, phaseTitle, worktreeAbs, schema, issue) {
  const command = resolverCommand(role, worktreeAbs)
  const runtime = await agent([
    `Resolve the octo-lite ${role} runtime from roles.toml through the role resolver. One pass; read-only.`,
    'Run EXACTLY this command from the repo root and parse its VALID-TOML output:',
    command,
    'The whole stdout is one TOML document. Return provider, model, effort, and service_tier',
    'from the [runtime] table; contract_blob from [contract].blob; contract_text as the VERBATIM',
    '[contract].text value; and skills as the [skills].resolved array.',
    'Do not invent or override any field; report exactly what the resolver printed.',
  ].join('\n'), {
    label: `${role}-runtime:${issue}`, phase: phaseTitle, schema, agentType: 'Explore',
  })
  if (runtime === null) throw new Error(`${role} runtime resolution returned no result`)
  return runtime
}

// TUR-447 ruling-56 cycle2 canonical GitHub repo slug (loop-correctness single-writer; delivery-
// lifecycle launch-readback). A.repo is a LOCAL PATH used for git -C; the canonical owner/repo gh
// identity is the SEPARATE A.repo_slug the host derives from the worktree remote (git -C <worktree>
// remote get-url origin, normalized to owner/repo) and binds into the envelope. Every gh command in a
// subagent prompt is pinned to THIS slug (gh pr view --repo <slug> / gh api repos/<slug>/...), so gh
// never infers the repository from the ambient (foreign lane) cwd. A missing slug fails closed.
function ghRepoSlug() {
  return requiredNonEmptyString(A.repo_slug, 'canonical GitHub repo slug (owner/repo)')
}

// TUR-447 ruling-59 host-trusted identity trust anchor (loop-correctness single-writer;
// delivery-lifecycle launch-readback, delivery-entry-gate; role-runtime launch-identity,
// launch-entrypoint-revalidation, launch-containment, launch-receipt). The prior identity cycles
// were self-referential: readiness/ack/launch-revision validated the envelope repo_slug/worktree/
// starting_head OVER the same forgeable child envelope, so a foreign-but-well-formed envelope
// self-consistently passed. This runs BEFORE any Shaped -> Todo fire or spawn and validates the
// envelope against TWO anchors the child cannot forge, NEITHER derived from the envelope:
//   Anchor A - a HOST-PROVISIONED receipt read from a HOST-TRUSTED location (the OCTO_RECEIPT env
//     var / launch-context path the launcher set, NEVER a path in the child envelope), carrying
//     [workspace] repo_slug/worktree/starting_head; assertReceiptWorkspaceBinding rejects unless
//     the envelope matches it (catches a forged envelope claiming a different repo/worktree/head).
//   Anchor B - a LIVE git read of the RECEIPT-pinned worktree (git -C <receipt.worktree> rev-parse
//     HEAD / --abbrev-ref HEAD / remote get-url origin); assertLiveWorktreeIdentity rejects unless
//     the live HEAD/branch/origin match the receipt+envelope (catches the tur-456 shape: a matching
//     worktree PATH that is actually on a FOREIGN branch / different remote, which Anchor A misses).
// The loop cannot read files, env, or git, so each anchor is read by a host-controlled subagent that
// returns the values THROUGH these production gates. A mismatch on either -> reject, no fire, no spawn.
const HOST_RECEIPT_ENV = 'OCTO_RECEIPT'
const RECEIPT_READ_SCHEMA = {
  type: 'object',
  required: ['source', 'repo', 'repo_slug', 'worktree', 'starting_head'],
  properties: {
    source: { type: 'string' },
    repo: { type: 'string' },
    repo_slug: { type: 'string' },
    worktree: { type: 'string' },
    starting_head: { type: 'string' },
  },
}
const LIVE_WORKTREE_READ_SCHEMA = {
  type: 'object',
  required: ['source', 'read_worktree', 'head', 'branch', 'repo_slug'],
  properties: {
    source: { type: 'string' },
    read_worktree: { type: 'string' },
    head: { type: 'string' },
    branch: { type: 'string' },
    repo_slug: { type: 'string' },
  },
}

async function hostTrustedIdentity(role, phaseTitle) {
  const issue = required(A.issue, 'issue')
  // The identity envelope the anchors validate carries the CONTAINED ABSOLUTE worktree (worktree_root +
  // the contained relative worktree, containment-checked), the canonical repo_slug, the pass starting
  // HEAD, and the branch. The receipt records the absolute worktree and the workspace starting HEAD, so
  // the anchors compare like-with-like. This is derived from the envelope but validated AGAINST the
  // host-provisioned receipt and the live git read, NEITHER of which is envelope-derived.
  const identityEnvelope = {
    repo_slug: required(A.repo_slug, 'repo_slug'),
    worktree: assertContainment(required(A.worktree_root, 'worktree root'), required(A.worktree, 'worktree')),
    starting_head: required(A.starting_head ?? A.shaping_head ?? A.head, 'starting head'),
    branch: required(A.branch, 'branch'),
  }
  // Anchor A: a host-controlled Read-restricted subagent reads the receipt from the HOST-TRUSTED
  // OCTO_RECEIPT location (env var / launch-context path), NEVER a path supplied by the child
  // envelope. It returns the receipt [workspace] repo/repo_slug/worktree/starting_head, stamped
  // host-provisioned-receipt. The loop never tells it a child-envelope path.
  const receipt = await agent([
    `You are a fresh HOST-CONTROLLED, READ-ONLY octo-lite receipt reader for the ${role} identity anchor.`,
    'One pass; never mutate. Read the host-provisioned launch RECEIPT the LAUNCHER wrote at spawn from the',
    `HOST-TRUSTED location named by the ${HOST_RECEIPT_ENV} environment variable (its value is a receipt.toml`,
    'path the host set; resolve $' + HOST_RECEIPT_ENV + ' yourself). Do NOT accept, resolve, or read any receipt',
    'path supplied by the delivery envelope, the caller, a worker, or this prompt: the receipt location is the',
    `host env var ${HOST_RECEIPT_ENV} ONLY. Parse its [workspace] table and return source`,
    '"host-provisioned-receipt", repo, repo_slug, worktree, and starting_head EXACTLY as the receipt records them.',
    'If $' + HOST_RECEIPT_ENV + ' is unset or the receipt is missing, fail closed (do not fabricate a receipt).',
  ].join('\n'), {
    label: `${role}-receipt:${issue}`, phase: phaseTitle, schema: RECEIPT_READ_SCHEMA,
    agentType: 'Explore', effort: 'low',
  })
  if (receipt === null) throw new Error(`${role} host-provisioned receipt read returned no result`)
  // Anchor A gate: the identity envelope repo_slug/worktree/starting_head MUST match the host receipt.
  assertReceiptWorkspaceBinding(identityEnvelope, receipt)
  // Anchor B: a host-controlled subagent does a LIVE git read of the RECEIPT-pinned worktree (never an
  // envelope path). It returns the live HEAD, branch, and origin repo slug it read, stamped
  // host-receipt-pinned-worktree-read, over the receipt.worktree it echoes as read_worktree.
  const receiptWorktree = requiredNonEmptyString(receipt.worktree, 'receipt worktree')
  const live = await agent([
    `You are a fresh HOST-CONTROLLED, READ-ONLY octo-lite worktree-reality reader for the ${role} identity anchor.`,
    'One pass; never mutate. Perform a LIVE git read of the RECEIPT-PINNED worktree below (the path came from the',
    'host-provisioned receipt, NOT the delivery envelope). Operate ONLY on this exact path; do NOT rely on the',
    'ambient current working directory (a foreign lane worktree on a shared box):',
    `  receipt-pinned worktree: ${receiptWorktree}`,
    `- head: \`git -C ${receiptWorktree} rev-parse HEAD\`.`,
    `- branch: \`git -C ${receiptWorktree} rev-parse --abbrev-ref HEAD\`.`,
    `- repo_slug: \`git -C ${receiptWorktree} remote get-url origin\`, normalized to the canonical owner/repo slug.`,
    'Return source "host-receipt-pinned-worktree-read", read_worktree set to the exact receipt-pinned worktree',
    'path above, and head, branch, and repo_slug as you actually read them from git. Never fabricate a value.',
  ].join('\n'), {
    label: `${role}-worktree-reality:${issue}`, phase: phaseTitle, schema: LIVE_WORKTREE_READ_SCHEMA,
    agentType: 'Explore', effort: 'low',
  })
  if (live === null) throw new Error(`${role} live receipt-pinned worktree read returned no result`)
  // Anchor B gate: the live HEAD/branch/origin of the receipt-pinned worktree MUST match receipt+envelope.
  // Catches the tur-456 shape (matching path, foreign branch / different remote) that Anchor A alone misses.
  return assertHostTrustedIdentity(identityEnvelope, receipt, live)
}

// Live readback immediately before EVERY native spawn (TUR-447 F3 Unit H; role-runtime
// launch-readback, launch-gates-workflow-layer). The loop itself cannot read Linear, the
// PR, or git (the Workflow sandbox has no filesystem or network), and it must NOT trust a
// caller-supplied fresh_reads blob as if it were live: a stale caller could hand back an
// internally-consistent blob that agrees with its own stale envelope. So the ONLY source
// of fresh reads is a spawned read-only agentType:'Explore' subagent that performs the
// live reads here and RETURNS them. assertLaunchReadback then compares the caller envelope
// against those returned live reads and rejects a stale self-consistent envelope whose
// Linear state, Linear fingerprint, PR head, or branch disagrees with the live read. The
// live git HEAD is proven equal to the caller starting HEAD too, so a stale HEAD never
// spawns. This runs before the ack/relay spawn in EVERY delivery mode (implement,
// code-review, fix, qa-capture, qa-review), not just implement.
async function liveReadback(role, phaseTitle, startingHead, worktree) {
  const issue = required(A.issue, 'issue')
  const pr = required(A.pr, 'pr')
  const branch = required(A.branch, 'branch')
  // TUR-447 ruling-56 host cwd pin (loop-correctness single-writer): the readback subagent runs in an
  // AMBIENT cwd that on the shared box is a FOREIGN lane worktree, so a bare git read would read the
  // WRONG worktree. Pin the git read to the host issue worktree (git -C ${worktree}) and forbid the
  // subagent from relying on the ambient current working directory.
  requiredNonEmptyString(worktree, 'readback host worktree')
  // TUR-447 ruling-56 cycle2 gh repo pin (loop-correctness single-writer): a gh read must NOT infer
  // the repo from the ambient (foreign lane) cwd. Every gh command is pinned to the canonical
  // owner/repo slug from the bound inputs, so it always selects the right repository.
  const slug = ghRepoSlug()
  const fresh = await agent([
    `You are a fresh READ-ONLY octo-lite readback subagent for the ${role} spawn. One pass;`,
    'never mutate. Perform LIVE reads NOW, immediately before dispatch, and return them:',
    `- linear_state: the live Linear state of ${issue}.`,
    // TUR-447 ruling-55 canonical fingerprint source (delivery-lifecycle launch-readback; the
    // envelope fingerprint the loop compares against is octo-control linear-read exact_fingerprint).
    // linear_fingerprint MUST be that same canonical read, NEVER an improvised or self-hashed
    // fingerprint, so the readback and the envelope are like-with-like and a genuine unchanged
    // Todo-entry passes while a real content change still diverges the exact_fingerprint.
    `- linear_fingerprint: run scripts/octo-control linear-read ${issue} and use ITS returned`,
    '  fingerprint field verbatim. Do NOT improvise, recompute, or self-hash the fingerprint.',
    `- pr_head: the live PR head oid (\`gh pr view ${pr} --repo ${slug} --json headRefOid\`) of the PR.`,
    `  The gh read is REPO-PINNED to ${slug}; never let gh infer the repo from the current working directory.`,
    `- branch: the live head branch of the PR (\`gh pr view ${pr} --repo ${slug} --json headRefName\`, expected ${branch}).`,
    `- git_head: the live git HEAD of the host issue worktree, read via \`git -C ${worktree} rev-parse HEAD\`.`,
    `  Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    '  it may be a foreign lane worktree on a shared box.',
    'Read state, pr_head, branch, and git_head yourself from Linear, GitHub, and the host-pinned worktree;',
    'do NOT copy any value from this prompt or from any caller-supplied blob. Return exactly the five fields.',
  ].join('\n'), {
    label: `${role}-readback:${issue}`, phase: phaseTitle, schema: FRESH_READS_SCHEMA,
    agentType: 'Explore', effort: 'low',
  })
  if (fresh === null) throw new Error(`${role} live readback returned no result`)
  // Pure readback gate: the caller envelope must agree with the live reads or no spawn.
  assertLaunchReadback(A, fresh)
  // The live git HEAD must equal the exact starting HEAD this pass binds; a stale HEAD
  // recomputed from caller input never spawns.
  required(startingHead, 'starting head')
  if (fresh.git_head !== startingHead) {
    throw new Error('stale envelope: git HEAD disagrees with fresh read')
  }
  return fresh
}

// Launch-revision resolution from the FRESH-read starting HEAD (TUR-447 F3 Unit H;
// role-runtime launch-entrypoint-revalidation). launch_revision is REQUIRED; it is never
// recomputed from a possibly-stale caller A.launch_revision fallback. The loop recomputes
// the revision here from the bound inputs whose starting HEAD was just proven live by
// liveReadback, then asserts the required caller revision equals it, so an omitted or
// stale-derived revision is rejected and only a fresh-derived (or explicitly-required and
// matching) revision admits.
function resolveLaunchRevision(bound) {
  const revision = required(A.launch_revision, 'launch revision')
  assertLaunchRevision(revision, bound)
  return revision
}

// TUR-447 F4b-A Unit I: the reconciler-as-Workflow-subagent spawn path (role-runtime
// role-worker-migration, role-claude-native, role-reconciler-input, role-reconciler-authority,
// role-reconciler-escalation, role-reconciler-bootstrap-snapshot-proof, workspace-cleanup-reconcile;
// operating-model decision-109-workflow-native, decision-109-binding). This is ADDITIVE to the
// live provider-argv sweep gateway (octo_lite.launch prepare_reconcile_launch / run_reconcile_launch),
// which stays alive until sweep-operator-gate migrates operator-sweep to this path.
//
// Unlike a delivery worker, the reconciler is Read-restricted: BOTH the acknowledgment phase and the
// classification phase run under the real read-only subagent type (agentType: 'Explore'), which
// genuinely withholds Edit, Write, and mutating Bash at the runtime, because the reconciler never
// mutates a source. The durable binding is the reconcile journal entry the owning host bound BEFORE
// this spawn through octo_lite.launch bind_reconcile_workflow_journal, which persisted the final
// snapshot.md, bound its path+bytes+digest, wrote NO reconcile TOML receipt, and rejected the retired
// octo-lite-reconcile receipt shape. The host resolves the reconciler runtime and journal facts, spawns
// the ack phase, verifies the snapshot-proof echo against the journal, spawns the classification phase,
// then binds the classification and cleans up the read-only worktree KEYED ON the durable journal entry.
// The loop cannot read files or the network, so each Python-side step (journal bind, ack verify, result
// bind + cleanup) runs inside a spawned subagent that invokes octo_lite.launch and returns its result.
// Only the real agent() opts ({label, phase, schema, model, effort, isolation, agentType}) are passed.
async function spawnReconciler(phaseTitle) {
  const issue = required(A.issue, 'issue')
  const journalPath = required(A.journal_path, 'reconcile journal path')
  const worktreeRoot = required(A.worktree_root, 'worktree root')
  const worktree = assertContainment(worktreeRoot, required(A.worktree, 'reconcile worktree'))
  // Admission: a reconcile purpose admits ONLY role reconciler as a Read-restricted subagent; the
  // Linear-state gate does not apply to a whole-operation reconcile sweep (no single delivery issue).
  assertAdmission({ purpose: 'reconcile', role: 'reconciler', readRestricted: true })
  // Manifest-shape admission over the journal binding the host bound before this spawn.
  assertManifestShape({ shape: 'worker-journal', role: 'reconciler', purpose: 'reconcile', readRestricted: true })
  // Phase 1: read-only acknowledgment spawn. Write tools are withheld (agentType: 'Explore'). The
  // reconciler opens the journal-bound snapshot file, hashes its bytes, and echoes the bound identity
  // plus snapshot path and digest; it returns ONLY the ack.
  assertContainment(worktreeRoot, worktree)
  const ackPrompt = [
    'You are a fresh READ-ONLY octo-lite reconciler in the acknowledgment phase. Write tools are',
    'withheld: you cannot mutate anything, and you must never mutate any source. One pass only.',
    `Read the durable reconcile journal entry at ${journalPath} yourself.`,
    'Open the exact file at the journal-bound reconcile.snapshot_path, hash its bytes, and echo the',
    'bound snapshot_path and the ACTUAL snapshot_digest you computed, plus schema_version, spawn_id,',
    'launch_revision, role "reconciler", worktree, and starting_head from the journal. Set ready true',
    'and empty blocker only when the file exists and its digest matches the journal-bound digest;',
    'otherwise set ready false and a blocker. Return ONLY the ack object.',
  ].join('\n')
  const acknowledged = await agent(ackPrompt, {
    label: `reconciler-ack:${issue}`, phase: phaseTitle, schema: RECONCILE_ACK_SCHEMA, agentType: 'Explore',
  })
  if (acknowledged === null) throw new Error('reconciler read-only ack phase returned no result')
  // Host verifies the snapshot-proof echo against the durable journal binding through the launcher;
  // a missing or digest-mismatched snapshot, or the retired receipt shape, fails closed here. The
  // verifier RETURNS the journal-bound snapshot path and digest it proved, so the classifier is wired
  // to the ACTUAL verified snapshot (TUR-447 cycle1 pass3 reconcile binding, gpt-5.6-sol HIGH).
  const verified = await agent([
    'You are a fresh READ-ONLY octo-lite reconcile ack verifier. One pass; never mutate.',
    'Invoke octo_lite.launch verify_reconcile_workflow_ack with the journal path and the ack below;',
    `journal path: ${journalPath}`,
    'ack:', JSON.stringify(acknowledged.ack ?? acknowledged, null, 2),
    'It returns the verified echo. Return { verified: true, snapshot_path, snapshot_digest } echoing the',
    'journal-bound reconcile.snapshot_path and reconcile.snapshot_digest it verified; a GateError means',
    'fail closed, do not swallow it.',
  ].join('\n'), {
    label: `reconciler-ack-verify:${issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['verified', 'snapshot_path', 'snapshot_digest'],
      properties: {
        verified: { type: 'boolean' },
        snapshot_path: { type: 'string' }, snapshot_digest: { type: 'string' },
      },
    },
    agentType: 'Explore',
  })
  if (verified === null || verified.verified !== true) throw new Error('reconciler ack verification failed')
  const verifiedDigest = required(verified.snapshot_digest, 'verified snapshot digest')
  const verifiedPath = required(verified.snapshot_path, 'verified snapshot path')
  // Phase 2: read-only classification spawn (Sonnet classifies deltas; needs_fable escalates). Still
  // Read-restricted: the reconciler never mutates a source, so this phase also runs under agentType
  // 'Explore'. The classifier is bound to the verified snapshot: it receives the journal path AND the
  // verified snapshot path+digest, opens that exact journal-bound snapshot itself, classifies against
  // it (never blind), and re-echoes the verified ack.
  assertContainment(worktreeRoot, worktree)
  const brief = required(A.brief, 'reconcile brief')
  const classified = await agent([
    'You are a fresh READ-ONLY octo-lite reconciler in the classification phase. Never mutate a source,',
    'never override a deterministic mismatch, never investigate open-endedly, never silently resolve',
    'ambiguity. One pass only. Read the durable reconcile journal entry and the exact journal-bound',
    'verified snapshot yourself; classify against that snapshot, not blind. Classify the journal-bound',
    'normalized snapshot deltas as one of changed, missing, stale, contradictory, unchanged, or',
    'needs_fable. Missing or unparseable input and semantic ambiguity return needs_fable so Fable judges',
    'the case. Re-echo the verified ack object (its snapshot_path and snapshot_digest included) and return',
    'the classification, needs_fable, and the concrete deltas.',
    `journal path: ${journalPath}`,
    `verified snapshot_path: ${verifiedPath}`,
    `verified snapshot_digest: ${verifiedDigest}`,
    `\n${brief}`,
  ].join('\n'), {
    label: `reconciler:${issue}`, phase: phaseTitle, schema: RECONCILE_RESULT_SCHEMA, agentType: 'Explore',
  })
  if (classified === null) throw new Error('reconciler classification phase returned no result')
  // The classification is BOUND to the verified snapshot: the classifier's re-echoed ack must carry the
  // exact journal-bound snapshot digest the host verified, or the classification came from a different
  // (or no) snapshot and fails closed here before any binding. The ack is NOT discarded.
  const classifiedAck = classified.ack ?? {}
  if (String(classifiedAck.snapshot_digest) !== String(verifiedDigest)) {
    throw new Error('reconcile classification not bound to the verified snapshot')
  }
  // Host binds the classification into the durable journal and cleans up the read-only worktree KEYED ON
  // that journal entry (workspace-cleanup-reconcile), through the launcher. It carries the re-echoed ack
  // and the verified snapshot digest so bind_reconcile_workflow_result re-verifies the ack, the enum, the
  // digest, and needs_fable consistency; a vanished/substituted journal or retired receipt shape fails
  // closed and preserves the worktree.
  const bound = await agent([
    'You are a fresh octo-lite reconcile result binder. One pass only.',
    'Invoke octo_lite.launch bind_reconcile_workflow_result with the journal path and the classification',
    'below; it binds the result into the durable journal entry and cleans up the read-only worktree keyed',
    'on that journal entry. It re-verifies the carried ack against the journal and rejects a non-enum',
    'classification, a digest mismatch, a missing ack, or an inconsistent needs_fable flag. Never write a',
    'TOML receipt.',
    `journal path: ${journalPath}`,
    'classification:', JSON.stringify(
      {
        classification: classified.classification, needs_fable: classified.needs_fable,
        deltas: classified.deltas, snapshot_digest: verifiedDigest, ack: classifiedAck,
      },
      null, 2,
    ),
    'Return the bound result it returns.',
  ].join('\n'), {
    label: `reconciler-bind:${issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['bound', 'classification', 'needs_fable'],
      properties: {
        bound: { type: 'boolean' }, classification: { type: 'string' },
        needs_fable: { type: 'boolean' }, deltas: { type: 'array', items: { type: 'string' } },
      },
    },
  })
  if (bound === null || bound.bound !== true) throw new Error('reconcile result binding failed')
  return { classification: bound.classification, needs_fable: bound.needs_fable, deltas: bound.deltas ?? [] }
}

// Shared native spawn path for every worker pass (Unit B, TUR-447 F1): the admission
// matrix plus Linear-state gate, worktree containment, and launch-revision revalidation
// run before any subagent spawns, the journal records the exact bound inputs, and the
// worker binding is proven through an OBSERVABLE read-only acknowledgment phase before
// any mutation-capable spawn exists. The worker first runs in a read-only acknowledgment
// spawn under the real Workflow read-only subagent type (agentType: 'Explore'), which
// genuinely withholds Edit, Write, and mutating Bash at the runtime, and produces ONLY
// the schema-forced ack echo. The host verifies that echo against the journalled bound
// inputs through verifyAckThenUpgrade, and ONLY THEN spawns the write-capable mutation
// phase (the default agentType, which retains write tools). A worker that would mutate
// before verification cannot, because no write-capable spawn is issued until the
// read-only echo verifies. Every pass is a fresh subagent; a worker session is never
// resumed. Only the real agent() opts ({label, phase, schema, model, effort, isolation,
// agentType}) are passed; invented opts are silently ignored at runtime and enforce
// nothing, so they are never used.
async function spawnWorker(role, phaseTitle, startingHead, schema) {
  assertAdmission({ purpose: 'delivery', role, linearState: required(A.linear_state, 'linear state') })
  // Containment at admission (launch-containment).
  const worktree = assertContainment(
    required(A.worktree_root, 'worktree root'),
    required(A.worktree, 'worker worktree'),
  )
  const bound = journalledBoundInputs(role, startingHead)
  // TUR-447 ruling-56 cycle3 slug-identity-bound: the worker-liveness echo (below) reads the live PR
  // via a REPO-PINNED gh (never a cwd-inferred repo) and the live git via git -C the host worktree, so
  // pin the canonical slug and the numeric PR here for that prompt.
  const slug = ghRepoSlug()
  const pr = bound.pr
  // TUR-447 ruling-59 host-trusted identity anchor BEFORE any spawn: validate the envelope against the
  // host-provisioned receipt (Anchor A) AND the live git read of the receipt-pinned worktree (Anchor B),
  // neither derived from the envelope, so a foreign-but-well-formed envelope (or a matching path on a
  // foreign branch/remote) is rejected before any subagent spawns.
  await hostTrustedIdentity(role, phaseTitle)
  // Live readback immediately before spawn (launch-readback, TUR-447 F3): a fresh
  // read-only Explore subagent performs the live Linear/PR/branch/HEAD reads and the pure
  // readback gate rejects a stale self-consistent caller envelope. No caller fresh_reads
  // blob is trusted.
  await liveReadback(role, phaseTitle, startingHead, worktree)
  // Launch-revision revalidation before spawn (launch-entrypoint-revalidation): the
  // revision is REQUIRED and revalidated against the bound inputs whose HEAD was just
  // proven live; it is never recomputed from a stale caller fallback.
  const revision = resolveLaunchRevision(bound)
  log(`journal spawn ${role} ${bound.issue} ${bound.pr} ${bound.starting_head} ${bound.contract_hash} ${revision}`)
  const brief = required(A.brief, 'pass brief')
  // TUR-447 cycle1 pass2 F2c (role-runtime role-machine-map, role-worker-migration): resolve
  // the native worker runtime FROM roles.toml through the role resolver, not a hardcoded or
  // generic spawn. The mutation phase runs under the resolved model and effort, and the
  // resolved canonical contract text is carried into the worker prompt.
  const runtime = await resolveRuntime(role, phaseTitle, worktree, WORKER_RUNTIME_SCHEMA, bound.issue)
  // Containment again at each child subagent spawn (launch-containment).
  assertContainment(A.worktree_root, worktree)
  // Phase 1: read-only acknowledgment spawn under the real read-only subagent type
  // (agentType: 'Explore'), which genuinely withholds Edit, Write, and mutating Bash at
  // the runtime, so the worker physically cannot mutate; it returns ONLY the
  // schema-forced ack echo of the exact bound inputs. This is the observable pre-mutation
  // boundary.
  const ackAgentType = 'Explore'
  const ackPrompt = [
    `You are a fresh octo-lite ${role} in the read-only acknowledgment phase. Write tools`,
    'are withheld: you cannot mutate anything now. One pass only; never reuse a session.',
    'BOUND INPUTS: verify each against your own reads and echo them verbatim as the ack',
    'object in your structured result. Return ONLY the ack; do not attempt any change:',
    JSON.stringify(bound, null, 2),
  ].join('\n\n')
  const acknowledged = await agent(ackPrompt, {
    label: `${role}-ack:${bound.issue}`, phase: phaseTitle, schema: ACK_ONLY_SCHEMA,
    agentType: ackAgentType,
  })
  if (acknowledged === null) throw new Error(`${role} read-only ack phase returned no result`)
  // Host verifies the read-only echo against the journalled bound inputs and only then
  // authorizes the write-capable phase. The gate rejects any non-read-only ack agentType,
  // so the phase must have genuinely withheld write tools. A role, repo, issue, or PR
  // substitution blocks here exactly as a HEAD mismatch does.
  verifyAckThenUpgrade(bound, { agentType: ackAgentType, ack: acknowledged.ack })
  // Launch-revision revalidation again before the mutation-phase advance.
  assertLaunchRevision(revision, bound)
  // Phase 2: write-capable mutation spawn, reached ONLY after the echo verified. It uses
  // the default subagent type (no agentType), which retains write tools; a read-only
  // agentType is NOT passed here.
  assertContainment(A.worktree_root, worktree)
  const prompt = [
    `You are a fresh octo-lite ${role}. One pass only. Never reuse a worker session.`,
    'CANONICAL ROLE CONTRACT (resolved from roles.toml; follow it exactly):',
    runtime.contract_text,
    `RESOLVED SKILLS (load these): ${JSON.stringify(runtime.skills)}`,
    'BOUND INPUTS: verify each against your own reads, echo them verbatim as the ack',
    'object in your structured result, and stop before any mutation on any mismatch:',
    JSON.stringify(bound, null, 2),
    // TUR-447 D1 reshaped delivery loop (delivery-lifecycle delivery-tdd-committed-red,
    // delivery-tdd-committed-green, delivery-tdd-test-identity-binding): COMMIT a real failing red
    // then a GREEN commit on the isolated delivery branch. A missing file, module, export, or script
    // is NOT a valid red; the red must be a new or changed test that genuinely fails plus unchanged
    // production.
    'DELIVERY TDD (COMMITTED): on the isolated delivery branch, first COMMIT a real failing red: a new',
    'or changed spec-derived test that GENUINELY FAILS the named test, plus UNCHANGED production. A',
    'missing file, module, export, or script is not a valid red. Report red.exit_status nonzero, a',
    'scenario name, and red_commit as that durable commit id. Then COMMIT the GREEN: a PRODUCTION-ONLY',
    'change that makes the SAME named test pass, never editing the bound test. Report green.exit_status',
    'zero, the identical scenario name, and green_commit as that commit id. Report final_commit as the',
    'final HEAD after any later refactor commit (equal to green_commit if none). Bind the failing test',
    'by path and content digest in bound_test {path, digest}, unchanged across red, green, and final.',
    // TUR-447 D1 host-gated push (role-implementer-host-gated-push): the worker COMMITS but NEVER
    // pushes. The host pushes the verified branch only after the independent observer confirmation.
    'HOST-GATED PUSH: COMMIT the red and green on the isolated delivery branch, but do NOT git push.',
    'Set committed:true and pushed:false. Set head to your final delivered commit (final_commit). The',
    'host records your committed branch and red/green/final commit ids in the journal, spawns the',
    'independent tdd-observer to re-run those committed states in an isolated worktree, and pushes only',
    'after the observer confirms red-fail, green-pass, and a green final HEAD with the bound test',
    'unchanged; on ANY rejection the host abandons your unpushed branch and does NOT reset your commits.',
    // TUR-447 cycle2 pass1 stale-read race: echo the liveness fields you read so the host can
    // detect a live change during the intervening passes before it pushes.
    // TUR-447 ruling-55 canonical fingerprint source: the echoed linear_fingerprint MUST come from
    // scripts/octo-control linear-read (its returned fingerprint field verbatim), NEVER improvised or
    // self-hashed, so the host reconciles the echo against the octo-control linear-read-sourced envelope.
    'LIVENESS ECHO: read the live Linear state of the issue yourself, and read the live PR branch with a',
    // TUR-447 ruling-56 cycle3 slug-identity-bound: the PR read is REPO-PINNED to the canonical slug (the
    // PR NUMBER + --repo ${slug}), never a cwd-inferred repo, and the git read is pinned to the host issue
    // worktree via git -C ${worktree}; do NOT rely on the ambient current working directory (a foreign
    // lane worktree on a shared box).
    `REPO-PINNED gh (\`gh pr view ${pr} --repo ${slug} --json headRefName\`); do NOT rely on the current`,
    `working directory to infer the repo. Confirm the host git HEAD with \`git -C ${worktree} rev-parse HEAD\`,`,
    `operating ONLY on the host-pinned worktree at ${worktree}, not the ambient cwd. Obtain`,
    `the live Linear content fingerprint by running scripts/octo-control linear-read ${bound.issue} and`,
    'using ITS returned fingerprint field verbatim (do NOT improvise or self-hash it). Echo them as',
    'linear_state, linear_fingerprint, and branch in your result.',
    brief,
  ].join('\n\n')
  // The mutation spawn runs under the resolved model and effort from roles.toml; only the real
  // agent() opts are passed (label, phase, schema, model, effort).
  const result = await agent(prompt, {
    label: `${role}:${bound.issue}`, phase: phaseTitle, schema,
    model: runtime.model, effort: runtime.effort,
  })
  if (result === null) throw new Error(`${role} pass returned no result`)
  // TUR-447 F1 fix (role-runtime launch-identity, launch-receipt; operating-model
  // decision-109-binding; workspace-cleanup). agent() is atomic with no mid-turn host
  // gate, so the write-capable worker may already have mutated the worktree by the time
  // it returns. The achievable pre-acceptance boundary: the mutating worker's bound-input
  // echo is verified against the SAME journalled inputs the read-only ack phase bound,
  // and on ANY mismatch its output is REJECTED and the worktree changes are DISCARDED
  // through a workspace-cleanup spawn, so no mutation under an unverified or mismatched
  // identity is ever ACCEPTED (nothing is committed or pushed). Only a matching echo is
  // accepted. A HEAD, role, repo, issue, or PR substitution rejects here exactly as the
  // read-only ack gate would.
  await acceptWorkerEchoOrDiscard(role, phaseTitle, bound, result, worktree)
  // Launch-revision revalidation again before any mutation-phase advance.
  assertLaunchRevision(revision, bound)
  return result
}

// TUR-447 F1 / D1: verify the mutating worker's echo against the journalled bound inputs and, on ANY
// mismatch, DISCARD the unverified work so no mutation under an unverified identity is accepted. The
// discard mode depends on the worker model (role-runtime workspace-cleanup-committed-not-dirty,
// workspace-cleanup-rejected-unpushed): a COMMITTED delivery worker (implementer, committed:true) left
// durable commits on an ISOLATED unpushed branch, which is NOT dirty, so the correct abort is to ABANDON
// the unpushed branch, never a destructive reset of committed work the host never pushed; a genuinely
// dirty or diverged worktree still STOPS for inspection. A non-committing worker (qa-capture) that left
// an uncommitted working-tree change is reset to the starting HEAD. The loop cannot touch the filesystem,
// so the abort runs in a spawned subagent, then this rethrows so no result advances.
async function acceptWorkerEchoOrDiscard(role, phaseTitle, bound, result, worktree) {
  let echoError = null
  try {
    assertWorkerAckEcho(bound, result.ack)
  } catch (error) {
    echoError = error
  }
  if (echoError === null) return result
  if (result.committed === true) {
    await abandonUnpushedBranchOrStop(`${role} echo mismatch`, phaseTitle, bound, result, worktree)
  } else {
    await resetWorktreeOrThrow(`${role} echo mismatch`, phaseTitle, bound, worktree)
  }
  throw echoError
}

// TUR-447 D1 host-non-push abort for committed delivery work (role-runtime
// workspace-cleanup-committed-not-dirty, workspace-cleanup-rejected-unpushed, workspace-cleanup-dirty-still-stops;
// delivery-lifecycle delivery-tdd-host-gated-push-reject). On ANY rejection of a committed delivery pass, the
// host ABANDONS the unpushed isolated delivery branch: it does NOT push it, and it does NOT destructively reset
// the committed work (a durable commit on an isolated branch with an unchanged worktree has zero dirty lines,
// so reset is the wrong tool). A genuinely dirty or diverged worktree still STOPS for inspection rather than
// being silently discarded. The loop cannot touch git, so a subagent verifies the branch is unpushed and the
// worktree is clean at the committed HEAD, then leaves the branch in place unpushed.
async function abandonUnpushedBranchOrStop(reason, phaseTitle, bound, result, worktree) {
  const branch = required(A.branch, 'branch')
  const finalCommit = result.final_commit ?? result.head
  // TUR-447 ruling-56 cycle2 repo pin (obligation 4): the remote-verify read is pinned to the host
  // worktree (git -C ls-remote) or the canonical slug (gh api repos/<slug>/), never a cwd-inferred repo.
  const slug = ghRepoSlug()
  const abandoned = await agent([
    `You are a fresh octo-lite host-non-push abort subagent for a REJECTED committed ${bound.role} pass (${reason}).`,
    'One pass only; NEVER push. The worker committed the red then green on the ISOLATED delivery branch and the',
    'host rejected the pass, so the branch must be ABANDONED UNPUSHED: do NOT push it, and do NOT destructively',
    'reset the committed work (committed work on an isolated branch is not dirty). Only VERIFY and report:',
    `  worktree: ${worktree}`,
    `  isolated_branch: ${branch}`,
    `  committed_head: ${finalCommit}`,
    // TUR-447 ruling-56 host cwd pin: this abort subagent runs in an AMBIENT cwd that on the shared box is
    // a FOREIGN lane worktree; pin every git op to the host issue worktree via git -C, never the ambient cwd.
    `Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    'it may be a foreign lane worktree on a shared box.',
    `Confirm the branch is NOT pushed: read the live remote with \`git -C ${worktree} ls-remote origin ${branch}\``,
    `(or the repo-pinned \`gh api repos/${slug}/git/ref/heads/${branch}\`, which 404s when absent); its commits`,
    'must be ABSENT from the remote. Never infer the repo from the ambient cwd. Then read back the worktree',
    `HEAD (\`git -C ${worktree} rev-parse HEAD\`) and \`git -C ${worktree} status --porcelain\`. If the worktree is`,
    'clean at the committed HEAD, leave the branch in place unpushed and return abandoned:true, pushed:false,',
    'dirty:false with the head and status. If the',
    'worktree is genuinely DIRTY or DIVERGED, do NOT discard it: return abandoned:false, dirty:true so the',
    'host STOPS for inspection.',
  ].join('\n'), {
    label: `workspace-abandon:${bound.issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['abandoned', 'pushed', 'dirty', 'head', 'status'],
      properties: {
        abandoned: { type: 'boolean' }, pushed: { type: 'boolean' }, dirty: { type: 'boolean' },
        head: { type: 'string' }, status: { type: 'string' },
      },
    },
  })
  if (abandoned === null) throw new Error(`committed branch abandon failed: no result (${reason})`)
  if (abandoned.pushed === true) {
    throw new Error(`rejected committed pass must not be pushed (${reason})`)
  }
  if (abandoned.dirty === true || abandoned.abandoned !== true) {
    // A dirty or diverged worktree stops for inspection rather than being silently discarded.
    throw new Error(`rejected committed pass stopped for inspection: dirty or diverged worktree (${reason})`)
  }
}

// TUR-447 rejected-mutation cleanup for NON-committing workers (role-runtime workspace-cleanup).
// A worker that left an uncommitted working-tree change (qa-capture) is reset to the unchanged starting
// HEAD and every uncommitted change cleared before the rejection propagates. This is NOT used for a
// committed delivery pass, whose isolated branch is abandoned unpushed instead.
async function resetWorktreeOrThrow(reason, phaseTitle, bound, worktree) {
  const cleaned = await agent([
    `You are a fresh octo-lite workspace-cleanup subagent for a REJECTED pass (${reason}). One pass only.`,
    'The host rejected this pass, so its uncommitted mutation must be DISCARDED and nothing committed or',
    'pushed. In the host-pinned issue worktree below, reset the working tree to the exact bound starting HEAD',
    'and clear every uncommitted change:',
    `  worktree: ${worktree}`,
    `  starting_head: ${bound.starting_head}`,
    // TUR-447 ruling-56 host cwd pin: pin every git op to the host issue worktree via git -C, never the
    // ambient cwd (a foreign lane worktree on a shared box).
    `Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    'it may be a foreign lane worktree on a shared box.',
    `Run the reset (\`git -C ${worktree} reset --hard\` to the starting HEAD and \`git -C ${worktree} clean\` of`,
    `untracked changes), then read back and return the resulting HEAD (\`git -C ${worktree} rev-parse HEAD\`) and`,
    `\`git -C ${worktree} status --porcelain\` (empty status proves a clean tree).`,
  ].join('\n'), {
    label: `workspace-cleanup:${bound.issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['cleaned', 'head', 'status'],
      properties: { cleaned: { type: 'boolean' }, head: { type: 'string' }, status: { type: 'string' } },
    },
  })
  if (cleaned === null || cleaned.cleaned !== true || cleaned.head !== bound.starting_head || cleaned.status !== '') {
    throw new Error(`rejected mutation discard failed: worktree not clean at starting HEAD (${reason})`)
  }
}

// TUR-447 D1 cycle3 independent git read of the committed delivery branch (delivery-lifecycle
// delivery-tdd-observer-inputs-host-sourced, delivery-tdd-observer-inputs-host-journal-record,
// delivery-tdd-committed-red-commit, delivery-tdd-test-identity-binding; role-runtime role-tdd-observer,
// role-tdd-observer-host-sourced-inputs). Spawn a HOST-CONTROLLED, Read-restricted, Bash-CAPABLE subagent
// (NOT agentType 'Explore', which is read-only and cannot create a worktree, check out a commit, or run a
// test) in an isolated git worktree (opts.isolation: 'worktree'), DISTINCT from the mutating worker. It is
// given ONLY the committed BRANCH name, the exact bound EXPECTED STARTING HEAD, and the host-sourced
// canonical validation command; it is NEVER told the worker's claimed shas, path, or digest. It performs
// the independent git read over its isolated worktree, which DISCOVERS the bound test from the RED commit's
// diff (the single test file the red commit
// changed IS the bound test) and hashes it from actual git blob content, reads the ACTUAL red/green/final
// shas + ancestry + diff kinds + named-test exits, and returns them. assertIndependentGitRead verifies all
// of that and returns the DISCOVERED bound test; no worker string is ever interpolated here, so the trust
// root cannot be pointed at a forged commit or relabelled to a worker-named test.
async function independentGitRead(role, phaseTitle, bound, branch, expectedStartingHead) {
  const command = required(A.validation_command, 'canonical validation command from target AGENTS.md')
  const read = await agent([
    `You are a fresh HOST-CONTROLLED, Read-restricted, Bash-capable octo-lite git reader for the ${role}`,
    'pass. You run in your OWN ISOLATED git worktree; you are DISTINCT from the mutating worker and you NEVER',
    'push, reset, or mutate any source, branch, or the live repository working directory. One pass only. You',
    'are the INDEPENDENT trust root: you are given ONLY the committed branch name, the expected starting HEAD,',
    'and the host-sourced validation command below, NOT any worker-claimed sha, test path, or digest. Read',
    'every sha, diff, and digest YOURSELF from git; never accept one from a worker claim.',
    `COMMITTED delivery BRANCH to read: ${branch}`,
    `EXPECTED starting HEAD the branch must be rooted at: ${expectedStartingHead}`,
    `HOST-SOURCED canonical validation command (run EXACTLY this per commit, from the target AGENTS.md): ${command}`,
    'In your isolated worktree, perform the independent git read exactly as follows (assertIndependentGitRead',
    'inside deliverCommittedPass validates every field you return; the delivery TDD tests drive that seam):',
    '- base_head: the branch base (must be the expected starting HEAD above).',
    '- ancestry: `git rev-list --reverse <expectedStartingHead>..<branch>`, the ordered red -> ... -> final',
    '  chain (red first, final last), proving a LINEAR history rooted at base_head.',
    '- red_commit = ancestry[0]: its diff MUST change exactly one TEST file and no production file',
    '  (test-only). DISCOVER the bound test from that red diff yourself; the worker never names it. Check the',
    '  red out, run the command, record red_named_test_exit; it MUST be a genuine NONZERO (the discovered',
    '  bound test FAILS). A missing file/module/export/script is NOT a valid red.',
    '- green_commit = ancestry[1]: its diff must be PRODUCTION-ONLY (it never edits the discovered bound',
    '  test). Check it out, run the command; green_named_test_exit MUST be 0 (the same bound test PASSES).',
    '- final_commit = ancestry[last]: check it out, run the command; final_named_test_exit MUST be 0.',
    '- red_test/green_test/final_test: the DISCOVERED bound test file identity {path, digest}, where digest is',
    '  sha256 over the ACTUAL checked-out bytes of that file at each of the red, green, and final commits; it',
    '  must be present unchanged by the same path and content digest.',
    `Return source "${INDEPENDENT_GIT_READ_SOURCE}", read_by (your own subagent identity), the isolated`,
    'worktree path, the branch, base_head, red_commit/green_commit/final_commit, ancestry, the diff kinds, the',
    'three named-test exits, and the three discovered bound-test identities, all as you actually read them.',
    'Report honestly; never fabricate a sha, a diff kind, a passing or failing status, or a digest.',
  ].join('\n'), {
    label: `${role}-git-read:${bound.issue}`, phase: phaseTitle, schema: INDEPENDENT_GIT_READ_SCHEMA,
    isolation: 'worktree',
  })
  if (read === null) throw new Error(`${role} independent git read returned no result`)
  return assertIndependentGitRead(read, { branch, expectedStartingHead })
}

// TUR-447 D1 cycle2 host journal binding from the INDEPENDENT git read (delivery-lifecycle
// delivery-tdd-observer-inputs-host-journal-record; role-runtime role-tdd-observer-host-sourced-inputs).
// The HOST records the committed branch, the red/green/final commit ids the INDEPENDENT git reader read
// from git (never a raw worker claim), and the canonical validation command from the target AGENTS.md in
// the journal binding. assertHostJournalledCommits binds that record as the trust root: the commit ids are
// exactly the independent-read shas (already cross-checked against the worker claim) and the command is the
// host-sourced canonical command, never worker-authored. The resulting binding is the SOLE source of the
// observer's execution inputs.
function hostJournalCommits(trustRoot, command) {
  const branch = required(A.branch, 'branch')
  const binding = assertHostJournalledCommits(
    {
      branch,
      red_commit: trustRoot.redCommit,
      green_commit: trustRoot.greenCommit,
      final_commit: trustRoot.finalCommit,
      command,
    },
    trustRoot, command, branch,
  )
  log(`journal committed-branch ${branch} red ${binding.red_commit} green ${binding.green_commit} final ${binding.final_commit} (independent git read)`)
  return binding
}

// TUR-447 D1 independent observer replay of the committed states (delivery-lifecycle
// delivery-tdd-independent-observer, delivery-tdd-independent-observer-isolated,
// delivery-tdd-trusted-command-source, delivery-tdd-observer-inputs-host-sourced,
// delivery-tdd-final-head-verification, delivery-tdd-final-head-test-identity,
// delivery-tdd-no-forgeable-attestation; role-runtime role-tdd-observer, role-tdd-observer-trusted-source,
// role-tdd-observer-host-sourced-inputs). Spawn the dedicated Read-restricted, Bash-CAPABLE tdd-observer
// (NOT agentType 'Explore', which is read-only and cannot create a worktree, check out a commit, or run a
// test) in an isolated git worktree (opts.isolation: 'worktree'), DISTINCT from the mutating worker. Its
// execution inputs come ONLY from the HOST JOURNAL binding: the red, green, and final commit ids to check
// out AND the host-sourced canonical validation command. No worker-supplied command, path, digest, or
// scenario string is interpolated into the observer prompt, so independence cannot be forged. The observer
// checks out EACH host-journalled commit and the final HEAD in its isolated worktree (never the worker
// branch, main, or the live repo dir), runs the host-trusted command, DISCOVERS the bound test from the red
// commit's diff itself and hashes it from git blob content at each commit, and reports the exact commits it
// checked out, the command it ran, red/green/final exit + output, and the bound-test identity it observed.
// The host consumes assertObservedCommittedStates over THIS against the independently DISCOVERED bound test
// (host-sourced, never a worker string).
async function observeCommittedStates(role, phaseTitle, bound, binding) {
  const observation = await agent([
    `You are a fresh Read-restricted, Bash-capable octo-lite tdd-observer for the ${role} pass. You run in`,
    'your OWN ISOLATED git worktree; you are DISTINCT from the mutating worker and you NEVER mutate a source,',
    'push, or reset. One pass only. Your execution inputs are HOST-JOURNALLED below; use ONLY these, never any',
    'worker-authored commit id, command, path, digest, or scenario string.',
    'Check out EACH host-journalled commit and the final HEAD in your isolated worktree. Derive your test',
    'invocation ONLY from the committed test files and the host-supplied canonical validation command below.',
    `HOST-JOURNALLED RED commit (must FAIL the bound test): ${binding.red_commit}`,
    `HOST-JOURNALLED GREEN commit (must PASS the same bound test): ${binding.green_commit}`,
    `HOST-JOURNALLED FINAL HEAD (after any refactor; must PASS): ${binding.final_commit}`,
    `HOST-SOURCED canonical validation command (run EXACTLY this, from the target AGENTS.md): ${binding.command}`,
    "DISCOVER the bound test yourself from the red commit's diff (the single test file the red commit changed",
    'IS the bound test); the worker never names it. For each of the red, green, and final commit: check it out',
    'in your isolated worktree, run the command, and record the exit status and captured output. Also record',
    'the discovered bound test file identity you observe at that commit as {path, digest}, where digest is',
    'sha256 over the actual checked-out bytes: it must be present unchanged by the same path and content',
    'digest. A green or final HEAD that removes, weakens, or edits the bound test is a rejection even if tests',
    'pass.',
    `Return source "${INDEPENDENT_OBSERVER_SOURCE}", observed_by (your own subagent identity), the`,
    'isolated_worktree path you used, the command you ran, and red_commit/red_exit/red_output/red_test,',
    'green_commit/green_exit/green_output/green_test, final_commit/final_exit/final_output/final_test as you',
    'actually observed them. Report honestly; never fabricate a passing or failing status.',
  ].join('\n'), {
    label: `${role}-tdd-observer:${bound.issue}`, phase: phaseTitle, schema: OBSERVATION_SCHEMA,
    isolation: 'worktree',
  })
  if (observation === null) throw new Error(`${role} independent observer replay returned no result`)
  return observation
}

// TUR-447 D1 host-gated push of the verified committed branch (delivery-lifecycle
// delivery-tdd-host-gated-push, delivery-tdd-host-gated-push-reject, delivery-tdd-final-head-verification;
// role-runtime launch-identity-delivery-branch, launch-readback). Run ONLY after the worker's committed
// result is accepted, the host journalled its commits, and the independent observer confirmed the red
// fail, the green pass, the final-HEAD green, and the bound-test identity at every committed state. In
// order it: (1) verifies the worker's liveness echo against the bound (post-fire reconciled) ground
// truth; (2) takes a FRESH pre-push readback immediately before the push, rejecting if the live Linear
// state, fingerprint, PR head, branch, or the committed final HEAD changed since bind; (3) pushes the
// already-committed isolated branch (no new commit is authored: the worker's commits are pushed as-is);
// and (4) confirms the pushed HEAD by a LIVE REMOTE read (gh api or git ls-remote), never a local
// tracking ref. On ANY rejection in this flow the isolated branch is ABANDONED UNPUSHED with no
// destructive reset; a dirty or diverged worktree stops for inspection.
async function hostGatedPushCommittedBranch(role, phaseTitle, envelope, bound, result, binding, worktree) {
  const finalCommit = binding.final_commit
  // (1) The worker echoed the liveness fields it read; they must equal the bound ground truth. On a
  // mismatch, abandon the unpushed branch before rethrowing.
  try {
    assertWorkerLivenessEcho(envelope, result)
  } catch (error) {
    await abandonUnpushedBranchOrStop(`${role} liveness echo mismatch`, phaseTitle, bound, result, worktree)
    throw error
  }
  // (2) Fresh pre-push readback immediately before the push. The bound git HEAD is the committed final
  // HEAD (the worker committed on the isolated branch), not the starting HEAD.
  const issue = required(A.issue, 'issue')
  const pr = required(A.pr, 'pr')
  const branch = required(A.branch, 'branch')
  // TUR-447 ruling-56 cycle2 gh repo pin: the gh reads below are pinned to the canonical slug, never
  // inferred from the ambient (foreign lane) cwd.
  const slug = ghRepoSlug()
  const freshAfter = await agent([
    `You are a fresh READ-ONLY octo-lite pre-push readback subagent for the ${role} pass. One pass;`,
    'never mutate. Perform LIVE reads NOW, immediately before the host pushes the committed branch, and',
    'return them so the host can reject a live change since bind:',
    `- linear_state: the live Linear state of ${issue}.`,
    // TUR-447 ruling-55 canonical fingerprint source: linear_fingerprint MUST be the octo-control
    // linear-read exact_fingerprint (the same source as the envelope), NEVER improvised or self-hashed.
    `- linear_fingerprint: run scripts/octo-control linear-read ${issue} and use ITS returned`,
    '  fingerprint field verbatim. Do NOT improvise, recompute, or self-hash the fingerprint.',
    `- pr_head: the live PR head oid (\`gh pr view ${pr} --repo ${slug} --json headRefOid\`).`,
    `  The gh read is REPO-PINNED to ${slug}; never let gh infer the repo from the current working directory.`,
    `- branch: the live head branch of the PR (\`gh pr view ${pr} --repo ${slug} --json headRefName\`, expected ${branch}).`,
    `- git_head: the live git HEAD of the host issue worktree, read via \`git -C ${worktree} rev-parse HEAD\``,
    `  (expected the committed final HEAD ${finalCommit}).`,
    `  Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    '  it may be a foreign lane worktree on a shared box.',
    'Read state, pr_head, branch, and git_head yourself; do NOT copy any value from this prompt or a caller blob.',
  ].join('\n'), {
    label: `${role}-prepush-readback:${issue}`, phase: phaseTitle, schema: FRESH_READS_SCHEMA,
    agentType: 'Explore', effort: 'low',
  })
  if (freshAfter === null) {
    await abandonUnpushedBranchOrStop(`${role} pre-push readback missing`, phaseTitle, bound, result, worktree)
    throw new Error(`${role} pre-push readback returned no result`)
  }
  try {
    assertPrePushReadback(
      {
        linear_state: envelope.linear_state, linear_fingerprint: envelope.linear_fingerprint,
        pr_head: envelope.pr_head, branch: envelope.branch, git_head: finalCommit,
      },
      freshAfter,
    )
  } catch (error) {
    await abandonUnpushedBranchOrStop(`${role} pre-push stale race`, phaseTitle, bound, result, worktree)
    throw error
  }
  // (3) Only now: the host pushes the already-committed isolated branch. No new commit is authored; the
  // worker's committed red/green/final are pushed as-is.
  assertContainment(A.worktree_root, worktree)
  const pushed = await agent([
    `You are a fresh octo-lite host push subagent for a VERIFIED committed ${role} pass. One pass only.`,
    'The worker already COMMITTED the red then green on the isolated delivery branch; the independent',
    'observer confirmed the red fail, the green pass, and the green final HEAD, and the pre-push readback',
    'passed. PUSH the already-committed isolated branch as-is. Do NOT author a new commit, amend, or rebase.',
    `  worktree: ${worktree}`,
    `  branch: ${branch}`,
    `  committed_final_head: ${finalCommit}`,
    `Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    'it may be a foreign lane worktree on a shared box.',
    // TUR-447 ruling-56 cycle2 push pin (obligation 4): the PUSH command itself is pinned to the host
    // issue worktree via git -C, so it never pushes the ambient (foreign lane) cwd's branch.
    `PUSH the pinned worktree's branch with \`git -C ${worktree} push origin ${branch}\`; do not run an unpinned push.`,
    `Return pushed:true and the pushed head (\`git -C ${worktree} rev-parse HEAD\`, which must equal the committed final HEAD).`,
  ].join('\n'), {
    label: `host-push:${bound.issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['pushed', 'head'],
      properties: { pushed: { type: 'boolean' }, head: { type: 'string' } },
    },
  })
  if (pushed === null || pushed.pushed !== true) {
    throw new Error(`${role} host push failed: nothing pushed`)
  }
  if (pushed.head !== finalCommit) {
    throw new Error(`${role} host push head is not the verified committed final HEAD`)
  }
  // (4) Live-remote push readback: the pushed HEAD is confirmed by a LIVE REMOTE read (gh api or git
  // ls-remote), NEVER a local tracking ref. A SEPARATE read-only Explore subagent performs the live
  // remote read and stamps its source; assertLiveRemotePushReadback rejects a local-tracking-ref source
  // or a remote head that differs from the verified committed final HEAD.
  const readback = await agent([
    `You are a fresh READ-ONLY octo-lite post-push live-remote readback subagent for the ${role} pass.`,
    'One pass; never mutate. The host just pushed the committed branch. Confirm the pushed HEAD by a LIVE',
    'REMOTE read, NOT a local tracking ref:',
    `- remote_head: the live pushed head oid on remote branch ${branch}, read via a REPO-PINNED`,
    `  \`gh api repos/${slug}/git/ref/heads/${branch}\` (the repo-bound REST endpoint) or`,
    `  \`git -C ${worktree} ls-remote origin ${branch}\`; do NOT read a local remote-tracking ref.`,
    '- remote_source: "gh-api" if you used gh api, or "git-ls-remote" if you used git ls-remote.',
    // TUR-447 ruling-56 cycle2 repo pin (obligation 1): the REST call hits the repo-bound
    // repos/<slug>/ endpoint, never inferring the repo from cwd; any git ls-remote runs against the
    // host issue worktree via git -C, never the ambient cwd.
    `Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    'it may be a foreign lane worktree on a shared box. Read it yourself from the live remote; do NOT copy any',
    'value from this prompt or the push subagent.',
  ].join('\n'), {
    label: `${role}-postpush-readback:${bound.issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['remote_head', 'remote_source'],
      properties: { remote_head: { type: 'string' }, remote_source: { type: 'string' } },
    },
    agentType: 'Explore', effort: 'low',
  })
  if (readback === null) throw new Error(`${role} post-push live-remote readback returned no result`)
  assertLiveRemotePushReadback(readback, finalCommit)
  return finalCommit
}

// TUR-447 D1 cycle2 committed delivery pass orchestration (delivery-lifecycle delivery-tdd-committed-red,
// delivery-tdd-committed-green, delivery-tdd-independent-observer, delivery-tdd-observer-inputs-host-sourced,
// delivery-tdd-observer-inputs-host-journal-record, delivery-tdd-final-head-verification,
// delivery-tdd-host-gated-push, delivery-tdd-host-gated-push-reject; role-runtime role-implementer-host-gated-push,
// role-tdd-observer, role-tdd-observer-host-sourced-inputs, launch-identity-delivery-branch). The single
// reshaped delivery flow shared by implement and fix modes. In order:
//   (1) accept the worker's COMMITTED red/green/final commit ids and bound-test identity
//       (assertCommittedImplementation), rejecting a worker that did not commit, pushed, or collapsed the
//       red and green;
//   (2) establish the TRUST ROOT by an INDEPENDENT git read (independentGitRead): a host-controlled
//       Read-restricted, Bash-capable subagent in an isolated worktree, given ONLY the branch name and the
//       expected starting HEAD (never the worker's claimed shas, path, or digest), reads the ACTUAL
//       red/green/final shas from git, DISCOVERS the bound test from the red commit's diff and hashes it from
//       git blob content, and verifies test-only red (fails), production-only green (passes), passing final
//       HEAD, the discovered bound-test identity unchanged at each, and a linear red->green->final ancestry;
//   (3) CROSS-CHECK the worker's claimed shas (assertWorkerClaimCrossCheck) AND its claimed bound-test path +
//       digest (assertWorkerBoundTestCrossCheck) against the independently read/discovered ones: any mismatch
//       is rejected, so the worker cannot point the observer at a forged commit or relabel the bound test;
//   (4) the HOST journals the branch, the INDEPENDENT-READ commit ids, and the canonical validation command
//       from the target AGENTS.md (hostJournalCommits), the trust root the observer executes from;
//   (5) spawn the independent Read-restricted tdd-observer to RE-RUN each host-journalled committed state and
//       the final HEAD in an isolated worktree with the host-journalled commits + host-sourced command only
//       (observeCommittedStates);
//   (6) consume the observer replay, not any worker string (assertObservedCommittedStates): red fail, green
//       pass, final-HEAD green, bound-test identity present unchanged at each;
//   (7) the host pushes the verified committed branch and confirms the pushed HEAD by a LIVE REMOTE read
//       (hostGatedPushCommittedBranch).
// On ANY rejection the isolated branch is ABANDONED UNPUSHED with no destructive reset; a dirty or diverged
// worktree stops for inspection. The canonical validation command is a REQUIRED host-sourced input, never
// worker-authored.
async function deliverCommittedPass(role, phaseTitle, startingHead, bound, implementation, worktree) {
  const command = required(A.validation_command, 'canonical validation command from target AGENTS.md')
  const branch = required(A.branch, 'branch')
  // (1) Accept the committed worker result (no worker-authored observation is trusted here).
  let acceptedCommits
  try {
    acceptedCommits = assertCommittedImplementation(startingHead, implementation)
  } catch (error) {
    await abandonUnpushedBranchOrStop(`${role} committed result rejected`, phaseTitle, bound, implementation, worktree)
    throw error
  }
  // (2) INDEPENDENT git read establishes the trust root shas AND the DISCOVERED bound test from git itself
  //     (never a worker claim, path, or digest), then (3) cross-check the worker's claimed shas AND its
  //     claimed bound-test {path, digest} against the independently discovered ones. A forged/cherry-picked
  //     worker sha or a relabelled/mis-digested worker bound test is rejected here before any journal
  //     binding. The bound-test identity the host uses downstream is the INDEPENDENTLY DISCOVERED one.
  let trustRoot
  let boundTest
  try {
    const independentRead = await independentGitRead(role, phaseTitle, bound, branch, startingHead)
    trustRoot = assertWorkerClaimCrossCheck(independentRead, acceptedCommits)
    boundTest = assertWorkerBoundTestCrossCheck(independentRead, acceptedCommits.boundTest)
  } catch (error) {
    await abandonUnpushedBranchOrStop(`${role} independent git read / cross-check rejection`, phaseTitle, bound, implementation, worktree)
    throw error
  }
  // (4) Host journals the branch + the INDEPENDENT-READ commit ids + host-sourced validation command.
  const binding = hostJournalCommits(trustRoot, command)
  // (5) Independent observer RE-RUNS the host-journalled committed states in an isolated worktree.
  const observation = await observeCommittedStates(role, phaseTitle, bound, binding)
  // (6) Consume the observer replay, not any worker string, against the independently discovered bound test.
  //     On rejection, abandon the unpushed branch.
  try {
    assertObservedCommittedStates(observation, binding, boundTest)
  } catch (error) {
    await abandonUnpushedBranchOrStop(`${role} observer replay rejection`, phaseTitle, bound, implementation, worktree)
    throw error
  }
  // (7) Host-gated push of the verified committed branch + live-remote readback.
  return hostGatedPushCommittedBranch(role, phaseTitle, A, bound, implementation, binding, worktree)
}

// OpenAI-reviewer relay spawn path (TUR-447 F2b Unit G; role-runtime role-openai-relay,
// role-openai-fail-closed, launch-correctness-path, launch-review-sandbox-integrity,
// launch-resume-sandbox-config, launch-role-purpose-capability; operating-model
// decision-109-workflow-native). code-reviewer and qa-reviewer are OpenAI roles
// (provider=openai, gpt-5.6-sol) that MUST NOT run through the generic native agent()
// worker path. Instead this path runs three DISTINCT subagents so no single subagent both
// authors the verdict prose and vouches for its own effective identity:
//   1. a resolver subagent that reads roles.toml through the role resolver and RETURNS the
//      resolved runtime { provider, model, effort, service_tier, contract }; the loop
//      cannot read files and never hardcodes the runtime.
//   2. a relay subagent that runs one explicit `codex exec` for that resolved OpenAI
//      runtime (read-only-first bootstrap, then a live-read resume selected ONLY through
//      -c sandbox_mode config, never top-level -s), returns the codex final message
//      verbatim as its payload plus the claimed session id and the exact bootstrap/resume
//      argv and the review worktree HEAD+status captured before and after; it never
//      supplies the rollout record.
//   3. a SEPARATE read-only Explore subagent that reads the codex rollout record under
//      CODEX_HOME/sessions for the claimed session id and RETURNS the raw rollout data,
//      stamped as independent-rollout-subagent; this subagent is never the relay.
// acceptOpenaiReviewRelay then fails closed unless every provenance and sandbox law holds
// and the relay payload equals the independently fetched rollout final message. The
// verified final message becomes the reviewer verdict payload the review schema carries.
const REVIEWER_RUNTIME_SCHEMA = {
  type: 'object',
  required: ['provider', 'model', 'effort', 'service_tier', 'contract_blob', 'contract_text'],
  properties: {
    provider: { type: 'string' },
    model: { type: 'string' },
    effort: { type: 'string' },
    service_tier: { type: 'string' },
    contract_blob: { type: 'string' },
    // TUR-447 cycle1 pass2 P0 (role-runtime role-openai-relay): the resolver subagent returns
    // the canonical role contract TEXT it read from roles.toml so the relay carries the exact
    // contract as the codex exec prompt; the loop cannot read files and never hardcodes it.
    contract_text: { type: 'string' },
  },
}

// Native delivery-worker runtime resolved FROM roles.toml (TUR-447 cycle1 pass2 F2c;
// role-runtime role-machine-map, role-worker-migration). implementer and qa-capture are
// anthropic workers whose model, effort, and skill set must be resolved through the role
// resolver, not hardcoded. The resolver subagent returns the exact runtime plus the resolved
// skill set and the canonical contract text so the mutation spawn uses the resolved identity.
const WORKER_RUNTIME_SCHEMA = {
  type: 'object',
  required: ['provider', 'model', 'effort', 'service_tier', 'contract_blob', 'contract_text', 'skills'],
  properties: {
    provider: { type: 'string' },
    model: { type: 'string' },
    effort: { type: 'string' },
    service_tier: { type: 'string' },
    contract_blob: { type: 'string' },
    contract_text: { type: 'string' },
    skills: { type: 'array', items: { type: 'string' } },
  },
}

const WORKTREE_SNAPSHOT_SCHEMA = {
  type: 'object',
  required: ['head', 'status'],
  properties: { head: { type: 'string' }, status: { type: 'string' } },
}

const RELAY_SCHEMA = {
  type: 'object',
  required: [
    'claimed_session_id', 'payload', 'bootstrap_argv', 'resume_argv',
    'needs_live_reads', 'worktree_before', 'worktree_after',
  ],
  properties: {
    claimed_session_id: { type: 'string' },
    payload: { type: 'string' },
    bootstrap_argv: { type: 'array', items: { type: 'string' } },
    resume_argv: { type: 'array', items: { type: 'string' } },
    needs_live_reads: { type: 'boolean' },
    worktree_before: WORKTREE_SNAPSHOT_SCHEMA,
    worktree_after: WORKTREE_SNAPSHOT_SCHEMA,
  },
}

const ROLLOUT_SCHEMA = {
  type: 'object',
  required: ['source', 'data'],
  properties: {
    source: { type: 'string' },
    data: { type: 'object' },
  },
}

// TUR-447 cycle1 pass2 P0 (role-runtime role-openai-relay, launch-purpose-shaping-roles,
// launch-purpose-delivery-roles). The single OpenAI relay spawn path for every OpenAI role.
// admission is the exact purpose/role/linear-state gate the role's purpose requires (delivery
// for code-reviewer and qa-reviewer, shaping-review for shaping-reviewer); accept is the
// matching fail-closed relay acceptance gate. This one path resolves the runtime FROM
// roles.toml through the COMPLETE resolver command, carries the real per-pass brief, the
// contained worktree path, and the canonical contract TEXT into the relay prompt, reads the
// rollout record through a SEPARATE independent Explore subagent, and binds the verdict from
// the verbatim relay payload. shaping-reviewer now has a working spawn path here.
async function spawnOpenaiReviewer(role, phaseTitle, startingHead, schema, { admission, accept } = {}) {
  // Same admission, containment, journal, and revision revalidation as any relay pass. The
  // admission purpose/capabilities come from the caller so a shaping-review pass admits through
  // launch-purpose-shaping-roles and a reviewer pass through launch-purpose-delivery-roles.
  const admit = admission ?? { purpose: 'delivery', role, linearState: required(A.linear_state, 'linear state') }
  assertAdmission(admit)
  const acceptRelay = accept ?? acceptOpenaiReviewRelay
  const worktree = assertContainment(
    required(A.worktree_root, 'worktree root'),
    required(A.worktree, 'worker worktree'),
  )
  const bound = journalledBoundInputs(role, startingHead)
  // TUR-447 ruling-59 host-trusted identity anchor BEFORE the relay spawn: the OpenAI reviewer relay
  // path validates the envelope against the host-provisioned receipt (Anchor A) AND the live git read
  // of the receipt-pinned worktree (Anchor B), exactly as the native worker path does.
  await hostTrustedIdentity(role, phaseTitle)
  // Live readback immediately before the relay spawn (launch-readback, TUR-447 F3): the
  // OpenAI reviewer relay path revalidates against fresh live reads exactly as the native
  // worker path does, not just implement mode.
  await liveReadback(role, phaseTitle, startingHead, worktree)
  // Launch-revision REQUIRED and revalidated; never recomputed from a stale caller fallback.
  const revision = resolveLaunchRevision(bound)
  log(`journal relay-spawn ${role} ${bound.issue} ${bound.pr} ${bound.starting_head} ${bound.contract_hash} ${revision}`)
  const brief = required(A.brief, 'pass brief')
  assertContainment(A.worktree_root, worktree)
  // 1. Resolve the OpenAI runtime FROM roles.toml through the role resolver via the COMPLETE
  // resolver command (no literal '...'); the loop never hardcodes provider/model/effort/
  // service_tier and receives the canonical contract TEXT the relay carries.
  const runtime = await resolveRuntime(role, phaseTitle, worktree, REVIEWER_RUNTIME_SCHEMA, bound.issue)
  // 2. Relay subagent runs one codex exec for the resolved OpenAI runtime and returns the
  // verbatim final message plus the claimed session id, the exact bootstrap/resume argv, and
  // the review worktree HEAD+status before and after. It NEVER supplies the rollout record. The
  // relay carries the ACTUAL per-pass brief, the contained worktree path, and the canonical
  // contract TEXT (role-openai-relay).
  const relayPrompt = [
    `You are a fresh octo-lite codex relay subagent for the OpenAI ${role} role. One pass only.`,
    'BOUND INPUTS (verify against your own reads before relaying, echo verbatim is not required here):',
    JSON.stringify(bound, null, 2),
    'RESOLVED OPENAI RUNTIME to relay verbatim as the codex exec runtime:',
    JSON.stringify(
      { provider: runtime.provider, model: runtime.model, effort: runtime.effort, service_tier: runtime.service_tier },
      null, 2,
    ),
    `CONTAINED REVIEW WORKTREE (run codex exec with -C this exact path): ${worktree}`,
    // TUR-447 ruling-56 host cwd pin (loop-correctness single-writer): the relay subagent runs in an
    // AMBIENT cwd that on the shared box is a FOREIGN lane worktree. Pin the codex exec AND the worktree
    // snapshot git reads to the host issue worktree; do NOT rely on the current working directory.
    `Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    'it may be a foreign lane worktree on a shared box.',
    'CANONICAL ROLE CONTRACT to pass VERBATIM as the codex exec prompt (never copy a workflow literal):',
    runtime.contract_text,
    'PER-PASS BRIEF for this exact pass:',
    brief,
    'Run exactly one `codex exec` relay carrying that exact model, effort, service tier, the',
    'contained review worktree above, and the canonical role contract above as the exec prompt.',
    'Bootstrap read-only first (-s read-only). If the pass needs live GitHub or Linear reads,',
    'resume with the sandbox selected ONLY through -c sandbox_mode="workspace-write" plus -c',
    'sandbox_workspace_write.network_access=true; NEVER use the top-level -s flag on resume.',
    `Capture the review worktree HEAD (\`git -C ${worktree} rev-parse HEAD\`) and \`git -C ${worktree} status`,
    '--porcelain` once BEFORE the bootstrap and again AFTER the resumed pass; the review pass must not',
    'mutate the worktree.',
    'Return the codex final assistant message VERBATIM as payload (never summarize or edit it),',
    'the claimed_session_id, bootstrap_argv, resume_argv, needs_live_reads, worktree_before, and',
    'worktree_after. Do NOT read or return any codex rollout record; that is a separate reader.',
  ].join('\n\n')
  const relay = await agent(relayPrompt, {
    label: `${role}-relay:${bound.issue}`, phase: phaseTitle, schema: RELAY_SCHEMA,
  })
  if (relay === null) throw new Error(`${role} relay returned no result`)
  // 3. Independent read-only Explore subagent reads the codex rollout record for the claimed
  // session id under CODEX_HOME/sessions and returns the raw rollout data. This subagent is
  // NEVER the relay, so the fail-closed independent read-back is real.
  const rollout = await agent([
    `You are a fresh READ-ONLY octo-lite rollout reader for the ${role} relay. Never relay or mutate.`,
    `Read the codex rollout record under CODEX_HOME/sessions for session ${relay.claimed_session_id}.`,
    'Return { source: "independent-rollout-subagent", data: <the raw rollout record> } where data',
    'carries provider, model, effort, and final_message extracted FROM the rollout file itself.',
    'Do not accept any rollout content from the relay; read it yourself.',
  ].join('\n'), {
    label: `${role}-rollout:${bound.issue}`, phase: phaseTitle, schema: ROLLOUT_SCHEMA,
    agentType: 'Explore',
  })
  if (rollout === null) throw new Error(`${role} independent rollout read returned no result`)
  // Composite fail-closed acceptance: sandbox law, worktree immutability, independent
  // provenance, and relay-verbatim identity. A generic native agent() reviewer pass, a
  // relay-supplied rollout, an edited payload, or a top-level -s resume all reject here.
  const accepted = acceptRelay(role, runtime, relay, rollout)
  assertLaunchRevision(revision, bound)
  // The verified rollout final message is the reviewer verdict payload. The reviewer verdict
  // envelope is bound from the relay pass; the payload is the verbatim reviewer message.
  const verdict = await agent([
    `You are the ${role} verdict binder for this relay pass. One pass only; read-only.`,
    'BOUND INPUTS: verify each against your own reads and echo them verbatim as the ack object.',
    JSON.stringify(bound, null, 2),
    'The reviewer message is the verified verbatim codex final message below; bind the verdict',
    'envelope (verdict/findings/urls) strictly from it. Never re-author or soften it:',
    accepted.verdict_payload,
    brief,
  ].join('\n\n'), {
    label: `${role}:${bound.issue}`, phase: phaseTitle, schema, agentType: 'Explore',
  })
  if (verdict === null) throw new Error(`${role} verdict binding returned no result`)
  assertWorkerAckEcho(bound, verdict.ack)
  assertLaunchRevision(revision, bound)
  return verdict
}

// TUR-447 cycle1 pass2 P0 shaping-reviewer cutover (role-runtime launch-purpose-shaping-roles,
// role-openai-relay, role-openai-fail-closed, launch-correctness-path; role-worker-migration).
// roles.toml declares shaping-reviewer as an OpenAI Workflow relay, and the shaping flow needs
// the workflow to spawn it. This routes shaping-reviewer through the SAME relay path as the
// code/qa reviewers with the shaping-review admission purpose (launch-purpose-shaping-roles)
// and the shaping-review relay acceptance gate (acceptShapingReviewRelay), so it has a real
// cutover execution path with identical rollout-record provenance rather than none.
async function spawnShapingReviewer(phaseTitle, startingHead, schema) {
  return spawnOpenaiReviewer('shaping-reviewer', phaseTitle, startingHead, schema, {
    admission: { purpose: 'shaping-review', role: 'shaping-reviewer', linearState: required(A.linear_state, 'linear state') },
    accept: acceptShapingReviewRelay,
  })
}

// Loop fire (delivery-lifecycle linear-loop-fire-transition, delivery-entry-gate):
// the one mechanical Shaped -> Todo transition, performed by this loop through
// octo-control linear-transition before any delivery worker spawns. The runner is
// the owning orchestrator's mechanical helper invocation, not a worker role pass,
// so the role-purpose admission matrix and ack echo do not apply; octo-control
// itself verifies caller authority with compare, mutate, readback, notify.
async function loopFire() {
  const issue = required(A.issue, 'issue')
  const controlArgs = required(A.loop_fire_args, 'loop fire control args')
  const fire = await agent([
    'Run exactly this command from the owning orchestrator context, then report it:',
    `octo-control linear-transition ${issue} --expected Shaped --target Todo ${controlArgs}`,
    'Return command, exit_status, readback_state (the Linear state read back), and',
    'readback_fingerprint (the post-fire Linear content fingerprint of the issue).',
    // TUR-447 ruling-55 canonical fingerprint source: the post-fire readback_fingerprint MUST come from
    // scripts/octo-control linear-read (its returned fingerprint field verbatim), the SAME canonical
    // source as the envelope, NEVER improvised or self-hashed, so the reconciled envelope stays
    // like-with-like with the later liveReadback and assertLaunchReadback does not false-reject.
    `After the transition, run scripts/octo-control linear-read ${issue} and set readback_fingerprint to`,
    'ITS returned fingerprint field verbatim. Do NOT improvise, recompute, self-hash, or copy a pre-fire value.',
    'Never substitute a different transition, target, or issue.',
  ].join('\n'), { label: `loop-fire:${issue}`, phase: 'Implement', schema: FIRE_SCHEMA, effort: 'low' })
  if (fire === null || fire.exit_status !== 0) {
    throw new Error('delivery spawn at Shaped rejected: Shaped -> Todo loop fire failed')
  }
  return fire
}

if (mode === 'implement') {
  assertReadyEnvelope(A)
  // TUR-447 ruling-59 host-trusted identity anchor BEFORE the Shaped -> Todo fire: at Shaped the loop
  // is about to MUTATE Linear (the one mechanical transition), so the envelope identity must be proven
  // against the host-provisioned receipt (Anchor A) AND the live git read of the receipt-pinned
  // worktree (Anchor B) FIRST. Neither anchor derives from the envelope, so a foreign-but-well-formed
  // envelope (or a matching worktree path on a foreign branch/remote) is rejected before any transition
  // and before any spawn. A mismatch on either anchor rejects with no fire and no spawn.
  await hostTrustedIdentity('implementer', 'Implement')
  // Live readback runs inside spawnWorker immediately before every spawn (launch-readback,
  // TUR-447 F3): the loop no longer trusts a caller-supplied fresh_reads blob. A fresh
  // read-only Explore subagent performs the live reads and the readback gate rejects a
  // stale self-consistent envelope with no spawn. This holds in EVERY delivery mode, not
  // just implement.
  // Delivery entry: at Shaped this loop performs the Shaped -> Todo loop fire and
  // verifies the Todo readback before the implementer spawns; there is no path to a
  // delivery worker spawn at Shaped without that prior fire. The single ruling-15
  // orchestrator-performed manual Shaped -> Todo for TUR-447 is the one recorded
  // non-recurring exception; every later member fires through this gate.
  if (A.linear_state === 'Shaped') {
    const fired = await loopFire()
    if (fired.readback_state !== 'Todo') {
      throw new Error('delivery spawn at Shaped rejected: Todo readback missing after loop fire')
    }
    // TUR-447 cycle2 pass1 P0 self-rejection fix (delivery-lifecycle linear-loop-fire-transition,
    // delivery-entry-gate; role-runtime launch-readback). The loop just performed and confirmed
    // the Shaped -> Todo fire, so the true live Linear state is now Todo AND its content
    // fingerprint is the post-fire fingerprint. The subsequent liveReadback fetches that FRESH
    // Todo state AND fingerprint, and assertLaunchReadback compares BOTH against A.linear_state
    // and A.linear_fingerprint. The Linear fingerprint is a function of issue state, so the
    // Shaped fingerprint differs from the Todo fingerprint; the prior fix reconciled only the
    // state and left the STALE Shaped fingerprint, so EVERY genuine Shaped member self-rejected
    // on the fingerprint field and no worker ever spawned. Reconcile the bound envelope to the
    // CONFIRMED post-fire truth for BOTH state and fingerprint, derived from the fire's own fresh
    // readback, so a genuine Shaped member proceeds. This does NOT weaken the stale gate: a
    // genuinely wrong live state or fingerprint (e.g. Backlog, or a fingerprint disagreeing with
    // the post-fire truth) still rejects at assertLaunchReadback. The launch revision is
    // unaffected because neither linear_state nor linear_fingerprint is a bound-input fingerprint
    // field.
    A.linear_state = fired.readback_state
    A.linear_fingerprint = required(fired.readback_fingerprint, 'post-fire Linear fingerprint')
  }
  const implementation = await spawnWorker('implementer', 'Implement', A.shaping_head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'implement', implementation }
  const implWorktree = assertContainment(required(A.worktree_root, 'worktree root'), required(A.worktree, 'worker worktree'))
  const implBound = journalledBoundInputs('implementer', A.shaping_head)
  const deliveredHead = await deliverCommittedPass('implementer', 'Implement', A.shaping_head, implBound, implementation, implWorktree)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: deliveredHead,
    cycle: 1, implementation,
  }
}

if (mode === 'code-review') {
  const head = required(A.head, 'head')
  const reviewCycle = cycle()
  // An OpenAI code reviewer runs through the codex relay path (role-runtime
  // role-openai-relay, role-openai-fail-closed): a resolver subagent proves the runtime FROM
  // roles.toml, a relay subagent runs codex exec and returns the verbatim final message, a
  // SEPARATE read-only Explore subagent independently reads the codex rollout record, and
  // acceptOpenaiReviewRelay fails closed unless every provenance and sandbox law holds. This
  // is NOT the generic native agent() worker path.
  const review = await spawnOpenaiReviewer('code-reviewer', 'Code Review', head, REVIEW_SCHEMA)
  if (review.verdict === 'ambiguous') {
    return { stage: 'return-to-shaping', issue: A.issue, head, review }
  }
  // TUR-447 ruling-56 cycle3 slug-identity-bound: A.pr is now the canonical PR NUMBER, so the review
  // comment-URL prefix check uses A.pr_url (the PR web URL), falling back to A.reply_route.
  const gate = acceptCodeReview(head, required(A.pr_url ?? A.reply_route, 'PR URL'), review)
  if (gate.advance) {
    return { stage: 'code-clear', issue: A.issue, pr: A.pr, head, review, next: evidenceMode(A.user_facing !== false) }
  }
  if (reviewCycle === 3) return { stage: 'return-to-shaping', issue: A.issue, head, review }
  return { stage: 'fix-required', issue: A.issue, head, cycle: reviewCycle, findings: gate.findings }
}

if (mode === 'fix') {
  const head = required(A.head, 'head')
  const reviewCycle = cycle()
  if (reviewCycle >= 3) return { stage: 'return-to-shaping', issue: A.issue, head }
  if (!Array.isArray(A.findings) || A.findings.length === 0) throw new Error('blocking findings required')
  const implementation = await spawnWorker('implementer', 'Fix', head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'fix', implementation }
  const fixWorktree = assertContainment(required(A.worktree_root, 'worktree root'), required(A.worktree, 'worker worktree'))
  const fixBound = journalledBoundInputs('implementer', head)
  const deliveredHead = await deliverCommittedPass('implementer', 'Fix', head, fixBound, implementation, fixWorktree)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: deliveredHead,
    cycle: reviewCycle + 1, implementation,
  }
}

if (mode === 'evidence') {
  const head = required(A.head, 'head')
  if (!A.code_review || A.code_review.verdict !== 'clear' || A.code_review.head !== head) {
    throw new Error('clear exact-head code review required')
  }
  if (A.user_facing === false) {
    return {
      stage: 'backend-publication-required', issue: A.issue, head,
      required: ['code_review', 'validation', 'story_ids', 'spec_criteria', 'contract_checks'],
      next: 'Publish and read back the exact backend card, then run qa-review.',
    }
  }
  const capture = await spawnWorker('qa-capture', 'QA Capture', head, CAPTURE_SCHEMA)
  if (capture.blocked) return { stage: 'blocked', gate: 'qa-capture', capture }
  if (capture.head !== head) throw new Error('QA capture head mismatch')
  return {
    stage: 'visual-publication-required', issue: A.issue, head, capture,
    next: 'Publish and read back the exact visual card, then run qa-review.',
  }
}

if (mode === 'qa-review') {
  const head = required(A.head, 'head')
  if (
    !A.publication?.readback || A.publication.head !== head
    || !A.publication.packet_url || !A.publication.manifest
  ) {
    throw new Error('exact served publication readback required')
  }
  // The OpenAI qa-reviewer runs through the same codex relay path with independent rollout
  // provenance (role-runtime role-openai-relay, role-openai-fail-closed), not the generic
  // native agent() worker path.
  const qaReview = await spawnOpenaiReviewer('qa-reviewer', 'QA Review', head, QA_REVIEW_SCHEMA)
  if (qaReview.verdict === 'ambiguous') return { stage: 'return-to-shaping', issue: A.issue, head, qa_review: qaReview }
  const gate = acceptQaReview(head, { issue: A.issue, pr: A.pr, manifest: A.publication.manifest }, qaReview)
  return gate.advance
    ? {
        stage: 'verdict-publication-required', issue: A.issue, head, qa_review: qaReview,
        next: 'Publish verdict, read back card, then operator may accept.',
      }
    : { stage: 'fix-required', trigger: 'qa-review', issue: A.issue, head, cycle: cycle(), findings: gate.findings }
}

if (mode === 'publication-readback') {
  const accepted = acceptPublication(
    {
      issue: A.issue, pr: A.pr, head: A.head, story_ids: A.story_ids ?? [],
      acceptance_criteria: A.acceptance_criteria,
    },
    A.publication,
  )
  return {
    stage: 'awaiting-operator-acceptance', issue: A.issue, head: A.head,
    packet_url: accepted.packet_url,
    next: 'Operator may accept or reject. No agent may infer acceptance.',
  }
}

if (mode === 'reconcile') {
  // TUR-447 F4b-A Unit I: the reconciler-as-Workflow-subagent entry point (role-runtime
  // role-worker-migration, role-claude-native; operating-model decision-109-workflow-native).
  // The owning session bound the reconcile journal BEFORE this invocation through
  // octo_lite.launch bind_reconcile_workflow_journal, which persisted the final snapshot.md,
  // bound its path+bytes+digest, wrote NO reconcile TOML receipt, and rejected the retired
  // octo-lite-reconcile receipt shape. This mode spawns the Read-restricted reconciler, verifies
  // the snapshot-proof echo against that journal, classifies the deltas with needs_fable
  // escalation, and cleans up the read-only worktree keyed on the durable journal entry.
  const reconciled = await spawnReconciler('Reconcile')
  return {
    stage: reconciled.needs_fable ? 'reconcile-needs-fable' : 'reconcile-classified',
    issue: A.issue, classification: reconciled.classification,
    needs_fable: reconciled.needs_fable, deltas: reconciled.deltas,
    next: reconciled.needs_fable
      ? 'Fable judges the escalated reconcile case; no agent resolves ambiguity.'
      : 'Reconcile classification bound to the durable journal; worktree cleaned keyed on the journal.',
  }
}

if (mode === 'shaping-review') {
  // TUR-447 cycle1 pass2 P0 (role-runtime launch-purpose-shaping-roles, role-openai-relay,
  // role-worker-migration). The shaping-review cutover entry point: the shaping flow spawns the
  // OpenAI shaping-reviewer through the codex relay path with shaping-review admission and the
  // shaping-review relay acceptance gate. Same fail-closed independent rollout provenance and
  // sandbox law as the code/qa reviewers. This gives shaping-reviewer a real workflow spawn
  // path; the prior sole relay path admitted only code-reviewer and qa-reviewer.
  const head = required(A.head ?? A.shaping_head, 'head')
  const shapingReview = await spawnShapingReviewer('Shaping Review', head, SHAPING_REVIEW_SCHEMA)
  return { stage: 'shaping-review-verdict', issue: A.issue, head, shaping_review: shapingReview }
}

throw new Error(`unknown mode: ${mode}`)
