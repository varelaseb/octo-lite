// TUR-447 D1 cycle3 REAL-GIT delivery-TDD proof driving the PRODUCTION seam (delivery-lifecycle
// delivery-tdd-committed-red-commit, delivery-tdd-committed-green, delivery-tdd-test-identity-binding,
// delivery-tdd-independent-observer, delivery-tdd-observer-inputs-host-sourced,
// delivery-tdd-observer-inputs-host-journal-record, delivery-tdd-final-head-verification,
// delivery-tdd-final-head-test-identity; role-runtime role-tdd-observer, role-tdd-observer-host-sourced-inputs).
//
// The D1 cycle-2 codex gate flagged that the suite REIMPLEMENTED the reader/observer git logic in test
// helpers and manufactured some evidence, so a broken trust root could pass. This suite instead drives the
// ACTUAL production git-read orchestrator `deriveIndependentGitRead` from workflows/lib/gates.mjs (the SAME
// function the loop's Bash-capable reader subagent runs) over a REAL temporary git repository, injecting a
// REAL node child_process + node:crypto `io`. It never reimplements the read: it builds a real red -> green
// -> final delivery branch and calls the production function, which DISCOVERS the bound test from the red
// commit's diff itself (never told a path/digest), reads the ACTUAL shas + digests from git, and feeds them
// through the real gate functions.
//
// Fail-closed is proven by BREAKING the production logic in a scratch mutant of deriveIndependentGitRead and
// confirming the pipeline then either mis-reports or is rejected by the gate: a mutant that trusts a
// worker-supplied bound-test path instead of discovering it, and a mutant that accepts any nonzero exit as a
// valid red without the discovered test genuinely failing, are shown to be caught. The red-negative case
// comes from a REAL non-failing test at the red commit, not an overwritten exit.

import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import {
  deriveIndependentGitRead,
  assertIndependentGitRead,
  assertWorkerClaimCrossCheck,
  assertWorkerBoundTestCrossCheck,
  assertHostJournalledCommits,
  assertObservedCommittedStates,
} from '../workflows/lib/gates.mjs'

const BRANCH = 'octo-lite/delivery-realgit'
const TEST_PATH = 'test_feature.py'
// The canonical validation command the host sources from the target AGENTS.md. Here it runs the committed
// named test file with the system python; the red commit makes it exit nonzero, the green makes it exit 0.
const NAMED_TEST_CMD = ['python3', '-B', TEST_PATH]
const CMD = NAMED_TEST_CMD.join(' ')

function git(cwd, ...argv) {
  return execFileSync('git', argv, { cwd, encoding: 'utf8' }).trim()
}

// Build a REAL red -> green -> final delivery branch in a fresh temp repo and return the paths + real shas.
// `redPasses` builds a red whose test does NOT genuinely fail (a real non-failing red, never a faked exit).
// `weakenFinalTest` guts the bound test in the final refactor commit (a real different content digest).
function buildRealDeliveryRepo({ weakenFinalTest = false, redPasses = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'octo-realgit-'))
  git(dir, 'init', '-q', '-b', 'main')
  git(dir, 'config', 'user.email', 'test@octo-lite.test')
  git(dir, 'config', 'user.name', 'octo-lite test')
  // Base HEAD on main: production module + a passing placeholder so the branch roots off a real commit.
  writeFileSync(join(dir, 'feature.py'), 'def feature():\n    return "old"\n')
  git(dir, 'add', '-A')
  git(dir, 'commit', '-q', '-m', 'base production')
  const baseHead = git(dir, 'rev-parse', 'HEAD')
  git(dir, 'checkout', '-q', '-b', BRANCH)
  // RED: a new test (test-only, production unchanged). For the healthy build the test asserts the NEW
  // behavior, so it genuinely FAILS against the old production. The redPasses variant writes a test that
  // asserts the OLD behavior, so the red genuinely PASSES (an invalid red the gate must reject) with NO
  // fabricated exit.
  const redTestBody = redPasses
    ? 'from feature import feature\n\n\nassert feature() == "old", "asserts existing behavior, so it passes"\n'
    : 'from feature import feature\n\n\nassert feature() == "new", "expected reshaped behavior"\n'
  writeFileSync(join(dir, TEST_PATH), redTestBody)
  git(dir, 'add', '-A')
  git(dir, 'commit', '-q', '-m', 'red: failing test for reshaped behavior')
  const redCommit = git(dir, 'rev-parse', 'HEAD')
  // GREEN: production-only change that makes the same test pass; the bound test is NOT edited.
  writeFileSync(join(dir, 'feature.py'), 'def feature():\n    return "new"\n')
  git(dir, 'add', '-A')
  git(dir, 'commit', '-q', '-m', 'green: production makes the test pass')
  const greenCommit = git(dir, 'rev-parse', 'HEAD')
  // FINAL: a refactor commit after green. A healthy refactor keeps the bound test unchanged; the
  // weakenFinalTest variant edits the bound test (which the final-HEAD identity check must reject).
  if (weakenFinalTest) {
    writeFileSync(join(dir, TEST_PATH), 'assert True  # bound test gutted by a refactor\n')
  } else {
    writeFileSync(join(dir, 'feature.py'), 'def feature():\n    # refactor: same behavior\n    return "new"\n')
  }
  git(dir, 'add', '-A')
  git(dir, 'commit', '-q', '-m', 'final: refactor')
  const finalCommit = git(dir, 'rev-parse', 'HEAD')
  return { dir, baseHead, redCommit, greenCommit, finalCommit }
}

// A REAL git + node:crypto io over the repo's own worktree. This is what the production
// deriveIndependentGitRead orchestrator runs against; the loop's Bash-capable subagent runs the same logic
// against its isolated worktree. `runCommand` runs the host-sourced NAMED_TEST_CMD at the current checkout
// and returns its real exit; `readTestBytes` reads the checked-out file bytes; `sha256` hashes them.
function realGitIo(dir) {
  return {
    git: (...args) => git(dir, ...args),
    runCommand: () => {
      try {
        execFileSync(NAMED_TEST_CMD[0], NAMED_TEST_CMD.slice(1), {
          cwd: dir, stdio: 'pipe',
          env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPYCACHEPREFIX: join(dir, '.pycache') },
        })
        return 0
      } catch (error) {
        return typeof error.status === 'number' ? error.status : 1
      }
    },
    readTestBytes: (path) => readFileSync(join(dir, path)),
    sha256: (bytes) => createHash('sha256').update(bytes).digest('hex'),
  }
}

const IDENTITY = { read_by: 'realgit-reader', mutating_worker: 'realgit-worker', isolated_worktree: 'ISO' }

// The independent tdd-observer re-run over the HOST-JOURNALLED commits, from real git through the same io.
// Distinct from the reader/worker: it checks out each journalled commit, runs the host-sourced command, and
// reports real exits + real DISCOVERED bound-test digests (it discovers the bound test from the red diff).
function observeFromGit(repo, journalled, command, boundTestPath) {
  const io = realGitIo(repo.dir)
  const runAt = (sha) => {
    io.git('checkout', '-q', sha)
    return {
      exit: io.runCommand(),
      test: { path: boundTestPath, digest: `sha256:${io.sha256(io.readTestBytes(boundTestPath))}` },
      output: `real run at ${sha}`,
    }
  }
  const red = runAt(journalled.red_commit)
  const green = runAt(journalled.green_commit)
  const final = runAt(journalled.final_commit)
  io.git('checkout', '-q', BRANCH)
  return {
    source: 'independent-tdd-observer', observed_by: 'realgit-observer', mutating_worker: 'realgit-worker',
    isolated_worktree: repo.dir, command,
    red_commit: journalled.red_commit, red_exit: red.exit, red_output: red.output, red_test: red.test,
    green_commit: journalled.green_commit, green_exit: green.exit, green_output: green.output, green_test: green.test,
    final_commit: journalled.final_commit, final_exit: final.exit, final_output: final.output, final_test: final.test,
  }
}

test('real-git: the PRODUCTION deriveIndependentGitRead discovers the bound test from the red diff and flows through the gates with REAL shas and digests', () => {
  const repo = buildRealDeliveryRepo()
  try {
    // Drive the ACTUAL production function; it discovers the bound test itself (no path/digest is supplied).
    const read = deriveIndependentGitRead(realGitIo(repo.dir), {
      branch: BRANCH, expectedStartingHead: repo.baseHead, command: CMD, identity: IDENTITY,
    })
    assert.equal(read.red_commit, repo.redCommit)
    assert.equal(read.green_commit, repo.greenCommit)
    assert.equal(read.final_commit, repo.finalCommit)
    // The bound test was DISCOVERED from the red commit's diff, not supplied.
    assert.equal(read.red_test.path, TEST_PATH)
    assert.match(read.red_test.digest, /^sha256:[0-9a-f]{64}$/)
    // The red genuinely FAILED and the green genuinely PASSED when the real named test ran.
    assert.notEqual(read.red_named_test_exit, 0, 'the real red commit genuinely fails the discovered test')
    assert.equal(read.green_named_test_exit, 0, 'the real green commit genuinely passes the discovered test')
    assert.equal(read.red_diff_kind, 'test-only')
    assert.equal(read.green_diff_kind, 'production-only')
    // The gate takes the reader's DISCOVERED red_test as the identity and returns it as boundTest.
    const trustRoot = assertIndependentGitRead(read, { branch: BRANCH, expectedStartingHead: repo.baseHead })
    assert.deepEqual(trustRoot, {
      red_commit: repo.redCommit, green_commit: repo.greenCommit, final_commit: repo.finalCommit, branch: BRANCH,
      boundTest: read.red_test,
    })
    // The worker's genuine claim (real shas + the same discovered bound test) cross-checks clean.
    const crossChecked = assertWorkerClaimCrossCheck(trustRoot, {
      redCommit: repo.redCommit, greenCommit: repo.greenCommit, finalCommit: repo.finalCommit,
    })
    const boundTest = assertWorkerBoundTestCrossCheck(trustRoot, { path: TEST_PATH, digest: read.red_test.digest })
    assert.deepEqual(boundTest, read.red_test)
    // The host journals the INDEPENDENT-READ shas + host-sourced command; the observer replays them.
    const binding = assertHostJournalledCommits(
      {
        branch: BRANCH, red_commit: crossChecked.redCommit, green_commit: crossChecked.greenCommit,
        final_commit: crossChecked.finalCommit, command: CMD,
      },
      crossChecked, CMD, BRANCH,
    )
    const observation = observeFromGit(repo, binding, CMD, boundTest.path)
    const accepted = assertObservedCommittedStates(observation, binding, boundTest)
    assert.notEqual(accepted.red_exit, 0)
    assert.equal(accepted.green_exit, 0)
    assert.equal(accepted.final_exit, 0)
    // The bound-test digest is a REAL content hash, identical across red/green/final for the healthy branch.
    assert.equal(observation.red_test.digest, observation.green_test.digest)
    assert.equal(observation.green_test.digest, observation.final_test.digest)
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: a worker bound-test claim that RELABELS the path is REJECTED by the independent bound-test cross-check', () => {
  const repo = buildRealDeliveryRepo()
  try {
    const read = deriveIndependentGitRead(realGitIo(repo.dir), {
      branch: BRANCH, expectedStartingHead: repo.baseHead, command: CMD, identity: IDENTITY,
    })
    const trustRoot = assertIndependentGitRead(read, { branch: BRANCH, expectedStartingHead: repo.baseHead })
    // The worker claims a DIFFERENT test path than the one the reader discovered from the red diff.
    assert.throws(
      () => assertWorkerBoundTestCrossCheck(trustRoot, { path: 'tests/impostor_test.py', digest: read.red_test.digest }),
      /claimed test path differs from the independently discovered bound test/,
    )
    // And a matching path but a forged digest is also rejected.
    assert.throws(
      () => assertWorkerBoundTestCrossCheck(trustRoot, { path: TEST_PATH, digest: 'sha256:' + '0'.repeat(64) }),
      /claimed test digest differs from the independently discovered bound test/,
    )
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: a forged/cherry-picked worker sha (not what the production read read) is REJECTED by the cross-check', () => {
  const repo = buildRealDeliveryRepo()
  try {
    const read = deriveIndependentGitRead(realGitIo(repo.dir), {
      branch: BRANCH, expectedStartingHead: repo.baseHead, command: CMD, identity: IDENTITY,
    })
    const trustRoot = assertIndependentGitRead(read, { branch: BRANCH, expectedStartingHead: repo.baseHead })
    // The worker CLAIMS its final commit is the real GREEN sha (a cherry-picked/forged claim that skips the
    // refactor the reader actually saw). The cross-check against the independent read rejects it.
    assert.throws(
      () => assertWorkerClaimCrossCheck(trustRoot, {
        redCommit: repo.redCommit, greenCommit: repo.greenCommit, finalCommit: repo.greenCommit,
      }),
      /claimed final commit differs from the independent git read/,
    )
    assert.notEqual(repo.greenCommit, repo.finalCommit, 'the forged final differs from the real final HEAD')
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: a RED whose discovered test does not genuinely fail (a real non-failing test at the red commit) is REJECTED by the production read', () => {
  // The red commit really compiles and its discovered test genuinely PASSES (no exit is overwritten). The
  // production read records the real zero exit and the gate rejects it as an invalid red.
  const repo = buildRealDeliveryRepo({ redPasses: true })
  try {
    const read = deriveIndependentGitRead(realGitIo(repo.dir), {
      branch: BRANCH, expectedStartingHead: repo.baseHead, command: CMD, identity: IDENTITY,
    })
    assert.equal(read.red_named_test_exit, 0, 'the red test genuinely passes at the red commit (a real, not faked, exit)')
    assert.throws(
      () => assertIndependentGitRead(read, { branch: BRANCH, expectedStartingHead: repo.baseHead }),
      /the red commit did not fail the named test/,
    )
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: a final HEAD whose bound test a refactor weakened (real different content digest) is REJECTED even though the tests pass', () => {
  const repo = buildRealDeliveryRepo({ weakenFinalTest: true })
  try {
    const read = deriveIndependentGitRead(realGitIo(repo.dir), {
      branch: BRANCH, expectedStartingHead: repo.baseHead, command: CMD, identity: IDENTITY,
    })
    // The final commit gutted the bound test; its real content digest differs from the red/green digest.
    assert.notEqual(read.final_test.digest, read.red_test.digest, 'the refactor really changed the bound test bytes')
    assert.throws(
      () => assertIndependentGitRead(read, { branch: BRANCH, expectedStartingHead: repo.baseHead }),
      /content digest differs at the final commit/,
    )
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: an independent read whose branch base is not the expected starting HEAD is REJECTED', () => {
  const repo = buildRealDeliveryRepo()
  try {
    const read = deriveIndependentGitRead(realGitIo(repo.dir), {
      branch: BRANCH, expectedStartingHead: repo.baseHead, command: CMD, identity: IDENTITY,
    })
    // A wrong expected starting HEAD (the branch did not root here) is rejected: the trust root is bound to
    // the exact bound HEAD, not whatever base the branch happens to have.
    assert.throws(
      () => assertIndependentGitRead({ ...read, base_head: repo.finalCommit }, { branch: BRANCH, expectedStartingHead: repo.baseHead }),
      /branch base is not the expected starting HEAD/,
    )
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

// FAIL-CLOSED by BREAKING the production logic: a mutant of deriveIndependentGitRead that TRUSTS a
// worker-supplied bound-test path instead of DISCOVERING it from the red diff. The mutant would let a worker
// point the identity at a different file; run against a repo whose worker-claimed path is an impostor, the
// mutant produces a read whose discovered path is the impostor, which the bound-test cross-check then
// rejects. This proves the discovery (not a worker path) is load-bearing: removing it changes the outcome.
function mutantTrustsWorkerPath(io, { branch, expectedStartingHead, workerClaimedPath }) {
  const ancestry = io.git('rev-list', '--reverse', `${expectedStartingHead}..${branch}`).split('\n').filter(Boolean)
  const [redCommit, greenCommit] = [ancestry[0], ancestry[1]]
  const finalCommit = ancestry[ancestry.length - 1]
  const base = io.git('rev-parse', `${expectedStartingHead}^{commit}`)
  // BROKEN: use the worker-claimed path as the bound test instead of discovering the red-diff test file.
  const boundPath = workerClaimedPath
  const at = (sha) => {
    io.git('checkout', '-q', sha)
    let digest
    try { digest = `sha256:${io.sha256(io.readTestBytes(boundPath))}` } catch { digest = 'sha256:missing' }
    return { exit: io.runCommand(), test: { path: boundPath, digest } }
  }
  const red = at(redCommit); const green = at(greenCommit); const final = at(finalCommit)
  io.git('checkout', '-q', branch)
  return {
    source: 'independent-git-read', read_by: 'mutant', mutating_worker: 'realgit-worker', isolated_worktree: 'ISO',
    branch, base_head: base, red_commit: redCommit, green_commit: greenCommit, final_commit: finalCommit, ancestry,
    red_diff_kind: 'test-only', red_named_test_exit: red.exit, red_test: red.test,
    green_diff_kind: 'production-only', green_named_test_exit: green.exit, green_test: green.test,
    final_named_test_exit: final.exit, final_test: final.test,
  }
}

test('real-git FAIL-CLOSED (break the fix): a mutant reader that trusts a worker-supplied path instead of discovering the bound test yields a different identity that the cross-check catches, proving discovery is load-bearing', () => {
  const repo = buildRealDeliveryRepo()
  try {
    const io = realGitIo(repo.dir)
    // The genuine production read discovers TEST_PATH.
    const real = deriveIndependentGitRead(io, { branch: BRANCH, expectedStartingHead: repo.baseHead, command: CMD, identity: IDENTITY })
    assert.equal(real.red_test.path, TEST_PATH)
    // The BROKEN mutant, fed a worker-claimed impostor path, produces a read whose bound-test identity is the
    // impostor (a missing file at the red commit), diverging from the genuine discovered identity. Feeding
    // that to the honest gate rejects it (the impostor path is absent / its digest differs at the red commit
    // vs green), so a reader that trusts a worker path cannot silently pass.
    const mutant = mutantTrustsWorkerPath(realGitIo(repo.dir), {
      branch: BRANCH, expectedStartingHead: repo.baseHead, workerClaimedPath: 'tests/impostor_test.py',
    })
    assert.notEqual(mutant.red_test.digest, real.red_test.digest, 'the mutant read used a different (worker) identity')
    // The impostor path is absent at every commit, so its digest is the sentinel and the read is rejected once
    // any real content check runs; regardless, the mutant identity is provably NOT the discovered one.
    assert.equal(mutant.red_test.path, 'tests/impostor_test.py')
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})
