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

function assertProof(proof, label) {
  if (typeof proof !== 'object' || proof === null) throw new Error(`${label} required`)
  requiredNonEmptyString(proof.command, `${label} command`)
  requiredNonEmptyString(proof.outcome, `${label} outcome`)
  requiredNonEmptyString(proof.artifact, `${label} artifact`)
  if (!Number.isInteger(proof.exit_status)) throw new Error(`${label} exit status required`)
  return proof
}

function acceptImplementation(expectedHead, result, requireNewHead = true) {
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

function acceptOpenaiReviewRelay(role, resolvedRuntime, relay, rollout) {
  required(role, 'reviewer role')
  if (!OPENAI_REVIEWER_ROLES.has(role)) {
    throw new Error(`relay verbatim rejected: ${role} is not an OpenAI reviewer role`)
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
const PROOF_SCHEMA = {
  type: 'object',
  required: ['command', 'exit_status', 'outcome', 'artifact'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    outcome: { type: 'string' },
    artifact: { type: 'string' },
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

const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: [
    'ack', 'issue', 'pr_url', 'branch', 'head', 'handoff_url', 'red', 'green',
    'validation', 'blocked',
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
  required: ['command', 'exit_status', 'readback_state'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    readback_state: { type: 'string' },
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
    'BOUND INPUTS: verify each against your own reads, echo them verbatim as the ack',
    'object in your structured result, and stop before any mutation on any mismatch:',
    JSON.stringify(bound, null, 2),
    brief,
  ].join('\n\n')
  const result = await agent(prompt, {
    label: `${role}:${bound.issue}`, phase: phaseTitle, schema,
  })
  if (result === null) throw new Error(`${role} pass returned no result`)
  assertWorkerAckEcho(bound, result.ack)
  // Launch-revision revalidation again before any mutation-phase advance.
  assertLaunchRevision(revision, bound)
  return result
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
  required: ['provider', 'model', 'effort', 'service_tier', 'contract_blob'],
  properties: {
    provider: { type: 'string' },
    model: { type: 'string' },
    effort: { type: 'string' },
    service_tier: { type: 'string' },
    contract_blob: { type: 'string' },
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

async function spawnOpenaiReviewer(role, phaseTitle, startingHead, schema) {
  // Same admission, containment, journal, and revision revalidation as any delivery pass.
  assertAdmission({ purpose: 'delivery', role, linearState: required(A.linear_state, 'linear state') })
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
  // 1. Resolve the OpenAI runtime FROM roles.toml through the role resolver; the loop never
  // hardcodes provider/model/effort/service_tier.
  const runtime = await agent([
    `Resolve the octo-lite ${role} runtime from roles.toml through the role resolver.`,
    `Run: python3 workflows/lib/role_resolver.py resolve ${role} ... and read roles.toml.`,
    'Return provider, model, effort, service_tier, and contract_blob EXACTLY as resolved.',
    'Do not invent or override any field; read-only.',
  ].join('\n'), {
    label: `${role}-runtime:${bound.issue}`, phase: phaseTitle, schema: REVIEWER_RUNTIME_SCHEMA,
    agentType: 'Explore',
  })
  if (runtime === null) throw new Error(`${role} runtime resolution returned no result`)
  // 2. Relay subagent runs one codex exec for the resolved OpenAI runtime and returns the
  // verbatim final message plus the claimed session id, the exact bootstrap/resume argv, and
  // the review worktree HEAD+status before and after. It NEVER supplies the rollout record.
  const relayPrompt = [
    `You are a fresh octo-lite codex relay subagent for the OpenAI ${role} role. One pass only.`,
    'BOUND INPUTS (verify against your own reads before relaying, echo verbatim is not required here):',
    JSON.stringify(bound, null, 2),
    'RESOLVED OPENAI RUNTIME to relay verbatim as the codex exec runtime:',
    JSON.stringify(runtime, null, 2),
    'Run exactly one `codex exec` relay carrying that exact model, effort, service tier, the',
    'contained review worktree, and the canonical role contract as the exec prompt.',
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
  const accepted = acceptOpenaiReviewRelay(role, runtime, relay, rollout)
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
    'Return command, exit_status, and readback_state (the Linear state read back).',
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
  }
  const implementation = await spawnWorker('implementer', 'Implement', A.shaping_head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'implement', implementation }
  acceptImplementation(A.shaping_head, implementation, true)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: implementation.head,
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
  acceptImplementation(head, implementation, true)
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: implementation.head,
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

throw new Error(`unknown mode: ${mode}`)
