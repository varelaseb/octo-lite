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
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync, realpathSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
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

const REPO_SLUG = 'varelaseb/octo-lite'
const ISSUE = 'TUR-13'
const PR = 21
const PR_URL = `https://github.com/${REPO_SLUG}/pull/21`
const BRANCH = 'octo-lite/issue13-drop-loop-trust'

// The embedded loop calls the REAL assertContainment (git-linkage OWNERSHIP predicate) on
// A.worktree_root + A.worktree at admission and at every spawn. This fixture therefore drives the
// composed runtime over a REAL repository and a REAL linked sibling worktree, so the production
// containment path stays exercised end to end (a synthetic path with no on-disk .git linkage would be
// correctly rejected as an escape by the ownership predicate). WORKTREE_ROOT is the repository (the
// containment root); WORKTREE_ABS is the real sibling worktree `git worktree add` created, whose .git
// resolves bidirectionally into the repository's worktrees set; WORKTREE_REL is the root-relative path
// to it. Populated in before(), torn down in after().
let TMP_DIR
let REPO
let WORKTREE_ROOT
let WORKTREE_REL
let WORKTREE_ABS
// The absolute git-common-dir the host derives for BOTH the worktree and the worktree_root. The linked
// sibling worktree and its repository share one common-dir (repo/.git), so the pure sandbox containment
// gate (git-common-dir equality) admits. Populated in before().
let WORKTREE_COMMON_DIR

function git(cwd, ...args) {
  execFileSync('git', args, { cwd, stdio: 'pipe' })
}

before(() => {
  TMP_DIR = realpathSync(mkdtempSync(join(tmpdir(), 'octo-loop-modes-')))
  const repo = join(TMP_DIR, 'repo')
  mkdirSync(repo)
  git(repo, 'init', '-q')
  git(repo, 'config', 'user.email', 't@t')
  git(repo, 'config', 'user.name', 't')
  writeFileSync(join(repo, 'f'), 'x')
  git(repo, 'add', 'f')
  git(repo, 'commit', '-qm', 'init')
  // Real linked sibling worktree: `git worktree add ../sib` writes bidirectional .git linkage back into
  // repo/.git/worktrees/sib, so its git-common-dir equals the repo's own and assertContainment admits it.
  git(repo, 'worktree', 'add', '-q', join(TMP_DIR, 'sib'))
  REPO = repo
  WORKTREE_ROOT = repo
  WORKTREE_ABS = join(TMP_DIR, 'sib')
  WORKTREE_REL = '../sib'
  // Real absolute git-common-dir shared by the repo and its linked sibling worktree.
  WORKTREE_COMMON_DIR = execFileSync(
    'git', ['-C', repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
    { encoding: 'utf8' },
  ).trim()
})

after(() => {
  if (TMP_DIR) rmSync(TMP_DIR, { recursive: true, force: true })
})
const HEAD = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const NEWHEAD = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
const SPEC_BLOBS = ['spec/domains/role-runtime.spec.html:loop-runs-on-cwd-and-branch']
// GH-65: contract_hash is the target AGENTS.md instruction-contract blob, a 40-hex git
// object id (git rev-parse <head>:AGENTS.md), not a role blob and not a 64-hex digest.
const CONTRACT = 'c8b0440cacc5188b2926b626ee6f506ced5368eb'

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

// A healthy OpenAI relay result: read-only bootstrap, read-only resume via -c sandbox_mode config,
// unchanged worktree, verbatim payload backed by the independently-read rollout record.
function relayResult(payload) {
  return {
    claimed_session_id: 'sess-1', payload,
    bootstrap_argv: ['codex', 'exec', '-s', 'read-only'],
    resume_argv: ['codex', 'exec', 'resume', 'sess-1', '-c', 'sandbox_mode="read-only"'],
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

// The canonical octo-lite-verdict block a real reviewer ends its final message with (the same shape
// octo_lite.runtime.verdict_body emits). GH-65 finding A1: the loop host-parses THIS verified payload to
// bind advancement, never an LLM agent claim, so the reviewer payload must carry the authoritative block.
function verdictBlock(verdict, findings = [], head = NEWHEAD, reviewType = 'code') {
  return [
    `<!-- octo-lite-verdict:${reviewType} -->`,
    '```toml',
    'schema_version = 1',
    `review_type = "${reviewType}"`,
    `verdict = "${verdict}"`,
    `head = "${head}"`,
    'bound_inputs = []',
    `findings = ${JSON.stringify(findings)}`,
    'reviewer_receipt = "reviewer-own-receipt"',
    'conversation_log_references = []',
    'conversation_cutoff = ""',
    '```',
  ].join('\n')
}

// A full reviewer final message: naming prose then the authoritative verdict block as its final content.
function verdictPayload(verdict, findings = [], head = NEWHEAD, reviewType = 'code') {
  return `Code review of PR ${PR} at head ${head}.\n` + verdictBlock(verdict, findings, head, reviewType)
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
    worktree_common_dir: WORKTREE_COMMON_DIR, worktree_root_common_dir: WORKTREE_COMMON_DIR,
    spawn_id: 'spawn-1', parent: 'orchestrator', reply_route: PR_URL,
    review_delivery: 'pr-comment', execution_location: 'local',
    starting_head: HEAD,
    ...overrides,
  }
}

// The read-only derivation reads the owning orchestrator's host-owned stream registry entry and returns
// the stream directory and caller session, so loopFire can build the installed linear-transition arg
// contract (--stream authority + --caller) from derived state, no faked or guessed value
// (delivery-lifecycle linear-loop-fire-arg-contract). ADR 0004 keeps the declared delivery entry exactly
// issue/PR/head; these are derived facts, not caller-declared ones.
const STREAM_DIR = '/streams/octo-lite-issue13'
const CALLER = 'orchestrator-session-13'
const STREAM_PARENT = 'operator'

function deliveryEntry(overrides = {}) {
  return { issue: ISSUE, pr: PR, head: HEAD, ...overrides }
}

// A DOWNSTREAM mode (code-review, fix, evidence, qa-review, acceptance) declares ONLY the three facts,
// its mode, and its own mode inputs (delivery-mode-envelope, delivery-mode-anti-forgery). It NEVER
// pre-supplies a derived envelope field: the loop derives the same envelope the implement entry binds
// BEFORE the mode dispatch. The advanced head is NEWHEAD (the mode runs past the implement entry head).
function downstreamEntry(mode, inputs = {}) {
  return { issue: ISSUE, pr: PR, head: NEWHEAD, mode, ...inputs }
}

// The derivation agent's response for a downstream pass: the same derived envelope, at the advanced
// head, with the LIVE Linear state In Progress (a downstream mode runs after the Shaped -> Todo entry
// fire). The universal checks (worktree-head agreement, one-orchestrator binding, canonical-source
// presence, containment) still run; three-way within-fire head agreement, shaping ancestor-descent,
// and the Shaped/Todo entry-state gate are implement-only.
function derivedInProgress(overrides = {}) {
  return derivedDeliveryEntry({
    linear_state: 'In Progress',
    worktree_head: NEWHEAD,
    pr_head: NEWHEAD,
    shaping_verdict_head: NEWHEAD,
    shaping_head_descends: true,
    ...overrides,
  })
}

function derivedDeliveryEntry(overrides = {}) {
  return {
    linear_issue: ISSUE,
    linear_state: 'Shaped',
    linear_fingerprint: 'fp-shaped',
    repo_slug: REPO_SLUG,
    pr_head: HEAD,
    pr_base: 'main',
    pr_issue: ISSUE,
    worktree: WORKTREE_ABS,
    worktree_root: WORKTREE_ROOT,
    worktree_head: HEAD,
    worktree_common_dir: WORKTREE_COMMON_DIR,
    worktree_root_common_dir: WORKTREE_COMMON_DIR,
    lane: WORKTREE_REL,
    lane_issue: ISSUE,
    branch: BRANCH,
    branch_issue: ISSUE,
    shaping_verdict: 'clear',
    shaping_verdict_head: HEAD,
    shaping_head_descends: true,
    shaping_reviewer_receipt: 'rcpt-1',
    spec_blobs: SPEC_BLOBS,
    adr_blobs: [],
    contract_hash: CONTRACT,
    // GH-65: the raw `git rev-parse <head>:AGENTS.md` output the loop binds contract_hash to.
    agents_md_blob: CONTRACT,
    brief: 'Implement the signed issue and spec contract.',
    stream: STREAM_DIR,
    caller: CALLER,
    parent: STREAM_PARENT,
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
  const logs = []
  const result = await factory(agent, JSON.stringify(env), (message) => logs.push(message))
  return { result, calls: agent.calls, logs }
}

// ---- implement mode: fires Shaped -> Todo, spawns implementer, returns code-review-required ----
test('implement mode derives the three-fact delivery entry, journals its output receipt, then fires', async () => {
  const entry = deliveryEntry()
  const { result, calls, logs } = await runMode(entry, [
    ['delivery-entry-derive:', derivedDeliveryEntry()],
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
  const deriveAt = labels.findIndex((l) => l.startsWith('delivery-entry-derive:'))
  const fireAt = labels.findIndex((l) => l.startsWith('loop-fire:'))
  const implAt = labels.findIndex((l) => l.startsWith('implementer:'))
  assert.ok(deriveAt >= 0 && fireAt > deriveAt && implAt > fireAt, 'derive, receipt, fire, then spawn')
  const receipt = logs.find((line) => line.startsWith('journal delivery-entry-output-receipt '))
  assert.ok(receipt, 'the fire must journal the derivation as an output receipt')
  assert.deepEqual(JSON.parse(receipt.slice(receipt.indexOf('{'))), {
    declared: entry,
    derived: derivedDeliveryEntry(),
  })
})

test('implement mode admits a declared head descended from the shaping-cleared head', async () => {
  const shapingClearedHead = '9999999999999999999999999999999999999999'
  const run = runMode(deliveryEntry(), [
    ['delivery-entry-derive:', derivedDeliveryEntry({
      shaping_verdict_head: shapingClearedHead,
      shaping_head_descends: true,
    })],
    ['loop-fire:', { command: 'octo-control linear-transition', exit_status: 0, readback_state: 'Todo' }],
    ['implementer-runtime:', RESOLVED_WORKER_RUNTIME],
    ['implementer:', {
      issue: ISSUE, pr_url: PR_URL, branch: BRANCH, head: NEWHEAD,
      red_commit: RED_COMMIT, green_commit: GREEN_COMMIT, final_commit: NEWHEAD,
      bound_test: { ...BOUND_TEST }, validation: 'node --test', blocked: false,
    }],
  ])

  await assert.doesNotReject(run, 'ancestor-descended implement entry must be admitted')
  const { result, calls } = await run
  assert.equal(result.stage, 'code-review-required')
  assert.ok(
    calls.some(({ label }) => label.startsWith('loop-fire:')),
    'ancestor-descended implement entry must reach loop fire',
  )
  assert.ok(
    calls.some(({ label }) => label.startsWith('implementer:')),
    'ancestor-descended implement entry must spawn the implementer',
  )
})

test('implement mode refuses a declared head that does not descend from the shaping-cleared head', async () => {
  const shapingClearedHead = '9999999999999999999999999999999999999999'
  const agent = makeAgent([
    ['delivery-entry-derive:', derivedDeliveryEntry({
      shaping_verdict_head: shapingClearedHead,
      shaping_head_descends: false,
    })],
  ])

  await assert.rejects(
    loadLoop()(agent, JSON.stringify(deliveryEntry()), noop),
    new RegExp(
      `delivery entry rejected: declared head ${HEAD} does not descend from ` +
      `shaping-verdict head ${shapingClearedHead}`,
    ),
  )
  assert.ok(
    !agent.calls.some(({ label }) => label.startsWith('loop-fire:')),
    'non-descended implement entry must prevent mutation',
  )
})

test('implement mode fails loud on a head inconsistency before loop fire', async () => {
  const agent = makeAgent([
    ['delivery-entry-derive:', derivedDeliveryEntry({ pr_head: NEWHEAD })],
  ])
  await assert.rejects(
    loadLoop()(agent, JSON.stringify(deliveryEntry()), noop),
    /delivery entry head inconsistency.*declared head.*PR head/,
  )
  assert.ok(!agent.calls.some(({ label }) => label.startsWith('loop-fire:')), 'head mismatch must prevent mutation')
})

test('implement mode enforces one orchestrator per issue before loop fire', async () => {
  const agent = makeAgent([
    ['delivery-entry-derive:', derivedDeliveryEntry({ pr_issue: 'TUR-99' })],
  ])
  await assert.rejects(
    loadLoop()(agent, JSON.stringify(deliveryEntry()), noop),
    /one-orchestrator-per-issue rule.*spawn a lane for TUR-13/,
  )
  assert.ok(!agent.calls.some(({ label }) => label.startsWith('loop-fire:')), 'cross-issue fire must prevent mutation')
})

test('implement mode rejects a contract_hash that is not the reviewed-head AGENTS.md blob', async () => {
  // GH-65 loop-binding-fix item 2 (role-runtime launch-stream-envelope-sources): the loop
  // binds contract_hash to the target AGENTS.md blob agents_md_blob, re-derived every fire.
  // A derivation that returns a contract_hash diverging from agents_md_blob (the classic bug:
  // a role contract blob instead of the target AGENTS.md blob) is rejected fail-closed before
  // any loop fire or worker spawn, so no worker or bound verdict ever carries the wrong hash.
  const agent = makeAgent([
    ['delivery-entry-derive:', derivedDeliveryEntry({
      contract_hash: 'a307436965a307436965a307436965a307436965',
      agents_md_blob: CONTRACT,
    })],
  ])
  await assert.rejects(
    loadLoop()(agent, JSON.stringify(deliveryEntry()), noop),
    /contract_hash.*is not the reviewed-head AGENTS\.md blob/,
  )
  assert.ok(!agent.calls.some(({ label }) => label.startsWith('loop-fire:')), 'wrong contract_hash must prevent mutation')
})

test('implement mode rejects a malformed non-40-hex AGENTS.md blob', async () => {
  // GH-65 item 2: the bound AGENTS.md blob must be a well-formed 40-hex git object id; a
  // 64-hex digest or any malformed id fails closed rather than binding a worker.
  const agent = makeAgent([
    ['delivery-entry-derive:', derivedDeliveryEntry({
      contract_hash: 'c8b0440cacc5188b2926b626ee6f506ced5368ebbda67dc6b1ed0d542cddc34c',
      agents_md_blob: 'c8b0440cacc5188b2926b626ee6f506ced5368ebbda67dc6b1ed0d542cddc34c',
    })],
  ])
  await assert.rejects(
    loadLoop()(agent, JSON.stringify(deliveryEntry()), noop),
    /AGENTS\.md blob.*is not a 40-hex object id/,
  )
})

test('implement mode rejects a delivery spawn at Shaped when the Todo readback is missing', async () => {
  const env = deliveryEntry()
  await assert.rejects(
    runMode(env, [
      ['delivery-entry-derive:', derivedDeliveryEntry()],
      ['loop-fire:', { command: 'octo-control linear-transition', exit_status: 0, readback_state: 'Shaped' }],
    ]),
    /Todo readback missing/,
  )
})

// ---- code-review mode: derives the envelope, then spawns the OpenAI code-reviewer through the relay ----
// The mode declares ONLY {issue, pr, head, mode, cycle}; the loop derives linear_state, worktree,
// contract_hash, brief, and spec_blobs from the mocked derivation agent BEFORE the reviewer spawns
// (delivery-mode-envelope). No pre-supplied envelope field.
test('code-review mode derives the envelope then spawns the code-reviewer through the relay and advances on a clear verdict', async () => {
  const env = downstreamEntry('code-review', { cycle: 1 })
  const payload = verdictPayload('clear', [])
  const { result, calls } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
    ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['code-reviewer-relay:', relayResult(payload)],
    ['code-reviewer-rollout:', rolloutFor(payload)],
    ['code-reviewer:', { head: NEWHEAD, verdict: 'clear', findings: [] }],
    ['code-reviewer-publish:', {
      card_url: `${PR_URL}#rev`, readable: true, verdict: 'clear', head: NEWHEAD, findings: [],
    }],
  ])
  assert.equal(result.stage, 'code-clear')
  // The envelope was derived before dispatch, then the reviewer ran through the relay path.
  const labels = calls.map((c) => c.label)
  const deriveAt = labels.findIndex((l) => l.startsWith('delivery-entry-derive:'))
  const relayAt = labels.findIndex((l) => l.startsWith('code-reviewer-relay:'))
  assert.ok(deriveAt >= 0 && relayAt > deriveAt, 'derive the envelope before the reviewer spawns')
  assert.ok(labels.some((l) => l.startsWith('code-reviewer-rollout:')), 'independent rollout read required')
})

test('code-review mode propagates the verified reviewer session id into the verdict-publish call', async () => {
  // GH-65 codex finding 2: the loop, which independently read+verified the reviewer rollout, holds the
  // verified session id (acceptRelayVerdict returns it). The host loop (not the reviewer subagent)
  // publishes the verdict through octo-control verdict-publish, routing that verified session id as
  // --reviewer-session-id, and surfaces it on the review result so item-3b's required arg never breaks
  // the running loop.
  const env = downstreamEntry('code-review', { cycle: 1 })
  const payload = verdictPayload('clear', [])
  let publishPrompt = ''
  const { result } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
    ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['code-reviewer-relay:', relayResult(payload)],
    ['code-reviewer-rollout:', rolloutFor(payload)],
    ['code-reviewer:', { head: NEWHEAD, verdict: 'clear', findings: [], comment_url: `${PR_URL}#binder` }],
    ['code-reviewer-publish:', ({ prompt }) => {
      publishPrompt = prompt
      return { card_url: `${PR_URL}#published`, readable: true, verdict: 'clear', head: NEWHEAD, findings: [] }
    }],
  ])
  assert.equal(result.stage, 'code-clear')
  // The relay's verified claimed session id (sess-1) must reach the verdict-publish command.
  assert.match(publishPrompt, /octo-control verdict-publish/)
  assert.match(publishPrompt, /--reviewer-session-id/)
  assert.match(publishPrompt, /sess-1/)
  // The verified session id is surfaced on the review result for the journal/downstream publication.
  assert.equal(result.review.reviewer_session_id, 'sess-1')
  // The durable verdict comment is the one verdict-publish wrote, not the reviewer subagent's post.
  assert.equal(result.review.comment_url, `${PR_URL}#published`)
})

test('code-review mode returns fix-required with findings on a blocking verdict', async () => {
  const env = downstreamEntry('code-review', { cycle: 1 })
  const payload = verdictPayload('blocking', ['bug'])
  const { result } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
    ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['code-reviewer-relay:', relayResult(payload)],
    ['code-reviewer-rollout:', rolloutFor(payload)],
    ['code-reviewer:', { head: NEWHEAD, verdict: 'blocking', findings: ['bug'] }],
    ['code-reviewer-publish:', {
      card_url: `${PR_URL}#rev`, readable: true, verdict: 'blocking', head: NEWHEAD, findings: ['bug'],
    }],
  ])
  assert.equal(result.stage, 'fix-required')
  assert.deepEqual(result.findings, ['bug'])
})

test('code-review advancement binds to the host parse of the verified payload, not any agent claim', async () => {
  // GH-65 finding A1 (definitive): the loop runs in a process-free VM, so the verdict-publish PUBLISHER
  // is itself a second LLM whose CLAIMED {verdict, head, findings} cannot be trusted for advancement.
  // Advancement must bind to a DETERMINISTIC HOST PARSE of the verified reviewer payload
  // (accepted.verdict_payload, the host-verified verbatim reviewer final message). Here the verified
  // payload asserts BLOCKING with the reviewer's real findings, while BOTH the LLM binder AND the
  // publisher agent claim CLEAR (empty findings) at the same head/PR. Binding to either agent claim would
  // enter code-clear on an unverified verdict; the loop MUST route to fix carrying the reviewer's OWN
  // verified findings parsed from the payload.
  const env = downstreamEntry('code-review', { cycle: 1 })
  const payload = verdictPayload('blocking', ['real-defect'])
  const { result } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
    ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['code-reviewer-relay:', relayResult(payload)],
    ['code-reviewer-rollout:', rolloutFor(payload)],
    // The LLM binder DISAGREES with the verified payload: it claims clear (no findings) at the head.
    ['code-reviewer:', { head: NEWHEAD, verdict: 'clear', findings: [] }],
    // The publisher agent ALSO claims CLEAR (empty findings) at the same head: it is a second unverified
    // transcription and must NOT drive advancement. It supplies only the display comment url.
    ['code-reviewer-publish:', {
      card_url: `${PR_URL}#published`, readable: true,
      verdict: 'clear', head: NEWHEAD, findings: [],
    }],
  ])
  // Advancement bound to the HOST PARSE of the verified payload: both agents said clear with NO findings,
  // yet the loop routes to fix carrying the reviewer's OWN verified findings. Binding to either agent
  // would have entered code-clear with an empty fix payload.
  assert.equal(result.stage, 'fix-required')
  assert.deepEqual(result.findings, ['real-defect'])
})

test('code-review host parse rejects a payload with an earlier example block before the final block', async () => {
  // GH-65 finding A2 (loop parser mirrors the octo-control rule): a reviewer payload carrying an earlier
  // CLEAR example block AND a final authoritative BLOCKING block must fail CLOSED, never yield clear. The
  // host parse requires exactly one octo-lite-verdict marker whose fenced block is the final content.
  const env = downstreamEntry('code-review', { cycle: 1 })
  const payload = `Code review of PR ${PR} at head ${NEWHEAD}.\n`
    + 'For reference a clear block looks like:\n'
    + verdictBlock('clear', [])
    + '\nThe authoritative verdict is:\n'
    + verdictBlock('blocking', ['real-defect'])
  await assert.rejects(
    runMode(env, [
      ['delivery-entry-derive:', derivedInProgress()],
      ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
      ['code-reviewer-relay:', relayResult(payload)],
      ['code-reviewer-rollout:', rolloutFor(payload)],
      ['code-reviewer:', { head: NEWHEAD, verdict: 'clear', findings: [] }],
      ['code-reviewer-publish:', {
        card_url: `${PR_URL}#published`, readable: true, verdict: 'clear', head: NEWHEAD, findings: [],
      }],
    ]),
    /more than one octo-lite-verdict block/,
  )
})

test('code-review host parse rejects a verified payload whose block hides a [metadata] table flipping the verdict', async () => {
  // GH-65 finding A (final closure): the exact codex reproducer. The verified reviewer
  // payload declares a top-level BLOCKING verdict with a real finding, then a TOML
  // [metadata] TABLE that flips verdict="clear"/findings=[]. Before the strict grammar
  // the JS loop parser silently SKIPPED the table header and let the inner verdict="clear"
  // OVERWRITE the top-level one, so host advancement saw CLEAR while octo-control's Python
  // tomllib kept the top-level BLOCKING -> the loop would enter code-clear over a durable
  // blocking verdict. The one strict canonical grammar REJECTS any table header, so the
  // loop fails CLOSED here: advancement NEVER sees clear (mirrors the A2 example-block
  // reject above). Both the LLM binder AND the publisher claim clear; neither can drive it.
  const env = downstreamEntry('code-review', { cycle: 1 })
  const payload = `Code review of PR ${PR} at head ${NEWHEAD}.\n` + [
    `<!-- octo-lite-verdict:code -->`,
    '```toml',
    'schema_version = 1',
    'review_type = "code"',
    'verdict = "blocking"',
    `head = "${NEWHEAD}"`,
    'bound_inputs = []',
    'findings = ["a real defect"]',
    'reviewer_receipt = "reviewer-own-receipt"',
    'conversation_log_references = []',
    'conversation_cutoff = ""',
    '[metadata]',
    'verdict = "clear"',
    'findings = []',
    '```',
  ].join('\n')
  await assert.rejects(
    runMode(env, [
      ['delivery-entry-derive:', derivedInProgress()],
      ['code-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
      ['code-reviewer-relay:', relayResult(payload)],
      ['code-reviewer-rollout:', rolloutFor(payload)],
      ['code-reviewer:', { head: NEWHEAD, verdict: 'clear', findings: [] }],
      ['code-reviewer-publish:', {
        card_url: `${PR_URL}#published`, readable: true, verdict: 'clear', head: NEWHEAD, findings: [],
      }],
    ]),
    /table/,
  )
})

// ---- fix mode: derives the envelope, spawns implementer, returns code-review-required ----
test('fix mode derives the envelope, spawns the implementer, and returns code-review-required at the next cycle', async () => {
  const env = downstreamEntry('fix', { cycle: 1, findings: ['bug'] })
  const finalHead = 'cccccccccccccccccccccccccccccccccccccccc'
  const { result, calls } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
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
  const labels = calls.map((c) => c.label)
  const deriveAt = labels.findIndex((l) => l.startsWith('delivery-entry-derive:'))
  const implAt = labels.findIndex((l) => l.startsWith('implementer:'))
  assert.ok(deriveAt >= 0 && implAt > deriveAt, 'derive the envelope before the implementer spawns')
})

// ---- evidence mode: derives the envelope, spawns qa-capture, posts the card, returns qa-review-required ----
test('evidence mode derives the envelope, spawns qa-capture, posts the evidence card, and returns qa-review-required', async () => {
  const env = downstreamEntry('evidence', { code_review: { verdict: 'clear', head: NEWHEAD } })
  const { result, calls } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
    ['qa-capture-runtime:', RESOLVED_WORKER_RUNTIME],
    ['qa-capture:', { head: NEWHEAD, plan: [{}], manifest: 'm1', artifacts: ['shot.png'], card_url: '', blocked: false }],
    ['publish-visual:', { card_url: `${PR_URL}#card`, readable: true }],
  ])
  assert.equal(result.stage, 'qa-review-required')
  assert.equal(result.card_url, `${PR_URL}#card`)
  const labels = calls.map((c) => c.label)
  const deriveAt = labels.findIndex((l) => l.startsWith('delivery-entry-derive:'))
  const captureAt = labels.findIndex((l) => l.startsWith('qa-capture:'))
  assert.ok(deriveAt >= 0 && captureAt > deriveAt, 'derive the envelope before qa-capture spawns')
  assert.ok(labels.some((l) => l.startsWith('publish-visual:')), 'evidence card posted')
})

// ---- backend evidence -> qa-review round-trip: the nonvisual branch must carry manifest forward ----
test('backend evidence mode returns the default manifest so the evidence->qa-review round-trip does not fail closed', async () => {
  // Backend-only delivery (user_facing:false), no A.manifest supplied: the branch defaults to
  // 'backend-packet'. The returned result must include that manifest so the next qa-review pass (which
  // requires A.manifest) does not fail closed on the manifest reason. Each mode derives its own envelope.
  const evidenceEnv = downstreamEntry('evidence', {
    user_facing: false, code_review: { verdict: 'clear', head: NEWHEAD },
  })
  const { result: evidenceResult } = await runMode(evidenceEnv, [
    ['delivery-entry-derive:', derivedInProgress()],
    ['publish-nonvisual:', { card_url: `${PR_URL}#backend-card`, readable: true }],
  ])
  assert.equal(evidenceResult.stage, 'qa-review-required')
  assert.equal(evidenceResult.user_facing, false)
  assert.equal(evidenceResult.manifest, 'backend-packet')

  // Feed the returned evidence result straight into qa-review: it must NOT throw the manifest error.
  const qaEnv = downstreamEntry('qa-review', {
    head: evidenceResult.head, card_url: evidenceResult.card_url, manifest: evidenceResult.manifest,
  })
  const payload = JSON.stringify({ verdict: 'satisfied' })
  const { result: qaResult } = await runMode(qaEnv, [
    ['delivery-entry-derive:', derivedInProgress()],
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

// ---- qa-review mode: derives the envelope, spawns qa-reviewer through the relay ----
test('qa-review mode derives the envelope then spawns the qa-reviewer through the relay and advances to acceptance on satisfied', async () => {
  const env = downstreamEntry('qa-review', { card_url: `${PR_URL}#card`, manifest: 'm1' })
  const payload = JSON.stringify({ verdict: 'satisfied' })
  const { result, calls } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
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
  const deriveAt = labels.findIndex((l) => l.startsWith('delivery-entry-derive:'))
  const relayAt = labels.findIndex((l) => l.startsWith('qa-reviewer-relay:'))
  assert.ok(deriveAt >= 0 && relayAt > deriveAt, 'derive the envelope before the qa-reviewer spawns')
})

// ---- acceptance mode: derives the envelope, then BUILDS + POSTS + SENDS the package, NEVER self-accepts ----
test('acceptance mode derives the envelope then builds, posts, and sends the acceptance package and never self-accepts', async () => {
  const env = downstreamEntry('acceptance', {
    code_review: { verdict: 'clear', head: NEWHEAD },
    qa_review: { verdict: 'satisfied', head: NEWHEAD },
    card_url: `${PR_URL}#card`, summary: 'collapsed the loop to six modes',
  })
  const { result, calls } = await runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
    ['acceptance-publish:', { card_url: `${PR_URL}#pkg`, readable: true }],
    ['acceptance-send:', { sent: true, route: 'operator-pane' }],
  ])
  assert.equal(result.stage, 'awaiting-operator-acceptance')
  assert.equal(result.package.self_accepted, false)
  assert.equal(result.package_url, `${PR_URL}#pkg`)
  const labels = calls.map((c) => c.label)
  // The envelope is derived first, then the package is posted to the evidence site and then sent.
  const deriveAt = labels.findIndex((l) => l.startsWith('delivery-entry-derive:'))
  const pubAt = labels.findIndex((l) => l.startsWith('acceptance-publish:'))
  const sendAt = labels.findIndex((l) => l.startsWith('acceptance-send:'))
  assert.ok(deriveAt >= 0 && pubAt > deriveAt && sendAt > pubAt, 'derive, then post, then send')
  // No mode ever runs an acceptance/merge/transition itself; the returned next says the operator decides.
  assert.match(result.next, /operator/i)
})

test('acceptance mode fails closed without a satisfied exact-head qa-review verdict', async () => {
  const env = downstreamEntry('acceptance', {
    code_review: { verdict: 'clear', head: NEWHEAD },
    qa_review: { verdict: 'satisfied', head: 'wrong-head' },
    card_url: `${PR_URL}#card`, summary: 'x',
  })
  await assert.rejects(runMode(env, [
    ['delivery-entry-derive:', derivedInProgress()],
  ]), /satisfied exact-head qa-review/)
})

// ---- reconcile mode: a NON-delivery mode (delivery-mode-envelope-scope). Its caller LEGITIMATELY
// pre-supplies the derived context envelope (worktree, common-dirs, repo, repo_slug, issue) that
// spawnReconciler consumes directly. The delivery-entry derivation and its anti-forgery derived-field
// guard are DELIVERY-mode-only and must NOT run here; otherwise the guard rejects the normal reconcile
// envelope ("caller may not supply the derived field ..."). ----
function reconcileEnvelope(overrides = {}) {
  return {
    mode: 'reconcile',
    issue: ISSUE, pr: PR, head: HEAD,
    repo: REPO, repo_slug: REPO_SLUG,
    worktree_root: WORKTREE_ROOT, worktree: WORKTREE_REL,
    worktree_common_dir: WORKTREE_COMMON_DIR, worktree_root_common_dir: WORKTREE_COMMON_DIR,
    starting_head: HEAD,
    ...overrides,
  }
}

test('reconcile mode classifies with its caller-supplied context and never runs the delivery-entry derive', async () => {
  const { result, calls } = await runMode(reconcileEnvelope(), [
    ['reconciler-runtime:', RESOLVED_RECONCILER_RUNTIME],
    ['reconciler:', { classification: 'unchanged', needs_fable: false, deltas: [] }],
  ])
  assert.equal(result.stage, 'reconcile-classified')
  assert.equal(result.classification, 'unchanged')
  assert.equal(result.needs_fable, false)
  const labels = calls.map((c) => c.label)
  // The delivery-entry derivation is DELIVERY-mode-only: a non-delivery reconcile pass never runs it,
  // so its anti-forgery guard never rejects the caller-supplied context envelope.
  assert.ok(!labels.some((l) => l.startsWith('delivery-entry-derive:')), 'reconcile must not run the delivery-entry derive')
  assert.ok(labels.some((l) => l.startsWith('reconciler:')), 'the reconciler spawned from the caller-supplied context')
})

// ---- shaping-review mode: a NON-delivery mode (delivery-mode-envelope-scope). Its caller LEGITIMATELY
// pre-supplies the derived context envelope the relay spawn path (journalledBoundInputs + resolveRuntime)
// requires: worktree/common-dirs/repo/repo_slug/issue/pr/linear_state/brief/contract_hash/spec_blobs/head.
// The delivery-entry derivation and its anti-forgery guard must NOT run here. ----
function shapingReviewEnvelope(overrides = {}) {
  return {
    mode: 'shaping-review',
    issue: ISSUE, pr: PR, head: HEAD, shaping_head: HEAD,
    repo: REPO, repo_slug: REPO_SLUG,
    worktree_root: WORKTREE_ROOT, worktree: WORKTREE_REL,
    worktree_common_dir: WORKTREE_COMMON_DIR, worktree_root_common_dir: WORKTREE_COMMON_DIR,
    linear_state: 'Shaped', brief: 'shape-review the signed issue',
    spec_blobs: SPEC_BLOBS, contract_hash: CONTRACT,
    ...overrides,
  }
}

test('shaping-review mode reviews through the relay with its caller-supplied context and never runs the delivery-entry derive', async () => {
  const payload = JSON.stringify({ verdict: 'clear', findings: [], comment_url: `${PR_URL}#shaping` })
  const { result, calls } = await runMode(shapingReviewEnvelope(), [
    ['shaping-reviewer-runtime:', RESOLVED_REVIEWER_RUNTIME],
    ['shaping-reviewer-relay:', relayResult(payload)],
    ['shaping-reviewer-rollout:', rolloutFor(payload)],
    ['shaping-reviewer:', { head: HEAD, verdict: 'clear', findings: [], comment_url: `${PR_URL}#shaping` }],
  ])
  assert.equal(result.stage, 'shaping-review-verdict')
  assert.equal(result.head, HEAD)
  const labels = calls.map((c) => c.label)
  assert.ok(!labels.some((l) => l.startsWith('delivery-entry-derive:')), 'shaping-review must not run the delivery-entry derive')
  // The shaping-reviewer runs through the retained relay path with independent rollout provenance.
  const relayAt = labels.findIndex((l) => l.startsWith('shaping-reviewer-relay:'))
  const rolloutAt = labels.findIndex((l) => l.startsWith('shaping-reviewer-rollout:'))
  assert.ok(relayAt >= 0 && rolloutAt > relayAt, 'shaping-review runs the relay then the independent rollout read')
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
