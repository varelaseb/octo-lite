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
    { title: 'Acceptance' },
    { title: 'Reconcile' },
  ],
}

// The Workflow tool requires `export const meta` to be the first statement and runs this script in a
// sandbox with NO Node.js API: no module load, no node builtin. So this script is fully
// self-contained. The gate helpers below are embedded inline, byte-identical to the node-tested
// canonical source workflows/lib/gates.mjs with only the `export ` keyword stripped, delimited by the
// two stable markers below and drift-guarded by tests/test_conformance.py. gates.mjs remains the
// canonical, unit-tested source under node --test (tests/gates.test.mjs).
//
// ADR 0003 (drop the loop trust-root and retire the observer): the loop-entry trust root is removed
// wholesale. There is no provision-record read, no frozen-environment seam, no environment-equals
// -record cross-check, no launch-revision revalidation, no ack-echo two-phase gate, no independent
// git-read / observer replay, and no pre-push readback. The loop derives its worktree from the process
// working directory (cwd) and its branch from git and runs (loop-runs-on-cwd-and-branch): six modes,
// each of which spawns the right resolved role, moves the tracker state at the mode boundary, and posts
// evidence; the acceptance mode builds, posts, and sends the acceptance package and NEVER self-accepts.
// The fresh adversarial code-reviewer is the delivery-TDD guard and the host pushes the verified branch
// directly (delivery-tdd-reviewer-guard). The RETAINED OpenAI reviewer relay-provenance gate stays for
// cross-model review integrity (role-openai-relay, role-openai-fail-closed).
// GATES-EMBED-BEGIN
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
function assertRepoSlug(value, label) {
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
function requiredPrNumber(value, label) {
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

// Manifest-shape admission (role-runtime launch-receipt-manifest-shapes, launch-receipt-persistent):
// exactly one durable receipt shape remains, the generic persistent launch receipt for role
// meta-operator or orchestrator carrying no pass purpose; every worker pass, including reconcile,
// binds through the workflow journal under the role-purpose-capability matrix.
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

// Readiness envelope (delivery-lifecycle delivery-entry-gate, shaping-state; role-runtime
// launch-linear-state-gate). The loop derives its worktree from the process cwd and its branch from
// git (loop-runs-on-cwd-and-branch); readiness still validates the bound shaping verdict, the exact
// head, the canonical repo slug, the PR number (never a URL), and worktree containment before the one
// mechanical Shaped -> Todo fire, but performs no provision-record read or launch-revision check.
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

// QA-review acceptance (delivery-lifecycle qa-verdict, qa-acceptance-chain): a satisfied verdict with
// every criterion pass advances to the acceptance package; otherwise it returns the non-pass findings.
function acceptQaReview(expectedHead, expected, review) {
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
function buildAcceptancePackage(inputs) {
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

// A review-pass bootstrap must be read-only-first: the exec bootstrap selects the read-only sandbox
// before any workspace-write resume.
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

// Review-worktree immutability gate (role-runtime launch-review-sandbox-integrity): an OpenAI review
// pass must not mutate its worktree. status is the exact `git status --porcelain` output, empty for an
// unchanged worktree.
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

function acceptOpenaiReviewRelay(role, resolvedRuntime, relay, rollout) {
  return acceptRelayVerdict(
    OPENAI_REVIEWER_ROLES, 'an OpenAI reviewer role', role, resolvedRuntime, relay, rollout,
  )
}

function acceptShapingReviewRelay(role, resolvedRuntime, relay, rollout) {
  return acceptRelayVerdict(
    SHAPING_REVIEWER_ROLES, 'a shaping-review relay role', role, resolvedRuntime, relay, rollout,
  )
}
// GATES-EMBED-END

// POSIX single-quote one shell argument so a value carrying a space or a shell metacharacter cannot
// break the command or inject: wrap in single quotes and escape an embedded single quote as the
// standard '\''  sequence. Every interpolated value in a resolver command or a codex exec command a
// subagent runs is passed through this.
function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`
}

// This Workflow spawns every worker role pass natively as a fresh subagent (role-runtime
// launch-correctness-path, role-worker-migration). Worker binding proof is the workflow journal entry
// for the spawn. No worker TOML receipt exists. An OpenAI review role runs through a codex relay
// subagent brief with independent rollout provenance. Roles resolve through roles.toml; raw adapter
// files are never spawn inputs.

const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const mode = A.mode ?? 'implement'

// Schema-forced structured-result shapes. A worker echoes the bound issue and delivered facts; the
// loop no longer runs an ack-echo two-phase gate (ADR 0003), so the ack is a plain structured field.
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['head', 'verdict', 'findings', 'comment_url'],
  properties: {
    head: { type: 'string' },
    verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    comment_url: { type: 'string' },
  },
}

const SHAPING_REVIEW_SCHEMA = {
  type: 'object',
  required: ['head', 'verdict', 'findings', 'comment_url'],
  properties: {
    head: { type: 'string' },
    verdict: { enum: ['clear', 'blocking', 'ambiguous'] },
    findings: { type: 'array', items: { type: 'string' } },
    comment_url: { type: 'string' },
  },
}

// The implementer commits a spec-derived red then green on the isolated delivery branch and reports the
// distinct commit ids plus the bound test (path + digest). The fresh adversarial code-reviewer is the
// delivery-TDD guard (delivery-tdd-reviewer-guard); the loop performs no observer replay.
const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: [
    'issue', 'pr_url', 'branch', 'head', 'red_commit', 'green_commit',
    'validation', 'blocked',
  ],
  properties: {
    issue: { type: 'string' },
    pr_url: { type: 'string' },
    branch: { type: 'string' },
    head: { type: 'string' },
    red_commit: { type: 'string' },
    green_commit: { type: 'string' },
    final_commit: { type: 'string' },
    bound_test: {
      type: 'object',
      required: ['path', 'digest'],
      properties: { path: { type: 'string' }, digest: { type: 'string' } },
    },
    validation: { type: 'string' },
    summary: { type: 'string' },
    blocked: { type: 'boolean' },
    blocker: { type: 'string' },
  },
}

const CAPTURE_SCHEMA = {
  type: 'object',
  required: ['head', 'plan', 'manifest', 'artifacts', 'card_url', 'blocked'],
  properties: {
    head: { type: 'string' },
    plan: { type: 'array', items: { type: 'object' } },
    manifest: { type: 'string' },
    artifacts: { type: 'array', items: { type: 'string' } },
    card_url: { type: 'string' },
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
  required: ['head', 'verdict', 'issue', 'pr', 'manifest', 'criteria', 'packet_url'],
  properties: {
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
  required: ['command', 'exit_status', 'readback_state'],
  properties: {
    command: { type: 'string' },
    exit_status: { type: 'integer' },
    readback_state: { type: 'string' },
  },
}

const PUBLISH_SCHEMA = {
  type: 'object',
  required: ['card_url', 'readable'],
  properties: {
    card_url: { type: 'string' },
    readable: { type: 'boolean' },
  },
}

const SEND_SCHEMA = {
  type: 'object',
  required: ['sent'],
  properties: {
    sent: { type: 'boolean' },
    route: { type: 'string' },
  },
}

const REVIEWER_RUNTIME_SCHEMA = {
  type: 'object',
  required: ['provider', 'model', 'effort', 'service_tier', 'contract_blob', 'contract_text'],
  properties: {
    provider: { type: 'string' },
    model: { type: 'string' },
    effort: { type: 'string' },
    service_tier: { type: 'string' },
    contract_blob: { type: 'string' },
    contract_text: { type: 'string' },
  },
}

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

const RECONCILE_RESULT_SCHEMA = {
  type: 'object',
  required: ['classification', 'needs_fable', 'deltas'],
  properties: {
    classification: { enum: ['changed', 'missing', 'stale', 'contradictory', 'needs_fable', 'unchanged'] },
    needs_fable: { type: 'boolean' },
    deltas: { type: 'array', items: { type: 'string' } },
  },
}

function cycle() {
  const value = Number(A.cycle ?? 1)
  if (!Number.isInteger(value) || value < 1 || value > 3) throw new Error('cycle must be 1 through 3')
  return value
}

function specBlobs() {
  if (!Array.isArray(A.spec_blobs) || A.spec_blobs.length === 0) throw new Error('spec blobs required')
  return A.spec_blobs
}

// The canonical owner/repo gh identity is the A.repo_slug the host derived from the worktree remote and
// bound into the envelope. Every gh command in a subagent prompt is pinned to THIS slug so gh never
// infers the repository from the ambient (foreign lane) cwd. A.repo is the LOCAL PATH used for git -C.
function ghRepoSlug() {
  return requiredNonEmptyString(A.repo_slug, 'canonical GitHub repo slug (owner/repo)')
}

// The exact bound inputs for one worker pass. The workflow journal records this object at spawn time.
// ADR 0003 removed the launch-revision fingerprint and the ack-echo cross-check; the loop derives its
// worktree from cwd and its branch from git, so this binds the readiness-checked identity fields only.
function journalledBoundInputs(role, startingHead) {
  return {
    role,
    repo: required(A.repo, 'repo'),
    repo_slug: assertRepoSlug(A.repo_slug, 'repo_slug'),
    worktree: assertContainment(required(A.worktree_root, 'worktree root'), required(A.worktree, 'worker worktree')),
    issue: required(A.issue, 'issue'),
    pr: (requiredPrNumber(A.pr, 'pr'), A.pr),
    starting_head: required(startingHead, 'starting head'),
    spec_blobs: specBlobs(),
    contract_hash: required(A.contract_hash, 'contract hash'),
  }
}

// The COMPLETE, runnable role-resolver command carrying every required argument from the bound inputs
// (role-runtime role-machine-map, role-resolver, role-openai-relay). worktreeAbs is the contained
// absolute worktree path (worktree_root + worktree, containment-checked). The loop runs inside its
// provisioned worktree, so the resolver resolves from the current worktree.
function resolverCommand(role, worktreeAbs) {
  const repo = required(A.repo, 'repo')
  const spawnId = A.spawn_id ?? `${role}-${required(A.issue, 'issue')}-${required(A.starting_head ?? A.shaping_head ?? A.head, 'starting head')}`
  const parent = A.parent ?? 'orchestrator'
  const replyRoute = A.reply_route ?? A.pr_url ?? required(A.pr, 'pr')
  const executionLocation = A.execution_location ?? 'local'
  const reviewDelivery = A.review_delivery ?? A.pr_url ?? required(A.pr, 'pr')
  // The loop runs inside its provisioned worktree and derives paths from cwd; the resolver is the
  // worktree-relative role_resolver.py. Every interpolated value is POSIX single-quoted (residual 1).
  const resolverPath = 'workflows/lib/role_resolver.py'
  const parts = [
    'python3', resolverPath, 'resolve', role,
    '--spawn-id', shellQuote(spawnId),
    '--parent', shellQuote(parent),
    '--reply-route', shellQuote(replyRoute),
    '--repo', shellQuote(repo),
    '--worktree', shellQuote(worktreeAbs),
    '--execution-location', shellQuote(executionLocation),
    '--review-delivery', shellQuote(reviewDelivery),
    '--emit-contract',
  ]
  if (A.operator_loopback === true || A.operator_loopback === false) {
    parts.push('--operator-loopback', shellQuote(String(A.operator_loopback)))
  }
  const capabilities = Array.isArray(A.capabilities) ? A.capabilities : []
  for (const capability of capabilities) parts.push('--capability', shellQuote(capability))
  return parts.join(' ')
}

// Resolve one role's runtime FROM roles.toml through the role resolver in a read-only Explore subagent
// that runs the COMPLETE resolverCommand and returns the exact resolved provider, model, effort,
// service_tier, contract_blob, the canonical contract TEXT, and (for native workers) the resolved skill
// set. The loop cannot read files, so it never hardcodes any runtime field.
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

// Spawn a native delivery worker as a PLAIN role subagent (ADR 0003 decision-drop-loop-trust-root,
// role-worker-migration). No provision-record read, no live readback, no launch-revision revalidation,
// no ack-echo two-phase gate: the loop derives its worktree from cwd and its branch from git, resolves
// the role runtime from roles.toml, and spawns the resolved role with the canonical contract text and
// the per-pass brief. Containment is checked at admission and at spawn (launch-containment).
async function spawnWorker(role, phaseTitle, startingHead, schema) {
  assertAdmission({ purpose: 'delivery', role, linearState: required(A.linear_state, 'linear state') })
  const worktree = assertContainment(
    required(A.worktree_root, 'worktree root'),
    required(A.worktree, 'worker worktree'),
  )
  const bound = journalledBoundInputs(role, startingHead)
  const slug = ghRepoSlug()
  const pr = bound.pr
  log(`journal spawn ${role} ${bound.issue} ${bound.pr} ${bound.starting_head} ${bound.contract_hash}`)
  const brief = required(A.brief, 'pass brief')
  const runtime = await resolveRuntime(role, phaseTitle, worktree, WORKER_RUNTIME_SCHEMA, bound.issue)
  assertContainment(A.worktree_root, worktree)
  const prompt = [
    `You are a fresh octo-lite ${role}. One pass only. Never reuse a worker session.`,
    'CANONICAL ROLE CONTRACT (resolved from roles.toml; follow it exactly):',
    runtime.contract_text,
    `RESOLVED SKILLS (load these): ${JSON.stringify(runtime.skills)}`,
    'BOUND INPUTS: verify each against your own reads and stop before any mutation on any mismatch:',
    JSON.stringify(bound, null, 2),
    // Delivery TDD (delivery-tdd-committed-red, delivery-tdd-committed-green,
    // delivery-tdd-test-identity-binding): on the isolated delivery branch, first COMMIT a real failing
    // red (a new or changed spec-derived test that GENUINELY FAILS, plus unchanged production; a missing
    // file/module/export/script is NOT a valid red), then COMMIT the GREEN (production-only, making the
    // same named test pass, never editing the bound test). Bind the failing test by path and content
    // digest, unchanged red -> green -> final. Report red_commit, green_commit, final_commit, and
    // bound_test. The fresh adversarial code-reviewer is the delivery-TDD guard.
    'DELIVERY TDD: on the isolated delivery branch COMMIT a real failing red (a new or changed',
    'spec-derived test that genuinely fails, plus UNCHANGED production; a missing file/module/export/',
    'script is not a valid red), then COMMIT the production-only GREEN making the same named test pass',
    'without editing the bound test. Report red_commit, green_commit, final_commit, and bound_test',
    '{path, digest} unchanged across red, green, and final. Set head to your final delivered commit.',
    'Set blocked false on success. Do not push; the host pushes the verified branch after the fresh',
    'adversarial code-reviewer confirms red-fail, green-pass, and the unweakened bound test.',
    brief,
  ].join('\n\n')
  const result = await agent(prompt, {
    label: `${role}:${bound.issue}`, phase: phaseTitle, schema,
    model: runtime.model, effort: runtime.effort,
  })
  if (result === null) throw new Error(`${role} pass returned no result`)
  return result
}

// The single OpenAI relay spawn path for every OpenAI role (role-runtime role-openai-relay,
// role-openai-fail-closed). RETAINED by ADR 0003 for cross-model review integrity. admission is the
// exact purpose/role/linear-state gate the role's purpose requires (delivery for code-reviewer and
// qa-reviewer, shaping-review for shaping-reviewer); accept is the matching fail-closed relay
// acceptance gate. This path resolves the runtime FROM roles.toml, carries the real per-pass brief, the
// contained worktree path, and the canonical contract TEXT into the relay prompt, reads the rollout
// record through a SEPARATE independent Explore subagent, and binds the verdict from the verbatim relay
// payload. The OpenAI reviewer roles never use the plain spawnWorker path.
async function spawnOpenaiReviewer(role, phaseTitle, startingHead, schema, { admission, accept } = {}) {
  const admit = admission ?? { purpose: 'delivery', role, linearState: required(A.linear_state, 'linear state') }
  assertAdmission(admit)
  const acceptRelay = accept ?? acceptOpenaiReviewRelay
  const worktree = assertContainment(
    required(A.worktree_root, 'worktree root'),
    required(A.worktree, 'worker worktree'),
  )
  const bound = journalledBoundInputs(role, startingHead)
  log(`journal relay-spawn ${role} ${bound.issue} ${bound.pr} ${bound.starting_head} ${bound.contract_hash}`)
  const brief = required(A.brief, 'pass brief')
  assertContainment(A.worktree_root, worktree)
  // 1. Resolve the OpenAI runtime FROM roles.toml through the COMPLETE resolver command; the loop never
  // hardcodes provider/model/effort/service_tier and receives the canonical contract TEXT the relay carries.
  const runtime = await resolveRuntime(role, phaseTitle, worktree, REVIEWER_RUNTIME_SCHEMA, bound.issue)
  // 2. Relay subagent runs the codex exec for the resolved OpenAI runtime and returns the verbatim final
  // message plus the claimed session id, the exact bootstrap/resume argv, and the review worktree
  // HEAD+status before and after. It NEVER supplies the rollout record. The codex exec runs detached,
  // run-to-completion, resuming the SAME session on any cut (launch-review-background-resume,
  // launch-review-resume-not-restart). Read-only bootstrap-first via top-level -s read-only; resume
  // selects its sandbox ONLY through -c sandbox_mode (launch-resume-sandbox-config).
  const relayPrompt = [
    `You are a fresh octo-lite codex relay subagent for the OpenAI ${role} role. One pass only.`,
    'BOUND INPUTS (verify against your own reads before relaying):',
    JSON.stringify(bound, null, 2),
    'RESOLVED OPENAI RUNTIME to relay verbatim as the codex exec runtime:',
    JSON.stringify(
      { provider: runtime.provider, model: runtime.model, effort: runtime.effort, service_tier: runtime.service_tier },
      null, 2,
    ),
    `CONTAINED REVIEW WORKTREE (run codex exec with -C this exact path): ${worktree}`,
    `Operate ONLY on the host-pinned issue worktree at ${worktree}. Do NOT rely on the current working directory;`,
    'it may be a foreign lane worktree on a shared box.',
    `Capture the review worktree HEAD (\`git -C ${worktree} rev-parse HEAD\`) and \`git -C ${worktree} status`,
    '--porcelain` once BEFORE the bootstrap and again AFTER the resumed-to-completion pass; do not mutate the worktree.',
    'CANONICAL ROLE CONTRACT to pass VERBATIM as the codex exec prompt (never copy a workflow literal):',
    runtime.contract_text,
    'PER-PASS BRIEF for this exact pass:',
    brief,
    'Run the `codex exec` relay in the BACKGROUND, detached, RUN-TO-COMPLETION, carrying that exact model, effort, service tier, the contained worktree, and the canonical contract as the exec prompt.',
    'Do NOT run a single blocking timeout-bound codex exec: launch it detached via `nohup codex exec ... &` to a log file, then POLL to completion until the codex final assistant message exists.',
    'On ANY cut BEFORE the codex final assistant message exists, RESUME THE SAME session in the background via `codex exec resume <claimed_session_id>` (detached, run-to-completion). The claimed_session_id is STABLE across resumes.',
    'NEVER restart the pass from scratch and NEVER spawn a NEW session on a cut: a restart loses progress and creates provenance ambiguity.',
    'Bootstrap read-only first (-s read-only); if the pass needs live GitHub or Linear reads, resume with the sandbox selected ONLY through -c sandbox_mode="workspace-write" plus -c sandbox_workspace_write.network_access=true; NEVER use the top-level -s flag on resume.',
    'Return the codex final assistant message VERBATIM as payload (never summarize or edit it), the claimed_session_id, bootstrap_argv, resume_argv, needs_live_reads, worktree_before, and worktree_after. Do NOT read or return any codex rollout record; that is a separate reader.',
  ].join('\n\n')
  const relay = await agent(relayPrompt, {
    label: `${role}-relay:${bound.issue}`, phase: phaseTitle, schema: RELAY_SCHEMA,
  })
  if (relay === null) throw new Error(`${role} relay returned no result`)
  // 3. Independent read-only Explore subagent reads the codex rollout record for the claimed session id
  // under CODEX_HOME/sessions and returns the raw rollout data. This subagent is NEVER the relay, so the
  // fail-closed independent read-back is real.
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
  // Composite fail-closed acceptance: sandbox law, worktree immutability, independent provenance, and
  // relay-verbatim identity. A generic native worker pass, a relay-supplied rollout, an edited payload,
  // or a top-level -s resume all reject here.
  const accepted = acceptRelay(role, runtime, relay, rollout)
  // The verified rollout final message is the reviewer verdict payload; the reviewer verdict envelope is
  // bound from the relay pass strictly from that verbatim message.
  const verdict = await agent([
    `You are the ${role} verdict binder for this relay pass. One pass only; read-only.`,
    'The reviewer message is the verified verbatim codex final message below; bind the verdict',
    'envelope (verdict/findings/urls) strictly from it. Never re-author or soften it:',
    accepted.verdict_payload,
    brief,
  ].join('\n\n'), {
    label: `${role}:${bound.issue}`, phase: phaseTitle, schema, agentType: 'Explore',
  })
  if (verdict === null) throw new Error(`${role} verdict binding returned no result`)
  return verdict
}

async function spawnShapingReviewer(phaseTitle, startingHead, schema) {
  return spawnOpenaiReviewer('shaping-reviewer', phaseTitle, startingHead, schema, {
    admission: { purpose: 'shaping-review', role: 'shaping-reviewer', linearState: required(A.linear_state, 'linear state') },
    accept: acceptShapingReviewRelay,
  })
}

// Reconcile spawn path (role-runtime role-worker-migration, role-claude-native, role-reconciler-input,
// role-reconciler-authority, role-reconciler-escalation). The reconciler is Read-restricted and never
// mutates a source; it classifies deltas with needs_fable escalation.
async function spawnReconciler(phaseTitle) {
  const issue = required(A.issue, 'issue')
  const worktreeRoot = required(A.worktree_root, 'worktree root')
  const worktree = assertContainment(worktreeRoot, required(A.worktree, 'reconcile worktree'))
  assertAdmission({ purpose: 'reconcile', role: 'reconciler', readRestricted: true })
  assertManifestShape({ shape: 'worker-journal', role: 'reconciler', purpose: 'reconcile', readRestricted: true })
  const runtime = await resolveRuntime('reconciler', phaseTitle, worktree, WORKER_RUNTIME_SCHEMA, issue)
  const reconciled = await agent([
    `You are a fresh READ-ONLY octo-lite reconciler. One pass only; never mutate a source.`,
    'CANONICAL ROLE CONTRACT (resolved from roles.toml; follow it exactly):',
    runtime.contract_text,
    'Classify the delta between the durable sources and the live state as changed, missing, stale,',
    'contradictory, needs_fable, or unchanged. Missing, unparseable, or ambiguous input escalates',
    'with needs_fable so Fable judges. Return classification, needs_fable, and the deltas list.',
  ].join('\n'), {
    label: `reconciler:${issue}`, phase: phaseTitle, schema: RECONCILE_RESULT_SCHEMA, agentType: 'Explore',
  })
  if (reconciled === null) throw new Error('reconciler pass returned no result')
  return reconciled
}

// Loop fire (delivery-lifecycle linear-loop-fire-transition, delivery-entry-gate): the one mechanical
// Shaped -> Todo transition through octo-control linear-transition before any delivery worker spawns.
async function loopFire() {
  const issue = required(A.issue, 'issue')
  const controlArgs = required(A.loop_fire_args, 'loop fire control args')
  const fire = await agent([
    'Run exactly this command from the owning orchestrator context, then report it:',
    `octo-control linear-transition ${issue} --expected Shaped --target Todo ${controlArgs}`,
    'Return command, exit_status, and readback_state (the Linear state read back after the transition).',
    'Never substitute a different transition, target, or issue.',
  ].join('\n'), { label: `loop-fire:${issue}`, phase: 'Implement', schema: FIRE_SCHEMA, effort: 'low' })
  if (fire === null || fire.exit_status !== 0) {
    throw new Error('delivery spawn at Shaped rejected: Shaped -> Todo loop fire failed')
  }
  return fire
}

// Post one evidence card to the evidence site and read it back (delivery-lifecycle
// qa-publication-boundary, qa-served, edge-evidence-missing). A card that is not readable on the served
// site is not ready.
async function postEvidenceCard(phaseTitle, kind, head, manifest, artifacts) {
  const issue = required(A.issue, 'issue')
  const published = await agent([
    `You are a fresh octo-lite evidence publisher for the ${kind} card of ${issue}. One pass.`,
    `Publish the ${kind} evidence card for issue ${issue}, PR ${A.pr}, head ${head} to the evidence`,
    'site through the deterministic publication helper, then READ IT BACK from the served site.',
    `Manifest: ${manifest}. Artifacts: ${JSON.stringify(artifacts ?? [])}.`,
    'Return card_url (the served card link) and readable true only if the card is readable for the',
    'exact issue, PR, head, and criterion coverage. Never mutate the whole-operation dashboard.',
  ].join('\n'), { label: `publish-${kind}:${issue}`, phase: phaseTitle, schema: PUBLISH_SCHEMA, effort: 'low' })
  if (published === null || published.readable !== true) {
    throw new Error(`${kind} evidence card not readable on the served site`)
  }
  return requiredNonEmptyString(published.card_url, `${kind} evidence card URL`)
}

// ---- Mode dispatch (loop-runs-on-cwd-and-branch). Each mode spawns the right resolved role, moves the
// tracker state at the mode boundary, and posts evidence; acceptance builds+posts+sends the package. ----

if (mode === 'implement') {
  assertReadyEnvelope(A)
  // Delivery entry: at Shaped this loop performs the one mechanical Shaped -> Todo loop fire and verifies
  // the Todo readback before the implementer spawns (delivery-entry-gate, linear-loop-fire-transition);
  // Shaped never moves directly to In Progress. The single ruling-15 orchestrator-performed manual
  // Shaped -> Todo for TUR-447 is the one recorded non-recurring exception; every later member fires here.
  if (A.linear_state === 'Shaped') {
    const fired = await loopFire()
    if (fired.readback_state !== 'Todo') {
      throw new Error('delivery spawn at Shaped rejected: Todo readback missing after loop fire')
    }
    A.linear_state = fired.readback_state
  }
  const implementation = await spawnWorker('implementer', 'Implement', A.shaping_head, IMPLEMENT_SCHEMA)
  if (implementation.blocked) return { stage: 'blocked', gate: 'implement', implementation }
  return {
    stage: 'code-review-required', issue: A.issue, pr: A.pr, head: implementation.head,
    cycle: 1, implementation,
  }
}

if (mode === 'code-review') {
  const head = required(A.head, 'head')
  const reviewCycle = cycle()
  // The OpenAI code reviewer runs through the codex relay path with independent rollout provenance
  // (role-openai-relay, role-openai-fail-closed), NOT the generic native worker path. This is the
  // delivery-TDD guard (delivery-tdd-reviewer-guard).
  const review = await spawnOpenaiReviewer('code-reviewer', 'Code Review', head, REVIEW_SCHEMA)
  if (review.verdict === 'ambiguous') {
    return { stage: 'return-to-shaping', issue: A.issue, head, review }
  }
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
    // Backend-only work skips browser capture; a deterministic helper assembles the nonvisual packet
    // and the same publish/readback path serves it (qa-backend, qa-backend-packet, qa-backend-site).
    const cardUrl = await postEvidenceCard('QA Capture', 'nonvisual', head, required(A.manifest ?? 'backend-packet', 'backend manifest'), A.artifacts)
    return {
      stage: 'qa-review-required', issue: A.issue, head, card_url: cardUrl, user_facing: false,
      manifest: (A.manifest ?? 'backend-packet'),
      next: 'Run qa-review over the served backend card.',
    }
  }
  const capture = await spawnWorker('qa-capture', 'QA Capture', head, CAPTURE_SCHEMA)
  if (capture.blocked) return { stage: 'blocked', gate: 'qa-capture', capture }
  if (capture.head !== head) throw new Error('QA capture head mismatch')
  const cardUrl = await postEvidenceCard('QA Capture', 'visual', head, capture.manifest, capture.artifacts)
  return {
    stage: 'qa-review-required', issue: A.issue, head, capture, card_url: cardUrl,
    manifest: capture.manifest,
    next: 'Run qa-review over the served visual card.',
  }
}

if (mode === 'qa-review') {
  const head = required(A.head, 'head')
  if (!A.card_url || !A.manifest) throw new Error('served evidence card and manifest required')
  // The OpenAI qa-reviewer runs through the same codex relay path with independent rollout provenance
  // (role-openai-relay, role-openai-fail-closed), not the generic native worker path.
  const qaReview = await spawnOpenaiReviewer('qa-reviewer', 'QA Review', head, QA_REVIEW_SCHEMA)
  if (qaReview.verdict === 'ambiguous') return { stage: 'return-to-shaping', issue: A.issue, head, qa_review: qaReview }
  const gate = acceptQaReview(head, { issue: A.issue, pr: A.pr, manifest: A.manifest }, qaReview)
  return gate.advance
    ? {
        stage: 'acceptance-required', issue: A.issue, head, qa_review: qaReview, packet_url: gate.packet_url,
        next: 'Build the acceptance package, post it, and send it to the operator.',
      }
    : { stage: 'fix-required', trigger: 'qa-review', issue: A.issue, head, cycle: cycle(), findings: gate.findings }
}

if (mode === 'acceptance') {
  // Acceptance mode BUILDS the acceptance package, POSTS it to the evidence site, and SENDS it to the
  // operator, then returns awaiting-operator-acceptance. It NEVER self-accepts: actual acceptance stays
  // the human instruction and the meta-operator executes it (delivery-merge, linear-operator-authority,
  // qa-human-acceptance). No merge or Linear acceptance transition happens here.
  const head = required(A.head, 'head')
  const pkg = buildAcceptancePackage({
    issue: A.issue,
    pr: A.pr,
    head,
    code_review: required(A.code_review, 'code review verdict'),
    qa_review: required(A.qa_review, 'qa review verdict'),
    evidence_card_links: A.evidence_card_links ?? (A.card_url ? [A.card_url] : []),
    linear_state: required(A.linear_state, 'linear state'),
    summary: required(A.summary, 'what-changed summary'),
  })
  const posted = await agent([
    `You are a fresh octo-lite acceptance-package publisher for ${A.issue}. One pass.`,
    'Post this acceptance package to the evidence site through the deterministic publication helper,',
    'then read it back. Return card_url (the served package link) and readable true only if it serves:',
    JSON.stringify(pkg, null, 2),
  ].join('\n'), { label: `acceptance-publish:${A.issue}`, phase: 'Acceptance', schema: PUBLISH_SCHEMA, effort: 'low' })
  if (posted === null || posted.readable !== true) {
    throw new Error('acceptance package not readable on the served site')
  }
  const packageUrl = requiredNonEmptyString(posted.card_url, 'served acceptance package URL')
  const sent = await agent([
    `You are a fresh octo-lite operator relay for ${A.issue}. One pass; do not accept, merge, or transition.`,
    'SEND the acceptance package below and its served link to the operator for the acceptance decision.',
    `Served acceptance package: ${packageUrl}.`,
    'The operator DECIDES acceptance; no agent may infer, self-authorize, or execute acceptance here.',
    JSON.stringify(pkg, null, 2),
    'Return sent true and the route.',
  ].join('\n'), { label: `acceptance-send:${A.issue}`, phase: 'Acceptance', schema: SEND_SCHEMA, effort: 'low' })
  if (sent === null || sent.sent !== true) {
    throw new Error('acceptance package was not sent to the operator')
  }
  return {
    stage: 'awaiting-operator-acceptance', issue: A.issue, head,
    package: pkg, package_url: packageUrl, sent_route: sent.route ?? null,
    next: 'Operator may accept or reject. No agent may infer, self-authorize, or execute acceptance.',
  }
}

if (mode === 'reconcile') {
  const reconciled = await spawnReconciler('Reconcile')
  return {
    stage: reconciled.needs_fable ? 'reconcile-needs-fable' : 'reconcile-classified',
    issue: A.issue, classification: reconciled.classification,
    needs_fable: reconciled.needs_fable, deltas: reconciled.deltas,
    next: reconciled.needs_fable
      ? 'Fable judges the escalated reconcile case; no agent resolves ambiguity.'
      : 'Reconcile classification bound to the durable journal.',
  }
}

if (mode === 'shaping-review') {
  const head = required(A.head ?? A.shaping_head, 'head')
  const shapingReview = await spawnShapingReviewer('Shaping Review', head, SHAPING_REVIEW_SCHEMA)
  return { stage: 'shaping-review-verdict', issue: A.issue, head, shaping_review: shapingReview }
}

throw new Error(`unknown mode: ${mode}`)
