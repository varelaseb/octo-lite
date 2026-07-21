// TUR-447 cycle1 pass1 composed-runtime proof (role-runtime launch-readback,
// launch-identity, launch-receipt, launch-gates-workflow-layer; delivery-lifecycle
// delivery-entry-gate, linear-loop-fire-transition, prompt-tdd-red, prompt-tdd-green;
// operating-model decision-109-workflow-native, decision-109-binding).
//
// The prior verifiers gave FALSE green by checking only source ordering plus unit
// gate tests. This harness instead builds in-memory stubs for the Workflow globals
// (agent(), args, log()) and DRIVES an ACTUAL delivery pass through the loop's mode
// logic end to end, asserting composed behavior. gpt-5.6-sol reproduced the P0 with
// exactly such an in-memory Workflow mock.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { launchRevision } from '../workflows/lib/gates.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const LOOP_SRC = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8')

// The loop is NOT a module: it uses bare Workflow globals (agent, args, log) and
// top-level `return` in mode branches. To run it as a real composed pass, strip the
// `export ` keyword (module-only) and wrap the whole source in an async function whose
// parameters ARE the injected Workflow globals. This executes the identical loop logic
// the real Workflow tool runs, just with stubbed globals. No loop source is edited.
function loadLoop() {
  const stripped = LOOP_SRC.replace(/^export /gm, '')
  // eslint-disable-next-line no-new-func
  const factory = new Function(
    'agent', 'args', 'log',
    `return (async () => { ${stripped}\n })()`,
  )
  return factory
}

const REPO = '/root/octo-lite'
const ISSUE = 'TUR-447'
const PR = 'https://github.com/x/y/pull/6'
const BRANCH = 'octo-lite/tur-443-operating-model'
const HEAD = 'f00b13357cb1be87b5c5e6d7bd98fd9572915154'
const NEWHEAD = 'abc1234new'
const SPEC_BLOBS = ['spec/domains/role-runtime.spec.html:anchor-1']
const CONTRACT = 'c8b0440cacc5188b2926b626ee6f506ced5368ebbda67dc6b1ed0d542cddc34c'

// TUR-447 cycle2 pass1 ANTI-GAMING: the Linear fingerprint is a FUNCTION of the issue state.
// The prior harness reused ONE constant fingerprint ('lfp-1') across the Shaped -> Todo fire, so
// the stale-fingerprint P0 could never surface. Here Shaped and Todo yield DIFFERENT fingerprints,
// so a genuine pass MUST reconcile the bound fingerprint to the post-fire (Todo) value or it
// self-rejects at assertLaunchReadback. fingerprintFor is the single source; no test reuses a
// constant fingerprint across a state change.
const FINGERPRINTS = { Shaped: 'fp-shaped-a1', Todo: 'fp-todo-b2', Backlog: 'fp-backlog-c3' }
function fingerprintFor(state) {
  const fp = FINGERPRINTS[state]
  if (!fp) throw new Error(`composed harness: no fingerprint modelled for state ${state}`)
  return fp
}

function boundInputs(role) {
  return {
    role,
    repo: REPO,
    issue: ISSUE,
    pr: PR,
    starting_head: HEAD,
    spec_blobs: SPEC_BLOBS,
    contract_hash: CONTRACT,
  }
}

function ackFor(role, overrides = {}) {
  const b = boundInputs(role)
  return {
    role: b.role, repo: b.repo, issue: b.issue, pr: b.pr,
    starting_head: b.starting_head, spec_blobs: b.spec_blobs, contract_hash: b.contract_hash,
    ...overrides,
  }
}

function readyEnvelope(overrides = {}) {
  const base = {
    mode: 'implement',
    repo: REPO, issue: ISSUE, pr: PR, branch: BRANCH,
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
    // Resolver-required bound inputs the loop threads into the COMPLETE role_resolver.py resolve
    // command (TUR-447 cycle1 pass2 F2). starting_head lets resolverCommand build a spawn id.
    spawn_id: 'spawn-tur447-1', parent: 'orchestrator', reply_route: PR,
    review_delivery: 'pr-comment', execution_location: 'local',
    starting_head: HEAD,
  }
  const merged = { ...base, ...overrides }
  // A genuine caller supplies the launch_revision computed over the exact bound inputs
  // whose starting HEAD is shaping_head; recompute it here so it matches the loop.
  merged.launch_revision = launchRevision(boundInputs('implementer'))
  return merged
}

// Freshly-read live values a genuine readback subagent returns. Default is a healthy
// post-fire world: Linear is Todo (the loop fired Shaped -> Todo), so its fingerprint is the
// TODO fingerprint (NOT the Shaped one), git HEAD unchanged. The Todo fingerprint differs from the
// Shaped fingerprint the envelope originally bound, so the loop MUST have reconciled the bound
// fingerprint to Todo for this to agree.
function freshReads(overrides = {}) {
  return {
    linear_state: 'Todo', linear_fingerprint: fingerprintFor('Todo'),
    pr_head: HEAD, branch: BRANCH, git_head: HEAD,
    ...overrides,
  }
}

// Build an agent() stub that answers each labelled spawn from a scripted table.
// It records the ordered sequence of (label, agentType) so the harness can assert
// which phases actually ran (e.g. the write-capable mutation phase was REACHED).
function makeAgent(script) {
  const calls = []
  async function agent(prompt, opts = {}) {
    const label = opts.label ?? ''
    calls.push({ label, agentType: opts.agentType ?? null, phase: opts.phase, prompt, opts })
    for (const [matcher, responder] of script) {
      if (label.startsWith(matcher)) {
        const value = typeof responder === 'function' ? responder({ prompt, opts, calls }) : responder
        return value
      }
    }
    throw new Error(`composed harness: no scripted response for label ${label}`)
  }
  agent.calls = calls
  return agent
}

const noop = () => {}

// The resolved runtime a genuine role-resolver subagent returns after running the COMPLETE
// role_resolver.py resolve command (TUR-447 cycle1 pass2 F2). Native workers resolve model,
// effort, service_tier, contract_blob, the canonical contract TEXT, and the skill set FROM
// roles.toml; the loop never hardcodes them.
const RESOLVED_WORKER_RUNTIME = {
  provider: 'anthropic', model: 'claude-sonnet-5', effort: 'xhigh', service_tier: 'default',
  contract_blob: 'wk-contract-blob', contract_text: '# Implementer\ncanonical contract text',
  skills: ['tdd', 'commit'],
}
const RESOLVED_REVIEWER_RUNTIME = {
  provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', service_tier: 'default',
  contract_blob: 'rv-contract-blob', contract_text: '# Code reviewer\ncanonical contract text',
}

// TUR-447 D1 reshaped delivery loop: a full healthy implement script under the COMMITTED model. fire
// (post-fire Todo state AND fingerprint) -> readback -> runtime -> ack (Explore) -> mutation (write,
// committed:true, pushed:false, distinct red/green/final commit ids, bound_test path+digest, liveness
// echoed) -> tdd-observer replay of the host-journalled committed states (Explore) -> pre-push readback
// -> host push of the committed branch -> live-remote post-push readback confirming the pushed HEAD.
const SCENARIO = 'shaped-member-fires-todo'
const RED_COMMIT = 'redc0mm1t0000000000000000000000000000001'
const GREEN_COMMIT = 'greenc0mm1t000000000000000000000000000002'
const FINAL_COMMIT = 'f1nalc0mm1t000000000000000000000000000003'
const BOUND_TEST = { path: 'tests/loop_composed.test.mjs', digest: 'sha256:boundtestdigest' }
const VALIDATION_COMMAND = 'node --test tests/'

// TUR-447 D1 cycle2: the INDEPENDENT git read a genuine host-controlled git-reader subagent returns. It is
// a DISTINCT Read-restricted subagent from the mutating worker, given ONLY the branch name and expected
// starting HEAD (never the worker's claimed shas). It read the ACTUAL red/green/final shas from git and
// verified the test-only red (fails), production-only green (passes), passing final HEAD, bound-test
// identity unchanged at each, and a linear red->green->final ancestry rooted at the starting HEAD. The host
// journals THESE shas and cross-checks the worker claim against them.
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

// TUR-447 D1: the INDEPENDENT tdd-observer's replay a genuine observer subagent returns. It is a DISTINCT
// Read-restricted subagent from the mutating worker: it checked out EACH host-journalled committed state
// and the final HEAD in an ISOLATED worktree and ran the HOST-SOURCED command, seeing red FAIL, green PASS,
// final HEAD PASS, with the bound test present unchanged by path+digest at every state. The host consumes
// THIS replay, never a worker string. Commit ids default to the host-journalled ones.
function observationFor(overrides = {}) {
  return {
    source: 'independent-tdd-observer', observed_by: 'observer-subagent-1', mutating_worker: 'implementer-subagent',
    isolated_worktree: '/root/octo-lite-tdd-observer-wt',
    command: VALIDATION_COMMAND,
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
} = {}) {
  // Committed model: red is the committed failing test (a real nonzero test exit), green the committed
  // production-only pass; both name the same scenario. The observer replay, not these strings, is proof.
  const goodRed = red ?? {
    command: VALIDATION_COMMAND, exit_status: 1, outcome: 'FAIL: behavior wrong',
    artifact: `${PR}#c1`, head: RED_COMMIT, scenario: SCENARIO,
  }
  const goodGreen = green ?? {
    command: VALIDATION_COMMAND, exit_status: 0, outcome: 'PASS: behavior right',
    artifact: `${PR}#c2`, head: FINAL_COMMIT, scenario: SCENARIO,
  }
  // Pre-push readback default: git_head is the committed FINAL HEAD (the worker committed on the branch).
  const goodPrePush = prePush ?? freshReads({ git_head: FINAL_COMMIT })
  return [
    ['loop-fire:', {
      command: 'octo-control linear-transition', exit_status: 0,
      readback_state: fireState, readback_fingerprint: fireFingerprint,
    }],
    ['implementer-readback:', fresh],
    ['implementer-runtime:', RESOLVED_WORKER_RUNTIME],
    ['implementer-ack:', { ack: ackFor('implementer') }],
    ['implementer:', {
      ack: mutationAck, issue: ISSUE, pr_url: PR, branch: BRANCH, head: FINAL_COMMIT,
      handoff_url: `${PR}#h`, red: goodRed, green: goodGreen, validation: 'suite', blocked: false,
      // Committed model: the worker COMMITTED the red then green and did NOT push, and echoed liveness.
      committed: true, pushed: false,
      red_commit: RED_COMMIT, green_commit: GREEN_COMMIT, final_commit: FINAL_COMMIT,
      bound_test: { ...BOUND_TEST },
      linear_state: liveness.linear_state, linear_fingerprint: liveness.linear_fingerprint,
      ...mutationOverrides,
    }],
    // Independent git read: a host-controlled Read-restricted subagent reads the ACTUAL red/green/final
    // shas from git (given only the branch + expected starting HEAD, never the worker's claimed shas).
    ['implementer-git-read:', gitRead],
    // Independent tdd-observer: a SEPARATE Read-restricted subagent replays the host-journalled commits.
    ['implementer-tdd-observer:', observation],
    // Host-non-push abort (only reached on a rejection): the isolated branch is abandoned unpushed.
    ['workspace-abandon:', { abandoned: true, pushed: false, dirty: false, head: FINAL_COMMIT, status: '' }],
    ['workspace-cleanup:', { cleaned: true, head: HEAD, status: '' }],
    // Pre-push readback: a fresh live read immediately before the host pushes the committed branch.
    ['implementer-prepush-readback:', goodPrePush],
    // Host push: pushes the already-committed isolated branch as-is (no new commit authored).
    ['host-push:', { pushed: true, head: FINAL_COMMIT }],
    // Post-push readback: independent LIVE REMOTE read of the pushed HEAD (gh api / git ls-remote).
    ['implementer-postpush-readback:', postPush ?? { remote_head: FINAL_COMMIT, remote_source: 'git-ls-remote' }],
  ]
}

// readyEnvelope for the committed model carries the host-sourced canonical validation command.
function committedEnvelope(overrides = {}) {
  return readyEnvelope({ validation_command: VALIDATION_COMMAND, ...overrides })
}

test('P0: a genuine Shaped member fires Todo, the bound fingerprint is RECONCILED, and it reaches the mutation spawn without self-rejecting', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  assert.equal(A.linear_fingerprint, fingerprintFor('Shaped'))
  assert.notEqual(fingerprintFor('Shaped'), fingerprintFor('Todo'))
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  assert.equal(result.head, FINAL_COMMIT)
  const labels = agent.calls.map((c) => `${c.label}|${c.agentType}`)
  const ackIdx = labels.findIndex((l) => l.startsWith(`implementer-ack:${ISSUE}|Explore`))
  const mutIdx = labels.findIndex((l) => l === `implementer:${ISSUE}|null`)
  assert.ok(ackIdx >= 0, 'read-only ack (Explore) phase ran')
  assert.ok(mutIdx > ackIdx, 'write-capable mutation phase reached after ack')
})

test('P0-fingerprint: reusing the STALE Shaped fingerprint after the fire self-rejects (proves reconciliation is real, not a constant)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ fireFingerprint: fingerprintFor('Shaped') }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /stale envelope: Linear fingerprint disagrees with fresh read/,
  )
})

test('stale-race: a live change BEFORE push (Linear fingerprint moved after bind) is REJECTED, nothing pushed', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({
    prePush: freshReads({ git_head: FINAL_COMMIT, linear_fingerprint: 'fp-moved-since-bind' }),
  }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /pre-push readback: Linear fingerprint changed since bind/,
  )
  assert.ok(
    !agent.calls.some((c) => c.label.startsWith('host-push:')),
    'host push not reached when a live change is detected before push',
  )
})

// --- Named delivery-TDD tests (delivery-lifecycle delivery-tdd-named-tests-list) -----------------

// test_observer_replays_committed_red_then_green
test('test_observer_replays_committed_red_then_green: the observer replays the committed red and green in an isolated worktree and reports red fail then green pass for the same scenario', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  // TUR-447 D1 cycle3: the observer spawn runs in an ISOLATED git worktree (opts.isolation: 'worktree')
  // with a Bash-capable agent (NOT agentType 'Explore', which is read-only and cannot check out/run tests),
  // AFTER the mutation and BEFORE the host push.
  const labels = agent.calls.map((c) => c.label)
  const mutIdx = agent.calls.findIndex((c) => c.label === `implementer:${ISSUE}` && c.agentType === null)
  const obsIdx = agent.calls.findIndex((c) => c.label === `implementer-tdd-observer:${ISSUE}`)
  const pushIdx = labels.findIndex((l) => l.startsWith('host-push:'))
  assert.ok(obsIdx > mutIdx, 'observer runs after the committed mutation')
  assert.ok(obsIdx >= 0 && obsIdx < pushIdx, 'observer runs before the host push')
  const obs = agent.calls[obsIdx]
  assert.equal(obs.opts.isolation, 'worktree', 'observer runs in an isolated git worktree')
  assert.equal(obs.agentType, null, 'observer is Bash-capable, NOT read-only Explore (which cannot run tests)')
  // The observer replays each HOST-JOURNALLED commit in an ISOLATED worktree.
  assert.ok(obs.prompt.includes(RED_COMMIT) && obs.prompt.includes(GREEN_COMMIT) && obs.prompt.includes(FINAL_COMMIT),
    'observer prompt carries the host-journalled red/green/final commit ids')
  assert.ok(/isolated worktree/i.test(obs.prompt), 'observer checks out in an isolated worktree')
})

// test_observer_rejects_worker_supplied_observation
test('test_observer_rejects_worker_supplied_observation: a worker-authored red or green verdict string is never proof; no independent observation is REJECTED', async () => {
  const factory = loadLoop()
  // The worker's committed result is flawless; only the independent observation is absent. Removing the
  // observer wiring surfaces here.
  const agent = makeAgent(implementScript({ observation: null }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /independent observer replay/,
  )
  assert.ok(
    !agent.calls.some((c) => c.label.startsWith('host-push:')),
    'nothing pushed without an independent observation',
  )
})

test('test_observer_rejects_worker_supplied_observation: an observation stamped as the worker (not the independent observer) is REJECTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ observation: observationFor({ source: 'implementer' }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /not from the independent tdd-observer/,
  )
})

test('test_observer_rejects_worker_supplied_observation: an observation whose observer identity IS the mutating worker is REJECTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({
    observation: observationFor({ observed_by: 'implementer-subagent', mutating_worker: 'implementer-subagent' }),
  }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /the observer cannot be the mutating worker/,
  )
})

// test_observer_inputs_exclude_worker_strings
test('test_observer_inputs_exclude_worker_strings: no worker-supplied command or scenario string enters the observer prompt or execution inputs', async () => {
  const factory = loadLoop()
  // The worker reports a DIFFERENT command and scenario in its red proof; the observer prompt must carry
  // ONLY the host-sourced validation command and the host-journalled commit ids, never the worker strings.
  const workerRed = {
    command: 'WORKER-CONTROLLED-COMMAND --danger', exit_status: 1, outcome: 'FAIL',
    artifact: `${PR}#c1`, head: RED_COMMIT, scenario: 'WORKER-CONTROLLED-SCENARIO',
  }
  const workerGreen = {
    command: 'WORKER-CONTROLLED-COMMAND --danger', exit_status: 0, outcome: 'PASS',
    artifact: `${PR}#c2`, head: FINAL_COMMIT, scenario: 'WORKER-CONTROLLED-SCENARIO',
  }
  const agent = makeAgent(implementScript({ red: workerRed, green: workerGreen }))
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  const obs = agent.calls.find((c) => c.label === `implementer-tdd-observer:${ISSUE}`)
  assert.ok(!obs.prompt.includes('WORKER-CONTROLLED-COMMAND'), 'no worker command string in observer prompt')
  assert.ok(!obs.prompt.includes('WORKER-CONTROLLED-SCENARIO'), 'no worker scenario string in observer prompt')
  assert.ok(obs.prompt.includes(VALIDATION_COMMAND), 'observer carries the host-sourced validation command')
})

// test_observer_commit_inputs_are_host_journalled
test('test_observer_commit_inputs_are_host_journalled: an observer that checked out a commit differing from the host-journalled committed branch commits is REJECTED', async () => {
  const factory = loadLoop()
  // The observer replays a red commit that is NOT the host-journalled red commit: a worker-claimed
  // (or wrong) commit id never sources what the host accepts.
  const agent = makeAgent(implementScript({ observation: observationFor({ red_commit: 'someOtherRedCommit000000000000000000000009' }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /red commit checked out is not the host-journalled red commit/,
  )
})

test('test_observer_commit_inputs_are_host_journalled: a worker-claimed commit id that differs from the committed branch commits is REJECTED at the committed-result gate', async () => {
  const factory = loadLoop()
  // The worker claims a green_commit equal to its red_commit: the red and green collapse to one commit.
  const agent = makeAgent(implementScript({ mutationOverrides: { green_commit: RED_COMMIT } }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /red and green must be distinct commits/,
  )
})

// --- TUR-447 D1 cycle2 independent git-read trust root + worker-claim cross-check ---------------------

// test_independent_git_read_is_the_trust_root
test('test_independent_git_read_is_the_trust_root: the host establishes the observer inputs from an INDEPENDENT git read (given only the branch + expected HEAD, never the worker shas/path/digest), runs after the mutation and before the observer, and is a distinct Bash-capable subagent in an isolated worktree (NOT read-only Explore)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  const labels = agent.calls.map((c) => c.label)
  const mutIdx = agent.calls.findIndex((c) => c.label === `implementer:${ISSUE}` && c.agentType === null)
  const readIdx = agent.calls.findIndex((c) => c.label === `implementer-git-read:${ISSUE}`)
  const obsIdx = agent.calls.findIndex((c) => c.label === `implementer-tdd-observer:${ISSUE}`)
  const pushIdx = labels.findIndex((l) => l.startsWith('host-push:'))
  assert.ok(readIdx > mutIdx, 'independent git read runs after the committed mutation')
  assert.ok(readIdx < obsIdx, 'independent git read runs before the observer replay')
  assert.ok(obsIdx >= 0 && obsIdx < pushIdx, 'observer runs before the push')
  // TUR-447 D1 cycle3: the reader and observer run in ISOLATED git worktrees (opts.isolation: 'worktree')
  // with a Bash-capable agent, NOT agentType 'Explore' (read-only, cannot check out or run a test).
  const read = agent.calls[readIdx]
  assert.equal(read.opts.isolation, 'worktree', 'git read runs in an isolated git worktree')
  assert.equal(read.agentType, null, 'git reader is Bash-capable, NOT read-only Explore (which cannot run tests)')
  assert.equal(agent.calls[obsIdx].opts.isolation, 'worktree', 'observer runs in an isolated git worktree')
  assert.equal(agent.calls[obsIdx].agentType, null, 'observer is Bash-capable, NOT read-only Explore')
  // The git-read subagent is given ONLY the branch + expected starting HEAD, NEVER the worker's claimed
  // shas, and NEVER the worker's claimed bound-test path or digest (it DISCOVERS the bound test itself).
  assert.ok(read.prompt.includes(BRANCH), 'git-read prompt carries the committed branch name')
  assert.ok(read.prompt.includes(HEAD), 'git-read prompt carries the expected starting HEAD')
  assert.ok(!read.prompt.includes(RED_COMMIT), 'git-read prompt does NOT carry the worker-claimed red sha')
  assert.ok(!read.prompt.includes(GREEN_COMMIT), 'git-read prompt does NOT carry the worker-claimed green sha')
  assert.ok(!read.prompt.includes(FINAL_COMMIT), 'git-read prompt does NOT carry the worker-claimed final sha')
  assert.ok(!read.prompt.includes(BOUND_TEST.digest), 'git-read prompt does NOT carry the worker-claimed bound-test digest')
  assert.ok(/DISCOVER the bound test/i.test(read.prompt), 'reader discovers the bound test from the red diff itself')
  assert.ok(/YOURSELF from git/i.test(read.prompt), 'reader reads the shas/diffs/digests itself from git')
  // The observer then executes the INDEPENDENT-READ shas (which here equal the genuine committed shas).
  const obs = agent.calls.find((c) => c.label === `implementer-tdd-observer:${ISSUE}`)
  assert.ok(obs.prompt.includes(RED_COMMIT) && obs.prompt.includes(FINAL_COMMIT), 'observer executes the host-journalled (independent-read) commits')
})

// test_worker_claim_cross_checked_against_independent_read
test('test_worker_claim_cross_checked_against_independent_read: a worker whose claimed final commit is NOT what the independent git read read is REJECTED (a forged/cherry-picked worker sha never reaches the observer)', async () => {
  const factory = loadLoop()
  // The independent git read genuinely reads FINAL_COMMIT off the branch, but the worker CLAIMED a
  // different final_commit. The cross-check rejects it; nothing is journalled, observed, or pushed.
  const forgedFinal = 'forgedFinalWorkerClaim000000000000000009'
  const agent = makeAgent(implementScript({
    mutationOverrides: { final_commit: forgedFinal, head: forgedFinal },
    green: {
      command: VALIDATION_COMMAND, exit_status: 0, outcome: 'PASS', artifact: `${PR}#c2`,
      head: forgedFinal, scenario: SCENARIO,
    },
  }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /claimed final commit differs from the independent git read/,
  )
  assert.ok(!agent.calls.some((c) => c.label.startsWith('implementer-tdd-observer:')), 'observer never runs on a cross-check mismatch')
  assert.ok(!agent.calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed on a cross-check mismatch')
  assert.ok(agent.calls.some((c) => c.label.startsWith('workspace-abandon:')), 'the branch is abandoned unpushed on a cross-check mismatch')
})

// test_forged_independent_read_rejected
test('test_forged_independent_read_rejected: a git read NOT stamped by the independent reader (a worker masquerading as the trust root) is REJECTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ gitRead: gitReadFor({ source: 'implementer-subagent' }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /not from the independent git reader/,
  )
  assert.ok(!agent.calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed on a forged trust root')
})

// test_independent_read_rejects_nonlinear_or_wrong_base
test('test_independent_read_rejects_nonlinear_or_wrong_base: an independent read whose branch base is not the expected starting HEAD is REJECTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ gitRead: gitReadFor({ base_head: 'someUnrelatedBase00000000000000000000009' }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /branch base is not the expected starting HEAD/,
  )
})

test('test_independent_read_rejects_nonlinear_or_wrong_base: an independent read whose red commit is only a missing file (never genuinely failed) is REJECTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ gitRead: gitReadFor({ red_named_test_exit: 0 }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /the red commit did not fail the named test/,
  )
})

// test_observer_command_source_is_host_trusted
test('test_observer_command_source_is_host_trusted: the observer command is the canonical validation command from AGENTS.md supplied by the host, and a worker-authored command is rejected rather than executed', async () => {
  const factory = loadLoop()
  // The observer reports it ran a command that is NOT the host-sourced validation command.
  const agent = makeAgent(implementScript({ observation: observationFor({ command: 'malicious --worker-command' }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /command run is not the host-sourced validation command/,
  )
})

// test_invalid_red_missing_file_rejected
test('test_invalid_red_missing_file_rejected: a red that is only a missing file, module, export, or script (the observer never saw it genuinely FAIL) is REJECTED', async () => {
  const factory = loadLoop()
  // A missing-file red is not a genuine failing test: the observer records red_exit 0 (no genuine fail),
  // which the gate rejects. (An unrunnable invocation is not a valid red.)
  const agent = makeAgent(implementScript({ observation: observationFor({ red_exit: 0 }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /the red commit did not fail the named test/,
  )
})

// test_invalid_red_that_does_not_fail_rejected
test('test_invalid_red_that_does_not_fail_rejected: a red commit whose named test passes is REJECTED', async () => {
  const factory = loadLoop()
  // The worker reports a red proof with exit_status 0 (its own red passed): rejected at the committed gate.
  const passingRed = {
    command: VALIDATION_COMMAND, exit_status: 0, outcome: 'PASS', artifact: `${PR}#c1`,
    head: RED_COMMIT, scenario: SCENARIO,
  }
  const agent = makeAgent(implementScript({ red: passingRed }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /red must fail the named test before the production change/,
  )
})

// test_test_identity_binding_green_may_not_weaken_red
test('test_test_identity_binding_green_may_not_weaken_red: a green that removes, weakens, or edits the red bound test by path and content digest is REJECTED', async () => {
  const factory = loadLoop()
  // The observer sees the bound test at the GREEN commit with a DIFFERENT content digest: a green that
  // weakened/edited the bound test. Rejected even though tests pass.
  const agent = makeAgent(implementScript({
    observation: observationFor({ green_test: { path: BOUND_TEST.path, digest: 'sha256:weakened' } }),
  }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /bound test content digest differs at the green commit/,
  )
})

// test_push_ordering_host_push_only_after_observation_echo_readback
test('test_push_ordering_host_push_only_after_observation_echo_readback: the host push runs only after observation, ack echo, and the fresh pre-push readback, and the worker never pushes', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  // The mutation worker committed but did NOT push.
  const mut = agent.calls.find((c) => c.label === `implementer:${ISSUE}` && c.agentType === null)
  assert.ok(mut, 'mutation spawn ran')
  assert.ok(/HOST-GATED PUSH/.test(mut.prompt) && /do NOT git push/.test(mut.prompt), 'worker told to commit but not push')
  assert.ok(/COMMIT the red/.test(mut.prompt), 'worker told to commit the red then green')
  // Order: ack (Explore) -> mutation -> observer -> pre-push readback -> host push -> post-push readback.
  const order = agent.calls.map((c) => c.label)
  const mutIdx = order.findIndex((l) => l === `implementer:${ISSUE}`)
  const obsIdx = order.findIndex((l) => l.startsWith('implementer-tdd-observer:'))
  const readbackIdx = order.findIndex((l) => l.startsWith('implementer-prepush-readback:'))
  const pushIdx = order.findIndex((l) => l.startsWith('host-push:'))
  assert.ok(obsIdx > mutIdx, 'observer after mutation')
  assert.ok(readbackIdx > obsIdx, 'pre-push readback after observation')
  assert.ok(pushIdx > readbackIdx, 'host push after the pre-push readback')
  assert.equal(result.head, FINAL_COMMIT)
})

test('test_push_ordering: a worker that ALREADY pushed is REJECTED (the worker never pushes)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ mutationOverrides: { pushed: true } }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /implementer must not push/,
  )
})

test('test_push_ordering: a worker that did NOT commit is REJECTED (the committed model requires a commit)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ mutationOverrides: { committed: false } }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /implementer must commit the red then green/,
  )
})

// test_rejection_abandons_unpushed_branch
test('test_rejection_abandons_unpushed_branch: a rejected pass leaves its isolated branch unpushed with no destructive reset', async () => {
  const factory = loadLoop()
  // The observer replay fails (red did not fail): the host must ABANDON the unpushed branch, not reset.
  const agent = makeAgent(implementScript({ observation: observationFor({ red_exit: 0 }) }))
  const A = committedEnvelope()
  await assert.rejects(() => factory(agent, JSON.stringify(A), noop))
  // The host-non-push abort ran (branch abandoned unpushed); NO destructive reset of committed work.
  assert.ok(agent.calls.some((c) => c.label.startsWith('workspace-abandon:')), 'unpushed-branch abort invoked')
  assert.ok(!agent.calls.some((c) => c.label.startsWith('workspace-cleanup:')), 'no destructive reset of committed work')
  assert.ok(!agent.calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed on rejection')
  // The abort prompt tells the subagent NOT to push and NOT to destructively reset committed work.
  const abort = agent.calls.find((c) => c.label === `workspace-abandon:${ISSUE}`)
  assert.ok(/ABANDONED UNPUSHED/.test(abort.prompt), 'branch abandoned unpushed')
  assert.ok(/do NOT destructively/.test(abort.prompt), 'no destructive reset of committed work')
  assert.ok(/DIRTY or DIVERGED/.test(abort.prompt), 'a dirty or diverged worktree stops for inspection')
})

test('test_rejection_abandons_unpushed_branch: a genuinely dirty or diverged worktree STOPS for inspection rather than silently discarding', async () => {
  const factory = loadLoop()
  // Override the abandon subagent to report a dirty/diverged worktree.
  const factory2 = loadLoop()
  const agent2 = makeAgent(implementScript({ observation: observationFor({ red_exit: 0 }) }).map(
    ([m, r]) => m === 'workspace-abandon:'
      ? [m, { abandoned: false, pushed: false, dirty: true, head: FINAL_COMMIT, status: ' M tests/x' }]
      : [m, r],
  ))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory2(agent2, JSON.stringify(A), noop),
    /stopped for inspection: dirty or diverged worktree/,
  )
})

// test_final_head_independently_verified_green
test('test_final_head_independently_verified_green: the exact final pushed HEAD, after any refactor, is independently executed green by the observer before the push is accepted', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.head, FINAL_COMMIT)
  const obs = agent.calls.find((c) => c.label === `implementer-tdd-observer:${ISSUE}`)
  assert.ok(obs.prompt.includes(FINAL_COMMIT), 'observer executes the final HEAD')
  assert.ok(/FINAL HEAD/.test(obs.prompt) && /must PASS/.test(obs.prompt), 'final HEAD confirmed green')
})

test('test_final_head_independently_verified_green: a final HEAD the observer did NOT see green is REJECTED, nothing pushed', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ observation: observationFor({ final_exit: 1 }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /the final pushed HEAD is not green/,
  )
  assert.ok(!agent.calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed when the final HEAD is not green')
})

// test_final_head_binds_test_identity
test('test_final_head_binds_test_identity: the final-HEAD observation confirms the bound test unchanged at the final pushed HEAD, and a final HEAD whose bound test a refactor weakened/edited/removed is REJECTED', async () => {
  const factory = loadLoop()
  // The observer sees the bound test ABSENT (different path) at the FINAL HEAD: a refactor removed it.
  const agent = makeAgent(implementScript({
    observation: observationFor({ final_test: { path: 'tests/other.mjs', digest: BOUND_TEST.digest } }),
  }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /bound test path absent or changed at the final commit/,
  )
})

// test_push_readback_uses_live_remote
test('test_push_readback_uses_live_remote: the pushed-HEAD confirmation reads the live remote through gh api or git ls-remote, never a local tracking ref', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.head, FINAL_COMMIT)
  const order = agent.calls.map((c) => c.label)
  const pushIdx = order.findIndex((l) => l.startsWith('host-push:'))
  const rbIdx = order.findIndex((l) => l.startsWith('implementer-postpush-readback:'))
  assert.ok(rbIdx > pushIdx, 'live-remote readback runs after the push, before advancing')
  const rb = agent.calls.find((c) => c.label === `implementer-postpush-readback:${ISSUE}`)
  assert.equal(rb.agentType, 'Explore', 'live-remote readback is read-only')
  assert.ok(/LIVE\s+REMOTE/.test(rb.prompt) && /gh api|git ls-remote/.test(rb.prompt), 'reads the live remote')
  assert.ok(/NOT a local tracking ref/.test(rb.prompt), 'not a local tracking ref')
})

test('test_push_readback_uses_live_remote: a readback whose source is a local tracking ref (not gh api / git ls-remote) is REJECTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ postPush: { remote_head: FINAL_COMMIT, remote_source: 'local-tracking-ref' } }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /must be confirmed by a live remote read/,
  )
})

test('test_push_readback_uses_live_remote: a live remote HEAD that does not match the verified committed final HEAD is REJECTED (no false advance)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ postPush: { remote_head: 'someOtherHead0000000000000000000000000000', remote_source: 'gh-api' } }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /live remote HEAD does not match the expected pushed final HEAD/,
  )
})

// F1 preserved: a write-worker whose ack echo MISMATCHES has its committed pass abandoned unpushed.
test('F1: a write-worker whose ack echo MISMATCHES has its committed pass ABANDONED unpushed (not reset)', async () => {
  const factory = loadLoop()
  const script = implementScript({ mutationAck: ackFor('implementer', { issue: 'TUR-999' }) })
  const agent = makeAgent(script)
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /worker ack issue mismatch/,
  )
  // The committed pass is abandoned unpushed (no destructive reset), and nothing is pushed.
  assert.ok(agent.calls.some((c) => c.label.startsWith('workspace-abandon:')), 'committed echo mismatch abandons the unpushed branch')
  assert.ok(!agent.calls.some((c) => c.label.startsWith('host-push:')), 'nothing pushed on echo mismatch')
})

test('F1-positive: a matching committed-worker echo is ACCEPTED with no abort', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  assert.ok(!agent.calls.some((c) => c.label.startsWith('workspace-abandon:')), 'no abort on a matching echo')
})

// TDD gate: a red/green whose SCENARIO differs is REJECTED (not the same behavior).
test('TDD gate: a committed red/green whose SCENARIO differs is REJECTED (not the same behavior)', async () => {
  const factory = loadLoop()
  const red = {
    command: VALIDATION_COMMAND, exit_status: 1, outcome: 'FAIL', artifact: `${PR}#c1`,
    head: RED_COMMIT, scenario: 'scenario-A',
  }
  const green = {
    command: VALIDATION_COMMAND, exit_status: 0, outcome: 'PASS', artifact: `${PR}#c2`,
    head: FINAL_COMMIT, scenario: 'scenario-B',
  }
  const agent = makeAgent(implementScript({ red, green }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /green must prove the same scenario as red/,
  )
})

test('TDD gate: a genuine committed red-then-green delivery pass is ACCEPTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  assert.equal(result.implementation.green.exit_status, 0)
})

test('P0-negative: an actually-wrong post-fire Linear state STILL rejects (stale gate not weakened)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ fresh: freshReads({ linear_state: 'Backlog' }) }))
  const A = committedEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /stale envelope: Linear state disagrees with fresh read/,
  )
})

// F2 preserved: the implementer pass resolves runtime from roles.toml via a COMPLETE resolver command.
test('F2: the implementer pass resolves runtime from roles.toml via a COMPLETE resolver command and mutates under the resolved model/effort', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = committedEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  const runtimeCall = agent.calls.find((c) => c.label === `implementer-runtime:${ISSUE}`)
  assert.ok(runtimeCall, 'implementer runtime-resolution spawn ran')
  assert.equal(runtimeCall.agentType, 'Explore', 'runtime resolution is read-only')
  const brief = runtimeCall.prompt
  assert.ok(brief.includes('role_resolver.py'), 'resolver script named')
  assert.ok(/\bresolve\b/.test(brief) && brief.includes('resolve implementer'), 'resolve subcommand + role present')
  assert.ok(!brief.includes('...'), 'no literal ... placeholder in the resolver command')
  for (const arg of ['--spawn-id', '--parent', '--reply-route', '--repo', '--worktree',
    '--execution-location', '--review-delivery']) {
    assert.ok(brief.includes(arg), `resolver command passes ${arg}`)
  }
  assert.ok(brief.includes(`--repo ${REPO}`), 'repo threaded into the command')
  assert.ok(brief.includes('--worktree /root/octo-lite'), 'absolute contained worktree threaded')
  assert.ok(brief.includes('--execution-location local'), 'execution-location threaded')
  const mut = agent.calls.find((c) => c.label === `implementer:${ISSUE}` && c.agentType === null)
  assert.ok(mut, 'write-capable mutation spawn ran')
  assert.equal(mut.opts.model, RESOLVED_WORKER_RUNTIME.model, 'mutation uses resolved model')
  assert.equal(mut.opts.effort, RESOLVED_WORKER_RUNTIME.effort, 'mutation uses resolved effort')
  assert.ok(mut.prompt.includes(RESOLVED_WORKER_RUNTIME.contract_text), 'resolved contract text in worker prompt')
})


// The loop binds journalledBoundInputs(role, startingHead) and revalidates the launch revision
// over THAT object, so a reviewer/shaping pass must carry the revision computed for its own role
// and starting HEAD (not the implementer's), exactly as a genuine caller would.
function boundInputsFor(role, startingHead) {
  return {
    role, repo: REPO, issue: ISSUE, pr: PR,
    starting_head: startingHead, spec_blobs: SPEC_BLOBS, contract_hash: CONTRACT,
  }
}

// A code-review pass drives the OpenAI relay path end to end through the composed loop.
function reviewEnvelope(overrides = {}) {
  const base = readyEnvelope()
  const merged = {
    ...base, mode: 'code-review', head: HEAD, cycle: 1,
    linear_state: 'Todo', linear_fingerprint: fingerprintFor('Todo'), ...overrides,
  }
  merged.launch_revision = launchRevision(boundInputsFor('code-reviewer', HEAD))
  return merged
}

function reviewerScript({
  role = 'code-reviewer', runtime = RESOLVED_REVIEWER_RUNTIME, verdict = 'clear', linearState = 'Todo',
} = {}) {
  const SESSION = 'sess-tur447'
  const PAYLOAD = 'REVIEWER FINAL MESSAGE VERBATIM'
  const ack = ackFor(role)
  return [
    [`${role}-readback:`, freshReads({ linear_state: linearState, linear_fingerprint: fingerprintFor(linearState) })],
    [`${role}-runtime:`, runtime],
    [`${role}-relay:`, {
      claimed_session_id: SESSION, payload: PAYLOAD,
      bootstrap_argv: ['codex', 'exec', '--json', '-C', '/root/octo-lite', '-m', runtime.model, '-s', 'read-only', '-'],
      resume_argv: [
        'codex', 'exec', 'resume', '--json',
        '-c', 'sandbox_mode="workspace-write"', '-c', 'sandbox_workspace_write.network_access=true', SESSION, '-',
      ],
      needs_live_reads: true,
      worktree_before: { head: HEAD, status: '' }, worktree_after: { head: HEAD, status: '' },
    }],
    [`${role}-rollout:`, {
      source: 'independent-rollout-subagent',
      data: { provider: runtime.provider, model: runtime.model, effort: runtime.effort, final_message: PAYLOAD },
    }],
    [`${role}:`, {
      ack, head: HEAD, verdict, findings: verdict === 'blocking' ? ['f'] : [],
      comment_url: `${PR}#c`,
    }],
  ]
}

// P0 composed-runtime proof: the OpenAI relay prompt carries the REAL per-pass brief, the
// contained WORKTREE path, and the canonical CONTRACT TEXT resolved from roles.toml, and the
// runtime is resolved through the COMPLETE resolver command (role-openai-relay).
test('P0: the code-reviewer relay prompt carries the real brief, worktree path, and resolved canonical contract text', async () => {
  const factory = loadLoop()
  const agent = makeAgent(reviewerScript())
  const A = reviewEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-clear')
  // Runtime resolved from roles.toml via the COMPLETE resolver command.
  const runtimeCall = agent.calls.find((c) => c.label === `code-reviewer-runtime:${ISSUE}`)
  assert.ok(runtimeCall && runtimeCall.agentType === 'Explore', 'reviewer runtime resolved read-only')
  assert.ok(!runtimeCall.prompt.includes('...'), 'no ... in reviewer resolver command')
  assert.ok(runtimeCall.prompt.includes('resolve code-reviewer'), 'resolves the code-reviewer role')
  assert.ok(runtimeCall.prompt.includes('--review-delivery'), 'reviewer resolver command complete')
  // The relay prompt carries brief + worktree + canonical contract text.
  const relayCall = agent.calls.find((c) => c.label === `code-reviewer-relay:${ISSUE}`)
  assert.ok(relayCall, 'relay spawn ran')
  assert.ok(relayCall.prompt.includes('do the work'), 'relay carries the real per-pass brief')
  assert.ok(relayCall.prompt.includes('/root/octo-lite'), 'relay carries the contained worktree path')
  assert.ok(
    relayCall.prompt.includes(RESOLVED_REVIEWER_RUNTIME.contract_text),
    'relay carries the resolved canonical contract text',
  )
  // The rollout reader is a DISTINCT read-only spawn (independent provenance).
  const rolloutCall = agent.calls.find((c) => c.label === `code-reviewer-rollout:${ISSUE}`)
  assert.ok(rolloutCall && rolloutCall.agentType === 'Explore', 'independent rollout reader ran read-only')
})

// P0 composed-runtime proof: shaping-reviewer has a WORKING spawn path through the same relay
// with the shaping-review admission purpose and the shaping-review relay acceptance gate.
test('P0: shaping-reviewer has a working relay spawn path (launch-purpose-shaping-roles)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(reviewerScript({ role: 'shaping-reviewer', linearState: 'Shaped' }))
  // A shaping-review pass runs at a shaping-eligible Linear state (Shaped) with head bound.
  const A = {
    ...readyEnvelope(), mode: 'shaping-review', head: HEAD, linear_state: 'Shaped',
    launch_revision: launchRevision(boundInputsFor('shaping-reviewer', HEAD)),
  }
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'shaping-review-verdict')
  assert.equal(result.shaping_review.verdict, 'clear')
  // The shaping-reviewer runtime resolved from roles.toml and its relay ran.
  assert.ok(
    agent.calls.some((c) => c.label === `shaping-reviewer-runtime:${ISSUE}` && c.agentType === 'Explore'),
    'shaping-reviewer runtime resolved read-only',
  )
  assert.ok(
    agent.calls.some((c) => c.label === `shaping-reviewer-relay:${ISSUE}`),
    'shaping-reviewer relay spawn ran',
  )
})

// P0 composed proof: the shaping relay is genuinely fail-closed. A relay-supplied rollout (not
// from the independent read-only subagent) is rejected exactly as at the reviewer gate.
test('P0-negative: a shaping-reviewer relay whose rollout is not from the independent reader is REJECTED', async () => {
  const factory = loadLoop()
  const script = reviewerScript({ role: 'shaping-reviewer', linearState: 'Shaped' }).map(([m, r]) =>
    m === 'shaping-reviewer-rollout:' ? [m, { ...r, source: 'relay' }] : [m, r])
  const agent = makeAgent(script)
  const A = {
    ...readyEnvelope(), mode: 'shaping-review', head: HEAD, linear_state: 'Shaped',
    launch_revision: launchRevision(boundInputsFor('shaping-reviewer', HEAD)),
  }
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /not from the independent read-only subagent/,
  )
})

// F2 real-run proof: the exact resolver command the loop tells its subagent to run actually
// exits 0 and PRINTS the resolved runtime (provider/model/effort/service_tier/contract_blob)
// plus the canonical contract text, parseably. This proves the brief is runnable, not just
// well-formed.
test('F2: the resolver command runs for real, exits 0, and prints the resolved runtime + contract', () => {
  const out = execFileSync('python3', [
    'workflows/lib/role_resolver.py', 'resolve', 'code-reviewer',
    '--spawn-id', 'composed-1', '--parent', 'orchestrator', '--reply-route', 'route',
    '--repo', ROOT, '--worktree', ROOT, '--execution-location', 'local',
    '--review-delivery', 'pr-comment', '--emit-contract',
  ], { cwd: ROOT, encoding: 'utf8' })
  assert.ok(out.includes('[runtime]'), 'resolve prints a runtime section')
  assert.ok(out.includes('provider = "openai"'), 'resolve prints provider')
  assert.ok(out.includes('model = "gpt-5.6-sol"'), 'resolve prints model')
  assert.ok(/effort = "high"/.test(out), 'resolve prints effort')
  assert.ok(/service_tier = "default"/.test(out), 'resolve prints service_tier')
  assert.ok(out.includes('[contract]'), 'resolve prints the canonical contract table')
  assert.ok(/blob = "[0-9a-f]{40,64}"/.test(out), 'resolve prints contract blob')
  assert.ok(out.includes('Independently review one exact implementation HEAD'), 'resolve prints contract text')
})

// TUR-447 cycle1 pass3 reconcile binding (role-runtime role-reconciler-snapshot-receipt-binding,
// role-reconciler-snapshot-integrity, role-reconciler-authority; operating-model
// decision-109-binding). The gpt-5.6-sol HIGH finding: the reconcile classifier received neither
// the journal path nor the verified snapshot, so it classified BLIND, and the loop discarded the
// classified.ack, binding whatever classification came back. These composed tests drive the ACTUAL
// reconcile mode end to end and prove the classifier is wired to the journal-bound snapshot and the
// verified ack is carried into the binder, never discarded.
const JOURNAL_PATH = '/root/worktrees/sweep-1/journal.json'
const SNAP_DIGEST = 'd'.repeat(64)

function reconcileEnvelope(overrides = {}) {
  return {
    mode: 'reconcile',
    repo: REPO, issue: ISSUE, pr: PR, branch: BRANCH,
    worktree_root: '/root/worktrees', worktree: 'sweep-1',
    journal_path: JOURNAL_PATH,
    brief: 'Classify the reconcile deltas against the journal-bound snapshot.',
    ...overrides,
  }
}

// A healthy reconcile script: read-only ack (Explore) -> ack verify -> read-only classify
// (Explore) -> bind. The ack + ack-verify echo the journal-bound snapshot digest; the
// classifier re-echoes the verified ack; the binder returns the bound result.
function reconcileScript({
  ackSnapshotDigest = SNAP_DIGEST, verifiedDigest = SNAP_DIGEST,
  classification = 'changed', needsFable = false, classifierAck, boundOk = true,
} = {}) {
  const ack = {
    schema_version: 1, spawn_id: 'spawn-recon-1', launch_revision: 'lr-recon',
    role: 'reconciler', worktree: '/root/worktrees/sweep-1', starting_head: HEAD,
    snapshot_path: '/root/worktrees/sweep-1/snapshot.md', snapshot_digest: ackSnapshotDigest,
    ready: true, blocker: '',
  }
  const echoedAck = classifierAck ?? ack
  return [
    ['reconciler-ack:', { ack }],
    ['reconciler-ack-verify:', {
      verified: true, snapshot_path: ack.snapshot_path, snapshot_digest: verifiedDigest,
    }],
    ['reconciler:', {
      ack: echoedAck, classification, needs_fable: needsFable,
      deltas: ['TUR-1 PR head moved'],
    }],
    ['reconciler-bind:', ({ prompt }) => {
      // A genuine binder subagent invokes bind_reconcile_workflow_result, which now REQUIRES
      // the re-echoed ack; a bind prompt that omitted it would fail closed in Python. The
      // composed binder returns the bound result the loop reports.
      return boundOk
        ? { bound: true, classification, needs_fable: needsFable, deltas: ['TUR-1 PR head moved'] }
        : { bound: false, classification, needs_fable: needsFable, deltas: [] }
    }],
  ]
}

test('reconcile: the classifier receives the journal path AND the verified snapshot (not blind)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(reconcileScript())
  const A = reconcileEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'reconcile-classified')
  assert.equal(result.classification, 'changed')
  const classifierCall = agent.calls.find((c) => c.label === `reconciler:${ISSUE}`)
  assert.ok(classifierCall, 'classifier spawn ran')
  assert.equal(classifierCall.agentType, 'Explore', 'classifier is read-only')
  // Not blind: the classifier prompt carries the journal path so it classifies against the
  // ACTUAL journal-bound snapshot, and it carries the verified snapshot digest.
  assert.ok(classifierCall.prompt.includes(JOURNAL_PATH), 'classifier brief carries the journal path')
  assert.ok(classifierCall.prompt.includes(SNAP_DIGEST), 'classifier brief carries the verified snapshot digest')
})

test('reconcile: the verified ack is CARRIED into the binder, never discarded', async () => {
  const factory = loadLoop()
  const agent = makeAgent(reconcileScript())
  const A = reconcileEnvelope()
  await factory(agent, JSON.stringify(A), noop)
  const bindCall = agent.calls.find((c) => c.label === `reconciler-bind:${ISSUE}`)
  assert.ok(bindCall, 'bind spawn ran')
  // The classifier re-echoed the verified ack; the binder prompt must carry that ack (its
  // snapshot_path + digest) so bind_reconcile_workflow_result can re-verify it. A loop that
  // discarded classified.ack would omit it here.
  assert.ok(bindCall.prompt.includes('snapshot_digest'), 'bind prompt carries the ack snapshot digest field')
  assert.ok(bindCall.prompt.includes(SNAP_DIGEST), 'bind prompt carries the verified snapshot digest')
  assert.ok(bindCall.prompt.includes('/root/worktrees/sweep-1/snapshot.md'), 'bind prompt carries the ack snapshot path')
})

test('reconcile: a classifier whose re-echoed ack digest MISMATCHES the verified digest is REJECTED', async () => {
  const factory = loadLoop()
  // The classifier re-echoes an ack whose snapshot digest disagrees with the digest the host
  // verified against the journal: the reconciler is not bound to the verified snapshot.
  const badAck = {
    schema_version: 1, spawn_id: 'spawn-recon-1', launch_revision: 'lr-recon',
    role: 'reconciler', worktree: '/root/worktrees/sweep-1', starting_head: HEAD,
    snapshot_path: '/root/worktrees/sweep-1/snapshot.md', snapshot_digest: '0'.repeat(64),
    ready: true, blocker: '',
  }
  const agent = makeAgent(reconcileScript({ classifierAck: badAck }))
  const A = reconcileEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /reconcile classification not bound to the verified snapshot/,
  )
  // The binder was never reached: a mismatch fails closed in the loop before binding.
  assert.ok(!agent.calls.some((c) => c.label === `reconciler-bind:${ISSUE}`), 'binder not reached on ack mismatch')
})
