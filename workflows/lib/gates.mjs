// octo-lite delivery-loop gate helpers (role-runtime launch-gates-workflow-layer,
// loop-runs-on-cwd-and-branch; delivery-lifecycle delivery-tdd-reviewer-guard). This is the
// canonical, node-tested source (tests/gates.test.mjs). The delivery loop
// workflows/octo-loop-qa.js embeds this file inline, byte-identical with only the `export `
// keyword stripped, between its GATES-EMBED markers, because the Workflow sandbox forbids any
// module load. A parity test (tests/test_conformance.py) fails closed if the inline region
// drifts from this module.
//
// ADR 0003 dropped the loop-entry trust root and the independent observer: no provision-record
// read, no frozen-environment seam, no environment-equals-record cross-check, no launch-revision
// revalidation, no ack-echo two-phase gate, no independent git-read / observer replay, and no
// pre-push readback. The loop derives its worktree from the process working directory and its
// branch from git and runs; the fresh adversarial code-reviewer is the delivery-TDD guard and the
// host pushes the verified branch directly. The OpenAI reviewer relay-provenance gate is RETAINED
// (role-runtime role-openai-relay, role-openai-fail-closed): cross-model review integrity still
// requires the independent rollout-record read-back and the relay-verbatim gate.

function required(value, label) {
  if (value === undefined || value === null || value === '') {
    throw new Error(`${label} required`)
  }
  return value
}

function requiredNonEmptyString(value, label) {
  if (typeof value !== 'string' || value === '') throw new Error(`${label} required`)
  return value
}

function requiredNonEmptyArray(value, label) {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`${label} required`)
  return value
}

// The canonical GitHub repo slug is owner/repo (exactly one slash, no scheme, no spaces). A missing
// or malformed slug (a bare name, a URL, or an owner/repo/extra path) is rejected so gh is always
// pinned to the right repository and never infers it from the ambient (foreign lane) cwd.
export function assertRepoSlug(value, label) {
  requiredNonEmptyString(value, label)
  if (!/^[^/\s]+\/[^/\s]+$/.test(value)) {
    throw new Error(`${label} must be a canonical owner/repo slug`)
  }
  return value
}

// The canonical gh identity is the PR NUMBER, never a URL: `gh pr view <URL> --repo <slug>` lets the
// URL OVERRIDE --repo and select the URL's repository. requiredPrNumber accepts an integer or an
// all-digits string and REJECTS a URL (or any non-numeric), returning the canonical string form so a
// numeric 6 and a string '6' compare equal.
export function requiredPrNumber(value, label) {
  required(value, label)
  if (typeof value === 'number') {
    if (!Number.isInteger(value) || value <= 0) throw new Error(`${label} must be a positive PR number`)
    return String(value)
  }
  if (typeof value === 'string' && /^[0-9]+$/.test(value)) return value
  throw new Error(`${label} must be a PR number, not a URL`)
}

// Pure-JS POSIX path resolution, enough for worktree containment. No node:path. Resolves `./`, `../`,
// and repeated separators against an absolute root; relative roots resolve against '/'.
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

// Worktree containment (role-runtime launch-containment): checked exactly at admission and at child
// subagent spawn; a wrong or escaping worktree path never spawns.
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

// The delivery roles (role-runtime launch-purpose-delivery-roles). ADR 0003 retired the independent
// observer role, so no Read-restricted delivery role remains.
const DELIVERY_ROLES = new Set(['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer'])

// Linear-state gate (role-runtime launch-linear-state-gate): shaping-review launches only from Ideas,
// Todo, Shaped, or In Progress; delivery only from Shaped, Todo, or In Progress; every other state,
// including Awaiting Accept and terminal states, is rejected for both purposes.
const SHAPING_REVIEW_STATES = new Set(['Ideas', 'Todo', 'Shaped', 'In Progress'])
const DELIVERY_STATES = new Set(['Shaped', 'Todo', 'In Progress'])

function assertLinearState(purpose, linearState, admitted) {
  required(linearState, `${purpose} Linear state`)
  if (!admitted.has(linearState)) {
    throw new Error(`Linear state ${linearState} rejected for ${purpose} purpose`)
  }
}

// Workflow-layer admission matrix plus Linear-state gate (role-runtime launch-role-purpose-capability,
// launch-purpose-shaping-roles, launch-purpose-delivery-roles, launch-purpose-reconcile,
// launch-linear-state-gate). Called before each subagent spawn; an invalid combination fails closed
// with no spawn.
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

// Manifest-shape admission (role-runtime launch-receipt-manifest-shapes, launch-receipt-persistent):
// exactly one durable receipt shape remains, the generic persistent launch receipt for role
// meta-operator or orchestrator carrying no pass purpose; every worker pass, including reconcile,
// binds through the workflow journal under the role-purpose-capability matrix.
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

// Readiness envelope (delivery-lifecycle delivery-entry-gate, shaping-state; role-runtime
// launch-linear-state-gate). The loop derives its worktree from the process cwd and its branch from
// git (loop-runs-on-cwd-and-branch); readiness still validates the bound shaping verdict, the exact
// head, the canonical repo slug, the PR number (never a URL), and worktree containment before the one
// mechanical Shaped -> Todo fire, but performs no provision-record read or launch-revision check.
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

// Code-review acceptance (delivery-lifecycle delivery-fix-review, delivery-tdd-reviewer-guard): a
// clear verdict advances to QA, a blocking verdict returns fresh findings for a fix pass.
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

// QA-review acceptance (delivery-lifecycle qa-verdict, qa-acceptance-chain): a satisfied verdict with
// every criterion pass advances to the acceptance package; otherwise it returns the non-pass findings.
export function acceptQaReview(expectedHead, expected, review) {
  required(review, 'qa review')
  if (review.head !== expectedHead) throw new Error('QA review HEAD mismatch')
  required(review.packet_url, 'served packet')
  if (review.issue !== expected.issue) throw new Error('QA review issue mismatch')
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

// Acceptance package (delivery-lifecycle delivery-merge, linear-operator-authority,
// qa-acceptance-chain, qa-human-acceptance). The acceptance mode BUILDS this package from the
// delivered facts and hands it to the loop to POST to the evidence site and SEND to the operator; it
// NEVER self-accepts. A satisfied fresh QA-review verdict, a clear code-review verdict, the delivered
// PR and head, at least one evidence-site card link, the current Linear state, and a plain
// what-changed summary are all required, so an incomplete package fails closed rather than being
// offered for acceptance. No acceptance decision, merge, or Linear acceptance transition happens here.
export function buildAcceptancePackage(inputs) {
  required(inputs, 'acceptance inputs')
  const issue = requiredNonEmptyString(inputs.issue, 'acceptance issue')
  const pr = requiredPrNumber(inputs.pr, 'acceptance PR')
  const head = requiredNonEmptyString(inputs.head, 'acceptance head')
  const codeReview = required(inputs.code_review, 'acceptance code-review verdict')
  if (codeReview.verdict !== 'clear' || codeReview.head !== head) {
    throw new Error('acceptance package requires a clear exact-head code-review verdict')
  }
  const qaReview = required(inputs.qa_review, 'acceptance qa-review verdict')
  if (qaReview.verdict !== 'satisfied' || qaReview.head !== head) {
    throw new Error('acceptance package requires a satisfied exact-head qa-review verdict')
  }
  const cardLinks = requiredNonEmptyArray(inputs.evidence_card_links, 'acceptance evidence card links')
  for (const link of cardLinks) requiredNonEmptyString(link, 'acceptance evidence card link')
  const linearState = requiredNonEmptyString(inputs.linear_state, 'acceptance Linear state')
  const summary = requiredNonEmptyString(inputs.summary, 'acceptance what-changed summary')
  return {
    issue,
    pr,
    head,
    evidence_card_links: cardLinks,
    code_review_verdict: codeReview.verdict,
    qa_review_verdict: qaReview.verdict,
    linear_state: linearState,
    summary,
    self_accepted: false,
  }
}

// ---------------------------------------------------------------------------
// RETAINED OpenAI reviewer relay-provenance gate (role-runtime role-openai-relay,
// role-openai-fail-closed, launch-review-sandbox-integrity, launch-resume-sandbox-config). ADR 0003
// removed the loop trust root and the observer, but cross-model review integrity still requires that
// an OpenAI reviewer verdict be proven from an INDEPENDENTLY-read codex rollout record with the
// relay-verbatim gate; the OpenAI reviewer roles never use the plain worker spawn path.
// ---------------------------------------------------------------------------

// Pure relay-verbatim verification. The loop cannot read files, sessions, or the network, so the
// caller resolves the OpenAI rollout record through a separate read-only subagent and passes the
// record here. The relay itself never supplies the record. rolloutLookup is the INDEPENDENTLY-fetched
// rollout data, either the single record for the claimed session id or a map of session id to record.
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

// Sandbox-law predicates (role-runtime launch-review-sandbox-integrity, launch-resume-sandbox-config).
// Every OpenAI resume selects its sandbox through -c sandbox_mode=... config, never the top-level -s
// flag, because the installed CLI resume subcommand rejects -s while the exec bootstrap still accepts it.
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

// A review-pass bootstrap must be read-only-first: the exec bootstrap selects the read-only sandbox
// before any workspace-write resume.
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

// Review-worktree immutability gate (role-runtime launch-review-sandbox-integrity): an OpenAI review
// pass must not mutate its worktree. status is the exact `git status --porcelain` output, empty for an
// unchanged worktree.
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

// Composite fail-closed relay verdict acceptance (role-runtime role-openai-relay,
// role-openai-fail-closed, launch-review-sandbox-integrity, launch-resume-sandbox-config). The single
// deterministic gate that accepts an OpenAI reviewer verdict produced through the codex relay: role
// admission, resolved-OpenAI-runtime shape, relay/rollout provenance (the rollout MUST come from the
// independent read-only reader, never the relay), sandbox law over the exact argv, worktree
// immutability, and relay-verbatim effective identity proven FROM the independently fetched rollout
// record. An OpenAI reviewer verdict can never be admitted through the generic native worker path or
// with relay-supplied rollout data.
const INDEPENDENT_ROLLOUT_SOURCE = 'independent-rollout-subagent'
const OPENAI_REVIEWER_ROLES = new Set(['code-reviewer', 'qa-reviewer'])
const SHAPING_REVIEWER_ROLES = new Set(['shaping-reviewer'])

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
  if (relay.rollout_source !== undefined && relay.rollout_source !== null) {
    throw new Error('relay verbatim rejected: relay must not supply the rollout record')
  }
  if (relay.rollout !== undefined && relay.rollout !== null) {
    throw new Error('relay verbatim rejected: relay must not supply the rollout record')
  }
  if (rollout.source !== INDEPENDENT_ROLLOUT_SOURCE) {
    throw new Error('relay verbatim rejected: rollout record not from the independent read-only subagent')
  }
  assertReadOnlyFirstBootstrap(relay.bootstrap_argv)
  assertResumeSandboxConfig(relay.resume_argv, { needsLiveReads: relay.needs_live_reads === true })
  assertReviewWorktreeImmutable(relay.worktree_before, relay.worktree_after)
  const verified = verifyRelayVerbatim(resolvedRuntime, claimedSessionId, relay.payload, rollout.data)
  return { verdict_payload: verified.final_message, session_id: claimedSessionId, runtime: verified }
}

export function acceptOpenaiReviewRelay(role, resolvedRuntime, relay, rollout) {
  return acceptRelayVerdict(
    OPENAI_REVIEWER_ROLES, 'an OpenAI reviewer role', role, resolvedRuntime, relay, rollout,
  )
}

export function acceptShapingReviewRelay(role, resolvedRuntime, relay, rollout) {
  return acceptRelayVerdict(
    SHAPING_REVIEWER_ROLES, 'a shaping-review relay role', role, resolvedRuntime, relay, rollout,
  )
}
