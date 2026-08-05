// Cross-language differential harness (GH-65 parser equivalence): expose the LIVE
// loop parser parseVerifiedReviewerVerdict from workflows/octo-loop-qa.js and run it
// over the SHARED fixture payloads, printing one JSON result line per case. The Python
// differential test (tests/test_verdict_provenance.py) shells this and asserts the JS
// results are IDENTICAL to the Python parser's on the same inputs, proving the two
// implementations accept and reject exactly the same blocks.
//
// The loop is not a module (bare Workflow globals, top-level returns in mode branches).
// Load it exactly as tests/loop_modes.test.mjs does, but return the hoisted parser from
// the TOP of the async body before any mode logic runs.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')

async function loadParser() {
  const stripped = readFileSync(join(ROOT, 'workflows/octo-loop-qa.js'), 'utf8').replace(/^export /gm, '')
  // The loop is not a module. Run its body exactly as tests/loop_modes.test.mjs does so every
  // top-level definition (including the `const CANONICAL_VERDICT_KEYS` the parser closes over)
  // initializes; capture the hoisted parser via a closure over the loop scope, then let the body
  // reject at the delivery-mode gate (it runs long after the parser is defined). Grabbing after the
  // rejection is safe: the initialized bindings stay reachable through the captured closure.
  const capture = {}
  // eslint-disable-next-line no-new-func
  const factory = new Function(
    'agent', 'args', 'log', 'capture',
    `return (async () => { capture.get = () => ({ parseVerifiedReviewerVerdict }); ${stripped}\n })()`,
  )
  await factory(() => {}, '{}', () => {}, capture).catch(() => {})
  return capture.get()
}

const fixturePath = process.argv[2] ?? join(ROOT, 'tests/fixtures/verdict_grammar_cases.json')
const cases = JSON.parse(readFileSync(fixturePath, 'utf8'))
const { parseVerifiedReviewerVerdict } = await loadParser()
if (typeof parseVerifiedReviewerVerdict !== 'function') {
  throw new Error('probe failed to capture parseVerifiedReviewerVerdict from the loop')
}

const results = cases.map((c) => {
  try {
    const parsed = parseVerifiedReviewerVerdict(c.payload, c.review_type)
    return { name: c.name, outcome: 'accept', parsed: { verdict: parsed.verdict, head: parsed.head, findings: parsed.findings } }
  } catch (error) {
    return { name: c.name, outcome: 'reject', error: String(error && error.message ? error.message : error) }
  }
})

process.stdout.write(JSON.stringify(results))
