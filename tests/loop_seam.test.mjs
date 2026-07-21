// TUR-447 D1 cycle4 PRODUCTION-SEAM delivery-TDD fidelity proof (delivery-lifecycle
// delivery-tdd-observer-inputs-host-sourced, delivery-tdd-observer-inputs-host-journal-record,
// delivery-tdd-named-test-forgery-reject, delivery-tdd-no-forgeable-attestation,
// delivery-tdd-independent-observer, delivery-tdd-final-head-verification,
// delivery-tdd-final-head-test-identity, delivery-tdd-committed-red-commit; role-runtime
// role-tdd-observer, role-tdd-observer-host-sourced-inputs, role-implementer-host-gated-push).
//
// The D1 cycle-3 codex gate flagged a TEST-FIDELITY defect: the delivery-TDD fail-closed proofs
// exercised a standalone helper (deriveIndependentGitRead) and a test-reimplemented observer
// (observeFromGit) over a real repo, but did NOT prove the REAL production SEAM fails closed. In
// the deployed Workflow runtime the production reader/observer are SUBAGENTS whose returned outputs
// are validated by the gates INSIDE deliverCommittedPass; deriveIndependentGitRead is never called
// on that path. So a broken assertIndependentGitRead / assertWorkerClaimCrossCheck / observer
// confirmation IN deliverCommittedPass could have shipped while the helper-driven tests stayed green.
//
// This suite drives the ACTUAL production function deliverCommittedPass (through the loop's implement
// mode, exactly as the Workflow tool runs it) with the composed harness's mocked GLOBAL agent(),
// returning chosen git-read / observer / push outputs per spawn label. It proves the production
// wiring: (1) ACCEPTS a good/consistent set of agent outputs (reaches the host-gated push); (2)
// REJECTS forged/bad agent outputs AT THE REAL GATES in deliverCommittedPass; and (3) is FAIL-CLOSED
// at the SEAM: BREAKING the production wiring (removing assertIndependentGitRead,
// assertWorkerClaimCrossCheck, or the observer confirmation from deliverCommittedPass in a SCRATCH
// mutant of the loop source) makes the corresponding rejection flip to a non-rejection, proving each
// gate is LOAD-BEARING on the production path, not a dead helper.

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { launchRevision } from '../workflows/lib/gates.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const LOOP_SRC = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8')

// The loop is not a module: it uses bare Workflow globals (agent, args, log) and top-level `return`
// in mode branches. Strip `export ` and wrap the whole source in an async function whose params ARE
// the injected globals, exactly as loop_composed.test.mjs does. `mutate` optionally rewrites the
// source FIRST, to break one production-seam gate call in a scratch copy; the healthy build passes
// mutate through unchanged, so both builds run the identical production mode logic.
function loadLoop(mutate = (src) => src) {
  const stripped = mutate(LOOP_SRC).replace(/^export /gm, '')
  // eslint-disable-next-line no-new-func
  const factory = new Function(
    'agent', 'args', 'log',
    `return (async () => { ${stripped}\n })()`,
  )
  return factory
}

// A scratch mutant removes exactly ONE production-seam gate call from deliverCommittedPass (or the
// independent-read gate the seam depends on). Each replacement target is a UNIQUE line in the loop
// source; if a target ever stops matching, the assertion below fails loudly rather than silently
// mutating nothing.
function removeSeamGate(src, target, replacement) {
  assert.ok(src.includes(target), `seam mutant target not found (loop source drifted): ${target}`)
  return src.replace(target, replacement)
}

// Break the independent git-read gate: the reader's returned `read` object flows through UNVALIDATED
// (assertIndependentGitRead removed), so a read that claims a red which never failed is no longer
// rejected at the seam.
const BREAK_INDEPENDENT_READ = (src) => removeSeamGate(
  src,
  'return assertIndependentGitRead(read, { branch, expectedStartingHead })',
  'return { red_commit: read.red_commit, green_commit: read.green_commit, final_commit: read.final_commit, branch, boundTest: read.red_test }',
)
// Break the worker-claim cross-check: the worker's claimed shas are trusted without cross-checking
// them against the independent read, so a forged/cherry-picked worker final sha is no longer rejected.
const BREAK_CROSS_CHECK = (src) => removeSeamGate(
  src,
  'trustRoot = assertWorkerClaimCrossCheck(independentRead, acceptedCommits)',
  'trustRoot = { redCommit: independentRead.red_commit, greenCommit: independentRead.green_commit, finalCommit: independentRead.final_commit }',
)
// Break the observer confirmation: the independent observation is never consumed, so an observation
// whose red did not fail (or whose final HEAD is not green) is no longer rejected at the seam.
const BREAK_OBSERVER = (src) => removeSeamGate(
  src,
  'assertObservedCommittedStates(observation, binding, boundTest)',
  'void observation; void binding; void boundTest',
)

// --- Composed-harness fixtures (mirrors loop_composed.test.mjs) --------------------------------
const REPO = '/root/octo-lite'
const REPO_SLUG = 'varelaseb/octo-lite'
const ISSUE = 'TUR-447'
// TUR-447 ruling-56 cycle3 slug-identity-bound: the canonical gh identity is the PR NUMBER + --repo
// <slug>, never a URL. The prior fixture bound a foreign x/y URL that OVERRODE --repo and hid the
// foreign-repo bug; the PR is now the number 6 and the PR web URL names the CANONICAL repo slug.
const PR = 6
const PR_URL = `https://github.com/${REPO_SLUG}/pull/6`
const WORKTREE_ABS = '/root/octo-lite'
const BRANCH = 'octo-lite/tur-443-operating-model'
const HEAD = 'f00b13357cb1be87b5c5e6d7bd98fd9572915154'
const SPEC_BLOBS = ['spec/domains/role-runtime.spec.html:anchor-1']
const CONTRACT = 'c8b0440cacc5188b2926b626ee6f506ced5368ebbda67dc6b1ed0d542cddc34c'

const FINGERPRINTS = { Shaped: 'fp-shaped-a1', Todo: 'fp-todo-b2', Backlog: 'fp-backlog-c3' }
function fingerprintFor(state) {
  const fp = FINGERPRINTS[state]
  if (!fp) throw new Error(`seam harness: no fingerprint modelled for state ${state}`)
  return fp
}

function boundInputs(role) {
  return {
    role, repo: REPO, repo_slug: REPO_SLUG, worktree: WORKTREE_ABS, issue: ISSUE, pr: PR,
    starting_head: HEAD, spec_blobs: SPEC_BLOBS, contract_hash: CONTRACT,
  }
}

function ackFor(role, overrides = {}) {
  const b = boundInputs(role)
  return {
    role: b.role, repo: b.repo, repo_slug: b.repo_slug, worktree: b.worktree,
    issue: b.issue, pr: b.pr,
    starting_head: b.starting_head, spec_blobs: b.spec_blobs, contract_hash: b.contract_hash,
    ...overrides,
  }
}

// TUR-447 ruling-59 host-trusted identity anchors (host-provisioned receipt + receipt-pinned live
// worktree read) the loop reads BEFORE the fire and before the spawn.
function receiptFor(overrides = {}) {
  return {
    source: 'host-provisioned-receipt', repo: REPO, repo_slug: REPO_SLUG,
    worktree: WORKTREE_ABS, starting_head: HEAD, ...overrides,
  }
}
function worktreeRealityFor(overrides = {}) {
  return {
    source: 'host-receipt-pinned-worktree-read', read_worktree: WORKTREE_ABS,
    head: HEAD, branch: BRANCH, repo_slug: REPO_SLUG, ...overrides,
  }
}

function readyEnvelope(overrides = {}) {
  const base = {
    mode: 'implement',
    repo: REPO, repo_slug: REPO_SLUG, issue: ISSUE, pr: PR, pr_url: PR_URL, branch: BRANCH,
    shaping_head: HEAD, pr_head: HEAD, pr_base: 'main',
    spec_revision: 'r1', linear_revision: 'lr1', topology_revision: 't1',
    linear_fingerprint: fingerprintFor('Shaped'), linear_state: 'Shaped',
    shaping_verdict: 'clear', shaping_verdict_head: HEAD,
    shaping_reviewer_receipt: 'rcpt-1', conversation_cutoff: 'session.jsonl:1',
    conversation_log_references: ['session.jsonl:1-1'],
    spec_blobs: SPEC_BLOBS, adr_blobs: [], shaping_verdict_inputs: ['in-1'],
    acceptance_criteria: ['works'],
    contract_hash: CONTRACT,
    brief: 'do the work',
    worktree_root: '/root', worktree: 'octo-lite',
    loop_fire_args: '--reason ship',
    spawn_id: 'spawn-tur447-1', parent: 'orchestrator', reply_route: PR_URL,
    review_delivery: 'pr-comment', execution_location: 'local',
    starting_head: HEAD,
  }
  const merged = { ...base, ...overrides }
  merged.launch_revision = launchRevision(boundInputs('implementer'))
  return merged
}

function freshReads(overrides = {}) {
  return {
    linear_state: 'Todo', linear_fingerprint: fingerprintFor('Todo'),
    pr_head: HEAD, branch: BRANCH, git_head: HEAD,
    ...overrides,
  }
}

function makeAgent(script) {
  const calls = []
  async function agent(prompt, opts = {}) {
    const label = opts.label ?? ''
    calls.push({ label, agentType: opts.agentType ?? null, phase: opts.phase, prompt, opts })
    for (const [matcher, responder] of script) {
      if (label.startsWith(matcher)) {
        return typeof responder === 'function' ? responder({ prompt, opts, calls }) : responder
      }
    }
    throw new Error(`seam harness: no scripted response for label ${label}`)
  }
  agent.calls = calls
  return agent
}

const noop = () => {}

const RESOLVED_WORKER_RUNTIME = {
  provider: 'anthropic', model: 'claude-sonnet-5', effort: 'xhigh', service_tier: 'default',
  contract_blob: 'wk-contract-blob', contract_text: '# Implementer\ncanonical contract text',
  skills: ['tdd', 'commit'],
}

const SCENARIO = 'shaped-member-fires-todo'
const RED_COMMIT = 'redc0mm1t0000000000000000000000000000001'
const GREEN_COMMIT = 'greenc0mm1t000000000000000000000000000002'
const FINAL_COMMIT = 'f1nalc0mm1t000000000000000000000000000003'
const BOUND_TEST = { path: 'tests/loop_composed.test.mjs', digest: 'sha256:boundtestdigest' }
const VALIDATION_COMMAND = 'node --test tests/'

function gitReadFor(overrides = {}) {
  return {
    source: 'independent-git-read', read_by: 'git-reader-subagent-1', mutating_worker: 'implementer-subagent',
    isolated_worktree: '/root/octo-lite-git-read-wt', branch: BRANCH, base_head: HEAD,
    red_commit: RED_COMMIT, green_commit: GREEN_COMMIT, final_commit: FINAL_COMMIT,
    ancestry: [RED_COMMIT, GREEN_COMMIT, FINAL_COMMIT],
    red_diff_kind: 'test-only', red_named_test_exit: 1, red_test: { ...BOUND_TEST },
    green_diff_kind: 'production-only', green_named_test_exit: 0, green_test: { ...BOUND_TEST },
    final_named_test_exit: 0, final_test: { ...BOUND_TEST },
    ...overrides,
  }
}

function observationFor(overrides = {}) {
  return {
    source: 'independent-tdd-observer', observed_by: 'observer-subagent-1', mutating_worker: 'implementer-subagent',
    isolated_worktree: '/root/octo-lite-tdd-observer-wt', command: VALIDATION_COMMAND,
    red_commit: RED_COMMIT, red_exit: 1, red_output: 'AssertionError: expected reshaped delivery\n1 failing',
    red_test: { ...BOUND_TEST },
    green_commit: GREEN_COMMIT, green_exit: 0, green_output: 'ok\nall passing', green_test: { ...BOUND_TEST },
    final_commit: FINAL_COMMIT, final_exit: 0, final_output: 'ok\nall passing', final_test: { ...BOUND_TEST },
    ...overrides,
  }
}

function implementScript({
  fresh = freshReads(), red, green, mutationAck = ackFor('implementer'),
  fireState = 'Todo', fireFingerprint = fingerprintFor('Todo'),
  mutationOverrides = {}, prePush, gitRead = gitReadFor(), observation = observationFor(), postPush,
  liveness = { linear_state: 'Todo', linear_fingerprint: fingerprintFor('Todo'), branch: BRANCH },
  receipt = receiptFor(), reality = worktreeRealityFor(),
} = {}) {
  const goodRed = red ?? {
    command: VALIDATION_COMMAND, exit_status: 1, outcome: 'FAIL: behavior wrong',
    artifact: `${PR_URL}#c1`, head: RED_COMMIT, scenario: SCENARIO,
  }
  const goodGreen = green ?? {
    command: VALIDATION_COMMAND, exit_status: 0, outcome: 'PASS: behavior right',
    artifact: `${PR_URL}#c2`, head: FINAL_COMMIT, scenario: SCENARIO,
  }
  const goodPrePush = prePush ?? freshReads({ git_head: FINAL_COMMIT })
  return [
    // TUR-447 ruling-59 host-trusted identity anchors, read before the fire and before the spawn.
    ['implementer-receipt:', receipt],
    ['implementer-worktree-reality:', reality],
    ['loop-fire:', {
      command: 'octo-control linear-transition', exit_status: 0,
      readback_state: fireState, readback_fingerprint: fireFingerprint,
    }],
    ['implementer-readback:', fresh],
    ['implementer-runtime:', RESOLVED_WORKER_RUNTIME],
    ['implementer-ack:', { ack: ackFor('implementer') }],
    ['implementer:', {
      ack: mutationAck, issue: ISSUE, pr_url: PR_URL, branch: BRANCH, head: FINAL_COMMIT,
      handoff_url: `${PR_URL}#h`, red: goodRed, green: goodGreen, validation: 'suite', blocked: false,
      committed: true, pushed: false,
      red_commit: RED_COMMIT, green_commit: GREEN_COMMIT, final_commit: FINAL_COMMIT,
      bound_test: { ...BOUND_TEST },
      linear_state: liveness.linear_state, linear_fingerprint: liveness.linear_fingerprint,
      ...mutationOverrides,
    }],
    ['implementer-git-read:', gitRead],
    ['implementer-tdd-observer:', observation],
    ['workspace-abandon:', { abandoned: true, pushed: false, dirty: false, head: FINAL_COMMIT, status: '' }],
    ['workspace-cleanup:', { cleaned: true, head: HEAD, status: '' }],
    ['implementer-prepush-readback:', goodPrePush],
    ['host-push:', { pushed: true, head: FINAL_COMMIT }],
    ['implementer-postpush-readback:', postPush ?? { remote_head: FINAL_COMMIT, remote_source: 'git-ls-remote' }],
  ]
}

function committedEnvelope(overrides = {}) {
  return readyEnvelope({ validation_command: VALIDATION_COMMAND, ...overrides })
}

// Drive the production seam once and return { result?, error?, calls }. The intact loop runs the
// real deliverCommittedPass; a mutant runs it with one seam gate removed.
async function driveSeam(mutate, scriptOpts = {}) {
  const factory = loadLoop(mutate)
  const agent = makeAgent(implementScript(scriptOpts))
  const A = committedEnvelope()
  try {
    const result = await factory(agent, JSON.stringify(A), noop)
    return { result, calls: agent.calls }
  } catch (error) {
    return { error, calls: agent.calls }
  }
}

const IDENTITY = (src) => src // healthy build: no mutation

// === (1) The production seam ACCEPTS a good/consistent set of agent outputs ======================
test('seam-accept: deliverCommittedPass ACCEPTS a good/consistent set of mocked agent outputs and reaches the host-gated push', async () => {
  const { result, error, calls } = await driveSeam(IDENTITY)
  assert.equal(error, undefined, 'no rejection on the healthy consistent path')
  assert.equal(result.stage, 'code-review-required')
  assert.equal(result.head, FINAL_COMMIT)
  // The healthy path reached the real host-gated push and the live-remote readback INSIDE the seam.
  assert.ok(calls.some((c) => c.label.startsWith('host-push:')), 'reached the host-gated push')
  assert.ok(calls.some((c) => c.label.startsWith('implementer-postpush-readback:')), 'reached the live-remote readback')
  // It reached the real git-read and observer spawns of deliverCommittedPass, in order.
  const gr = calls.findIndex((c) => c.label === `implementer-git-read:${ISSUE}`)
  const obs = calls.findIndex((c) => c.label === `implementer-tdd-observer:${ISSUE}`)
  const push = calls.findIndex((c) => c.label.startsWith('host-push:'))
  assert.ok(gr >= 0 && obs > gr && push > obs, 'git-read -> observer -> push order at the seam')
})

// === (2) The production seam REJECTS forged/bad agent outputs AT THE REAL GATES ==================

test('seam-reject: a git-read output claiming a RED that did not fail is REJECTED by assertIndependentGitRead in deliverCommittedPass', async () => {
  const { error, calls } = await driveSeam(IDENTITY, { gitRead: gitReadFor({ red_named_test_exit: 0 }) })
  assert.match(error.message, /the red commit did not fail the named test/)
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed')
})

test('seam-reject: a worker-claimed sha differing from the independent reader is REJECTED by assertWorkerClaimCrossCheck', async () => {
  const forgedFinal = 'forgedFinalWorkerClaim000000000000000009'
  const { error, calls } = await driveSeam(IDENTITY, {
    mutationOverrides: { final_commit: forgedFinal, head: forgedFinal },
    green: {
      command: VALIDATION_COMMAND, exit_status: 0, outcome: 'PASS', artifact: `${PR_URL}#c2`,
      head: forgedFinal, scenario: SCENARIO,
    },
  })
  assert.match(error.message, /claimed final commit differs from the independent git read/)
  assert.ok(!calls.some((c) => c.label.startsWith('implementer-tdd-observer:')), 'observer never runs on a cross-check mismatch')
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed')
})

test('seam-reject: a relabelled/mis-digested worker bound test is REJECTED by assertWorkerBoundTestCrossCheck', async () => {
  const { error, calls } = await driveSeam(IDENTITY, {
    mutationOverrides: { bound_test: { path: 'tests/impostor_test.mjs', digest: BOUND_TEST.digest } },
  })
  assert.match(error.message, /claimed test path differs from the independently discovered bound test/)
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed')
})

test('seam-reject: an observer output that did not confirm the red FAIL is REJECTED by assertObservedCommittedStates', async () => {
  const { error, calls } = await driveSeam(IDENTITY, { observation: observationFor({ red_exit: 0 }) })
  assert.match(error.message, /the red commit did not fail the named test/)
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed')
})

test('seam-reject: an observer output whose FINAL HEAD is not green is REJECTED by assertObservedCommittedStates', async () => {
  const { error, calls } = await driveSeam(IDENTITY, { observation: observationFor({ final_exit: 1 }) })
  assert.match(error.message, /the final pushed HEAD is not green/)
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed')
})

test('seam-reject: a bound test WEAKENED at the final HEAD (real digest differs) is REJECTED by the observer confirmation', async () => {
  const { error, calls } = await driveSeam(IDENTITY, {
    observation: observationFor({ final_test: { path: BOUND_TEST.path, digest: 'sha256:weakened' } }),
  })
  assert.match(error.message, /bound test content digest differs at the final commit/)
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed')
})

test('seam-reject: a wrong branch base (not the expected starting HEAD) is REJECTED by assertIndependentGitRead', async () => {
  const { error, calls } = await driveSeam(IDENTITY, {
    gitRead: gitReadFor({ base_head: 'someUnrelatedBase00000000000000000000009' }),
  })
  assert.match(error.message, /branch base is not the expected starting HEAD/)
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed')
})

// === (3) FAIL-CLOSED at the SEAM: breaking the production wiring flips a rejection ===============
// Each of these takes a bad-output scenario the INTACT seam rejects, removes exactly the gate that
// catches it from deliverCommittedPass (or the independent read it depends on) in a SCRATCH mutant
// of the loop source, and proves the rejection DISAPPEARS. This proves the gate is LOAD-BEARING on
// the production deliverCommittedPass path, not a dead helper: without the gate call, the forged
// output flows through unchecked.

test('seam-fail-closed: REMOVING assertIndependentGitRead from deliverCommittedPass lets a non-failing red flow through (rejection disappears)', async () => {
  // First confirm the intact seam rejects.
  const intact = await driveSeam(IDENTITY, { gitRead: gitReadFor({ red_named_test_exit: 0 }) })
  assert.match(intact.error.message, /the red commit did not fail the named test/)
  // Now break the wiring: with assertIndependentGitRead removed, the git-read claiming a non-failing
  // red is no longer validated by the seam. The read still carries the (real) shas, so the pass
  // proceeds through the (unbroken) observer and reaches the push: the rejection is gone.
  const broken = await driveSeam(BREAK_INDEPENDENT_READ, { gitRead: gitReadFor({ red_named_test_exit: 0 }) })
  assert.equal(broken.error, undefined, 'removing assertIndependentGitRead drops the red-did-not-fail rejection')
  assert.ok(broken.calls.some((c) => c.label.startsWith('host-push:')), 'the broken seam reaches the push it should have gated')
})

test('seam-fail-closed: REMOVING assertWorkerClaimCrossCheck from deliverCommittedPass lets a forged worker final sha flow through (rejection disappears)', async () => {
  const forgedFinal = 'forgedFinalWorkerClaim000000000000000009'
  const scriptOpts = {
    mutationOverrides: { final_commit: forgedFinal, head: forgedFinal },
    green: {
      command: VALIDATION_COMMAND, exit_status: 0, outcome: 'PASS', artifact: `${PR_URL}#c2`,
      head: forgedFinal, scenario: SCENARIO,
    },
  }
  const intact = await driveSeam(IDENTITY, scriptOpts)
  assert.match(intact.error.message, /claimed final commit differs from the independent git read/)
  const broken = await driveSeam(BREAK_CROSS_CHECK, scriptOpts)
  assert.equal(broken.error, undefined, 'removing assertWorkerClaimCrossCheck drops the forged-sha rejection')
  // The forged worker claim is dropped; the independent-read shas are used, so the push confirms the
  // real final HEAD. The point is the SEAM no longer rejected the forged claim.
  assert.ok(broken.calls.some((c) => c.label.startsWith('host-push:')), 'the broken seam reaches the push it should have gated')
})

test('seam-fail-closed: REMOVING the observer confirmation from deliverCommittedPass lets a non-failing-red observation flow through (rejection disappears)', async () => {
  const intact = await driveSeam(IDENTITY, { observation: observationFor({ red_exit: 0 }) })
  assert.match(intact.error.message, /the red commit did not fail the named test/)
  const broken = await driveSeam(BREAK_OBSERVER, { observation: observationFor({ red_exit: 0 }) })
  assert.equal(broken.error, undefined, 'removing assertObservedCommittedStates drops the observer rejection')
  assert.ok(broken.calls.some((c) => c.label.startsWith('host-push:')), 'the broken seam reaches the push it should have gated')
})

test('seam-fail-closed: REMOVING the observer confirmation also drops the not-green FINAL-HEAD rejection', async () => {
  const intact = await driveSeam(IDENTITY, { observation: observationFor({ final_exit: 1 }) })
  assert.match(intact.error.message, /the final pushed HEAD is not green/)
  const broken = await driveSeam(BREAK_OBSERVER, { observation: observationFor({ final_exit: 1 }) })
  assert.equal(broken.error, undefined, 'removing assertObservedCommittedStates drops the not-green final-HEAD rejection')
  assert.ok(broken.calls.some((c) => c.label.startsWith('host-push:')), 'the broken seam reaches the push it should have gated')
})

// === Provenance at the seam: the production reader output flows THROUGH assertIndependentGitRead ==
// The production reader is an AGENT; its returned read is validated by assertIndependentGitRead in
// deliverCommittedPass (via independentGitRead). A read NOT stamped by the independent reader (a
// worker masquerading as the trust root) is rejected at that seam gate.
test('seam-provenance: a git-read NOT stamped by the independent reader is REJECTED at the seam (production output flows through assertIndependentGitRead)', async () => {
  const { error, calls } = await driveSeam(IDENTITY, { gitRead: gitReadFor({ source: 'implementer-subagent' }) })
  assert.match(error.message, /not from the independent git reader/)
  assert.ok(!calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed on a forged trust root')
})

// === TUR-447 ruling-55: canonical Linear fingerprint source pinned at all FOUR readback/liveness
// prompts (delivery-lifecycle launch-readback; loop-correctness single-writer). The bound-inputs
// envelope fingerprint and the octo-control linear-transition both derive from octo-control
// linear-read exact_fingerprint. Before this fix the readback/liveness subagents IMPROVISED (self-
// hashed) their own fingerprint, so assertLaunchReadback compared an improvised readback fingerprint
// against the canonical envelope fingerprint, they never matched, and a genuine unchanged Todo-entry
// launch was FALSE-REJECTED. The fix pins scripts/octo-control linear-read as the single canonical
// fingerprint source at all four prompts so readback and envelope are like-with-like. This is a
// SOURCE assertion over the real production loop text, not a mocked path: each of the four prompt
// regions must cite octo-control linear-read for the fingerprint and must NOT tell the subagent to
// improvise/recompute/self-hash it. It STRENGTHENS fail-closed: a real Linear content change still
// changes exact_fingerprint, so assertLaunchReadback still rejects a stale envelope.
const FINGERPRINT_SITES = [
  { name: 'liveReadback', anchor: 'You are a fresh READ-ONLY octo-lite readback subagent' },
  { name: 'worker-liveness-echo', anchor: 'LIVENESS ECHO: read the live Linear state' },
  { name: 'pre-push readback', anchor: 'You are a fresh READ-ONLY octo-lite pre-push readback' },
  { name: 'loopFire', anchor: 'readback_fingerprint (the post-fire Linear content fingerprint' },
]

function promptRegion(anchor) {
  const start = LOOP_SRC.indexOf(anchor)
  assert.ok(start >= 0, `fingerprint-source anchor missing from loop source: ${anchor}`)
  // The prompt array joins into a single agent() call; 1000 chars covers the fingerprint instruction.
  return LOOP_SRC.slice(start, start + 1000)
}

test('fingerprint-source: all four readback/liveness prompts cite octo-control linear-read as the single canonical fingerprint source', () => {
  for (const site of FINGERPRINT_SITES) {
    const region = promptRegion(site.anchor)
    assert.match(
      region, /octo-control linear-read/,
      `${site.name} must cite scripts/octo-control linear-read as the fingerprint source`,
    )
    assert.match(
      region, /returned\s+fingerprint field verbatim|fingerprint field verbatim/,
      `${site.name} must use the octo-control linear-read returned fingerprint field verbatim`,
    )
  }
})

test('fingerprint-source: no readback/liveness prompt tells the subagent to improvise or self-hash the Linear fingerprint', () => {
  for (const site of FINGERPRINT_SITES) {
    const region = promptRegion(site.anchor)
    // The instruction line must explicitly forbid an improvised/self-hashed fingerprint. All four
    // sites word it slightly differently, but every one names both improvise and self-hash.
    assert.match(
      region, /do NOT improvise[^.]*self-hash/i,
      `${site.name} must forbid an improvised/self-hashed fingerprint`,
    )
    // The pre-fix self-read phrasing paired linear_state AND linear_fingerprint on one line and told
    // the subagent to read the "live Linear state and content fingerprint" itself; that improvised
    // instruction must be gone (the fingerprint now comes only from octo-control linear-read).
    assert.doesNotMatch(
      region, /live Linear state and (content )?fingerprint/i,
      `${site.name} must not tell the subagent to self-read the content fingerprint`,
    )
  }
})

// === TUR-447 ruling-56: host-pin subagent cwd to the ISSUE worktree at every git-reading
// readback/liveness/pre-push/review prompt (delivery-lifecycle launch-readback; loop-correctness
// single-writer). On the shared box the loop readback/liveness/pre-push/review subagents run in an
// AMBIENT cwd that is a FOREIGN lane worktree, so a bare `git rev-parse HEAD` (or bare `git status`)
// read the WRONG worktree and the loop bound a stale/foreign HEAD. The fix pins EVERY such git op to
// the host-supplied issue worktree via `git -C ${worktree}` and forbids reliance on the ambient cwd.
// This is a SOURCE assertion over the real production loop text: each git-reading prompt region must
// interpolate `git -C ${worktree}` (never a bare cwd-dependent git) and must tell the subagent not to
// rely on the current working directory. It STRENGTHENS correctness on the shared box without
// weakening any gate: the pinned worktree is the host-contained issue worktree, containment-checked.
const CWD_PIN_SITES = [
  { name: 'liveReadback', anchor: 'You are a fresh READ-ONLY octo-lite readback subagent' },
  { name: 'pre-push readback', anchor: 'You are a fresh READ-ONLY octo-lite pre-push readback' },
  { name: 'host push', anchor: 'You are a fresh octo-lite host push subagent' },
  // TUR-447 ruling-56 cycle3: the worker-liveness echo reads live git (git -C ${worktree}) and the
  // live PR (repo-pinned gh), so it is in the cwd-pin AND gh-pin matrices.
  { name: 'worker-liveness-echo', anchor: 'LIVENESS ECHO: read the live Linear state' },
  // TUR-447 ruling-56 cycle2: the full git-reading site matrix must also cover the abort/abandon and
  // reset sites and the post-push live-remote readback, so every git op in them is worktree-pinned.
  { name: 'abandon/abort', anchor: 'You are a fresh octo-lite host-non-push abort subagent' },
  { name: 'reset', anchor: 'You are a fresh octo-lite workspace-cleanup subagent' },
  { name: 'post-push live-remote readback', anchor: 'You are a fresh READ-ONLY octo-lite post-push live-remote readback' },
  { name: 'reviewer relay worktree snapshot', anchor: 'CONTAINED REVIEW WORKTREE (run codex exec with -C this exact path)' },
]

function cwdPinRegion(anchor) {
  const start = LOOP_SRC.indexOf(anchor)
  assert.ok(start >= 0, `cwd-pin anchor missing from loop source: ${anchor}`)
  // Each prompt array joins into a single agent() call; 1700 chars covers the git-read instructions
  // (the reviewer relay region spans the runtime-relay preamble before its worktree snapshot capture).
  return LOOP_SRC.slice(start, start + 1700)
}

test('cwd-pin: every git-reading readback/liveness/pre-push/review prompt pins git to the host issue worktree with git -C ${worktree}', () => {
  for (const site of CWD_PIN_SITES) {
    const region = cwdPinRegion(site.anchor)
    assert.match(
      region, /git -C \$\{worktree\}/,
      `${site.name} must pin git to the host issue worktree via git -C \${worktree}`,
    )
  }
})

test('cwd-pin: no git-reading readback/liveness/pre-push/review prompt uses a bare cwd-dependent git rev-parse or git status', () => {
  for (const site of CWD_PIN_SITES) {
    const region = cwdPinRegion(site.anchor)
    // A bare `git rev-parse` / `git status` (no -C) would inherit the ambient (foreign) cwd. Every git
    // read in these prompts must carry the -C host-worktree pin, so no bare form may remain.
    assert.doesNotMatch(
      region, /\bgit rev-parse HEAD\b/,
      `${site.name} must not use a bare cwd-dependent git rev-parse HEAD`,
    )
    assert.doesNotMatch(
      region, /\bgit status --porcelain\b(?![^]*git -C)/,
      `${site.name} must not use a bare cwd-dependent git status --porcelain`,
    )
  }
})

test('cwd-pin: every git-reading prompt explicitly instructs the subagent not to rely on the ambient current working directory', () => {
  for (const site of CWD_PIN_SITES) {
    const region = cwdPinRegion(site.anchor)
    assert.match(
      region, /do NOT rely on the current working directory|not the ambient cwd|never the ambient cwd/i,
      `${site.name} must forbid relying on the ambient current working directory`,
    )
  }
})

// TUR-447 ruling-56 cycle3: the source-wide bare-git scanner is TIGHTENED. Two cycle-2 holes:
//   (a) it BLANKET-exempted every bare `git rev-list` ANYWHERE in the source, so a bare rev-list on a
//       NON-isolation line (e.g. a readback prompt) would have slipped through. The exemption must be
//       REGION-scoped: a bare git literal is sanctioned ONLY inside the independentGitRead /
//       observeCommittedStates prompts (the opts.isolation: 'worktree' readers), located by line range.
//   (b) it matched only the FIRST `git ...` per line, so a line carrying a pinned git AND a second bare
//       git (or bare git + bare push) would report at most one and could hide the second. The scanner
//       must scan ALL git literals per line (matchAll).
// Compute the isolation-reader region by its function anchors; any bare git OUTSIDE that region on a
// non-comment line is an offender.
function isolationReaderRegion() {
  const lines = LOOP_SRC.split('\n')
  const start = lines.findIndex((l) => /^async function independentGitRead\(/.test(l))
  const end = lines.findIndex((l) => /^async function hostGatedPushCommittedBranch\(/.test(l))
  assert.ok(start >= 0 && end > start, 'isolation-reader region anchors missing from loop source')
  return { start, end }
}

test('cwd-pin: no subagent prompt in the loop carries a bare cwd-dependent backtick git command literal (rev-list exempt ONLY inside the isolation reader)', () => {
  const lines = LOOP_SRC.split('\n')
  const { start, end } = isolationReaderRegion()
  const offenders = []
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    // Skip pure comment lines (JSDoc / inline rationale); they are not subagent prompt strings.
    if (/^\s*\/\//.test(line)) continue
    // Scan EVERY backtick-quoted git command literal on the line, not just the first.
    for (const m of line.matchAll(/`git (?!-C\b)([a-z-]+)/g)) {
      const inIsolationReader = i >= start && i < end
      // The ONLY sanctioned bare git is the isolation reader's ancestry `git rev-list`, and ONLY inside
      // the isolation-reader region. Anywhere else (or any other subcommand) is an offender.
      if (m[1] === 'rev-list' && inIsolationReader) continue
      offenders.push(`L${i + 1}: git ${m[1]}`)
    }
  }
  assert.deepEqual(
    offenders, [],
    `every backtick git command in a subagent prompt must be git -C \${worktree} (bare git only inside the isolation reader): ${offenders.join(', ')}`,
  )
})

// A bare `git rev-list` OUTSIDE the isolation-reader region must be flagged: the region-scoped exemption
// is not a blanket rev-list exemption. This proves the tightening: a rev-list literal placed in, say, a
// readback prompt would be an offender.
test('cwd-pin: a bare git rev-list OUTSIDE the isolation-reader region is NOT exempted', () => {
  const { start, end } = isolationReaderRegion()
  // A readback prompt line (well before the isolation reader) with a bare rev-list must be flagged.
  const outsideLine = 100
  assert.ok(outsideLine < start || outsideLine >= end, 'chosen probe line is outside the isolation region')
  const line = '    `git rev-list --reverse a..b`,'
  const m = [...line.matchAll(/`git (?!-C\b)([a-z-]+)/g)]
  assert.equal(m.length, 1)
  const inIsolationReader = outsideLine >= start && outsideLine < end
  assert.equal(inIsolationReader, false, 'a rev-list outside the isolation region is not exempt')
})

// The per-line scan must catch a SECOND bare git after a pinned one (matchAll, not the first match only).
test('cwd-pin: the scanner scans ALL git literals per line (a pinned git + a bare push on one line is caught)', () => {
  const line = 'read `git -C ${worktree} rev-parse HEAD` then `git push origin main`'
  const bare = [...line.matchAll(/`git (?!-C\b)([a-z-]+)/g)].map((m) => m[1])
  assert.deepEqual(bare, ['push'], 'the bare git push after a pinned git is caught by the all-matches scan')
})

// === TUR-447 ruling-56 cycle2: GITHUB reads must be REPO-PINNED, and the host PUSH + abort remote
// verify must be git -C-pinned (delivery-lifecycle launch-readback, delivery-tdd-host-gated-push,
// delivery-tdd-named-test-live-remote-readback; loop-correctness single-writer). The cycle-1 fix
// pinned only git HEAD reads with git -C, leaving TWO residual repo-inference holes:
//   (obligation 1) every `gh pr view` / `gh api` in a subagent prompt inferred the repo from the
//   AMBIENT cwd, so on the shared box a foreign lane worktree could select the WRONG repository. A gh
//   read must be REPO-PINNED to the canonical owner/repo slug from bound inputs: `gh pr view <pr>
//   --repo <slug>` or a repo-bound `gh api repos/<slug>/...` endpoint, never a cwd-inferred repo.
//   (obligation 4) the host git PUSH command itself was unspecified (a subagent could run bare `git
//   push` in the foreign cwd) and the abort remote-verify was unpinned. The push must be `git -C
//   <worktree> push` and the abandon/abort remote verify must use `git -C <worktree>` (or a repo-
//   pinned gh), so nothing inherits the ambient cwd or a cwd-inferred repo.
// These are SOURCE assertions over the real production loop text. They FAIL on the cycle-1 loop
// (which had bare `gh pr view`, a bare `gh api` with no repos/<slug>/ endpoint, and no `git -C
// <worktree> push` literal) and pass only after the gh + push pin lands.

// Every gh-reading prompt site and the gh command shape it must carry. `apiEndpoint:true` sites use
// the gh REST api (must carry a repo-bound `repos/<slug>/` endpoint); the rest use `gh pr view`
// (must carry `--repo <slug>`). Both derive the canonical slug from the bound inputs, never cwd.
const GH_PIN_SITES = [
  { name: 'liveReadback', anchor: 'You are a fresh READ-ONLY octo-lite readback subagent', apiEndpoint: false },
  { name: 'pre-push readback', anchor: 'You are a fresh READ-ONLY octo-lite pre-push readback', apiEndpoint: false },
  { name: 'post-push live-remote readback', anchor: 'You are a fresh READ-ONLY octo-lite post-push live-remote readback', apiEndpoint: true },
  // TUR-447 ruling-56 cycle3: the worker-liveness echo reads the live PR via a repo-pinned gh pr view.
  { name: 'worker-liveness-echo', anchor: 'LIVENESS ECHO: read the live Linear state', apiEndpoint: false },
]

function ghPinRegion(anchor) {
  const start = LOOP_SRC.indexOf(anchor)
  assert.ok(start >= 0, `gh-pin anchor missing from loop source: ${anchor}`)
  // Each prompt array joins into a single agent() call; 1700 chars covers the gh-read instructions.
  return LOOP_SRC.slice(start, start + 1700)
}

test('gh-pin: every gh-reading prompt is REPO-PINNED to the canonical slug (gh pr view --repo <slug> / gh api repos/<slug>/), never a cwd-inferred repo', () => {
  for (const site of GH_PIN_SITES) {
    const region = ghPinRegion(site.anchor)
    if (site.apiEndpoint) {
      // A gh api read must hit a repo-BOUND endpoint (repos/<slug>/...), interpolating the slug.
      assert.match(
        region, /gh api repos\/\$\{slug\}\//,
        `${site.name} gh api must use a repo-bound endpoint gh api repos/\${slug}/...`,
      )
    } else {
      // A gh pr view read must carry --repo <slug> so gh does not infer the repo from cwd.
      assert.match(
        region, /gh pr view \$\{pr\} --repo \$\{slug\}/,
        `${site.name} must pin gh pr view with --repo \${slug}`,
      )
    }
  }
})

test('gh-pin: no gh-reading prompt carries a bare cwd-inferred gh pr view (no --repo) or a repo-unpinned gh api', () => {
  for (const site of GH_PIN_SITES) {
    const region = ghPinRegion(site.anchor)
    // A `gh pr view <pr>` not immediately followed by --repo would infer the repo from the ambient
    // (foreign) cwd. None may remain.
    assert.doesNotMatch(
      region, /gh pr view \$\{pr\} --json/,
      `${site.name} must not use a bare gh pr view (no --repo) that infers the repo from cwd`,
    )
    // A backtick `gh api` command literal not bound to a repos/<slug>/ endpoint infers the repo from
    // cwd. None may remain (prose references to the "gh api" label are not command literals).
    assert.doesNotMatch(
      region, /`gh api(?!\s+repos\/\$\{slug\}\/)/,
      `${site.name} must not use a repo-unpinned gh api command that infers the repo from cwd`,
    )
  }
})

test('push-pin: the host push COMMAND is git -C ${worktree}-pinned (git -C <worktree> push), never a bare git push', () => {
  const start = LOOP_SRC.indexOf('You are a fresh octo-lite host push subagent')
  assert.ok(start >= 0, 'host-push anchor missing from loop source')
  const region = LOOP_SRC.slice(start, start + 1700)
  // The push command itself must be pinned to the host issue worktree; a bare `git push` would push
  // from the ambient (foreign) cwd's branch.
  assert.match(
    region, /git -C \$\{worktree\} push/,
    'the host push command must be git -C ${worktree} push',
  )
  assert.doesNotMatch(
    region, /`git push\b/,
    'the host push command must not be a bare git push',
  )
})

test('push-pin: the abort remote-verify is git -C ${worktree}-pinned (or repo-pinned gh), never a cwd-inferred remote read', () => {
  const start = LOOP_SRC.indexOf('You are a fresh octo-lite host-non-push abort subagent')
  assert.ok(start >= 0, 'abort anchor missing from loop source')
  const region = LOOP_SRC.slice(start, start + 1700)
  // The abort verifies the branch is NOT on the remote. That remote read must be pinned: a
  // git -C <worktree> ls-remote or a repo-pinned gh api repos/<slug>/, never a bare cwd-inferred read.
  assert.match(
    region, /git -C \$\{worktree\} ls-remote|gh api repos\/\$\{slug\}\//,
    'the abort remote-verify must use git -C ${worktree} ls-remote or a repo-pinned gh api',
  )
  assert.doesNotMatch(
    region, /`gh api(?!\s+repos\/\$\{slug\}\/)/,
    'the abort must not use a repo-unpinned gh api command that infers the repo from cwd',
  )
})

// Source-wide audit (loop-correctness single-writer): NO subagent prompt in the loop may carry a
// repo-UNPINNED gh command literal. Every backtick-quoted `gh <cmd>` string the loop hands a subagent
// must be repo-pinned to the canonical slug: `gh pr view ... --repo ${slug}` or `gh api repos/${slug}/`,
// so nothing infers the repo from the ambient (foreign lane) cwd. There is NO isolation-reader
// exemption for gh: even an isolated-worktree reader that hits GitHub must name the canonical repo.
// TUR-447 ruling-56 cycle3: the gh scanner must scan ALL gh literals per line, not just the first. A
// line carrying a pinned gh AND a second UNPINNED gh must be flagged. The per-line pinned-check is
// tightened to require the pin to accompany EACH gh literal: a `gh pr view` literal must be immediately
// followed by --repo ${slug}, and a `gh api` literal must hit repos/${slug}/, so a stray line-level
// --repo cannot excuse a co-located unpinned gh api (or vice versa).
test('gh-pin: no subagent prompt in the loop carries a repo-unpinned backtick gh command literal (all gh literals per line scanned)', () => {
  const lines = LOOP_SRC.split('\n')
  const offenders = []
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    if (/^\s*\/\//.test(line)) continue // skip pure comment lines
    // Scan EVERY backtick-quoted gh command literal on the line.
    for (const m of line.matchAll(/`gh (pr|api|issue|repo|release|run|workflow)\b([^`]*)/g)) {
      const sub = m[1]
      const rest = m[2] ?? ''
      // Each gh literal must carry its OWN pin: a gh api literal must hit repos/${slug}/; every other gh
      // literal (pr view, issue, etc.) must carry --repo ${slug} within the same backtick literal.
      const pinned = sub === 'api'
        ? /repos\/\$\{slug\}\//.test(rest)
        : /--repo \$\{slug\}/.test(rest)
      if (pinned) continue
      offenders.push(`L${i + 1}: gh ${sub}`)
    }
  }
  assert.deepEqual(
    offenders, [],
    `every backtick gh command in a subagent prompt must be repo-pinned (--repo \${slug} or repos/\${slug}/): ${offenders.join(', ')}`,
  )
})

// The per-line gh scan must catch a SECOND unpinned gh after a pinned one (matchAll, per-literal pin).
test('gh-pin: the scanner scans ALL gh literals per line (a pinned gh + an unpinned gh api on one line is caught)', () => {
  const line = 'read `gh pr view ${pr} --repo ${slug} --json x` then `gh api repos/other/git/ref`'
  const offenders = []
  for (const m of line.matchAll(/`gh (pr|api|issue|repo|release|run|workflow)\b([^`]*)/g)) {
    const sub = m[1]
    const rest = m[2] ?? ''
    const pinned = sub === 'api' ? /repos\/\$\{slug\}\//.test(rest) : /--repo \$\{slug\}/.test(rest)
    if (!pinned) offenders.push(`gh ${sub}`)
  }
  assert.deepEqual(offenders, ['gh api'], 'the unpinned gh api after a pinned gh pr view is caught')
})

// The source-wide bare-git scanner must also catch a bare `git push`, not only reads. The cycle-1
// scanner exempted `git rev-list` (the isolation reader's ancestry read); it must NOT blanket-exempt
// every git subcommand. This asserts a bare backtick `git push` (no -C) is caught as an offender by
// the existing scanner regex, so a host push command can never be an unpinned bare git push.
test('push-pin: the source-wide bare-git scanner catches a bare backtick git push (not exempted)', () => {
  // The scanner regex from the audit above; a bare `git push` must match it (and is not the rev-list
  // exemption), proving a bare push literal would be reported as an offender.
  const m = '`git push origin'.match(/`git (?!-C\b)([a-z-]+)/)
  assert.ok(m && m[1] === 'push', 'a bare git push must be caught by the bare-git scanner')
  assert.notEqual(m[1], 'rev-list', 'git push is not the sanctioned rev-list exemption')
})
