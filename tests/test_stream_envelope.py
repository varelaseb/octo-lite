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
# StreamEnvelopeProductionInvocationTests instead of at module top so a
# missing/broken entrypoint can only ever fail THIS class's own tests, never
# mask collection of the builder tests elsewhere in this file.

ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = ROOT / "workflows" / "lib" / "gates.mjs"

HEAD = "f00b13357cb1be87b5c5e6d7bd98fd9572915154"

# ADR 0003 (loop-runs-on-cwd-and-branch): the worktree, its root, the repo slug, the
# starting head, and the branch are SOURCED from the running loop's process working
# directory and git, NOT a frozen OCTO_* launch environment.
CWD_GIT = {
    "worktree": "/root/octo-lite",
    "worktree_root": "/root",
    "repo_slug": "varelaseb/octo-lite",
    "starting_head": HEAD,
    "branch": "octo-lite/tur-443-operating-model",
}

STREAM = {
    "issue": "TUR-447",
    "pr": 6,
    "pr_base": "main",
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
        cwd_git=CWD_GIT, stream=STREAM, live_reads=LIVE_READS,
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
    # (never reimplemented): collect the field NAMES it reads.
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
    # ADR 0003 (spec launch-stream-envelope-builder, launch-stream-envelope-sources,
    # loop-runs-on-cwd-and-branch). Never reimplements assertReadyEnvelope: this suite
    # calls the REAL canonical function from workflows/lib/gates.mjs.

    def test_builder_emits_ready_envelope(self) -> None:
        envelope = _build()
        self.assertIsInstance(envelope, dict)
        result = _run_node_assert_ready_envelope(envelope)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("OK", result.stdout)

        required_fields = _extract_required_envelope_fields()
        missing = required_fields - set(envelope)
        self.assertEqual(set(), missing, f"envelope missing loop-required fields: {missing}")

        for field in ("repo", "repo_slug", "worktree", "branch", "issue", "pr", "spec_blobs", "contract_hash"):
            self.assertIn(field, envelope)

    def test_worktree_branch_and_head_are_sourced_from_cwd_and_git(self) -> None:
        # loop-runs-on-cwd-and-branch: the worktree, branch, repo slug, and starting head
        # come from the running loop's cwd + git, never a frozen OCTO_* env seam.
        envelope = _build()
        self.assertEqual(CWD_GIT["worktree"], envelope["worktree"])
        self.assertEqual(CWD_GIT["worktree"], envelope["repo"])
        self.assertEqual(CWD_GIT["worktree_root"], envelope["worktree_root"])
        self.assertEqual(CWD_GIT["repo_slug"], envelope["repo_slug"])
        self.assertEqual(CWD_GIT["branch"], envelope["branch"])
        self.assertEqual(CWD_GIT["starting_head"], envelope["shaping_head"])

    def test_missing_source_fails_closed_before_any_envelope_is_returned(self) -> None:
        cases = [
            dict(cwd_git={k: v for k, v in CWD_GIT.items() if k != "worktree"}),
            dict(cwd_git={k: v for k, v in CWD_GIT.items() if k != "branch"}),
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
    # A GENUINE invocation regression test: passes a stream NAME through the REAL
    # production entrypoint (build envelope + start the loop through the injected runner)
    # and asserts the injected runner received PARSED JSON envelope args (a dict), never a
    # raw `--stream <name>` string. The runner signature is (cwd, envelope): ADR 0003
    # removed the frozen-env seam, so no env argument is threaded.
    def setUp(self) -> None:
        from octo_lite.stream_envelope import launch_stream_lane

        self.launch_stream_lane = launch_stream_lane

    def _provision(self) -> LaneProvision:
        record = {
            "schema_version": 1,
            "source": "host-provisioned-worktree",
            "lane": "gh8-workspace-admit",
            "control_repo": CWD_GIT["worktree"],
            "worktree": CWD_GIT["worktree"],
            "worktree_root": CWD_GIT["worktree_root"],
            "repo_slug": CWD_GIT["repo_slug"],
            "branch": CWD_GIT["branch"],
            "starting_head": CWD_GIT["starting_head"],
            "resolver_root": CWD_GIT["worktree"],
            "install_check": "clean",
            "provisioned_at": "2026-07-21T00:00:00+00:00",
        }
        return LaneProvision(
            record=record,
            record_path=Path("/root/octo-lite-worktrees/.octo-provisions/gh8-workspace-admit.json"),
            install_check_owner_route=None,
        )

    def test_stream_name_reaches_runner_as_parsed_json_never_raw_flag(self) -> None:
        provision = self._provision()
        calls = []

        def runner(cwd, args):
            calls.append((cwd, args))
            return {"ok": True}

        stream_name = "gh8-workspace-admit"
        output = self.launch_stream_lane(
            stream_name, provision=provision, cwd_git=CWD_GIT, stream=STREAM, live_reads=LIVE_READS,
            contract_hash=CONTRACT_HASH, shaping_journal=SHAPING_JOURNAL, runner=runner,
        )
        self.assertEqual({"ok": True}, output)
        self.assertEqual(1, len(calls))
        cwd, args = calls[0]
        self.assertEqual(Path(CWD_GIT["worktree"]), cwd)
        self.assertIsInstance(args, dict)

        # The runner never receives a raw '--stream <name>' string.
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
                "", provision=provision, cwd_git=CWD_GIT, stream=STREAM, live_reads=LIVE_READS,
                contract_hash=CONTRACT_HASH, shaping_journal=SHAPING_JOURNAL,
                runner=lambda cwd, args: None,
            )
