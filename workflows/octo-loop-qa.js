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

const DELIVERY_ROLES = new Set(['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer'])

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

// Worker binding by journal plus schema-forced ack echo (role-runtime launch-identity,
// launch-receipt, launch-gates-workflow-layer; operating-model decision-109-binding).
// A worker pass binds no durable TOML receipt: its binding proof is the workflow journal
// entry for the spawn plus this echo of the exact bound inputs, which the owning
// orchestrator verifies before any mutation phase. A role, repo, issue, or PR
// substitution fails the echo exactly as a HEAD mismatch does.
const WORKER_ACK_FIELDS = [
  ['role', 'worker ack role'],
  ['repo', 'worker ack repo'],
  ['issue', 'worker ack issue'],
  ['pr', 'worker ack PR'],
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

// TUR-447 cycle2 pass1 TDD independent-observation fix (delivery-lifecycle prompt-tdd-red,
// prompt-tdd-no-fabrication; and the spec-derived red-green-refactor contract). The prior gate
// compared only worker-supplied red.head/scenario STRINGS, so a fabricated proof with no genuine
// failing run was accepted. The red must now carry a captured EVIDENCE ARTIFACT: the actual
// failing test output the worker observed, the exit status that run produced, and the exact HEAD
// it ran at. The host validates that artifact (non-empty captured output, a genuinely failing
// exit that MATCHES the reported red exit, and an evidence HEAD equal to the unchanged starting
// HEAD) rather than trusting bare strings. A red with no genuine artifact bound to the starting
// HEAD is REJECTED. This is the workflow-layer stand-in for re-running the target's suite: the
// gate requires and validates the observed artifact, it does not accept a proof-shaped object.
function assertRedEvidenceArtifact(red, expectedHead) {
  const evidence = red.evidence
  if (typeof evidence !== 'object' || evidence === null) {
    throw new Error('red evidence artifact required: capture the failing test output at the starting HEAD')
  }
  requiredNonEmptyString(evidence.captured_output, 'red evidence captured output')
  if (!Number.isInteger(evidence.exit_status)) {
    throw new Error('red evidence exit status required')
  }
  if (evidence.exit_status === 0) {
    throw new Error('red evidence must record a genuinely failing run (nonzero exit)')
  }
  if (evidence.exit_status !== red.exit_status) {
    throw new Error('red evidence exit status must match the reported red exit status')
  }
  requiredNonEmptyString(evidence.head, 'red evidence HEAD')
  if (evidence.head !== expectedHead) {
    throw new Error('red evidence must be bound to the unchanged starting HEAD')
  }
  return evidence
}

// TUR-447 cycle2 pass1 host-gated push (delivery-lifecycle prompt-tdd-red, prompt-tdd-green;
// role-runtime launch-identity, launch-receipt; operating-model decision-109-binding). The
// mutating worker no longer commits or pushes: it produces the mutation in the contained
// worktree plus its ack echo and red/green evidence, then STOPS. The host commits and pushes
// only after echo + pre-push readback + TDD verify. So the accepted worker result runs its red
// AND its green at the UNCHANGED starting HEAD (the mutation lives in the working tree, no
// commit HEAD exists yet), and it must assert committed:false and pushed:false. A worker that
// already committed or pushed is rejected, because a post-hoc worktree reset cannot undo an
// already-pushed mutation. requireNewHead now governs the HOST commit that follows acceptance,
// so acceptImplementation binds the pre-commit worker result, not a worker-produced new HEAD.
function acceptImplementation(expectedHead, result, requireHostGatedPush = true) {
  required(result, 'implementation result')
  if (result.blocked !== false) throw new Error('implementation blocked')
  required(result.head, 'implementation HEAD')
  assertProof(result.red, 'implementation red evidence')
  assertProof(result.green, 'implementation green evidence')
  if (result.red.exit_status === 0) throw new Error('red must fail before production change')
  if (result.green.exit_status !== 0) throw new Error('green must pass after production change')
  // The red is proven by an independently-observed captured artifact bound to the unchanged
  // starting HEAD, not by worker-supplied strings.
  assertRedEvidenceArtifact(result.red, expectedHead)
  required(result.validation, 'implementation validation')
  // Host-gated push: the worker must NOT commit or push. Its output is verified BEFORE any
  // commit/push, so it stops at the working-tree mutation over the unchanged starting HEAD.
  if (requireHostGatedPush) {
    if (result.committed !== false) {
      throw new Error('worker must not commit: host commits only after verification (host-gated push)')
    }
    if (result.pushed !== false) {
      throw new Error('worker must not push: host pushes only after verification (host-gated push)')
    }
    if (result.head !== expectedHead) {
      throw new Error('worker head must equal the unchanged starting HEAD: no worker commit before host verify')
    }
    if (result.green.head !== expectedHead) {
      throw new Error('green must run at the unchanged starting HEAD over the working-tree mutation before host commit')
    }
  }
  // The red must run at the UNCHANGED starting HEAD before mutation; the green must exercise the
  // SAME behavior scenario as the red.
  if (result.red.head !== expectedHead) {
    throw new Error('red must run at the unchanged starting HEAD before mutation')
  }
  if (result.green.head !== result.head) {
    throw new Error('green HEAD must equal the delivered implementation HEAD')
  }
  if (result.green.scenario !== result.red.scenario) {
    throw new Error('green must prove the same scenario as red')
  }
  return result
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
  if (review.pr !== expected.pr) throw new Error('QA review PR mismatch')
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
// TUR-447 TDD-gate fix: red/green proofs are schema-forced to carry the exact HEAD the
// proof ran at and the behavior scenario it exercised, so acceptImplementation can bind
// the red to the unchanged starting HEAD (red before mutation) and prove the same
// scenario went green. An arbitrary proof-shaped object missing head or scenario is
// rejected at the schema and again at the gate.
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

// TUR-447 cycle2 pass1 TDD independent-observation: the red proof carries a captured EVIDENCE
// ARTIFACT (the actual failing test output, its exit status, and the exact HEAD it ran at) so the
// host validates the observed artifact bound to the unchanged starting HEAD rather than trusting
// bare strings. The green proof stays PROOF_SCHEMA; only the red must carry evidence.
const RED_PROOF_SCHEMA = {
  type: 'object',
  required: ['command', 'exit_status', 'outcome', 'artifact', 'head', 'scenario', 'evidence'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    outcome: { type: 'string' },
    artifact: { type: 'string' },
    head: { type: 'string' },
    scenario: { type: 'string' },
    evidence: {
      type: 'object',
      required: ['captured_output', 'exit_status', 'head'],
      properties: {
        captured_output: { type: 'string' },
        exit_status: { type: 'integer' },
        head: { type: 'string' },
      },
    },
  },
}

// Schema-forced acknowledgment echo of the exact journalled bound inputs
// (role-runtime launch-identity, launch-receipt; operating-model decision-109-binding).
const ACK_SCHEMA = {
  type: 'object',
  required: ['role', 'repo', 'issue', 'pr', 'starting_head', 'spec_blobs', 'contract_hash'],
  properties: {
    role: { type: 'string' },
    repo: { type: 'string' },
    issue: { type: 'string' },
    pr: { type: 'string' },
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

// TUR-447 cycle2 pass1 (host-gated push + stale-read race + TDD independent observation):
// the mutating worker echoes the liveness fields it read (linear_state, linear_fingerprint,
// branch) so the host can assert they equal the bound ground truth and reconfirm them live
// before push; it reports committed:false and pushed:false because the HOST performs the
// commit/push only after echo + pre-push readback + TDD verify; and its red carries a captured
// evidence artifact (RED_PROOF_SCHEMA).
const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: [
    'ack', 'issue', 'pr_url', 'branch', 'head', 'handoff_url', 'red', 'green',
    'validation', 'blocked', 'committed', 'pushed',
    'linear_state', 'linear_fingerprint',
  ],
  properties: {
    ack: ACK_SCHEMA,
    issue: { type: 'string' },
    pr_url: { type: 'string' },
    branch: { type: 'string' },
    head: { type: 'string' },
    handoff_url: { type: 'string' },
    red: RED_PROOF_SCHEMA,
    green: PROOF_SCHEMA,
    validation: { type: 'string' },
    summary: { type: 'string' },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
    // Host-gated push: the worker must report it did NOT commit or push.
    committed: { type: 'boolean' },
    pushed: { type: 'boolean' },
    // Stale-read race: the worker echoes the liveness fields it read so the host asserts them
    // against the bound ground truth and reconfirms them live before push.
    linear_state: { type: 'string' },
    linear_fingerprint: { type: 'string' },
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

const QA_REVIEW_SCHEMA = {
  type: 'object',
  required: ['ack', 'head', 'verdict', 'issue', 'pr', 'manifest', 'criteria', 'packet_url'],
  properties: {
    ack: ACK_SCHEMA,
    head: { type: 'string' },
    verdict: { enum: ['satisfied', 'blocking', 'ambiguous'] },
    issue: { type: 'string' },
    pr: { type: 'string' },
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
function journalledBoundInputs(role, startingHead) {
  return {
    role,
    repo: required(A.repo, 'repo'),
    issue: required(A.issue, 'issue'),
    pr: required(A.pr, 'pr'),
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
  const replyRoute = A.reply_route ?? required(A.pr, 'pr')
  const executionLocation = A.execution_location ?? 'local'
  const reviewDelivery = A.review_delivery ?? required(A.pr, 'pr')
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
async function liveReadback(role, phaseTitle, startingHead) {
  const issue = required(A.issue, 'issue')
  const pr = required(A.pr, 'pr')
  const branch = required(A.branch, 'branch')
  const fresh = await agent([
    `You are a fresh READ-ONLY octo-lite readback subagent for the ${role} spawn. One pass;`,
    'never mutate. Perform LIVE reads NOW, immediately before dispatch, and return them:',
    `- linear_state and linear_fingerprint: the live Linear state and content fingerprint of ${issue}.`,
    `- pr_head: the live PR head oid (gh pr view ${pr} --json headRefOid) of the PR.`,
    `- branch: the live head branch of the PR (expected ${branch}).`,
    '- git_head: the live git HEAD of the contained worktree (git rev-parse HEAD).',
    'Read each one yourself from Linear, GitHub, and git; do NOT copy any value from this',
    'prompt or from any caller-supplied blob. Return exactly the five fields.',
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
  // Live readback immediately before spawn (launch-readback, TUR-447 F3): a fresh
  // read-only Explore subagent performs the live Linear/PR/branch/HEAD reads and the pure
  // readback gate rejects a stale self-consistent caller envelope. No caller fresh_reads
  // blob is trusted.
  await liveReadback(role, phaseTitle, startingHead)
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
    // TUR-447 cycle2 pass1 TDD independent observation: the red must run at the UNCHANGED
    // starting HEAD before any production change, capturing the ACTUAL failing test output as an
    // evidence artifact; the green must run the SAME scenario after the working-tree mutation,
    // still at the unchanged starting HEAD (you do NOT commit).
    'TDD: run the spec-derived red scenario FIRST against the unchanged starting HEAD',
    `(${bound.starting_head}); report red with its head set to that starting HEAD, a scenario`,
    'name, and an `evidence` object carrying the CAPTURED failing test output (captured_output),',
    'that run\'s exit status (evidence.exit_status, nonzero, matching red.exit_status), and the',
    `HEAD it ran at (evidence.head = the starting HEAD ${bound.starting_head}). Only then mutate`,
    'the WORKING TREE. Run the SAME scenario for green; report green with head set to the same',
    'unchanged starting HEAD and the identical scenario name. A red with no genuine evidence',
    'artifact bound to the starting HEAD, or a green whose scenario differs from red, is rejected.',
    // TUR-447 cycle2 pass1 host-gated push: you do NOT commit or push. Leave the mutation in the
    // contained working tree, report committed:false and pushed:false, and let the HOST commit and
    // push only after it verifies your echo, a fresh pre-push readback, and the TDD proof.
    'HOST-GATED PUSH: do NOT git commit and do NOT git push. Leave your change in the working tree',
    'of the contained worktree. Set committed:false and pushed:false in your result. Set head to the',
    `unchanged starting HEAD (${bound.starting_head}). The host commits and pushes after verifying`,
    'your ack echo, a fresh pre-push readback, and your TDD proof; if any check fails the host resets',
    'the worktree and nothing is pushed.',
    // TUR-447 cycle2 pass1 stale-read race: echo the liveness fields you read so the host can
    // detect a live change during the intervening passes before it pushes.
    'LIVENESS ECHO: read the live Linear state and content fingerprint of the issue and the live PR',
    'branch yourself, and echo them as linear_state, linear_fingerprint, and branch in your result.',
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

// TUR-447 F1: verify the mutating worker's echo against the journalled bound inputs and,
// on ANY mismatch, discard the worktree changes so an unverified mutation is never
// accepted. The cleanup runs in a spawned subagent because the loop cannot touch the
// filesystem; it resets the contained worktree to the bound starting HEAD and clears any
// working-tree changes (workspace-cleanup), then this rethrows so no result advances.
async function acceptWorkerEchoOrDiscard(role, phaseTitle, bound, result, worktree) {
  let echoError = null
  try {
    assertWorkerAckEcho(bound, result.ack)
  } catch (error) {
    echoError = error
  }
  if (echoError === null) return result
  const cleaned = await agent([
    `You are a fresh octo-lite workspace-cleanup subagent for a REJECTED ${role} pass. One pass only.`,
    'The mutating worker returned an ack echo that does NOT match its journalled bound inputs, so its',
    'mutation must be DISCARDED and nothing committed or pushed. In the contained worktree below, reset',
    'the working tree to the exact bound starting HEAD and clear every uncommitted change:',
    `  worktree: ${worktree}`,
    `  starting_head: ${bound.starting_head}`,
    'Run the reset (git reset --hard to the starting HEAD and git clean of untracked changes), then read',
    'back and return the resulting HEAD and `git status --porcelain` (empty status proves a clean tree).',
  ].join('\n'), {
    label: `workspace-cleanup:${bound.issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['cleaned', 'head', 'status'],
      properties: { cleaned: { type: 'boolean' }, head: { type: 'string' }, status: { type: 'string' } },
    },
  })
  if (cleaned === null || cleaned.cleaned !== true || cleaned.head !== bound.starting_head || cleaned.status !== '') {
    throw new Error(`${role} unverified mutation discard failed: worktree not clean at starting HEAD`)
  }
  throw echoError
}

// TUR-447 cycle2 pass1 host-gated push (delivery-lifecycle prompt-tdd-green, delivery-entry-gate;
// role-runtime launch-readback, launch-identity, launch-receipt; operating-model
// decision-109-binding). The mutating worker leaves an uncommitted working-tree mutation and does
// NOT push. This helper is the HOST push gate, run ONLY after acceptImplementation has verified the
// worker echo and the TDD proof. In order it: (1) verifies the worker's liveness echo against the
// bound (post-fire reconciled) ground truth; (2) takes a FRESH live readback immediately before the
// commit and rejects if the live Linear state, Linear fingerprint, PR head, branch, or git HEAD
// changed since bind; and (3) ONLY THEN spawns a write-capable commit/push subagent that commits
// the working-tree mutation and pushes, returning the new delivered HEAD. On any failure the
// contained worktree is reset and NOTHING is pushed. Because a fresh readback and a real
// worktree reset both need the filesystem/network the loop lacks, each runs in a spawned subagent.
async function hostGatedCommitPush(role, phaseTitle, envelope, bound, result, worktree) {
  // (1) The worker echoed the liveness fields it read; they must equal the bound ground truth.
  assertWorkerLivenessEcho(envelope, result)
  // (2) Fresh live readback immediately before the push. This is a NEW read, distinct from the
  // spawn-start liveReadback, so a change during the resolver/ack/mutation passes is caught.
  const issue = required(A.issue, 'issue')
  const pr = required(A.pr, 'pr')
  const branch = required(A.branch, 'branch')
  const freshAfter = await agent([
    `You are a fresh READ-ONLY octo-lite pre-push readback subagent for the ${role} pass. One pass;`,
    'never mutate. Perform LIVE reads NOW, immediately before the host commits and pushes, and return',
    'them so the host can reject a live change since bind:',
    `- linear_state and linear_fingerprint: the live Linear state and content fingerprint of ${issue}.`,
    `- pr_head: the live PR head oid (gh pr view ${pr} --json headRefOid).`,
    `- branch: the live head branch of the PR (expected ${branch}).`,
    `- git_head: the live git HEAD of the contained worktree (git rev-parse HEAD) at ${worktree}.`,
    'Read each one yourself; do NOT copy any value from this prompt or a caller blob.',
  ].join('\n'), {
    label: `${role}-prepush-readback:${issue}`, phase: phaseTitle, schema: FRESH_READS_SCHEMA,
    agentType: 'Explore', effort: 'low',
  })
  if (freshAfter === null) throw new Error(`${role} pre-push readback returned no result`)
  // The bound ground truth for the pre-push comparison is the post-fire reconciled envelope plus
  // the exact starting HEAD (git_head) the worker mutated over.
  assertPrePushReadback(
    {
      linear_state: envelope.linear_state, linear_fingerprint: envelope.linear_fingerprint,
      pr_head: envelope.pr_head, branch: envelope.branch, git_head: bound.starting_head,
    },
    freshAfter,
  )
  // (3) Only now: the host commits the working-tree mutation and pushes. This is the sole
  // commit/push seam; the worker never reached it. A write-capable subagent runs the commit and
  // push and returns the new delivered HEAD.
  assertContainment(A.worktree_root, worktree)
  const pushed = await agent([
    `You are a fresh octo-lite host commit/push subagent for a VERIFIED ${role} pass. One pass only.`,
    'The worker left its mutation uncommitted in the contained worktree; its echo, a fresh pre-push',
    'readback, and its TDD proof have all passed. Commit that working-tree mutation on the bound branch',
    'and push it. Reference the issue in the commit message. Do NOT amend or rebase foreign commits.',
    `  worktree: ${worktree}`,
    `  starting_head: ${bound.starting_head}`,
    `  branch: ${branch}`,
    'Return committed:true, pushed:true, and the new head (git rev-parse HEAD after the commit).',
  ].join('\n'), {
    label: `host-commit-push:${bound.issue}`, phase: phaseTitle,
    schema: {
      type: 'object', required: ['committed', 'pushed', 'head'],
      properties: { committed: { type: 'boolean' }, pushed: { type: 'boolean' }, head: { type: 'string' } },
    },
  })
  if (pushed === null || pushed.committed !== true || pushed.pushed !== true) {
    throw new Error(`${role} host commit/push failed: nothing pushed`)
  }
  if (pushed.head === bound.starting_head) {
    throw new Error(`${role} host commit produced no new HEAD`)
  }
  return pushed.head
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
  // Live readback immediately before the relay spawn (launch-readback, TUR-447 F3): the
  // OpenAI reviewer relay path revalidates against fresh live reads exactly as the native
  // worker path does, not just implement mode.
  await liveReadback(role, phaseTitle, startingHead)
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
    'CANONICAL ROLE CONTRACT to pass VERBATIM as the codex exec prompt (never copy a workflow literal):',
    runtime.contract_text,
    'PER-PASS BRIEF for this exact pass:',
    brief,
    'Run exactly one `codex exec` relay carrying that exact model, effort, service tier, the',
    'contained review worktree above, and the canonical role contract above as the exec prompt.',
    'Bootstrap read-only first (-s read-only). If the pass needs live GitHub or Linear reads,',
    'resume with the sandbox selected ONLY through -c sandbox_mode="workspace-write" plus -c',
    'sandbox_workspace_write.network_access=true; NEVER use the top-level -s flag on resume.',
    'Capture the review worktree HEAD and `git status --porcelain` once BEFORE the bootstrap',
    'and again AFTER the resumed pass; the review pass must not mutate the worktree.',
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
    'readback_fingerprint (the live Linear content fingerprint of the issue read back AFTER',
    'the transition). Read the post-fire fingerprint yourself; do not copy a pre-fire value.',
    'Never substitute a different transition, target, or issue.',
  ].join('\n'), { label: `loop-fire:${issue}`, phase: 'Implement', schema: FIRE_SCHEMA, effort: 'low' })
  if (fire === null || fire.exit_status !== 0) {
    throw new Error('delivery spawn at Shaped rejected: Shaped -> Todo loop fire failed')
  }
  return fire
}

if (mode === 'implement') {
  assertReadyEnvelope(A)
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
  // Host-gated push (TUR-447 cycle2 pass1): the worker left an uncommitted working-tree mutation
  // and did NOT push. acceptImplementation verifies the echo, the independently-observed red
  // evidence bound to the unchanged starting HEAD, and that the worker did not commit/push. ONLY
  // THEN the host performs the pre-push readback and commits/pushes, producing the delivered HEAD.
  acceptImplementation(A.shaping_head, implementation, true)
  const deliveredHead = await hostGatedCommitPush(
    'implementer', 'Implement', A,
    journalledBoundInputs('implementer', A.shaping_head), implementation,
    assertContainment(required(A.worktree_root, 'worktree root'), required(A.worktree, 'worker worktree')),
  )
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
  const gate = acceptCodeReview(head, A.pr, review)
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
  // Host-gated push (TUR-447 cycle2 pass1): identical to implement mode. The fix worker leaves an
  // uncommitted working-tree mutation; the host verifies echo + red evidence + no worker push,
  // then does the pre-push readback and commits/pushes the delivered HEAD.
  acceptImplementation(head, implementation, true)
  const deliveredHead = await hostGatedCommitPush(
    'implementer', 'Fix', A,
    journalledBoundInputs('implementer', head), implementation,
    assertContainment(required(A.worktree_root, 'worktree root'), required(A.worktree, 'worker worktree')),
  )
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
