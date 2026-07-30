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

// Worktree containment (role-runtime launch-containment, launch-containment-integrity,
// launch-containment-sandbox-safe, launch-containment-sandbox-guard): containment is a git-LINKAGE
// OWNERSHIP property, not path-prefix nesting. The candidate BELONGS to the repository iff its
// git-common-dir equals the repository's own git-common-dir, so a sibling worktree (`git worktree add
// ../name`, whose common-dir resolves back to that repository) and the repository's own top-level
// working tree (equal common-dir) are both admitted, while a path whose git linkage belongs to ANOTHER
// repository (a different common-dir) is rejected as an escape. This gate runs inside the delivery-loop
// Workflow interpreter, which has no host process, no filesystem, and no module access, so it NEVER
// reads git linkage itself: real git is the linkage authority (git rev-parse --git-common-dir already
// validates a genuine worktree) and the read-only delivery-entry derivation agent host-derives both
// absolute common-dirs on the host. The gate is a PURE equality of the two supplied common-dirs; on
// admit it resolves and returns the candidate worktree path (worktreeRoot + worktreePath). Checked at
// admission and at every child subagent spawn.
export function assertContainment(worktreeRootCommonDir, worktreeCommonDir, worktreeRoot, worktreePath) {
  required(worktreeRootCommonDir, 'repository git-common-dir')
  required(worktreeCommonDir, 'worktree git-common-dir')
  if (posixResolve(worktreeRootCommonDir) === posixResolve(worktreeCommonDir)) {
    return posixResolve(worktreeRoot, worktreePath)
  }
  throw new Error(`worktree ${worktreePath} escapes worktree root ${worktreeRoot}`)
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

// Sandbox-law predicates (role-runtime launch-review-sandbox-integrity, launch-resume-sandbox-config,
// launch-review-least-privilege). A review pass is read-only end to end: read-only plus no-network is
// the whole grant. gh#60 terminal allowlist: the resume-sandbox gate is FORM-INDEPENDENT AND
// ALIAS-INDEPENDENT BY CONSTRUCTION. Enumerating privilege flags can never be complete (the --yolo
// alias of --dangerously-bypass-approvals-and-sandbox failed open, and future aliases would too), so
// the gate STOPS enumerating privilege and instead ALLOWLISTS the tiny set of benign flags a reviewer
// resume ever carries. The relay legitimately emits exactly:
//   codex exec resume --json -m <model> -c model_reasoning_effort="..." -c service_tier="..." \
//       -c sandbox_mode="read-only" <session-id> -
// so the ONLY flags on the benign allowlist are --json (boolean), -m/--model (value), and -c/--config
// (value); the only positionals are codex, exec, resume, exactly one session-id token, and a bare -.
// Any token that begins with - and is not a bare - must resolve to one of those benign options in any
// clap spelling (attached -mVALUE/--model=VALUE/-cENTRY/--config=ENTRY or separated -m VALUE etc); ANY
// other flag -- -s, --sandbox, --dangerously-bypass-approvals-and-sandbox, --yolo, or any unknown flag
// -- is not on the allowlist and is rejected, which closes every privilege alias without enumerating
// it. Over the -c/--config entries exactly one sandbox_mode=read-only is required, and any
// workspace-write, danger-full-access, network-access, or sandbox_workspace_write content is rejected.

function stripSurroundingQuotes(value) {
  const first = value.charAt(0)
  if (value.length >= 2 && (first === '"' || first === "'") && value.charAt(value.length - 1) === first) {
    return value.slice(1, -1)
  }
  return value
}

// Walk the resume argv over the benign-flag allowlist and collect the -c/--config entries. Positionals
// (codex, exec, resume, the session id, and a bare -) carry no flags and are skipped; --json is a
// benign boolean; -m/--model consumes a benign model value (attached or separated); -c/--config
// consumes a config entry (attached or separated). ANY other token that begins with - is a
// forbidden/unrecognized resume flag and is rejected. Config entries are parsed key=value on the FIRST
// =, key and value trimmed, surrounding matched quotes stripped from the value.
function collectBenignResumeConfig(argv) {
  const configValues = []
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i]
    if (typeof token !== 'string') continue
    if (!token.startsWith('-') || token === '-') continue // positional (session id, bare - stdin)
    if (token === '--json') continue // benign boolean
    if (token === '-m' || token === '--model') { i += 1; continue } // separated model value
    if (token.startsWith('--model=')) continue // attached long model value
    if (token.startsWith('-m') && token.length > 2) continue // attached short model value
    if (token === '-c' || token === '--config') { // separated config value
      if (typeof argv[i + 1] === 'string') configValues.push(argv[i + 1])
      i += 1
      continue
    }
    if (token.startsWith('--config=')) { configValues.push(token.slice('--config='.length)); continue }
    if (token.startsWith('-c') && token.length > 2) { configValues.push(token.slice(2)); continue }
    throw new Error(`resume sandbox rejected: forbidden or unrecognized resume flag ${token}`)
  }
  return configValues.map((raw) => {
    const eq = raw.indexOf('=')
    if (eq === -1) return { key: raw.trim(), value: '' }
    return { key: raw.slice(0, eq).trim(), value: stripSurroundingQuotes(raw.slice(eq + 1).trim()) }
  })
}

export function assertResumeSandboxConfig(resumeArgv) {
  requiredNonEmptyArray(resumeArgv, 'resume argv')
  const configEntries = collectBenignResumeConfig(resumeArgv)
  // Zero *network_access* entries.
  if (configEntries.some((entry) => entry.key.includes('network_access'))) {
    throw new Error('resume sandbox rejected: read-only resume grants no network_access')
  }
  // Zero sandbox_workspace_write.* entries.
  if (configEntries.some((entry) => entry.key.startsWith('sandbox_workspace_write.'))) {
    throw new Error('resume sandbox rejected: read-only resume grants no sandbox_workspace_write config')
  }
  // No config entry whose value is workspace-write or danger-full-access, in any spelling.
  if (configEntries.some((entry) => entry.value === 'workspace-write' || entry.value === 'danger-full-access')) {
    throw new Error('resume sandbox rejected: reviewer resume must stay sandbox_mode=read-only')
  }
  // gh#60 config-KEY allowlist: the benign reviewer-resume -c keys are exactly sandbox_mode,
  // model_reasoning_effort, service_tier. Any other key (future_privilege, sandbox_permissions
  // disk-access, ...) is rejected by absence - form-independent, no bad-key enumeration.
  const allowedResumeConfigKeys = new Set(['sandbox_mode', 'model_reasoning_effort', 'service_tier'])
  const unrecognizedKey = configEntries.find((entry) => !allowedResumeConfigKeys.has(entry.key))
  if (unrecognizedKey) {
    throw new Error(`resume sandbox rejected: unrecognized resume config key '${unrecognizedKey.key}'`)
  }
  // Exactly one sandbox_mode config entry, and its value is exactly read-only.
  const modes = configEntries.filter((entry) => entry.key === 'sandbox_mode').map((entry) => entry.value)
  if (modes.length !== 1) {
    throw new Error('resume sandbox rejected: exactly one -c sandbox_mode config required')
  }
  if (modes[0] !== 'read-only') {
    throw new Error('resume sandbox rejected: reviewer resume must stay sandbox_mode=read-only')
  }
  return { sandbox_mode: 'read-only' }
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
  assertResumeSandboxConfig(relay.resume_argv)
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
