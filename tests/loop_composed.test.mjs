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

// A full healthy implement script: fire (returns post-fire Todo state AND Todo fingerprint) ->
// readback -> ack (Explore) -> mutation (write, host-gated: committed/pushed false, green at the
// UNCHANGED starting HEAD, red carries a captured evidence artifact bound to the starting HEAD,
// liveness fields echoed) -> pre-push readback -> host commit/push (produces the new HEAD).
function implementScript({
  fresh = freshReads(), red, green, mutationAck = ackFor('implementer'),
  fireState = 'Todo', fireFingerprint = fingerprintFor('Todo'),
  mutationOverrides = {}, prePush = freshReads(), commitResult,
  liveness = { linear_state: 'Todo', linear_fingerprint: fingerprintFor('Todo'), branch: BRANCH },
} = {}) {
  const goodRed = red ?? {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL: behavior wrong',
    artifact: `${PR}#c1`, head: HEAD, scenario: 'shaped-member-fires-todo',
    // Independently-observed evidence artifact bound to the unchanged starting HEAD.
    evidence: {
      captured_output: 'AssertionError: expected reconciled fingerprint, got stale\n1 failing',
      exit_status: 1, head: HEAD,
    },
  }
  // Host-gated push: green runs at the UNCHANGED starting HEAD (working-tree mutation, no commit).
  const goodGreen = green ?? {
    command: 'node --test tests/', exit_status: 0, outcome: 'PASS: behavior right',
    artifact: `${PR}#c2`, head: HEAD, scenario: 'shaped-member-fires-todo',
  }
  return [
    ['loop-fire:', {
      command: 'octo-control linear-transition', exit_status: 0,
      readback_state: fireState, readback_fingerprint: fireFingerprint,
    }],
    ['implementer-readback:', fresh],
    ['implementer-runtime:', RESOLVED_WORKER_RUNTIME],
    ['implementer-ack:', { ack: ackFor('implementer') }],
    ['implementer:', {
      ack: mutationAck, issue: ISSUE, pr_url: PR, branch: BRANCH, head: HEAD,
      handoff_url: `${PR}#h`, red: goodRed, green: goodGreen, validation: 'suite', blocked: false,
      // Host-gated push: the worker did NOT commit or push, and echoed its liveness reads.
      committed: false, pushed: false,
      linear_state: liveness.linear_state, linear_fingerprint: liveness.linear_fingerprint,
      ...mutationOverrides,
    }],
    ['workspace-cleanup:', { cleaned: true, head: HEAD, status: '' }],
    // Pre-push readback: a fresh live read immediately before the host commit.
    ['implementer-prepush-readback:', prePush],
    // Host commit/push: the ONLY commit/push seam, run after all verifies; produces the new HEAD.
    ['host-commit-push:', commitResult ?? { committed: true, pushed: true, head: NEWHEAD }],
  ]
}

test('P0: a genuine Shaped member fires Todo, the bound fingerprint is RECONCILED, and it reaches the mutation spawn without self-rejecting', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = readyEnvelope()
  // The envelope binds the SHAPED fingerprint; the post-fire live read reports the TODO
  // fingerprint (a different value). Without fingerprint reconciliation the pass self-rejects.
  assert.equal(A.linear_fingerprint, fingerprintFor('Shaped'))
  assert.notEqual(fingerprintFor('Shaped'), fingerprintFor('Todo'))
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

test('P0-fingerprint: reusing the STALE Shaped fingerprint after the fire self-rejects (proves reconciliation is real, not a constant)', async () => {
  const factory = loadLoop()
  // Model a loop that fired but did NOT reconcile the fingerprint: the fire reports the SHAPED
  // fingerprint as its post-fire fingerprint (a stale, wrong value). The subsequent live read
  // reports the true TODO fingerprint, so assertLaunchReadback must reject.
  const agent = makeAgent(implementScript({ fireFingerprint: fingerprintFor('Shaped') }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /stale envelope: Linear fingerprint disagrees with fresh read/,
  )
})

test('stale-race: a live change BEFORE push (Linear fingerprint moved after bind) is REJECTED, nothing pushed', async () => {
  const factory = loadLoop()
  // Spawn-start readback is healthy (Todo). But the pre-push readback reports a DIFFERENT live
  // fingerprint: the issue changed during the intervening resolver/ack/mutation passes.
  const agent = makeAgent(implementScript({
    prePush: freshReads({ linear_fingerprint: 'fp-moved-since-bind' }),
  }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /pre-push readback: Linear fingerprint changed since bind/,
  )
  // The host commit/push seam was NEVER reached: nothing was pushed.
  assert.ok(
    !agent.calls.some((c) => c.label.startsWith('host-commit-push:')),
    'host commit/push not reached when a live change is detected before push',
  )
})

test('host-gated push: the worker does NOT push; the host pushes ONLY after echo + pre-push readback + TDD verify', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = readyEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  // The mutation worker asserted committed:false and pushed:false (it did not push).
  const mut = agent.calls.find((c) => c.label === `implementer:${ISSUE}` && c.agentType === null)
  assert.ok(mut, 'mutation spawn ran')
  // The mutation prompt instructed host-gated push (no commit/push) and a red evidence artifact.
  assert.ok(/HOST-GATED PUSH/.test(mut.prompt), 'mutation prompt instructs host-gated push')
  assert.ok(/do NOT git commit and do NOT git push/.test(mut.prompt), 'worker told not to commit/push')
  assert.ok(/evidence/.test(mut.prompt) && /captured/i.test(mut.prompt), 'mutation prompt requires a captured red evidence artifact')
  // The host commit/push ran AFTER the pre-push readback, which ran AFTER the mutation spawn.
  const order = agent.calls.map((c) => c.label)
  const mutIdx = order.findIndex((l) => l === `implementer:${ISSUE}`)
  const readbackIdx = order.findIndex((l) => l.startsWith('implementer-prepush-readback:'))
  const pushIdx = order.findIndex((l) => l.startsWith('host-commit-push:'))
  assert.ok(mutIdx >= 0 && readbackIdx > mutIdx, 'pre-push readback runs after the mutation')
  assert.ok(pushIdx > readbackIdx, 'host commit/push runs after the pre-push readback')
  // The delivered HEAD is the HOST commit head, not a worker-produced head.
  assert.equal(result.head, NEWHEAD)
})

test('host-gated push: a worker that ALREADY pushed is REJECTED (post-hoc reset cannot undo a push)', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript({ mutationOverrides: { committed: true, pushed: true, head: NEWHEAD } }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /worker must not commit|worker must not push/,
  )
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

test('TDD gate: a fabricated proof with NO genuine evidence artifact is REJECTED (independent observation)', async () => {
  const factory = loadLoop()
  // Fabricated: proof-shaped strings but NO captured evidence artifact. The gate independently
  // requires the observed failing-test artifact bound to the starting HEAD, so bare strings fail.
  const fabRed = {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL',
    artifact: `${PR}#c1`, head: HEAD, scenario: 'x',
    // evidence deliberately omitted
  }
  const agent = makeAgent(implementScript({ red: fabRed }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /red evidence artifact required/,
  )
})

test('TDD gate: an evidence artifact NOT bound to the starting HEAD is REJECTED', async () => {
  const factory = loadLoop()
  // The evidence claims to have run at the NEW post-mutation head, not the unchanged starting
  // HEAD, so red-before-mutation is not genuinely observed.
  const fabRed = {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL',
    artifact: `${PR}#c1`, head: HEAD, scenario: 'x',
    evidence: { captured_output: '1 failing', exit_status: 1, head: NEWHEAD },
  }
  const agent = makeAgent(implementScript({ red: fabRed }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /red evidence must be bound to the unchanged starting HEAD/,
  )
})

test('TDD gate: an evidence exit that DISAGREES with the reported red exit is REJECTED', async () => {
  const factory = loadLoop()
  // The reported red exit is 1 (fail) but the captured artifact records exit 0: the artifact does
  // not corroborate the claimed failing run.
  const fabRed = {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL',
    artifact: `${PR}#c1`, head: HEAD, scenario: 'x',
    evidence: { captured_output: 'ok', exit_status: 0, head: HEAD },
  }
  const agent = makeAgent(implementScript({ red: fabRed }))
  const A = readyEnvelope()
  await assert.rejects(
    () => factory(agent, JSON.stringify(A), noop),
    /red evidence must record a genuinely failing run|red evidence exit status must match/,
  )
})

test('TDD gate: a red/green whose SCENARIO differs is REJECTED (not the same behavior)', async () => {
  const factory = loadLoop()
  const red = {
    command: 'node --test tests/', exit_status: 1, outcome: 'FAIL',
    artifact: `${PR}#c1`, head: HEAD, scenario: 'scenario-A',
    evidence: { captured_output: '1 failing', exit_status: 1, head: HEAD },
  }
  const green = {
    command: 'node --test tests/', exit_status: 0, outcome: 'PASS',
    artifact: `${PR}#c2`, head: HEAD, scenario: 'scenario-B',
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

// TUR-447 cycle1 pass2 F2 composed-runtime proof: a delivery worker pass ACTUALLY resolves its
// runtime FROM roles.toml, and the resolver-subagent brief carries a COMPLETE, runnable
// role_resolver.py resolve command with EVERY required arg and NO literal '...'. The mutation
// spawn then runs under the resolved model and effort, not a hardcoded generic spawn.
test('F2: the implementer pass resolves runtime from roles.toml via a COMPLETE resolver command and mutates under the resolved model/effort', async () => {
  const factory = loadLoop()
  const agent = makeAgent(implementScript())
  const A = readyEnvelope()
  const result = await factory(agent, JSON.stringify(A), noop)
  assert.equal(result.stage, 'code-review-required')
  // A runtime-resolution spawn ran, read-only, before the mutation.
  const runtimeCall = agent.calls.find((c) => c.label === `implementer-runtime:${ISSUE}`)
  assert.ok(runtimeCall, 'implementer runtime-resolution spawn ran')
  assert.equal(runtimeCall.agentType, 'Explore', 'runtime resolution is read-only')
  const brief = runtimeCall.prompt
  // The brief carries the COMPLETE resolver command: the script name, the resolve subcommand,
  // the role, and every required arg. No literal '...' placeholder.
  assert.ok(brief.includes('role_resolver.py'), 'resolver script named')
  assert.ok(/\bresolve\b/.test(brief) && brief.includes('resolve implementer'), 'resolve subcommand + role present')
  assert.ok(!brief.includes('...'), 'no literal ... placeholder in the resolver command')
  for (const arg of ['--spawn-id', '--parent', '--reply-route', '--repo', '--worktree',
    '--execution-location', '--review-delivery']) {
    assert.ok(brief.includes(arg), `resolver command passes ${arg}`)
  }
  // The bound values are actually substituted (not left as templates).
  assert.ok(brief.includes(`--repo ${REPO}`), 'repo threaded into the command')
  assert.ok(brief.includes('--worktree /root/octo-lite'), 'absolute contained worktree threaded')
  assert.ok(brief.includes('--execution-location local'), 'execution-location threaded')
  // The mutation spawn ran under the RESOLVED model and effort (from roles.toml), not hardcoded.
  const mut = agent.calls.find((c) => c.label === `implementer:${ISSUE}` && c.agentType === null)
  assert.ok(mut, 'write-capable mutation spawn ran')
  assert.equal(mut.opts.model, RESOLVED_WORKER_RUNTIME.model, 'mutation uses resolved model')
  assert.equal(mut.opts.effort, RESOLVED_WORKER_RUNTIME.effort, 'mutation uses resolved effort')
  // The resolved canonical contract text is carried into the worker prompt.
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
