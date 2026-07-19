function required(value, label) {
  if (value === undefined || value === null || value === '') {
    throw new Error(`${label} required`)
  }
  return value
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
  requiredNonEmptyArray(receipt.skills?.resolved, 'pass resolved skills')
  const blobs = requiredNonEmptyArray(receipt.skills?.blobs, 'pass skill blobs')
  if (blobs.length !== receipt.skills.resolved.length) throw new Error('pass skill blobs required')
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
