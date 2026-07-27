// octo-lite issue 13: collapsed six-mode delivery loop (ADR 0003 drop-loop-trust-root; role-runtime
// loop-runs-on-cwd-and-branch, launch-provisioning-trust-root; delivery-lifecycle
// delivery-tdd-reviewer-guard, delivery-entry-gate, linear-loop-fire-transition, qa-verdict,
// delivery-merge, linear-operator-authority).
//
// This suite drives the ACTUAL production loop octo-loop-qa.js through each of its six delivery modes
// with a mocked GLOBAL agent(), exactly as the Workflow tool runs it. It proves the collapsed essence:
// each mode spawns the right resolved role, moves the tracker state at the mode boundary, and posts
// evidence; the acceptance mode BUILDS + POSTS + SENDS the acceptance package and NEVER self-accepts.
// A companion removed-gates guard asserts the ADR-0003 trust-root/observer/readback/launch-revision
// symbols are gone from the loop and that no mode calls them, while the RETAINED OpenAI reviewer
// relay-provenance path (spawnOpenaiReviewer) remains.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const LOOP_SRC = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8')

// The loop is NOT a module: it uses bare Workflow globals (agent, args, log) and top-level `return` in
// mode branches. Strip `export ` (module-only) and wrap the whole source in an async function whose
// parameters ARE the injected Workflow globals; this executes the identical loop logic the real
// Workflow tool runs, just with stubbed globals. No loop source is edited.
function loadLoop() {
  const stripped = LOOP_SRC.replace(/^export /gm, '')
  // eslint-disable-next-line no-new-func
  return new Function(
    'agent', 'args', 'log',
    `return (async () => { ${stripped}\n })()`,
  )
}

const REPO = '/root/octo-lite'
const REPO_SLUG = 'varelaseb/octo-lite'
const ISSUE = 'TUR-13'
const PR = 21
const PR_URL = `https://github.com/${REPO_SLUG}/pull/21`
const WORKTREE_ROOT = '/root'
const WORKTREE_REL = 'octo-lite-issue13-wt'
const WORKTREE_ABS = `${WORKTREE_ROOT}/${WORKTREE_REL}`
const BRANCH = 'octo-lite/issue13-drop-loop-trust'
const HEAD = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const NEWHEAD = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
const SPEC_BLOBS = ['spec/domains/role-runtime.spec.html:loop-runs-on-cwd-and-branch']
const CONTRACT = 'c8b0440cacc5188b2926b626ee6f506ced5368ebbda67dc6b1ed0d542cddc34c'

const RESOLVED_WORKER_RUNTIME = {
  provider: 'anthropic', model: 'claude-opus-5', effort: 'xhigh', service_tier: 'default',
  contract_blob: 'wk-blob', contract_text: '# Implementer\ncontract', skills: ['tdd', 'commit'],
}
const RESOLVED_REVIEWER_RUNTIME = {
  provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', service_tier: 'default',
  contract_blob: 'rv-blob', contract_text: '# Code reviewer\ncontract',
}
const RESOLVED_RECONCILER_RUNTIME = {
  provider: 'anthropic', model: 'claude-sonnet-5', effort: 'high', service_tier: 'default',
  contract_blob: 'rc-blob', contract_text: '# Reconciler\ncontract', skills: [],
}

const RED_COMMIT = 'redc0mm1t00000000000000000000000000000001'
const GREEN_COMMIT = 'greenc0mm1t0000000000000000000000000000002'
const BOUND_TEST = { path: 'tests/loop_modes.test.mjs', digest: 'sha256:bounddigest' }

// A healthy OpenAI relay result: read-only bootstrap, workspace-write resume via -c sandbox_mode config,
// unchanged worktree, verbatim payload backed by the independently-read rollout record.
function relayResult(payload) {
  return {
    claimed_session_id: 'sess-1', payload,
    bootstrap_argv: ['codex', 'exec', '-s', 'read-only'],
    resume_argv: ['codex', 'exec', 'resume', 'sess-1', '-c', 'sandbox_mode="workspace-write"', '-c', 'sandbox_workspace_write.network_access=true'],
    needs_live_reads: true,
    worktree_before: { head: HEAD, status: '' },
    worktree_after: { head: HEAD, status: '' },
  }
}
function rolloutFor(payload, runtime = RESOLVED_REVIEWER_RUNTIME) {
  return {
    source: 'independent-rollout-subagent',
    data: { provider: runtime.provider, model: runtime.model, effort: runtime.effort, final_message: payload },
  }
}

function readyEnvelope(overrides = {}) {
  return {
    mode: 'implement',
    repo: REPO, repo_slug: REPO_SLUG, issue: ISSUE, pr: PR, pr_url: PR_URL, branch: BRANCH,
    shaping_head: HEAD, pr_head: HEAD, pr_base: 'main',
    spec_revision: 'r1', linear_revision: 'lr1', topology_revision: 't1',
    linear_fingerprint: 'fp-shaped', linear_state: 'Shaped',
    shaping_verdict: 'clear', shaping_verdict_head: HEAD,
    shaping_reviewer_receipt: 'rcpt-1', conversation_cutoff: 'session.jsonl:1',
    conversation_log_references: ['session.jsonl:1-1'],
    spec_blobs: SPEC_BLOBS, adr_blobs: [], shaping_verdict_inputs: ['in-1'],
    acceptance_criteria: ['loop collapses'],
    contract_hash: CONTRACT,
    brief: 'do the work',
    worktree_root: WORKTREE_ROOT, worktree: WORKTREE_REL,
    loop_fire_args: '--reason ship',
    spawn_id: 'spawn-1', parent: 'orchestrator', reply_route: PR_URL,
    review_delivery: 'pr-comment', execution_location: 'local',
    starting_head: HEAD,
    ...overrides,
  }
}

// Build an agent() stub that answers each labelled spawn from a scripted table and records the ordered
// call sequence so the harness can assert which roles were actually spawned, in order.
function makeAgent(script) {
  const calls = []
  async function agent(prompt, opts = {}) {
    const label = opts.label ?? ''
    calls.push({ label, agentType: opts.agentType ?? null, prompt })
    for (const [matcher, responder] of script) {
      if (label.startsWith(matcher)) {
        return typeof responder === 'function' ? responder({ prompt, opts, calls }) : responder
      }
    }
    throw new Error(`loop_modes harness: no scripted response for label ${label}`)
  }
  agent.calls = calls
  return agent
}
const noop = () => {}

async function runMode(env, script) {
  const agent = makeAgent(script)
  const factory = loadLoop()
  const result = await factory(agent, JSON.stringify(env), noop)
  return { result, calls: agent.calls }
}

// ---- implement mode: fires Shaped -> Todo, spawns implementer, returns code-review-required ----
test('implement mode fires Shaped->Todo then spawns the implementer and returns the pushed head', async () => {
  const env = readyEnvelope()
  const { result, calls } = await runMode(env, [
    ['loop-fire:', { command: 'octo-control linear-transition', exit_status: 0, readback_state: 'Todo' }],
    ['implementer-runtime:', RESOLVED_WORKER_RUNTIME],
    ['implementer:', {
      issue: ISSUE, pr_url: PR_URL, branch: BRANCH, head: NEWHEAD,
      red_commit: RED_COMMIT, green_commit: GREEN_COMMIT, final_commit: NEWHEAD,
      bound_test: { ...BOUND_TEST }, validation: 'node --test', blocked: false,
    }],
  ])
  assert.equal(result.stage, 'code-review-required')
  assert.equal(result.head, NEWHEAD)
  const labels = calls.map((c) => c.label)
  // The Shaped -> Todo fire runs before the implementer spawn.
  const fireAt = labels.findIndex((l) => l.startsWith('loop-fire:'))
  const implAt = labels.findIndex((l) => l.startsWith('implementer:'))
  assert.ok(fireAt >= 0 && implAt > fireAt, 'fire must precede the implementer spawn')
})

test('implement mode rejects a delivery spawn at Shaped when the Todo readback is missing', async () => {
  const env = readyEnvelope()
  await assert.rejects(
    runMode(env, [
      ['loop-fire:', { command: 'octo-control linear-transition', exit_status: 0, readback_state: 'Shaped' }],
    ]),
    /Todo readback missing/,
  )
})

// ---- code-review mode: spawns the OpenAI code-reviewer through the relay, returns clear|fix ----
test('code-review mode spawns the code-reviewer through the relay and advances on a clear verdict', async () => {
  const env = readyEnvelope({ mode: 'code-review', head: NEWHEAD, linear_state: 'In Progress', cycle: 1 })
  const payload = JSON.stringify({ verdict: 'clear', findings: [], comment_url: `${PR_URL}#rev` })
  const { result, calls } = await runMode(env, [
    ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['code-reviewer-relay:', relayResult(payload)],
    ['code-reviewer-rollout:', rolloutFor(payload)],
    ['code-reviewer:', { head: NEWHEAD, verdict: 'clear', findings: [], comment_url: `${PR_URL}#rev` }],
  ])
  assert.equal(result.stage, 'code-clear')
  // The reviewer ran through the relay path (a distinct relay spawn and an independent rollout read).
  const labels = calls.map((c) => c.label)
  assert.ok(labels.some((l) => l.startsWith('code-reviewer-relay:')), 'code-reviewer must use the relay path')
  assert.ok(labels.some((l) => l.startsWith('code-reviewer-rollout:')), 'independent rollout read required')
})

test('code-review mode returns fix-required with findings on a blocking verdict', async () => {
  const env = readyEnvelope({ mode: 'code-review', head: NEWHEAD, linear_state: 'In Progress', cycle: 1 })
  const payload = JSON.stringify({ verdict: 'blocking', findings: ['bug'], comment_url: `${PR_URL}#rev` })
  const { result } = await runMode(env, [
    ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['code-reviewer-relay:', relayResult(payload)],
    ['code-reviewer-rollout:', rolloutFor(payload)],
    ['code-reviewer:', { head: NEWHEAD, verdict: 'blocking', findings: ['bug'], comment_url: `${PR_URL}#rev` }],
  ])
  assert.equal(result.stage, 'fix-required')
  assert.deepEqual(result.findings, ['bug'])
})

// ---- fix mode: spawns implementer, returns code-review-required ----
test('fix mode spawns the implementer and returns code-review-required at the next cycle', async () => {
  const env = readyEnvelope({ mode: 'fix', head: NEWHEAD, linear_state: 'In Progress', cycle: 1, findings: ['bug'] })
  const finalHead = 'cccccccccccccccccccccccccccccccccccccccc'
  const { result } = await runMode(env, [
    ['implementer-runtime:', RESOLVED_WORKER_RUNTIME],
    ['implementer:', {
      issue: ISSUE, pr_url: PR_URL, branch: BRANCH, head: finalHead,
      red_commit: RED_COMMIT, green_commit: GREEN_COMMIT, final_commit: finalHead,
      bound_test: { ...BOUND_TEST }, validation: 'node --test', blocked: false,
    }],
  ])
  assert.equal(result.stage, 'code-review-required')
  assert.equal(result.head, finalHead)
  assert.equal(result.cycle, 2)
})

// ---- evidence mode: spawns qa-capture, posts the evidence card, returns qa-review-required ----
test('evidence mode spawns qa-capture, posts the evidence card, and returns qa-review-required', async () => {
  const env = readyEnvelope({
    mode: 'evidence', head: NEWHEAD, linear_state: 'In Progress',
    code_review: { verdict: 'clear', head: NEWHEAD },
  })
  const { result, calls } = await runMode(env, [
    ['qa-capture-runtime:', RESOLVED_WORKER_RUNTIME],
    ['qa-capture:', { head: NEWHEAD, plan: [{}], manifest: 'm1', artifacts: ['shot.png'], card_url: '', blocked: false }],
    ['publish-visual:', { card_url: `${PR_URL}#card`, readable: true }],
  ])
  assert.equal(result.stage, 'qa-review-required')
  assert.equal(result.card_url, `${PR_URL}#card`)
  const labels = calls.map((c) => c.label)
  assert.ok(labels.some((l) => l.startsWith('qa-capture:')), 'qa-capture spawned')
  assert.ok(labels.some((l) => l.startsWith('publish-visual:')), 'evidence card posted')
})

// ---- backend evidence -> qa-review round-trip: the nonvisual branch must carry manifest forward ----
test('backend evidence mode returns the default manifest so the evidence->qa-review round-trip does not fail closed', async () => {
  // Backend-only delivery (user_facing:false), no A.manifest supplied: the branch defaults to
  // 'backend-packet'. The returned result must include that manifest so the next qa-review pass (which
  // requires A.manifest) does not fail closed on the manifest reason.
  const evidenceEnv = readyEnvelope({
    mode: 'evidence', head: NEWHEAD, linear_state: 'In Progress', user_facing: false,
    code_review: { verdict: 'clear', head: NEWHEAD },
  })
  const { result: evidenceResult } = await runMode(evidenceEnv, [
    ['publish-nonvisual:', { card_url: `${PR_URL}#backend-card`, readable: true }],
  ])
  assert.equal(evidenceResult.stage, 'qa-review-required')
  assert.equal(evidenceResult.user_facing, false)
  assert.equal(evidenceResult.manifest, 'backend-packet')

  // Feed the returned evidence result straight into qa-review: it must NOT throw the manifest error.
  const qaEnv = readyEnvelope({
    mode: 'qa-review', head: evidenceResult.head, linear_state: 'In Progress',
    card_url: evidenceResult.card_url, manifest: evidenceResult.manifest,
  })
  const payload = JSON.stringify({ verdict: 'satisfied' })
  const { result: qaResult } = await runMode(qaEnv, [
    ['qa-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['qa-reviewer-relay:', relayResult(payload)],
    ['qa-reviewer-rollout:', rolloutFor(payload)],
    ['qa-reviewer:', {
      head: evidenceResult.head, verdict: 'satisfied', issue: ISSUE, pr: PR, manifest: 'backend-packet',
      criteria: [{ criterion: 'works', status: 'pass', observation: 'ok' }], packet_url: `${PR_URL}#pkt`,
    }],
  ])
  assert.equal(qaResult.stage, 'acceptance-required')
})

// ---- qa-review mode: spawns qa-reviewer through the relay, returns acceptance-required|fix ----
test('qa-review mode spawns the qa-reviewer through the relay and advances to acceptance on satisfied', async () => {
  const env = readyEnvelope({
    mode: 'qa-review', head: NEWHEAD, linear_state: 'In Progress', card_url: `${PR_URL}#card`, manifest: 'm1',
  })
  const payload = JSON.stringify({ verdict: 'satisfied' })
  const { result, calls } = await runMode(env, [
    ['qa-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['qa-reviewer-relay:', relayResult(payload)],
    ['qa-reviewer-rollout:', rolloutFor(payload)],
    ['qa-reviewer:', {
      head: NEWHEAD, verdict: 'satisfied', issue: ISSUE, pr: PR, manifest: 'm1',
      criteria: [{ criterion: 'works', status: 'pass', observation: 'ok' }], packet_url: `${PR_URL}#pkt`,
    }],
  ])
  assert.equal(result.stage, 'acceptance-required')
  const labels = calls.map((c) => c.label)
  assert.ok(labels.some((l) => l.startsWith('qa-reviewer-relay:')), 'qa-reviewer must use the relay path')
})

// ---- acceptance mode: BUILDS + POSTS + SENDS the package, NEVER self-accepts ----
test('acceptance mode builds, posts, and sends the acceptance package and never self-accepts', async () => {
  const env = readyEnvelope({
    mode: 'acceptance', head: NEWHEAD, linear_state: 'In Progress',
    code_review: { verdict: 'clear', head: NEWHEAD },
    qa_review: { verdict: 'satisfied', head: NEWHEAD },
    card_url: `${PR_URL}#card`, summary: 'collapsed the loop to six modes',
  })
  const { result, calls } = await runMode(env, [
    ['acceptance-publish:', { card_url: `${PR_URL}#pkg`, readable: true }],
    ['acceptance-send:', { sent: true, route: 'operator-pane' }],
  ])
  assert.equal(result.stage, 'awaiting-operator-acceptance')
  assert.equal(result.package.self_accepted, false)
  assert.equal(result.package_url, `${PR_URL}#pkg`)
  const labels = calls.map((c) => c.label)
  // The package is posted to the evidence site and then sent to the operator, in that order.
  const pubAt = labels.findIndex((l) => l.startsWith('acceptance-publish:'))
  const sendAt = labels.findIndex((l) => l.startsWith('acceptance-send:'))
  assert.ok(pubAt >= 0 && sendAt > pubAt, 'package must be posted then sent')
  // No mode ever runs an acceptance/merge/transition itself; the returned next says the operator decides.
  assert.match(result.next, /operator/i)
})

test('acceptance mode fails closed without a satisfied exact-head qa-review verdict', async () => {
  const env = readyEnvelope({
    mode: 'acceptance', head: NEWHEAD, linear_state: 'In Progress',
    code_review: { verdict: 'clear', head: NEWHEAD },
    qa_review: { verdict: 'satisfied', head: 'wrong-head' },
    card_url: `${PR_URL}#card`, summary: 'x',
  })
  await assert.rejects(runMode(env, []), /satisfied exact-head qa-review/)
})

// ---- removed-gates guard: ADR 0003 trust-root/observer/readback/launch-revision symbols are gone ----
test('removed-gates guard: the ADR-0003 trust-root, observer, readback, and launch-revision symbols are gone', () => {
  const removed = [
    'hostTrustedIdentity',
    'assertProvisionedWorkspaceBinding',
    'assertLiveWorktreeIdentity',
    'assertHostTrustedIdentity',
    'PROVISION_ENV_KEYS',
    'PROVISION_BINDING_FIELDS',
    'HOST_PROVISION_RECORD_ENV',
    'OCTO_PROVISION_RECORD',
    'DELIVERY_READ_RESTRICTED_ROLES',
    '-tdd-observer:',
    'observeCommittedStates',
    'assertObservedCommittedStates',
    'independentGitRead',
    'assertIndependentGitRead',
    'assertWorkerClaimCrossCheck',
    'launchRevision',
    'resolveLaunchRevision',
    'assertLaunchRevision',
    'liveReadback',
    'assertLaunchReadback',
    'assertWorkerAckEcho',
    'verifyAckThenUpgrade',
    'assertReadOnlyAckPhase',
    'assertPrePushReadback',
    'assertPrePushWorktreeReAnchor',
    'assertLiveRemotePushReadback',
    'assertWorkerLivenessEcho',
  ]
  for (const symbol of removed) {
    assert.ok(!LOOP_SRC.includes(symbol), `removed symbol still present in the loop: ${symbol}`)
  }
})

test('removed-gates guard: the retained OpenAI reviewer relay-provenance path remains', () => {
  // spawnOpenaiReviewer with independent rollout provenance and the relay-verbatim gate is RETAINED
  // (role-runtime role-openai-relay, role-openai-fail-closed); the OpenAI reviewer roles never use the
  // plain spawnWorker path.
  for (const kept of [
    'spawnOpenaiReviewer', 'independent-rollout-subagent', 'acceptOpenaiReviewRelay',
    "spawnOpenaiReviewer('code-reviewer'", "spawnOpenaiReviewer('qa-reviewer'",
  ]) {
    assert.ok(LOOP_SRC.includes(kept), `retained relay-provenance symbol missing: ${kept}`)
  }
  assert.ok(!LOOP_SRC.includes("spawnWorker('code-reviewer'"), 'code-reviewer must not use the plain worker path')
  assert.ok(!LOOP_SRC.includes("spawnWorker('qa-reviewer'"), 'qa-reviewer must not use the plain worker path')
})
