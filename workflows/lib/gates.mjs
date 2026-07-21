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

function assertProof(proof, label) {
  if (typeof proof !== 'object' || proof === null) throw new Error(`${label} required`)
  requiredNonEmptyString(proof.command, `${label} command`)
  requiredNonEmptyString(proof.outcome, `${label} outcome`)
  requiredNonEmptyString(proof.artifact, `${label} artifact`)
  if (!Number.isInteger(proof.exit_status)) throw new Error(`${label} exit status required`)
  return proof
}

export function acceptImplementation(expectedHead, result, requireNewHead = true) {
  required(result, 'implementation result')
  if (result.blocked !== false) throw new Error('implementation blocked')
  required(result.head, 'implementation HEAD')
  assertProof(result.red, 'implementation red evidence')
  assertProof(result.green, 'implementation green evidence')
  if (result.red.exit_status === 0) throw new Error('red must fail before production change')
  if (result.green.exit_status !== 0) throw new Error('green must pass after production change')
  required(result.validation, 'implementation validation')
  if (requireNewHead && result.head === expectedHead) throw new Error('implementation needs new HEAD')
  return result
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
