from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from octo_lite.launch import LaneProvision
from octo_lite.runtime import GateError
from octo_lite.stream_envelope import build_stream_envelope

# `launch_stream_lane` is imported LOCALLY inside
# StreamEnvelopeProductionInvocationTests instead of at module top (re-review
# finding 3, test_stream_envelope.py:12): a module-top import of a post-fix
# entrypoint would fail COLLECTION of this whole file at a state where that
# entrypoint does not yet exist, masking every OTHER regression in this file
# (e.g. REG-6's own builder assertion) behind an ImportError instead of
# letting it fail first on its own assertion.

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

    # REG-6 (code-review finding 6, stream_envelope.py:61): the builder must
    # fail closed on empty required arrays, on a non-'clear' shaping verdict,
    # and on a shaping_verdict_head that disagrees with shaping_head, mirroring
    # assertReadyEnvelope semantics BEFORE the envelope is returned.
    def test_builder_fails_closed_on_empty_required_arrays_and_bad_verdict(self) -> None:
        cases = [
            dict(live_reads=dict(LIVE_READS, spec_blobs=[])),
            dict(stream=dict(STREAM, acceptance_criteria=[])),
            dict(shaping_journal=dict(SHAPING_JOURNAL, shaping_verdict_inputs=[])),
            dict(stream=dict(STREAM, conversation_log_references=[])),
            dict(shaping_journal=dict(SHAPING_JOURNAL, shaping_verdict="blocking")),
            dict(shaping_journal=dict(SHAPING_JOURNAL, shaping_verdict_head="f" * 40)),
        ]
        for override in cases:
            with self.assertRaises(GateError, msg=override):
                _build(**override)


class StreamEnvelopeProductionInvocationTests(unittest.TestCase):
    # REG-7 (code-review finding 7, stream_envelope.py:70): a GENUINE
    # invocation regression test replacing the weak RED-11: passes a stream
    # NAME through the REAL production entrypoint (build envelope + start the
    # loop via run_lane_loop) and asserts the injected runner received
    # PARSED JSON envelope args (a dict/object), never a raw
    # `--stream <name>` string (TUR-488).
    #
    # `launch_stream_lane` is imported HERE, scoped to this class only (never
    # at module top), so a missing/broken post-fix entrypoint can only ever
    # fail THIS class's own tests, never mask collection of
    # StreamEnvelopeBuilderTests (REG-6) elsewhere in this file.
    def setUp(self) -> None:
        from octo_lite.stream_envelope import launch_stream_lane

        self.launch_stream_lane = launch_stream_lane

    def _provision(self) -> LaneProvision:
        record = {
            "schema_version": 1,
            "source": "host-provisioned-worktree",
            "lane": ENV["OCTO_LANE"],
            "control_repo": ENV["OCTO_CONTROL_REPO"],
            "worktree": ENV["OCTO_WORKTREE"],
            "worktree_root": ENV["OCTO_WORKTREE_ROOT"],
            "repo_slug": ENV["OCTO_REPO_SLUG"],
            "branch": STREAM["branch"],
            "starting_head": ENV["OCTO_STARTING_HEAD"],
            "resolver_root": ENV["OCTO_WORKTREE"],
            "install_check": "clean",
            "provisioned_at": "2026-07-21T00:00:00+00:00",
        }
        return LaneProvision(
            record=record, record_path=Path(ENV["OCTO_PROVISION_RECORD"]), install_check_owner_route=None,
        )

    def test_stream_name_reaches_runner_as_parsed_json_never_raw_flag(self) -> None:
        provision = self._provision()
        calls = []

        def runner(cwd, env, args):
            calls.append((cwd, env, args))
            return {"ok": True}

        stream_name = "gh8-workspace-admit"
        output = self.launch_stream_lane(
            stream_name, provision=provision, stream=STREAM, live_reads=LIVE_READS,
            contract_hash=CONTRACT_HASH, shaping_journal=SHAPING_JOURNAL, runner=runner,
        )
        self.assertEqual({"ok": True}, output)
        self.assertEqual(1, len(calls))
        cwd, env, args = calls[0]
        self.assertEqual(Path(ENV["OCTO_WORKTREE"]), cwd)
        self.assertEqual(ENV, env)
        self.assertIsInstance(args, dict)

        # The runner never receives a raw '--stream <name>' string: a dict
        # is not a string, and the string form is not even valid JSON.
        self.assertNotIsInstance(args, str)
        raw_flag = f"--stream {stream_name}"
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw_flag)
        self.assertNotEqual(raw_flag, json.dumps(args))

        # The built envelope still satisfies the real assertReadyEnvelope.
        result = _run_node_assert_ready_envelope(args)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_empty_stream_name_fails_closed(self) -> None:
        provision = self._provision()
        with self.assertRaises(GateError):
            self.launch_stream_lane(
                "", provision=provision, stream=STREAM, live_reads=LIVE_READS,
                contract_hash=CONTRACT_HASH, shaping_journal=SHAPING_JOURNAL,
                runner=lambda cwd, env, args: None,
            )


if __name__ == "__main__":
    unittest.main()
