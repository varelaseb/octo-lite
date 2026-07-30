// Unit tests for the canonical delivery-loop gate module (workflows/lib/gates.mjs). ADR 0003
// (drop-loop-trust-root) removed the loop-entry trust root, the independent observer, the ack-echo
// two-phase gate, the launch-revision revalidation, and the pre-push readback; the retained set is the
// admission matrix, containment, the code/QA review acceptance gates, the acceptance-package
// builder, and the OpenAI reviewer relay-provenance gate (role-runtime role-openai-relay,
// role-openai-fail-closed).
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  assertAdmission,
  assertManifestShape,
  assertContainment,
  assertRepoSlug,
  requiredPrNumber,
  acceptCodeReview,
  acceptQaReview,
  evidenceMode,
  buildAcceptancePackage,
  verifyRelayVerbatim,
  assertResumeSandboxConfig,
  assertReadOnlyFirstBootstrap,
  assertReviewWorktreeImmutable,
  acceptOpenaiReviewRelay,
  acceptShapingReviewRelay,
} from '../workflows/lib/gates.mjs'

test('assertAdmission admits the four delivery roles from a delivery state', () => {
  for (const role of ['implementer', 'code-reviewer', 'qa-capture', 'qa-reviewer']) {
    assert.deepEqual(assertAdmission({ purpose: 'delivery', role, linearState: 'Shaped' }), { purpose: 'delivery', role })
  }
})

test('assertAdmission rejects the retired observer role and non-delivery roles for delivery', () => {
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: 'tdd-observer', linearState: 'Shaped' }), /not admitted/)
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: 'reconciler', linearState: 'Shaped' }), /not admitted/)
})

test('assertAdmission enforces the Linear-state gate for delivery and shaping-review', () => {
  assert.throws(() => assertAdmission({ purpose: 'delivery', role: 'implementer', linearState: 'Awaiting Accept' }), /rejected/)
  assert.throws(() => assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer', linearState: 'Awaiting Accept' }), /rejected/)
  assert.deepEqual(
    assertAdmission({ purpose: 'shaping-review', role: 'shaping-reviewer', linearState: 'Ideas' }),
    { purpose: 'shaping-review', role: 'shaping-reviewer' },
  )
})

test('assertAdmission admits the reconciler only as a Read-restricted subagent', () => {
  assert.deepEqual(assertAdmission({ purpose: 'reconcile', role: 'reconciler', readRestricted: true }), { purpose: 'reconcile', role: 'reconciler' })
  assert.throws(() => assertAdmission({ purpose: 'reconcile', role: 'reconciler' }), /Read-restricted/)
})

test('assertAdmission rejects an unknown purpose', () => {
  assert.throws(() => assertAdmission({ purpose: 'merge', role: 'implementer' }), /purpose/)
  assert.throws(() => assertAdmission({ purpose: '', role: 'implementer' }), /purpose/)
})

test('assertManifestShape admits the persistent shape and the worker-journal shape', () => {
  assert.deepEqual(assertManifestShape({ shape: 'persistent', role: 'orchestrator' }), { shape: 'persistent', role: 'orchestrator' })
  assert.throws(() => assertManifestShape({ shape: 'persistent', role: 'orchestrator', purpose: 'delivery' }), /pass purpose rejected/)
  assert.deepEqual(
    assertManifestShape({ shape: 'worker-journal', role: 'implementer', purpose: 'delivery', linearState: 'Shaped' }),
    { shape: 'worker-journal', role: 'implementer', purpose: 'delivery' },
  )
})

// Containment is a git-LINKAGE OWNERSHIP property (role-runtime launch-containment-integrity,
// launch-containment-sandbox-safe), not path-prefix nesting: the candidate belongs to the repository iff
// its git-common-dir equals the repository's own git-common-dir. Because the gate runs inside the
// delivery-loop Workflow interpreter (no process, filesystem, or module access), it NEVER reads git
// itself: real git is the linkage authority and the read-only delivery-entry derivation agent
// host-derives BOTH absolute common-dirs and supplies them to the pure gate. assertContainment resolves
// and returns the candidate worktree path and admits iff the two supplied common-dirs are equal. A
// sibling worktree (`git worktree add ../sib`) and the repository's own top-level working tree both
// share the repository's common-dir (admitted); a path whose common-dir belongs to a DIFFERENT
// repository differs (rejected). No filesystem read, no injected reader: that linkage validation is now
// git's job on the host.
test('assertContainment admits equal common-dirs (sibling and repo-root) and rejects a differing common-dir', () => {
  const repoCommon = '/root/repo/.git'
  // Sibling worktree: candidate common-dir equals the repository's own; resolves to the sibling path.
  assert.equal(assertContainment(repoCommon, repoCommon, '/root/repo', '../sib'), '/root/sib')
  // Equal repo-root: the candidate IS the repository top-level working tree; same common-dir.
  assert.equal(assertContainment('/repo/.git', '/repo/.git', '/repo', '.'), '/repo')
  // Escape: the candidate's git-common-dir belongs to a DIFFERENT repository; differs -> rejected.
  assert.throws(() => assertContainment(repoCommon, '/root/other/.git', '/root/repo', '../other'), /escapes/)
})

test('assertRepoSlug and requiredPrNumber reject a URL and a bare name', () => {
  assert.equal(assertRepoSlug('a/b', 'slug'), 'a/b')
  assert.throws(() => assertRepoSlug('bare', 'slug'), /owner\/repo/)
  assert.equal(requiredPrNumber(6, 'pr'), '6')
  assert.equal(requiredPrNumber('6', 'pr'), '6')
  assert.throws(() => requiredPrNumber('https://x/pull/6', 'pr'), /not a URL/)
})

test('acceptCodeReview advances on clear and returns findings on blocking', () => {
  assert.deepEqual(acceptCodeReview('h', 'https://pr', { head: 'h', verdict: 'clear', comment_url: 'https://pr#c' }), { advance: true, findings: [] })
  assert.deepEqual(
    acceptCodeReview('h', 'https://pr', { head: 'h', verdict: 'blocking', findings: ['x'], comment_url: 'https://pr#c' }),
    { advance: false, findings: ['x'] },
  )
})

test('acceptQaReview advances on satisfied all-pass and returns non-pass findings otherwise', () => {
  const base = { head: 'h', issue: 'TUR-13', pr: 21, manifest: 'm' }
  const ok = acceptQaReview('h', base, { ...base, verdict: 'satisfied', packet_url: 'u', criteria: [{ criterion: 'c', status: 'pass', observation: 'o' }] })
  assert.equal(ok.advance, true)
  const bad = acceptQaReview('h', base, {
    ...base, verdict: 'blocking', packet_url: 'u',
    criteria: [{ criterion: 'c', status: 'fail', observation: 'o', artifact: 'a', fix: 'f' }],
  })
  assert.equal(bad.advance, false)
})

test('evidenceMode selects visual or nonvisual', () => {
  assert.equal(evidenceMode(true), 'visual')
  assert.equal(evidenceMode(false), 'nonvisual')
})

test('buildAcceptancePackage builds a complete package and marks self_accepted false', () => {
  const pkg = buildAcceptancePackage({
    issue: 'TUR-13', pr: 21, head: 'h',
    code_review: { verdict: 'clear', head: 'h' },
    qa_review: { verdict: 'satisfied', head: 'h' },
    evidence_card_links: ['https://site/card'],
    linear_state: 'In Progress', summary: 'collapsed the loop',
  })
  assert.equal(pkg.self_accepted, false)
  assert.equal(pkg.code_review_verdict, 'clear')
  assert.equal(pkg.qa_review_verdict, 'satisfied')
  assert.deepEqual(pkg.evidence_card_links, ['https://site/card'])
})

test('buildAcceptancePackage fails closed on a missing card link or an unsatisfied verdict', () => {
  const base = {
    issue: 'TUR-13', pr: 21, head: 'h',
    code_review: { verdict: 'clear', head: 'h' },
    qa_review: { verdict: 'satisfied', head: 'h' },
    evidence_card_links: ['https://site/card'], linear_state: 'In Progress', summary: 's',
  }
  assert.throws(() => buildAcceptancePackage({ ...base, evidence_card_links: [] }), /evidence card links/)
  assert.throws(() => buildAcceptancePackage({ ...base, qa_review: { verdict: 'blocking', head: 'h' } }), /satisfied exact-head/)
  assert.throws(() => buildAcceptancePackage({ ...base, code_review: { verdict: 'clear', head: 'other' } }), /clear exact-head/)
})

const RUNTIME = { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', service_tier: 'default' }
function relay(payload) {
  return {
    claimed_session_id: 's1', payload,
    bootstrap_argv: ['codex', 'exec', '-s', 'read-only'],
    resume_argv: ['codex', 'exec', 'resume', 's1', '-c', 'sandbox_mode="read-only"'],
    worktree_before: { head: 'h', status: '' },
    worktree_after: { head: 'h', status: '' },
  }
}
function rollout(payload) {
  return { source: 'independent-rollout-subagent', data: { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', final_message: payload } }
}

test('verifyRelayVerbatim proves effective identity from the rollout and rejects a payload edit', () => {
  const verified = verifyRelayVerbatim(RUNTIME, 's1', 'hello', { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', final_message: 'hello' })
  assert.equal(verified.final_message, 'hello')
  assert.throws(() => verifyRelayVerbatim(RUNTIME, 's1', 'edited', { provider: 'openai', model: 'gpt-5.6-sol', effort: 'high', final_message: 'hello' }), /payload mismatch/)
  assert.throws(() => verifyRelayVerbatim(RUNTIME, 's1', 'hello', { provider: 'anthropic', model: 'gpt-5.6-sol', effort: 'high', final_message: 'hello' }), /provider substitution/)
})

test('sandbox-law predicates enforce read-only bootstrap and a read-only -c sandbox_mode resume', () => {
  assert.deepEqual(assertReadOnlyFirstBootstrap(['codex', 'exec', '-s', 'read-only']), { sandbox_mode: 'read-only' })
  assert.throws(() => assertReadOnlyFirstBootstrap(['codex', 'exec', '-s', 'workspace-write']), /read-only-first/)
  // Resume admits EXACTLY one read-only -c sandbox_mode config and returns read-only.
  assert.deepEqual(
    assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="read-only"']),
    { sandbox_mode: 'read-only' },
  )
  // A workspace-write resume is rejected.
  assert.throws(() => assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="workspace-write"']), /read-only/)
  // A network-access resume config is rejected even alongside read-only.
  assert.throws(
    () => assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="read-only"', '-c', 'sandbox_workspace_write.network_access=true']),
    /network/,
  )
  // A top-level -s resume is rejected: -s is not on the benign resume allowlist.
  assert.throws(() => assertResumeSandboxConfig(['codex', 'resume', '-s', 'read-only']), /forbidden or unrecognized resume flag/)
  // The Codex 0.146.0 --yolo alias of --dangerously-bypass-approvals-and-sandbox is rejected too:
  // it is not on the benign allowlist, so no privilege alias has to be enumerated to close it.
  assert.throws(() => assertResumeSandboxConfig(['codex', 'resume', '-c', 'sandbox_mode="read-only"', '--yolo']), /forbidden or unrecognized resume flag/)
})

// launch-review-least-privilege conformance probe (role-runtime launch-review-least-privilege): the
// whole reviewer grant is read-only plus no-network. gh#60 terminal allowlist: the resume-sandbox gate
// is FORM-INDEPENDENT AND ALIAS-INDEPENDENT BY CONSTRUCTION. The ONLY flags a benign reviewer resume
// ever carries are --json (boolean), -m/--model (value), and -c/--config (value); every other flag
// token in ANY clap spelling -- -s, --sandbox, --dangerously-bypass-approvals-and-sandbox, its --yolo
// alias, or ANY unknown flag -- is simply not on the benign allowlist and is rejected without being
// enumerated, so a future privilege alias cannot fail open. Over the -c/--config entries the config
// KEY is itself allowlisted to exactly {sandbox_mode, model_reasoning_effort, service_tier}: any other
// key (future_privilege, sandbox_permissions, or any unknown sandbox-affecting key) is rejected, so a
// future relay edit reintroducing a write/network config key fails closed. Exactly one read-only
// sandbox_mode is required and every workspace-write, danger-full-access, network-access, or
// sandbox_workspace_write content is rejected in any spelling. This probe iterates the full
// reject/admit table so a reintroduced write, network, or bypass privilege cannot regress unseen.
const RESUME = ['codex', 'exec', 'resume', 's1']
const READ_ONLY_C = ['-c', 'sandbox_mode="read-only"']
test('launch-review-least-privilege admits benign read-only resume and rejects every non-allowlisted flag', () => {
  // REJECT: each privileged/unknown flag form, most carrying a legitimate read-only -c alongside it so
  // the probe proves the reintroduced privilege is caught even when a valid read-only config is present.
  const rejected = [
    // Attached long --config= smuggles a second, privileged sandbox_mode.
    [...RESUME, ...READ_ONLY_C, '--config=sandbox_mode="workspace-write"'],
    // Attached long --config= smuggles network access.
    [...RESUME, ...READ_ONLY_C, '--config=sandbox_workspace_write.network_access=true'],
    // Attached long sandbox selector (not on the benign allowlist).
    [...RESUME, ...READ_ONLY_C, '--sandbox=workspace-write'],
    // Separated long sandbox selector.
    [...RESUME, ...READ_ONLY_C, '--sandbox', 'workspace-write'],
    // Attached short -c config.
    [...RESUME, ...READ_ONLY_C, '-csandbox_mode="workspace-write"'],
    // Separated short -c config.
    [...RESUME, '-c', 'sandbox_mode="workspace-write"'],
    // Attached short sandbox selector.
    [...RESUME, ...READ_ONLY_C, '-sworkspace-write'],
    // Separated short sandbox selector.
    [...RESUME, ...READ_ONLY_C, '-s', 'workspace-write'],
    // Boolean bypass switch.
    [...RESUME, ...READ_ONLY_C, '--dangerously-bypass-approvals-and-sandbox'],
    // The Codex 0.146.0 --yolo alias of the bypass switch: closed by the allowlist, not enumerated.
    [...RESUME, ...READ_ONLY_C, '--yolo'],
    // An arbitrary unknown/future flag alongside a valid read-only config.
    [...RESUME, ...READ_ONLY_C, '--frobnicate'],
    // Repeated -c: a read-only then a workspace-write.
    [...RESUME, '-c', 'sandbox_mode="read-only"', '-c', 'sandbox_mode="workspace-write"'],
    // Whitespace TOML form around =.
    [...RESUME, '-c', 'sandbox_mode = "workspace-write"'],
    // Separated long --config network access.
    [...RESUME, ...READ_ONLY_C, '--config', 'sandbox_workspace_write.network_access=true'],
    // Danger-full-access value.
    [...RESUME, '-c', 'sandbox_mode="danger-full-access"'],
    // gh#60: -o present must NOT let a privilege flag through - workspace-write still rejected.
    [...RESUME, ...READ_ONLY_C, '-o', '/tmp/x.txt', '-c', 'sandbox_mode="workspace-write"'],
    // gh#60: -C present must NOT let a privilege flag through either.
    [...RESUME, ...READ_ONLY_C, '-C', '/root/wt', '-c', 'sandbox_mode="workspace-write"'],
    // gh#60 config-KEY allowlist: an unknown resume config key alongside a valid read-only mode.
    [...RESUME, ...READ_ONLY_C, '-c', 'future_privilege=true'],
    // A sandbox-affecting config key not on the allowlist (disk read-access permission list).
    [...RESUME, ...READ_ONLY_C, '-c', 'sandbox_permissions="[disk-full-read-access]"'],
  ]
  for (const argv of rejected) {
    assert.throws(() => assertResumeSandboxConfig(argv), /rejected/, `must reject: ${JSON.stringify(argv)}`)
  }
  // ADMIT parity: the exact canonical relay resume argv the launch relay legitimately emits MUST be
  // admitted so real reviewer runs never false-reject (--json boolean, -m model, three -c configs, the
  // session id, and a bare - stdin positional).
  const CANONICAL_RELAY_RESUME = [
    'codex', 'exec', 'resume', '--json', '-m', 'gpt-5.6-sol',
    '-c', 'model_reasoning_effort="high"', '-c', 'model_service_tier="default"',
    '-c', 'sandbox_mode="read-only"', 's1', '-',
  ]
  // ADMIT parity: every read-only spelling the installed CLI accepts (short/long, attached/separated).
  const admitted = [
    CANONICAL_RELAY_RESUME,
    // gh#60: the benign -o/--output-last-message host output file (how the relay captures the verdict);
    // no sandbox privilege, matches bootstrap. Both spellings, attached and separated.
    [...RESUME, ...READ_ONLY_C, '-o', '/tmp/cr-last-message.txt'],
    [...RESUME, ...READ_ONLY_C, '--output-last-message', '/tmp/cr-last-message.txt'],
    [...RESUME, ...READ_ONLY_C, '--output-last-message=/tmp/cr-last-message.txt'],
    // gh#60: the benign -C/--cd working-directory flag (the relay pins the review worktree via -C <path>).
    [...RESUME, ...READ_ONLY_C, '-C', '/root/wt'],
    [...RESUME, ...READ_ONLY_C, '--cd', '/root/wt'],
    [...RESUME, '-c', 'sandbox_mode="read-only"'],
    [...RESUME, '--config', 'sandbox_mode="read-only"'],
    [...RESUME, '--config=sandbox_mode="read-only"'],
    [...RESUME, '-csandbox_mode="read-only"'],
  ]
  for (const argv of admitted) {
    assert.deepEqual(assertResumeSandboxConfig(argv), { sandbox_mode: 'read-only' }, `must admit: ${JSON.stringify(argv)}`)
  }
  // The network-access and whitespace-mode forms carry their specific messages.
  assert.throws(
    () => assertResumeSandboxConfig([...RESUME, ...READ_ONLY_C, '--config', 'sandbox_workspace_write.network_access=true']),
    /network/,
  )
  assert.throws(
    () => assertResumeSandboxConfig([...RESUME, '-c', 'sandbox_mode = "workspace-write"']),
    /reviewer resume must stay sandbox_mode=read-only/,
  )
  // A non-allowlisted flag (short -s, the --yolo bypass alias, or an unknown flag) carries the clear
  // forbidden-flag message.
  assert.throws(() => assertResumeSandboxConfig([...RESUME, '-s', 'read-only']), /forbidden or unrecognized resume flag/)
  assert.throws(() => assertResumeSandboxConfig([...RESUME, ...READ_ONLY_C, '--yolo']), /forbidden or unrecognized resume flag/)
  // gh#60 config-KEY allowlist: a -c/--config key outside {sandbox_mode, model_reasoning_effort,
  // service_tier} carries the clear unrecognized-key message, closing -c future_privilege=true and any
  // other unknown sandbox-affecting config key a future relay edit might reintroduce.
  assert.throws(
    () => assertResumeSandboxConfig([...RESUME, ...READ_ONLY_C, '-c', 'future_privilege=true']),
    /unrecognized resume config key/,
  )
})

test('assertReviewWorktreeImmutable rejects a mutated review worktree', () => {
  assert.deepEqual(assertReviewWorktreeImmutable({ head: 'h', status: '' }, { head: 'h', status: '' }), { head: 'h', status: '' })
  assert.throws(() => assertReviewWorktreeImmutable({ head: 'h', status: '' }, { head: 'other', status: '' }), /HEAD changed/)
  assert.throws(() => assertReviewWorktreeImmutable({ head: 'h', status: '' }, { head: 'h', status: ' M f' }), /status changed/)
})

test('acceptOpenaiReviewRelay accepts a good reviewer relay and rejects a relay-supplied rollout', () => {
  const accepted = acceptOpenaiReviewRelay('code-reviewer', RUNTIME, relay('verdict'), rollout('verdict'))
  assert.equal(accepted.verdict_payload, 'verdict')
  const tainted = { ...relay('verdict'), rollout_source: 'relay' }
  assert.throws(() => acceptOpenaiReviewRelay('code-reviewer', RUNTIME, tainted, rollout('verdict')), /must not supply the rollout/)
  assert.throws(() => acceptOpenaiReviewRelay('implementer', RUNTIME, relay('v'), rollout('v')), /is not an OpenAI reviewer/)
})

test('acceptShapingReviewRelay admits the shaping-reviewer through the same fail-closed gate', () => {
  const accepted = acceptShapingReviewRelay('shaping-reviewer', RUNTIME, relay('verdict'), rollout('verdict'))
  assert.equal(accepted.verdict_payload, 'verdict')
  assert.throws(() => acceptShapingReviewRelay('code-reviewer', RUNTIME, relay('v'), rollout('v')), /is not a shaping-review/)
})
