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
export function assertAdmission({ purpose, role, capabilities = [], readRestricted = false, linearState } = {}) {
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

export function assertManifestShape(manifest = {}) {
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

export function launchRevision(boundInputs) {
  required(boundInputs, 'bound inputs')
  return sha256Hex(canonical(boundInputs))
}

export function assertLaunchRevision(revision, boundInputs) {
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

export function assertLaunchReadback(envelope, fresh) {
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
export function assertContainment(worktreeRoot, worktreePath) {
  required(worktreeRoot, 'worktree root')
  required(worktreePath, 'worker worktree')
  const root = posixResolve(worktreeRoot)
  const resolved = posixResolve(root, worktreePath)
  if (!resolved.startsWith(root + POSIX_SEP)) {
    throw new Error(`worktree ${worktreePath} escapes worktree root ${worktreeRoot}`)
  }
  return resolved
}

export function assertReadyEnvelope(envelope) {
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

export function assertWorkerAckEcho(journalled, ack) {
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

export function assertReadOnlyAckPhase(phase) {
  required(phase, 'ack phase')
  if (!READ_ONLY_AGENT_TYPES.has(phase.agentType)) {
    throw new Error(
      'ack phase must run read-only: spawn under a read-only agentType (write tools withheld) until the echo verifies',
    )
  }
  return phase
}

export function verifyAckThenUpgrade(journalled, phase) {
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
export function assertCommittedImplementation(startingHead, result) {
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
export function assertBoundTest(boundTest) {
  required(boundTest, 'bound test identity')
  requiredNonEmptyString(boundTest.path, 'bound test path')
  requiredNonEmptyString(boundTest.digest, 'bound test content digest')
  return { path: boundTest.path, digest: boundTest.digest }
}

// TUR-447 D1 host-journalled commit binding (delivery-lifecycle delivery-tdd-observer-inputs-host-sourced,
// delivery-tdd-observer-inputs-host-journal-record; role-runtime role-tdd-observer-host-sourced-inputs).
// The HOST records the worker's committed delivery branch, its red, green, and final commit ids, and the
// canonical validation command from the target AGENTS.md in the journal binding. That binding is the
// trust root: the observer checks out exactly these host-journalled commits and runs exactly this
// host-sourced command, never a worker-authored commit id or command string. A worker-claimed commit id
// that differs from the accepted (host-journalled) commits, or a worker-authored command, is rejected.
// acceptedCommits is the { redCommit, greenCommit, finalCommit } assertCommittedImplementation returned
// from the worker's committed result; command is the host's canonical validation command (never worker
// authored); branch is the worker's committed delivery branch.
export function assertHostJournalledCommits(binding, acceptedCommits, command, branch) {
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
export const INDEPENDENT_OBSERVER_SOURCE = 'independent-tdd-observer'

function assertObservedStateDigest(observedTest, boundTest, label) {
  required(observedTest, `observed ${label} bound test`)
  if (observedTest.path !== boundTest.path) {
    throw new Error(`observer replay rejected: bound test path absent or changed at the ${label} commit`)
  }
  if (observedTest.digest !== boundTest.digest) {
    throw new Error(`observer replay rejected: bound test content digest differs at the ${label} commit`)
  }
}

export function assertObservedCommittedStates(observation, journalled, boundTest) {
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

export function assertPrePushReadback(bound, freshAfter) {
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

export function assertWorkerLivenessEcho(bound, result) {
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

export function assertLiveRemotePushReadback(readback, expectedFinalHead) {
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

export function acceptCodeReview(expectedHead, expectedPr, review) {
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

export function evidenceMode(userFacing) {
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

export function acceptQaReview(expectedHead, expected, review) {
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

export function acceptPublication(expected, publication) {
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

export function verifyRelayVerbatim(expectedRuntime, claimedSessionId, relayPayload, rolloutLookup) {
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

export function assertResumeSandboxConfig(resumeArgv, { needsLiveReads = false } = {}) {
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
export function assertReadOnlyFirstBootstrap(bootstrapArgv) {
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
export function assertReviewWorktreeImmutable(before, after) {
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

export function acceptOpenaiReviewRelay(role, resolvedRuntime, relay, rollout) {
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
export function acceptShapingReviewRelay(role, resolvedRuntime, relay, rollout) {
  return acceptRelayVerdict(
    SHAPING_REVIEWER_ROLES, 'a shaping-review relay role', role, resolvedRuntime, relay, rollout,
  )
}
