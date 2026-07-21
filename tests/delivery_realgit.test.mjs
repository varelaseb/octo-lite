// TUR-447 D1 cycle2 REAL-GIT delivery-TDD proof (delivery-lifecycle delivery-tdd-committed-red-commit,
// delivery-tdd-committed-green, delivery-tdd-test-identity-binding, delivery-tdd-independent-observer,
// delivery-tdd-observer-inputs-host-sourced, delivery-tdd-observer-inputs-host-journal-record,
// delivery-tdd-final-head-verification, delivery-tdd-final-head-test-identity; role-runtime
// role-tdd-observer-host-sourced-inputs).
//
// The D1 codex-rigor gate flagged that the named delivery-TDD proofs manufactured observer/read evidence
// as scripted JSON with non-git commit ids and fake digests, so a broken trust root could pass. This suite
// instead drives REAL git: it creates an actual temporary git repository with a real red commit (a new
// failing test plus unchanged production), a real green commit (production-only, the same named test now
// passes), and a real final refactor commit, then performs the SAME independent git reads and observer
// re-runs the loop delegates to its Read-restricted subagents (rev-list ancestry, per-commit diff kind,
// per-commit named-test exit, and the bound-test file content digest), and feeds the ACTUAL shas and
// digests through the real gate functions. There are no scripted/fake commit ids or digests anywhere: the
// commit ids and digests come from git and node:crypto over real files.
//
// Fail-closed: the suite proves that if a worker points the observer at a forged/cherry-picked sha, the
// cross-check against the independent read rejects it; that a red that does not genuinely fail is rejected;
// and that a final HEAD whose bound test a refactor weakened is rejected. Removing the cross-check or the
// independent read would let a forged sha through, so these assertions fail closed on a broken fix.

import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import {
  assertIndependentGitRead,
  assertWorkerClaimCrossCheck,
  assertHostJournalledCommits,
  assertObservedCommittedStates,
} from '../workflows/lib/gates.mjs'

const BRANCH = 'octo-lite/delivery-realgit'
const TEST_PATH = 'test_feature.py'
// The canonical validation command the host sources from the target AGENTS.md. Here it runs the committed
// named test file with the system python; the red commit makes it exit nonzero, the green makes it exit 0.
const NAMED_TEST_CMD = ['python3', '-B', TEST_PATH]

function git(cwd, ...argv) {
  return execFileSync('git', argv, { cwd, encoding: 'utf8' }).trim()
}

// Run the committed named test at the current worktree state; return its real exit status. A genuine red
// commit yields a nonzero exit, a genuine green/final a zero exit. No status is fabricated.
function runNamedTest(cwd) {
  try {
    execFileSync(NAMED_TEST_CMD[0], NAMED_TEST_CMD.slice(1), {
      cwd, stdio: 'pipe', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPYCACHEPREFIX: join(cwd, '.pycache') },
    })
    return 0
  } catch (error) {
    return typeof error.status === 'number' ? error.status : 1
  }
}

// The bound-test file identity: path plus a REAL content digest over the checked-out file bytes.
function boundTestAt(cwd) {
  const bytes = readFileSync(join(cwd, TEST_PATH))
  return { path: TEST_PATH, digest: `sha256:${createHash('sha256').update(bytes).digest('hex')}` }
}

// Diff kind of a commit relative to its parent: 'test-only' if only the bound test path changed,
// 'production-only' if the bound test path did not change, else 'mixed'. Read from real git diff.
function diffKind(cwd, sha) {
  const files = git(cwd, 'diff', '--name-only', `${sha}~1`, sha).split('\n').filter(Boolean)
  const touchesTest = files.includes(TEST_PATH)
  const touchesProd = files.some((f) => f !== TEST_PATH)
  if (touchesTest && !touchesProd) return 'test-only'
  if (touchesProd && !touchesTest) return 'production-only'
  return 'mixed'
}

// Build a real red -> green -> final delivery branch in a fresh temp repo and return the paths + real shas.
function buildRealDeliveryRepo({ weakenFinalTest = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'octo-realgit-'))
  git(dir, 'init', '-q', '-b', 'main')
  git(dir, 'config', 'user.email', 'test@octo-lite.test')
  git(dir, 'config', 'user.name', 'octo-lite test')
  // Base HEAD on main: production module + a passing placeholder so the branch roots off a real commit.
  writeFileSync(join(dir, 'feature.py'), 'def feature():\n    return "old"\n')
  git(dir, 'add', '-A')
  git(dir, 'commit', '-q', '-m', 'base production')
  const baseHead = git(dir, 'rev-parse', 'HEAD')
  // Isolated delivery branch off the base HEAD.
  git(dir, 'checkout', '-q', '-b', BRANCH)
  // RED: a new failing test (test-only, production unchanged). The test asserts the NEW behavior, so it
  // genuinely FAILS against the old production.
  const redTestBody = 'from feature import feature\n\n\nassert feature() == "new", "expected reshaped behavior"\n'
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

// The INDEPENDENT git read, performed by real git reads over the branch, given ONLY the branch + expected
// starting HEAD (never a worker sha). This mirrors what the host-controlled Read-restricted git reader does.
function independentReadFromGit(repo, expectedStartingHead) {
  const { dir } = repo
  // Establish the branch base and the ordered red->final ancestry from real git, not from any worker claim.
  const base = git(dir, 'merge-base', 'main', BRANCH)
  const ancestry = git(dir, 'rev-list', '--reverse', `${base}..${BRANCH}`).split('\n').filter(Boolean)
  const [redCommit, greenCommit, finalCommit] = [ancestry[0], ancestry[1], ancestry[ancestry.length - 1]]
  const readAt = (sha) => {
    git(dir, 'checkout', '-q', sha)
    const exit = runNamedTest(dir)
    const test = boundTestAt(dir)
    const kind = diffKind(dir, sha)
    return { exit, test, kind }
  }
  const red = readAt(redCommit)
  const green = readAt(greenCommit)
  const final = readAt(finalCommit)
  git(dir, 'checkout', '-q', BRANCH)
  return {
    source: 'independent-git-read', read_by: 'realgit-reader', mutating_worker: 'realgit-worker',
    isolated_worktree: dir, branch: BRANCH, base_head: base,
    red_commit: redCommit, green_commit: greenCommit, final_commit: finalCommit, ancestry,
    red_diff_kind: red.kind, red_named_test_exit: red.exit, red_test: red.test,
    green_diff_kind: green.kind, green_named_test_exit: green.exit, green_test: green.test,
    final_named_test_exit: final.exit, final_test: final.test,
  }
}

// The independent tdd-observer re-run over the HOST-JOURNALLED commits, again from real git. Distinct from
// the reader/worker: it checks out each journalled commit, runs the host-sourced command, and reports real
// exits + real bound-test digests.
function observeFromGit(repo, journalled, command) {
  const { dir } = repo
  const runAt = (sha) => {
    git(dir, 'checkout', '-q', sha)
    return { exit: runNamedTest(dir), test: boundTestAt(dir), output: `real run at ${sha}` }
  }
  const red = runAt(journalled.red_commit)
  const green = runAt(journalled.green_commit)
  const final = runAt(journalled.final_commit)
  git(dir, 'checkout', '-q', BRANCH)
  return {
    source: 'independent-tdd-observer', observed_by: 'realgit-observer', mutating_worker: 'realgit-worker',
    isolated_worktree: dir, command,
    red_commit: journalled.red_commit, red_exit: red.exit, red_output: red.output, red_test: red.test,
    green_commit: journalled.green_commit, green_exit: green.exit, green_output: green.output, green_test: green.test,
    final_commit: journalled.final_commit, final_exit: final.exit, final_output: final.output, final_test: final.test,
  }
}

const CMD = NAMED_TEST_CMD.join(' ')

test('real-git: a genuine committed red->green->final delivery branch flows through the independent read, cross-check, host journal, and observer replay with REAL shas and digests', () => {
  const repo = buildRealDeliveryRepo()
  try {
    // The independent read is over real git; assert the shas it reads are the ACTUAL commit shas.
    const read = independentReadFromGit(repo, repo.baseHead)
    assert.equal(read.red_commit, repo.redCommit)
    assert.equal(read.green_commit, repo.greenCommit)
    assert.equal(read.final_commit, repo.finalCommit)
    // The red genuinely FAILED and the green genuinely PASSED when the real named test ran.
    assert.notEqual(read.red_named_test_exit, 0, 'the real red commit genuinely fails the named test')
    assert.equal(read.green_named_test_exit, 0, 'the real green commit genuinely passes the named test')
    assert.equal(read.red_diff_kind, 'test-only')
    assert.equal(read.green_diff_kind, 'production-only')
    const boundTest = read.red_test
    // The trust root is established from the independent read, not any worker claim.
    const trustRoot = assertIndependentGitRead(read, {
      branch: BRANCH, expectedStartingHead: repo.baseHead, boundTest,
    })
    assert.deepEqual(trustRoot, {
      red_commit: repo.redCommit, green_commit: repo.greenCommit, final_commit: repo.finalCommit, branch: BRANCH,
    })
    // The worker's genuine claim (the real shas) cross-checks clean.
    const crossChecked = assertWorkerClaimCrossCheck(trustRoot, {
      redCommit: repo.redCommit, greenCommit: repo.greenCommit, finalCommit: repo.finalCommit,
    })
    // The host journals the INDEPENDENT-READ shas + host-sourced command; the observer replays them.
    const binding = assertHostJournalledCommits(
      {
        branch: BRANCH, red_commit: crossChecked.redCommit, green_commit: crossChecked.greenCommit,
        final_commit: crossChecked.finalCommit, command: CMD,
      },
      crossChecked, CMD, BRANCH,
    )
    const observation = observeFromGit(repo, binding, CMD)
    const accepted = assertObservedCommittedStates(observation, binding, boundTest)
    assert.notEqual(accepted.red_exit, 0)
    assert.equal(accepted.green_exit, 0)
    assert.equal(accepted.final_exit, 0)
    // The bound-test digest is a REAL content hash, identical across red/green/final for the healthy branch.
    assert.equal(observation.red_test.digest, observation.green_test.digest)
    assert.equal(observation.green_test.digest, observation.final_test.digest)
    assert.match(boundTest.digest, /^sha256:[0-9a-f]{64}$/)
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: a forged/cherry-picked worker sha (not what the independent git read read) is REJECTED by the cross-check, so a broken trust root cannot pass', () => {
  const repo = buildRealDeliveryRepo()
  try {
    const read = independentReadFromGit(repo, repo.baseHead)
    const trustRoot = assertIndependentGitRead(read, {
      branch: BRANCH, expectedStartingHead: repo.baseHead, boundTest: read.red_test,
    })
    // The worker CLAIMS its final commit is the real GREEN sha (a cherry-picked/forged claim that skips the
    // refactor the reader actually saw). The cross-check against the independent read rejects it.
    assert.throws(
      () => assertWorkerClaimCrossCheck(trustRoot, {
        redCommit: repo.redCommit, greenCommit: repo.greenCommit, finalCommit: repo.greenCommit,
      }),
      /claimed final commit differs from the independent git read/,
    )
    // Proof the guard is real: with the cross-check REMOVED, the worker's forged final sha would be
    // journalled and the observer would run it (a false green). The real git read distinguishes them.
    assert.notEqual(repo.greenCommit, repo.finalCommit, 'the forged final differs from the real final HEAD')
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: a red that does not genuinely fail the named test is REJECTED by the independent read', () => {
  const repo = buildRealDeliveryRepo()
  try {
    const read = independentReadFromGit(repo, repo.baseHead)
    // Force the independent read to report the red passing (as if the red never genuinely failed): the gate
    // rejects it. The rest of the read is the REAL git read.
    const tampered = { ...read, red_named_test_exit: 0 }
    assert.throws(
      () => assertIndependentGitRead(tampered, { branch: BRANCH, expectedStartingHead: repo.baseHead, boundTest: read.red_test }),
      /the red commit did not fail the named test/,
    )
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: a final HEAD whose bound test a refactor weakened (real different content digest) is REJECTED even though the tests pass', () => {
  const repo = buildRealDeliveryRepo({ weakenFinalTest: true })
  try {
    const read = independentReadFromGit(repo, repo.baseHead)
    // The final commit gutted the bound test; its real content digest differs from the red/green digest.
    assert.notEqual(read.final_test.digest, read.red_test.digest, 'the refactor really changed the bound test bytes')
    assert.throws(
      () => assertIndependentGitRead(read, { branch: BRANCH, expectedStartingHead: repo.baseHead, boundTest: read.red_test }),
      /content digest differs at the final commit/,
    )
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})

test('real-git FAIL-CLOSED: an independent read whose branch base is not the expected starting HEAD is REJECTED', () => {
  const repo = buildRealDeliveryRepo()
  try {
    const read = independentReadFromGit(repo, repo.baseHead)
    // A wrong expected starting HEAD (the branch did not root here) is rejected: the trust root is bound to
    // the exact bound HEAD, not whatever base the branch happens to have.
    assert.throws(
      () => assertIndependentGitRead(read, { branch: BRANCH, expectedStartingHead: repo.finalCommit, boundTest: read.red_test }),
      /branch base is not the expected starting HEAD/,
    )
  } finally {
    rmSync(repo.dir, { recursive: true, force: true })
  }
})
