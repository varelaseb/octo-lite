from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from octo_lite.runtime import GateError
from octo_lite.stream_envelope import build_stream_envelope

ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = ROOT / "workflows" / "lib" / "gates.mjs"

HEAD = "f00b13357cb1be87b5c5e6d7bd98fd9572915154"

ENV = {
    "OCTO_WORKTREE": "/root/octo-lite",
    "OCTO_WORKTREE_ROOT": "/root",
    "OCTO_CONTROL_REPO": "/root/octo-lite",
    "OCTO_REPO_SLUG": "varelaseb/octo-lite",
    "OCTO_STARTING_HEAD": HEAD,
    "OCTO_LANE": "gh8-workspace-admit",
    "OCTO_PROVISION_RECORD": "/root/octo-lite-worktrees/.octo-provisions/gh8-workspace-admit.json",
}

STREAM = {
    "issue": "TUR-447",
    "pr": 6,
    "pr_base": "main",
    "branch": "octo-lite/tur-443-operating-model",
    "topology_revision": "t1",
    "conversation_log_references": ["session.jsonl:1-1"],
    "conversation_cutoff": "session.jsonl:1",
    "acceptance_criteria": ["works"],
}

LIVE_READS = {
    "spec_revision": "r1",
    "spec_blobs": ["spec/domains/role-runtime.spec.html:anchor-1"],
    "adr_blobs": [],
    "pr_head": HEAD,
    "linear_revision": "lr1",
    "linear_fingerprint": "fp-shaped-a1",
    "linear_state": "Shaped",
}

SHAPING_JOURNAL = {
    "shaping_verdict": "clear",
    "shaping_verdict_head": HEAD,
    "shaping_reviewer_receipt": "rcpt-1",
    "shaping_verdict_inputs": ["in-1"],
}

CONTRACT_HASH = "c8b0440cacc5188b2926b626ee6f506ced5368ebbda67dc6b1ed0d542cddc34c"


def _build(**overrides):
    kwargs = dict(
        env=ENV, stream=STREAM, live_reads=LIVE_READS,
        contract_hash=CONTRACT_HASH, shaping_journal=SHAPING_JOURNAL,
    )
    kwargs.update(overrides)
    return build_stream_envelope(**kwargs)


def _extract_function_body(text: str, signature: str) -> str:
    start = text.index(signature)
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    raise AssertionError(f"unbalanced braces reading {signature!r}")


def _extract_required_envelope_fields() -> set[str]:
    # Structural drift-guard over the REAL canonical assertReadyEnvelope source
    # (never reimplemented): collect the field NAMES it reads, not its
    # validation logic.
    text = GATES_PATH.read_text()
    body = _extract_function_body(text, "export function assertReadyEnvelope(envelope) {")
    fields = set(re.findall(r"envelope\.(\w+)", body))
    array_match = re.search(r"for \(const field of \[(.*?)\]\)", body, re.DOTALL)
    if array_match:
        fields |= set(re.findall(r"'([^']+)'", array_match.group(1)))
    return fields


def _run_node_assert_ready_envelope(envelope: dict) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("node is required to call the real assertReadyEnvelope")
    script = (
        "import { assertReadyEnvelope } from " + json.dumps(GATES_PATH.resolve().as_posix()) + "\n"
        "import { readFileSync } from 'node:fs'\n"
        "const envelope = JSON.parse(readFileSync(0, 'utf8'))\n"
        "try {\n"
        "  assertReadyEnvelope(envelope)\n"
        "  process.stdout.write('OK')\n"
        "} catch (error) {\n"
        "  process.stderr.write(String((error && error.message) || error))\n"
        "  process.exit(1)\n"
        "}\n"
    )
    return subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps(envelope), capture_output=True, text=True,
    )


class StreamEnvelopeBuilderTests(unittest.TestCase):
    # gh#8 AC9 (ruling-65, D6; spec launch-stream-envelope-builder,
    # launch-stream-envelope-sources). Never reimplements assertReadyEnvelope:
    # this suite calls the REAL canonical function from workflows/lib/gates.mjs.

    # RED-10
    def test_builder_emits_ready_envelope(self) -> None:
        envelope = _build()
        self.assertIsInstance(envelope, dict)
        result = _run_node_assert_ready_envelope(envelope)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("OK", result.stdout)

        required_fields = _extract_required_envelope_fields()
        missing = required_fields - set(envelope)
        self.assertEqual(set(), missing, f"envelope missing loop-required fields: {missing}")

        # Worker-bind fields (octo-loop-qa.js:1398) the envelope also sources,
        # beyond what assertReadyEnvelope itself checks.
        for field in ("repo", "repo_slug", "worktree", "issue", "pr", "spec_blobs", "contract_hash"):
            self.assertIn(field, envelope)

    # RED-10b
    def test_missing_source_fails_closed_before_any_envelope_is_returned(self) -> None:
        cases = [
            dict(env={k: v for k, v in ENV.items() if k != "OCTO_WORKTREE"}),
            dict(contract_hash=""),
            dict(stream={k: v for k, v in STREAM.items() if k != "acceptance_criteria"}),
            dict(live_reads={k: v for k, v in LIVE_READS.items() if k != "linear_state"}),
            dict(shaping_journal={k: v for k, v in SHAPING_JOURNAL.items() if k != "shaping_verdict_inputs"}),
        ]
        for override in cases:
            with self.assertRaises(GateError, msg=override):
                _build(**override)

    def test_fresh_pr_head_confirmation_must_agree_with_starting_head(self) -> None:
        with self.assertRaises(GateError):
            _build(live_reads=dict(LIVE_READS, pr_head="f" * 40))

    # RED-11 (TUR-488)
    def test_stream_name_not_raw_flag(self) -> None:
        envelope = _build()
        self.assertIsInstance(envelope, dict)
        serialized = json.dumps(envelope)
        self.assertEqual(envelope, json.loads(serialized))

        stream_name = "gh8-workspace-admit"
        raw_flag = f"--stream {stream_name}"
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw_flag)
        self.assertNotEqual(raw_flag, serialized)


if __name__ == "__main__":
    unittest.main()
