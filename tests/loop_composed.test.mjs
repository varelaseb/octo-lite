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
    linear_fingerprint: 'lfp-1', linear_state: 'Shaped',
    shaping_verdict: 'clear', shaping_verdict_head: HEAD,
    shaping_reviewer_receipt: 'rcpt-1', conversation_cutoff: 'session.jsonl:1',
    conversation_log_references: ['session.jsonl:1-1'],
    spec_blobs: SPEC_BLOBS, adr_blobs: [], shaping_verdict_inputs: ['in-1'],
    acceptance_criteria: ['works'],
    contract_hash: CONTRACT,
    brief: 'do the work',
    worktree_root: '/root', worktree: 'octo-lite',
    loop_fire_args: '--reason ship',
  }
  const merged = { ...base, ...overrides }
  // A genuine caller supplies the launch_revision computed over the exact bound inputs
  // whose starting HEAD is shaping_head; recompute it here so it matches the loop.
  merged.launch_revision = launchRevision(boundInputs('implementer'))
  return merged
}

// Freshly-read live values a genuine readback subagent returns. Default is a healthy
// post-fire world: Linear is Todo (the loop fired Shaped -> Todo), git HEAD unchanged.
function freshReads(overrides = {}) {
  return {
    linear_state: 'Todo', linear_fingerprint: 'lfp-1',
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
    calls.push({ label, agentType: opts.agentType ?? null, phase: opts.phase })
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

// A full healthy implement script: readback -> ack (Explore) -> mutation (write) each
// answer with a genuine echo, and a genuine red-before-mutation-then-green proof.
function implementScript({ fresh = freshReads(), red, green, mutationAck = ackFor('implementer'), fireState = 'Todo' } = {}) {
  const goodRed = red ?? {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL: behavior wrong',
    artifact: `${PR}#c1`, head: HEAD, scenario: 'shaped-member-fires-todo',
  }
  const goodGreen = green ?? {
    command: 'node --test tests/', exit_status: 0, outcome: 'PASS: behavior right',
    artifact: `${PR}#c2`, head: NEWHEAD, scenario: 'shaped-member-fires-todo',
  }
  return [
    ['loop-fire:', { command: 'octo-control linear-transition', exit_status: 0, readback_state: fireState }],
    ['implementer-readback:', fresh],
    ['implementer-ack:', { ack: ackFor('implementer') }],
    ['implementer:', {
      ack: mutationAck, issue: ISSUE, pr_url: PR, branch: BRANCH, head: NEWHEAD,
      handoff_url: `${PR}#h`, red: goodRed, green: goodGreen, validation: 'suite', blocked: false,
    }],
    ['workspace-cleanup:', { cleaned: true, head: HEAD, status: '' }],
  ]
}

test('P0: a genuine Shaped member fires Todo then REACHES the write-capable mutation spawn without self-rejecting', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = readyEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  assert.equal(result.head, NEWHEAD)
  // The write-capable mutation spawn was REACHED: an implementer spawn with NO
  // read-only agentType ran AFTER the read-only ack spawn.
  const labels = agent.calls.map((c) => `${c.label}|${c.agentType}`)
  const ackIdx = labels.findIndex((l) => l.startsWith(`implementer-ack:${ISSUE}|Explore`))
  const mutIdx = labels.findIndex((l) => l === `implementer:${ISSUE}|null`)
  assert.ok(ackIdx >= 0, 'read-only ack (Explore) phase ran')
  assert.ok(mutIdx > ackIdx, 'write-capable mutation phase reached after ack')
})

test('P0-negative: an actually-wrong post-fire Linear state STILL rejects (stale gate not weakened)', async () => {
  const factory = loadLoop()
  // Fresh live read reports Backlog, which disagrees with the true post-fire Todo.
  const agent = makeAgent(implementScript({ fresh: freshReads({ linear_state: 'Backlog' }) }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /stale envelope: Linear state disagrees with fresh read/,
  )
})

test('F1: a write-worker whose ack echo MISMATCHES has its mutation REJECTED and the worktree cleaned', async () => {
  const factory = loadLoop()
  // The mutation phase returns a WRONG issue in its ack echo: unverified identity.
  const script = implementScript({ mutationAck: ackFor('implementer', { issue: 'TUR-999' }) })
  const agent = makeAgent(script)
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /worker ack issue mismatch/,
  )
  // The worktree cleanup MUST have been invoked so no unverified mutation is accepted.
  const cleaned = agent.calls.some((c) => c.label.startsWith('workspace-cleanup:'))
  assert.ok(cleaned, 'worktree cleanup invoked on echo mismatch (mutation discarded, not accepted)')
})

test('F1-positive: a matching write-worker echo is ACCEPTED with no cleanup', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = readyEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  const cleaned = agent.calls.some((c) => c.label.startsWith('workspace-cleanup:'))
  assert.ok(!cleaned, 'no cleanup on a matching echo')
})

test('TDD gate: a fabricated proof-shaped object (red at post-mutation head) is REJECTED', async () => {
  const factory = loadLoop()
  // Fabricated: red claims to have run at the NEW post-mutation head, and green at the
  // same head. This is proof-shaped (all string/int fields present) but does not prove
  // red ran at the unchanged starting HEAD before mutation.
  const fabRed = {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL',
    artifact: `${PR}#c1`, head: NEWHEAD, scenario: 'x',
  }
  const fabGreen = {
    command: 'node --test tests/', exit_status: 0, outcome: 'PASS',
    artifact: `${PR}#c2`, head: NEWHEAD, scenario: 'x',
  }
  const agent = makeAgent(implementScript({ red: fabRed, green: fabGreen }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /red must run at the unchanged starting HEAD before mutation/,
  )
})

test('TDD gate: a red/green whose SCENARIO differs is REJECTED (not the same behavior)', async () => {
  const factory = loadLoop()
  const red = {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL',
    artifact: `${PR}#c1`, head: HEAD, scenario: 'scenario-A',
  }
  const green = {
    command: 'node --test tests/', exit_status: 0, outcome: 'PASS',
    artifact: `${PR}#c2`, head: NEWHEAD, scenario: 'scenario-B',
  }
  const agent = makeAgent(implementScript({ red, green }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /green must prove the same scenario as red/,
  )
})

test('TDD gate: a genuine red-before-mutation-then-green sequence is ACCEPTED', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = readyEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  assert.equal(result.implementation.green.exit_status, 0)
})
