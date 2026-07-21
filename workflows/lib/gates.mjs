function required(value, label) {
  if (value === undefined || value === null || value === '') {
    throw new Error(`${label} required`)
  }
  return value
}

// Pure JS SHA-256 (FIPS 180-4). No Node crypto dependency: the Workflow runtime
// that executes this module has no Node.js API access, only standard JS built-ins.
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

function sha256Hex(message) {
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19
  const bytes = new TextEncoder().encode(message)
  const bitLen = bytes.length * 8
  let paddedLen = bytes.length + 1
  while (paddedLen % 64 !== 56) paddedLen++
  paddedLen += 8
  const buf = new Uint8Array(paddedLen)
  buf.set(bytes)
  buf[bytes.length] = 0x80
  const view = new DataView(buf.buffer)
  view.setUint32(paddedLen - 4, bitLen >>> 0, false)
  view.setUint32(paddedLen - 8, Math.floor(bitLen / 0x100000000), false)

  const rotr = (x, n) => (x >>> n) | (x << (32 - n))
  const w = new Uint32Array(64)
  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(offset + i * 4, false)
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3)
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const temp1 = (h + S1 + ch + SHA256_K[i] + w[i]) >>> 0
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const temp2 = (S0 + maj) >>> 0
      h = g; g = f; f = e; e = (d + temp1) >>> 0
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map((x) => x.toString(16).padStart(8, '0')).join('')
}

// Mirrors octo_lite.runtime.exact_fingerprint: json.dumps(sort_keys=True, separators=(",", ":")).
function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']'
  const keys = Object.keys(value).sort()
  return '{' + keys.map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}'
}

export function exactFingerprint(value) {
  return sha256Hex(canonicalJson(value))
}

// Independently recomputes the launcher-owned result binding and checks it against
// both the pass result's own claim and the receipt's durable stored binding. A role
// output cannot self-author its binding: the launcher already overwrote it, so any
// mismatch here means the result was tampered with after the launcher bound it.
export function assertBoundPassResult(receipt, passResult) {
  required(passResult, 'pass result')
  const claimed = assertResultBinding(passResult)
  const { result_binding, ...unbound } = passResult
  const recomputed = exactFingerprint(unbound)
  if (recomputed !== claimed) throw new Error('pass result binding does not match its own content')
  if (receipt?.result?.bound !== true) throw new Error('receipt result not bound')
  if (receipt.result.binding !== recomputed) throw new Error('pass result binding does not match receipt')
  return recomputed
}

function typeOf(value) {
  if (Array.isArray(value)) return 'array'
  if (value === null) return 'null'
  return typeof value
}

export function assertSchema(schema, value, label) {
  if (schema.enum) {
    if (!schema.enum.includes(value)) throw new Error(`${label} must be one of ${schema.enum.join(', ')}`)
    return value
  }
  if (typeOf(value) !== schema.type) throw new Error(`${label} must be ${schema.type}`)
  if (schema.type === 'integer' && !Number.isInteger(value)) throw new Error(`${label} must be an integer`)
  if (schema.type === 'array' && schema.items) {
    value.forEach((item, index) => assertSchema(schema.items, item, `${label}[${index}]`))
  }
  if (schema.type === 'object') {
    for (const field of schema.required ?? []) {
      if (value[field] === undefined || value[field] === null || value[field] === '') {
        throw new Error(`${label}.${field} required`)
      }
    }
    for (const [key, propSchema] of Object.entries(schema.properties ?? {})) {
      if (value[key] !== undefined) assertSchema(propSchema, value[key], `${label}.${key}`)
    }
  }
  return value
}

const DELIVERY_ROLES = new Set(['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer'])

// Workflow-layer admission matrix (role-runtime launch-role-purpose-capability,
// launch-purpose-shaping-roles, launch-purpose-delivery-roles, launch-purpose-reconcile,
// launch-gates-workflow-layer). Called before each subagent spawn; an invalid
// combination fails closed with no spawn.
export function assertAdmission({ purpose, role, capabilities = [], readRestricted = false } = {}) {
  required(purpose, 'admission purpose')
  required(role, 'admission role')
  if (purpose === 'shaping-review') {
    const orchestratorWithShaping = role === 'orchestrator' && capabilities.includes('shaping')
    if (role !== 'shaping-reviewer' && !orchestratorWithShaping) {
      throw new Error(`role ${role} not admitted for shaping-review purpose`)
    }
  } else if (purpose === 'delivery') {
    if (!DELIVERY_ROLES.has(role)) throw new Error(`role ${role} not admitted for delivery purpose`)
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

function requiredNonEmptyObject(value, label) {
  if (typeof value !== 'object' || value === null || Object.keys(value).length === 0) {
    throw new Error(`${label} required`)
  }
  return value
}

export function assertPassReceipt(receipt, role, startingHead) {
  required(receipt, 'pass receipt')
  required(receipt.spawn_id, 'pass spawn ID')
  if (receipt.ready !== true || receipt.bootstrap?.verified !== true) {
    throw new Error('pass bootstrap not verified')
  }
  if (receipt.role?.name !== role) throw new Error('pass role mismatch')
  if (receipt.workspace?.starting_head !== startingHead) {
    throw new Error('pass starting HEAD mismatch')
  }
  requiredNonEmptyString(receipt.parent, 'pass parent')
  requiredNonEmptyString(receipt.reply_route, 'pass reply route')
  requiredNonEmptyString(receipt.launch_revision, 'pass launch revision')
  requiredNonEmptyString(receipt.bootstrap?.provider_session_id, 'pass provider session')
  requiredNonEmptyString(receipt.role?.contract_blob, 'pass role contract blob')
  requiredNonEmptyString(receipt.role?.mapping_revision, 'pass role mapping revision')
  // A role that declares no required or matched conditional skills resolves an exact
  // empty set. That is valid and distinct from a missing or malformed skills field.
  const resolvedSkills = receipt.skills?.resolved
  if (!Array.isArray(resolvedSkills)) throw new Error('pass resolved skills required')
  const blobs = receipt.skills?.blobs
  if (!Array.isArray(blobs) || blobs.length !== resolvedSkills.length) throw new Error('pass skill blobs required')
  requiredNonEmptyString(receipt.workspace?.repo, 'pass repo')
  requiredNonEmptyString(receipt.workspace?.instructions_blob, 'pass instructions blob')
  requiredNonEmptyString(receipt.issue?.identifier, 'pass issue identity')
  requiredNonEmptyString(receipt.issue?.fingerprint, 'pass issue fingerprint')
  requiredNonEmptyString(receipt.spec?.revision, 'pass spec revision')
  requiredNonEmptyArray(receipt.spec?.blobs, 'pass spec blobs')
  requiredNonEmptyString(receipt.pull_request?.url, 'pass pull request identity')
  requiredNonEmptyString(receipt.pull_request?.head, 'pass pull request head')
  if (!Number.isInteger(receipt.topology?.revision)) throw new Error('pass topology revision required')
  requiredNonEmptyObject(receipt.prior_gates, 'pass prior gates')
  requiredNonEmptyObject(receipt.access, 'pass access facts')
  requiredNonEmptyObject(receipt.resources, 'pass resources')
  return receipt
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

const RESULT_BINDING_PATTERN = /^[0-9a-f]{64}$/

export function assertResultBinding(result) {
  const binding = result?.result_binding
  if (typeof binding !== 'string' || !RESULT_BINDING_PATTERN.test(binding)) {
    throw new Error('exact result binding required')
  }
  return binding
}

function assertProof(proof, label) {
  if (typeof proof !== 'object' || proof === null) throw new Error(`${label} required`)
  requiredNonEmptyString(proof.command, `${label} command`)
  requiredNonEmptyString(proof.outcome, `${label} outcome`)
  requiredNonEmptyString(proof.artifact, `${label} artifact`)
  if (!Number.isInteger(proof.exit_status)) throw new Error(`${label} exit status required`)
  return proof
}

export function acceptImplementation(expectedHead, result, spawnId, requireNewHead = true) {
  required(result, 'implementation result')
  if (result.blocked !== false) throw new Error('implementation blocked')
  required(result.head, 'implementation HEAD')
  if (result.receipt !== spawnId) throw new Error('implementation receipt mismatch')
  assertProof(result.red, 'implementation red evidence')
  assertProof(result.green, 'implementation green evidence')
  if (result.red.exit_status === 0) throw new Error('red must fail before production change')
  if (result.green.exit_status !== 0) throw new Error('green must pass after production change')
  required(result.validation, 'implementation validation')
  if (requireNewHead && result.head === expectedHead) throw new Error('implementation needs new HEAD')
  assertResultBinding(result)
  return result
}

export function acceptCodeReview(expectedHead, expectedPr, review) {
  required(review, 'code review')
  if (review.head !== expectedHead) throw new Error('code review HEAD mismatch')
  required(review.receipt, 'code review receipt')
  requiredNonEmptyString(review.comment_url, 'code review comment')
  if (!review.comment_url.startsWith(expectedPr)) {
    throw new Error('code review comment URL does not match reviewed PR')
  }
  requiredNonEmptyArray(review.bound_inputs, 'code review bound inputs')
  assertResultBinding(review)
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
  required(review.receipt, 'QA review receipt')
  required(review.packet_url, 'served packet')
  if (review.issue !== expected.issue) throw new Error('QA review issue mismatch')
  if (review.pr !== expected.pr) throw new Error('QA review PR mismatch')
  if (review.manifest !== expected.manifest) throw new Error('QA review manifest mismatch')
  assertResultBinding(review)
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
