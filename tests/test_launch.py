from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import uuid
from pathlib import Path
from unittest import mock

from octo_lite import launch as launch_module
from octo_lite.launch import (
    GateError,
    bootstrap_from_receipt,
    fetch_stream_binding,
    mutation_prompt,
    parse_pass_output,
    prepare_launch,
    prepare_reconcile_launch,
    read_pull_request,
    render_receipt,
    run_bootstrap,
    run_launch,
    run_mutation,
    run_reconcile_launch,
    verify_bootstrap,
)
from octo_lite.runtime import exact_fingerprint, launch_revision, verdict_body


ROOT = Path(__file__).resolve().parents[1]


def openai_provider_output(session_id: str, message: dict) -> str:
    lines = [
        json.dumps({"type": "thread.started", "thread_id": session_id}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(message)}}),
    ]
    return "\n".join(lines)


def write_codex_rollout(codex_home: Path, session_id: str, *, model: str, effort: str, provider: str = "openai") -> None:
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "19"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rollout = sessions_dir / f"rollout-2026-07-19T00-00-00-{session_id}.jsonl"
    rollout.write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"session_id": session_id, "model_provider": provider}}),
                json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort}}),
            ]
        )
        + "\n"
    )


FAKE_GH_PR_VIEW = '''#!/usr/bin/env python3
import json
import sys

argv = sys.argv[1:]
fields = argv[argv.index("--json") + 1].split(",") if "--json" in argv else []
full = {
    "number": 6,
    "url": "https://github.com/org/repo/pull/6",
    "headRefOid": "a" * 40,
    "headRefName": "feature",
    "baseRefName": "main",
    "comments": [],
    "state": "OPEN",
    "reviewDecision": "APPROVED",
    "statusCheckRollup": [{"name": "conformance", "conclusion": "SUCCESS"}],
}
print(json.dumps({key: full[key] for key in fields if key in full}))
'''


class GitHubReadFacadeTests(unittest.TestCase):
    def test_read_pull_request_requests_and_binds_state_review_decision_and_status_check_rollup(self) -> None:
        # A real `gh pr view --json <fields>` only returns the exact fields listed
        # in --json; this fake mirrors that shape instead of a permissive mock that
        # would hide an incomplete field list in the real production call.
        with tempfile.TemporaryDirectory() as td:
            fake_bin = Path(td) / "bin"
            fake_bin.mkdir()
            gh = fake_bin / "gh"
            gh.write_text(FAKE_GH_PR_VIEW)
            gh.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": f"{fake_bin}:{os.environ['PATH']}"}):
                pull = read_pull_request("org/repo", 6)
            self.assertEqual("OPEN", pull.get("state"))
            self.assertEqual("APPROVED", pull.get("reviewDecision"))
            self.assertEqual(
                [{"name": "conformance", "conclusion": "SUCCESS"}],
                pull.get("statusCheckRollup"),
            )


class StatusCheckNormalizationTests(unittest.TestCase):
    def _pull(self, rollup: list) -> dict:
        return {
            "url": "https://github.com/org/repo/pull/6",
            "headRefOid": "a" * 40,
            "headRefName": "feature",
            "baseRefName": "main",
            "state": "OPEN",
            "reviewDecision": "",
            "statusCheckRollup": rollup,
        }

    def test_duplicate_name_checks_with_differing_outcomes_normalize_identically_regardless_of_api_order(
        self,
    ) -> None:
        entries = [
            {"__typename": "CheckRun", "name": "conformance", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"__typename": "CheckRun", "name": "conformance", "status": "COMPLETED", "conclusion": "FAILURE"},
        ]
        forward = fetch_stream_binding(
            linear_issue=None, pr_repo="org/repo", pr_number=6,
            read_pr=lambda _repo, _number: self._pull(entries),
        )
        reversed_entries = list(reversed(entries))
        reversed_binding = fetch_stream_binding(
            linear_issue=None, pr_repo="org/repo", pr_number=6,
            read_pr=lambda _repo, _number: self._pull(reversed_entries),
        )
        self.assertEqual(2, len(forward["pull_request"]["status_checks"]))
        self.assertEqual(
            forward["pull_request"]["status_checks"],
            reversed_binding["pull_request"]["status_checks"],
        )

    def test_status_checks_retain_current_status_alongside_outcome_for_in_progress_and_completed_states(
        self,
    ) -> None:
        entries = [
            {"__typename": "CheckRun", "name": "conformance", "status": "IN_PROGRESS", "conclusion": None},
            {"__typename": "CheckRun", "name": "conformance", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        binding = fetch_stream_binding(
            linear_issue=None, pr_repo="org/repo", pr_number=6,
            read_pr=lambda _repo, _number: self._pull(entries),
        )
        checks = binding["pull_request"]["status_checks"]
        self.assertEqual(2, len(checks))
        self.assertNotEqual(checks[0], checks[1])
        self.assertEqual({"IN_PROGRESS", "COMPLETED"}, {check["status"] for check in checks})


class LaunchBoundaryTests(unittest.TestCase):
    def test_foreground_cli_exposes_prepare_launch_and_verify(self) -> None:
        result = subprocess.run(
            [str(ROOT / "scripts" / "octo-launch"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("{prepare,launch,bootstrap,verify}", result.stdout)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.worktree_root = base / "passes"
        self.worktree = self.worktree_root / "pass-1"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "git@example.test:org/repo.git"], check=True)
        (self.repo / "AGENTS.md").write_text("# Target\n")
        spec = self.repo / "spec" / "domain.spec.html"
        spec.parent.mkdir()
        spec.write_text("<p data-anchor=\"behavior\">Works.</p>\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.head = self.git("rev-parse", "HEAD")
        self.spec_blob = self.git("hash-object", "spec/domain.spec.html")
        self.issue = {
            "identifier": "TUR-447",
            "state": "Shaped",
            "title": "Exact launch",
            "updatedAt": "2026-07-19T00:00:00Z",
        }
        self.comment = verdict_body(
            "shaping",
            "clear",
            self.head,
            ["linear:current", f"spec:{self.spec_blob}"],
            [],
            "review-session-1",
            ["session.jsonl:1-6824"],
            "session.jsonl:6824",
        )
        self.pr = {
            "number": 6,
            "url": "https://github.com/org/repo/pull/6",
            "headRefOid": self.head,
            "headRefName": "feature",
            "baseRefName": "main",
            "comments": [{"body": self.comment}],
        }
        self.envelope = {
            "issue": "TUR-447",
            "repo": "org/repo",
            "pr": self.pr["url"],
            "branch": "feature",
            "purpose": "delivery",
            "starting_head": self.head,
            "shaping_head": self.head,
            "spec_revision": self.spec_blob,
            "linear_revision": self.issue["updatedAt"],
            "linear_fingerprint": exact_fingerprint(self.issue),
            "linear_state": "Shaped",
            "pr_head": self.head,
            "pr_base": "main",
            "topology_revision": 2,
            "shaping_verdict": "clear",
            "shaping_verdict_head": self.head,
            "shaping_verdict_inputs": ["linear:current", f"spec:{self.spec_blob}"],
            "shaping_reviewer_receipt": "review-session-1",
            "spec_blobs": [f"spec/domain.spec.html:{self.spec_blob}"],
            "adr_blobs": [],
            "conversation_cutoff": "session.jsonl:6824",
            "conversation_log_references": ["session.jsonl:1-6824"],
            "pass_instruction": "Implement one pass. Return only the schema.",
            "acceptance_criteria": ["launch is exact"],
            "resource_claims": {
                "branch": "feature",
                "fixtures": [],
                "ports": [3100],
                "pids": [],
                "artifact_roots": [str(Path(self.temp.name) / "artifacts")],
            },
            "resource_conflicts": [],
            "provider_overloaded": False,
            "minimum_free_bytes": 1,
        }
        self.spawn_id = str(uuid.uuid4())

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def prepare(self, **overrides):
        values = {
            "root": ROOT,
            "envelope": self.envelope,
            "role_name": "implementer",
            "capabilities": {"python"},
            "spawn_id": self.spawn_id,
            "parent": "issue-orchestrator",
            "reply_route": "herdr:issue-orchestrator",
            "repo": self.repo,
            "worktree_root": self.worktree_root,
            "worktree": self.worktree,
            "receipt_path": Path(self.temp.name) / "launch.toml",
            "execution_location": "remote",
            "operator_loopback": False,
            "review_delivery": "https://review.example.test/TUR-447",
            "read_linear": lambda _issue: self.issue,
            "read_pr": lambda _repo, _pr: self.pr,
        }
        values.update(overrides)
        return prepare_launch(**values)

    def test_prepare_refetches_exact_sources_and_gates_mutation(self) -> None:
        prepared = self.prepare()
        receipt = tomllib.loads(prepared.receipt_path.read_text())

        self.assertEqual(self.head, receipt["workspace"]["starting_head"])
        self.assertEqual("TUR-447", receipt["issue"]["identifier"])
        self.assertEqual(self.spec_blob, receipt["spec"]["revision"])
        self.assertEqual(self.head, receipt["pull_request"]["head"])
        self.assertEqual(2, receipt["topology"]["revision"])
        self.assertEqual("octo-lite-pass", receipt["manifest_type"])
        self.assertEqual("feature", receipt["resources"]["branch"])
        self.assertEqual([3100], receipt["resources"]["ports"])
        self.assertEqual("review-session-1", receipt["prior_gates"]["shaping_reviewer_receipt"])
        self.assertFalse(receipt["bootstrap"]["verified"])
        self.assertTrue(self.worktree.is_dir())
        self.assertEqual(self.worktree.resolve(), Path(self.git("-C", str(self.worktree), "rev-parse", "--show-toplevel")).resolve())

        bootstrap = prepared.bootstrap_argv
        mutation = prepared.mutation_argv
        self.assertEqual("claude-sonnet-5", bootstrap[bootstrap.index("--model") + 1])
        self.assertEqual("xhigh", bootstrap[bootstrap.index("--effort") + 1])
        self.assertEqual("auto", bootstrap[bootstrap.index("--permission-mode") + 1])
        self.assertNotIn("--last", bootstrap + mutation)
        self.assertNotIn("--continue", bootstrap + mutation)
        self.assertNotIn("Edit", bootstrap[bootstrap.index("--tools") + 1])
        self.assertIn("Edit", mutation[mutation.index("--tools") + 1])
        self.assertIn("--resume", mutation)

    def test_shaping_review_purpose_launches_without_prior_verdict(self) -> None:
        envelope = dict(self.envelope, purpose="shaping-review")
        for field in (
            "shaping_verdict", "shaping_verdict_head", "shaping_reviewer_receipt", "shaping_verdict_inputs",
        ):
            envelope.pop(field, None)
        pr_without_verdict = dict(self.pr, comments=[])
        prepared = self.prepare(envelope=envelope, read_pr=lambda _repo, _pr: pr_without_verdict)
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual("shaping-review", receipt["purpose"])
        self.assertEqual(self.head, receipt["workspace"]["starting_head"])

    def test_shaping_review_launches_while_linear_is_in_progress(self) -> None:
        # Shaping re-review must run after material reconciliation while the
        # stream orchestrator still holds Linear In Progress.
        in_progress_issue = dict(self.issue, state="In Progress")
        envelope = dict(
            self.envelope,
            purpose="shaping-review",
            linear_state="In Progress",
            linear_fingerprint=exact_fingerprint(in_progress_issue),
        )
        for field in (
            "shaping_verdict", "shaping_verdict_head", "shaping_reviewer_receipt", "shaping_verdict_inputs",
        ):
            envelope.pop(field, None)
        pr_without_verdict = dict(self.pr, comments=[])
        prepared = self.prepare(
            envelope=envelope,
            read_linear=lambda _issue: in_progress_issue,
            read_pr=lambda _repo, _pr: pr_without_verdict,
        )
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual("shaping-review", receipt["purpose"])
        self.assertEqual("In Progress", receipt["issue"]["state"])

    def test_qa_reviewer_delivery_launches_while_linear_is_in_progress_with_fakes(self) -> None:
        # Turbo-like path: normal code and QA review launch for delivery while
        # Linear is still In Progress, and the exact shaping-verdict checks
        # delivery requires stay enforced (self.envelope keeps its clear
        # verdict comment and shaping_head binding unchanged).
        in_progress_issue = dict(self.issue, state="In Progress")
        envelope = dict(
            self.envelope,
            linear_state="In Progress",
            linear_fingerprint=exact_fingerprint(in_progress_issue),
        )
        prepared = self.prepare(
            envelope=envelope,
            role_name="qa-reviewer",
            capabilities=set(),
            worktree=self.worktree_root / "qa-review-in-progress",
            read_linear=lambda _issue: in_progress_issue,
        )
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual("delivery", receipt["purpose"])
        self.assertEqual("In Progress", receipt["issue"]["state"])
        self.assertEqual("clear", receipt["prior_gates"]["shaping_verdict"])

    def test_shaping_review_and_delivery_reject_awaiting_accept_and_terminal_linear_states(self) -> None:
        for state in ("Awaiting Accept", "Done"):
            shaping_envelope = dict(self.envelope, purpose="shaping-review", linear_state=state)
            with self.assertRaisesRegex(GateError, "Linear state invalid for shaping review"):
                self.prepare(envelope=shaping_envelope)
            self.assertFalse(self.worktree.exists())

            delivery_envelope = dict(self.envelope, linear_state=state)
            with self.assertRaisesRegex(GateError, "Linear state must be"):
                self.prepare(envelope=delivery_envelope)
            self.assertFalse(self.worktree.exists())

    def test_delivery_purpose_launches_at_current_head_retaining_shaping_verdict_binding(self) -> None:
        (self.repo / "b").write_text("advance\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "b"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fix"], check=True)
        current_head = self.git("rev-parse", "HEAD")
        self.assertNotEqual(self.head, current_head)

        envelope = dict(self.envelope, starting_head=current_head, pr_head=current_head)
        advanced_pr = dict(self.pr, headRefOid=current_head)
        prepared = self.prepare(envelope=envelope, read_pr=lambda _repo, _pr: advanced_pr)
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual(current_head, receipt["workspace"]["starting_head"])
        self.assertEqual(self.head, receipt["pull_request"]["shaping_head"])
        self.assertEqual("delivery", receipt["purpose"])

    def test_orchestrator_shaping_review_receipt_binds_shaping_authority_table(self) -> None:
        envelope = dict(self.envelope, purpose="shaping-review")
        for field in (
            "shaping_verdict", "shaping_verdict_head", "shaping_reviewer_receipt", "shaping_verdict_inputs",
        ):
            envelope.pop(field, None)
        pr_without_verdict = dict(self.pr, comments=[])
        prepared = self.prepare(
            envelope=envelope, role_name="orchestrator", read_pr=lambda _repo, _pr: pr_without_verdict,
        )
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual({"repo": "org/repo", "pr": 6, "head": self.head}, receipt["shaping"])

    def test_non_orchestrator_or_non_shaping_review_receipt_carries_no_shaping_authority(self) -> None:
        prepared = self.prepare()
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertNotIn("shaping", receipt)

    def test_delivery_purpose_still_requires_clear_verdict(self) -> None:
        envelope = dict(self.envelope, shaping_verdict="blocking")
        with self.assertRaisesRegex(GateError, "shaping verdict not clear"):
            self.prepare(envelope=envelope)

    def test_delivery_purpose_rejects_stale_or_substituted_verdict_conversation_evidence(self) -> None:
        # A nonempty conversation reference or cutoff is not enough: it must be the
        # exact one this envelope declares, or a stale or substituted verdict (from
        # an unrelated or earlier session) could otherwise pass preflight.
        stale_refs_comment = verdict_body(
            "shaping",
            "clear",
            self.head,
            ["linear:current", f"spec:{self.spec_blob}"],
            [],
            "review-session-1",
            ["stale-session.jsonl:1-1"],
            "session.jsonl:6824",
        )
        stale_refs_pr = dict(self.pr, comments=[{"body": stale_refs_comment}])
        with self.assertRaisesRegex(GateError, "shaping verdict mismatch: conversation_log_references"):
            self.prepare(read_pr=lambda _repo, _pr: stale_refs_pr)
        self.assertFalse(self.worktree.exists())

        stale_cutoff_comment = verdict_body(
            "shaping",
            "clear",
            self.head,
            ["linear:current", f"spec:{self.spec_blob}"],
            [],
            "review-session-1",
            ["session.jsonl:1-6824"],
            "stale-session.jsonl:1",
        )
        stale_cutoff_pr = dict(self.pr, comments=[{"body": stale_cutoff_comment}])
        with self.assertRaisesRegex(GateError, "shaping verdict mismatch: conversation_cutoff"):
            self.prepare(read_pr=lambda _repo, _pr: stale_cutoff_pr)
        self.assertFalse(self.worktree.exists())

    def test_stale_linear_or_pr_head_fails_before_worktree(self) -> None:
        stale_issue = dict(self.issue, title="changed")
        with self.assertRaisesRegex(GateError, "Linear fingerprint mismatch"):
            self.prepare(read_linear=lambda _issue: stale_issue)
        self.assertFalse(self.worktree.exists())

        wrong_repo = dict(self.envelope, repo="other/repo")
        with self.assertRaisesRegex(GateError, "repo identity mismatch"):
            self.prepare(envelope=wrong_repo)
        self.assertFalse(self.worktree.exists())

        stale_pr = dict(self.pr, headRefOid="0" * 40)
        with self.assertRaisesRegex(GateError, "PR HEAD mismatch"):
            self.prepare(read_pr=lambda _repo, _pr: stale_pr)
        self.assertFalse(self.worktree.exists())

    def test_resource_conflict_or_provider_overload_refuses_admission(self) -> None:
        conflict = dict(self.envelope, resource_conflicts=["port:3100"])
        with self.assertRaisesRegex(GateError, "resource conflict"):
            self.prepare(envelope=conflict)
        self.assertFalse(self.worktree.exists())
        overload = dict(self.envelope, provider_overloaded=True)
        with self.assertRaisesRegex(GateError, "provider overload"):
            self.prepare(envelope=overload)
        self.assertFalse(self.worktree.exists())

    def test_escape_and_missing_ack_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown role"):
            self.prepare(role_name="invented-role")
        self.assertFalse(self.worktree.exists())

        outside = Path(self.temp.name) / "outside"
        with self.assertRaisesRegex(GateError, "escapes allowed root"):
            self.prepare(worktree=outside)
        with self.assertRaisesRegex(GateError, "loopback delivery requires explicit operator access"):
            self.prepare(review_delivery="loopback_allowed")

        prepared = self.prepare()
        with self.assertRaisesRegex(GateError, "verified BOOTSTRAP_ACK required"):
            mutation_prompt(prepared)
        with self.assertRaisesRegex(GateError, "bootstrap acknowledgment mismatch"):
            verify_bootstrap(prepared.receipt_path, {"spawn_id": self.spawn_id})
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertFalse(receipt["bootstrap"]["verified"])

    def test_exact_ack_atomically_releases_mutation(self) -> None:
        prepared = self.prepare()
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        ack = prepared.expected_ack("provider-session-1")
        self.assertLessEqual(len(ack), 9)
        self.assertEqual(receipt["launch_revision"], ack["launch_revision"])
        verified = verify_bootstrap(prepared.receipt_path, ack)
        readback = tomllib.loads(prepared.receipt_path.read_text())

        self.assertEqual("provider-session-1", verified["provider_session_id"])
        self.assertTrue(readback["bootstrap"]["verified"])
        self.assertEqual("provider-session-1", readback["bootstrap"]["provider_session_id"])
        self.assertEqual(receipt["spawn_id"], readback["spawn_id"])
        self.assertEqual(receipt["workspace"]["starting_head"], readback["workspace"]["starting_head"])

    def test_run_releases_exact_session_only_after_ack(self) -> None:
        prepared = self.prepare()
        calls = []

        def blocked_runner(argv, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"session_id": self.spawn_id, "result": "{}"}), stderr="")

        with self.assertRaisesRegex(GateError, "bootstrap acknowledgment mismatch"):
            run_launch(prepared, runner=blocked_runner)
        self.assertEqual(1, len(calls))

        ack = prepared.expected_ack(self.spawn_id)
        ack.pop("provider_session_id")
        calls.clear()

        role_result = {"head": "f" * 40, "blocked": False, "validation": "ok"}

        def clear_runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")
            output = {"session_id": self.spawn_id, "result": json.dumps(role_result)}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        pass_result = run_launch(prepared, runner=clear_runner)
        self.assertEqual(2, len(calls))
        self.assertIn(self.spawn_id, calls[1])
        self.assertNotIn("--last", calls[1])
        self.assertEqual("f" * 40, pass_result["head"])
        self.assertEqual(self.spawn_id, pass_result["receipt"])
        self.assertRegex(pass_result["result_binding"], r"^[0-9a-f]{64}$")
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertTrue(readback["result"]["bound"])
        self.assertEqual(pass_result["result_binding"], readback["result"]["binding"])

    def test_run_launch_overwrites_a_self_asserted_result_binding(self) -> None:
        prepared = self.prepare()
        ack = prepared.expected_ack(self.spawn_id)
        ack.pop("provider_session_id")
        spoofed_result = {"head": "f" * 40, "blocked": False, "result_binding": "0" * 64}
        calls = []

        def spoofing_runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")
            output = {"session_id": self.spawn_id, "result": json.dumps(spoofed_result)}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        pass_result = run_launch(prepared, runner=spoofing_runner)
        self.assertNotEqual("0" * 64, pass_result["result_binding"])
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual(pass_result["result_binding"], readback["result"]["binding"])

    def test_bootstrap_from_receipt_verifies_via_working_tree_contract_blob(self) -> None:
        prepared = self.prepare()
        ack = prepared.expected_ack(self.spawn_id)
        ack.pop("provider_session_id")

        def clear_runner(argv, **kwargs):
            output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        session = bootstrap_from_receipt(prepared.receipt_path, runner=clear_runner)
        self.assertEqual(self.spawn_id, session)
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertTrue(readback["bootstrap"]["verified"])

    def test_bootstrap_from_receipt_works_before_the_role_contract_is_committed(self) -> None:
        # A dashboard edit to roles/*.md is a plain working-tree change until the
        # operator commits it. Bootstrap must not require `git cat-file` lookup of an
        # object that was never written to the object database.
        role_repo = Path(self.temp.name) / "role-src"
        subprocess.run(["git", "init", "-q", str(role_repo)], check=True)
        subprocess.run(["git", "-C", str(role_repo), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(role_repo), "config", "user.name", "T"], check=True)
        (role_repo / "roles").mkdir()
        contract = role_repo / "roles" / "implementer.md"
        contract.write_text("# Implementer\nCommitted contract.\n")
        subprocess.run(["git", "-C", str(role_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(role_repo), "commit", "-qm", "base"], check=True)
        contract.write_text("# Implementer\nUncommitted edit.\n")
        blob = subprocess.run(
            ["git", "-C", str(role_repo), "hash-object", "--no-filters", "roles/implementer.md"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run(
                ["git", "-C", str(role_repo), "cat-file", "-p", blob],
                check=True, capture_output=True, text=True,
            )

        receipt_path = Path(self.temp.name) / "bare-receipt.toml"
        receipt = {
            "schema_version": 1,
            "spawn_id": self.spawn_id,
            "parent": "issue-orchestrator",
            "reply_route": "herdr:issue-orchestrator",
            "ready": True,
            "role": {
                "name": "implementer",
                "root": str(role_repo),
                "contract_path": "roles/implementer.md",
                "contract_blob": blob,
                "mapping_revision": "map-1",
            },
            "runtime": {
                "provider": "anthropic", "model": "claude-sonnet-5", "effort": "xhigh",
                "mode": "auto", "session": "fresh", "service_tier": "default",
                "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "Skill"],
            },
            "skills": {"resolved": [], "matched_capabilities": [], "paths": [], "blobs": []},
            "workspace": {
                "repo": str(self.repo), "worktree": str(self.repo),
                "starting_head": self.head, "instructions_path": "AGENTS.md",
                "instructions_blob": self.git("hash-object", "AGENTS.md"),
            },
            "access": {
                "execution_location": "remote", "operator_loopback": False,
                "review_delivery": "reachable_url_required",
            },
            "bootstrap": {"verified": False, "provider_session_id": ""},
        }
        receipt["launch_revision"] = launch_revision(receipt)
        receipt_path.write_text(render_receipt(receipt))

        ack = {
            "schema_version": 1, "spawn_id": self.spawn_id, "provider_session_id": self.spawn_id,
            "launch_revision": receipt["launch_revision"], "role": "implementer",
            "worktree": str(self.repo), "starting_head": self.head, "ready": True, "blocker": "",
        }

        def clear_runner(argv, **kwargs):
            output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        session = bootstrap_from_receipt(receipt_path, runner=clear_runner)
        self.assertEqual(self.spawn_id, session)

    def test_bootstrap_from_receipt_rejects_spoofed_acknowledgment(self) -> None:
        prepared = self.prepare()
        ack = prepared.expected_ack(self.spawn_id)
        ack["role"] = "code-reviewer"

        def spoofing_runner(argv, **kwargs):
            output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        with self.assertRaisesRegex(GateError, "bootstrap acknowledgment mismatch"):
            bootstrap_from_receipt(prepared.receipt_path, runner=spoofing_runner)
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertFalse(readback["bootstrap"]["verified"])

    def test_parse_pass_output_extracts_the_exact_session_and_role_result_without_bootstrap_unwrap(self) -> None:
        anthropic_output = json.dumps({"session_id": "s1", "result": json.dumps({"head": "abc", "blocked": False})})
        self.assertEqual(("s1", {"head": "abc", "blocked": False}), parse_pass_output("anthropic", anthropic_output))

        # A role result that happens to contain a BOOTSTRAP_ACK-shaped key is not unwrapped:
        # unwrapping is bootstrap-specific and must not silently reshape a pass result.
        literal = json.dumps({"session_id": "s1", "result": json.dumps({"BOOTSTRAP_ACK": {"x": 1}, "head": "abc"})})
        self.assertEqual(("s1", {"BOOTSTRAP_ACK": {"x": 1}, "head": "abc"}), parse_pass_output("anthropic", literal))

        with self.assertRaisesRegex(GateError, "unreadable"):
            parse_pass_output("anthropic", "not json")

    def test_reused_worktree_path_rejected_for_fresh_pass(self) -> None:
        self.prepare()
        with self.assertRaisesRegex(GateError, "absent worktree path"):
            self.prepare()

    def test_read_only_role_uses_fresh_detached_worktree_at_exact_head(self) -> None:
        prepared = self.prepare(role_name="code-reviewer", capabilities=set())
        branch = subprocess.run(
            ["git", "-C", str(self.worktree), "branch", "--show-current"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual("", branch)
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual(self.head, receipt["workspace"]["starting_head"])

    def test_mutable_role_attaches_the_exact_bound_branch(self) -> None:
        self.prepare()
        branch = subprocess.run(
            ["git", "-C", str(self.worktree), "branch", "--show-current"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual("feature", branch)

    def test_resource_branch_mismatch_rejected_before_worktree_creation(self) -> None:
        mismatched = dict(
            self.envelope,
            resource_claims=dict(self.envelope["resource_claims"], branch="other-branch"),
        )
        with self.assertRaisesRegex(GateError, "resource branch mismatch"):
            self.prepare(envelope=mismatched)
        self.assertFalse(self.worktree.exists())

    def test_mutable_pass_never_silently_falls_back_to_detached_when_branch_is_busy(self) -> None:
        other = self.worktree_root / "other-pass"
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", "feature", str(other), self.head],
            check=True, capture_output=True, text=True,
        )
        with self.assertRaisesRegex(GateError, "worktree creation failed"):
            self.prepare()
        self.assertFalse(self.worktree.exists())

    def test_openai_review_role_needing_live_reads_resumes_with_workspace_write_network_access(self) -> None:
        # The installed codex CLI's resume subcommand rejects the top-level -s
        # flag (exit 2, "unexpected argument '-s'"); only the exec bootstrap
        # accepts it, so resume must select sandbox mode through -c config.
        prepared = self.prepare(role_name="code-reviewer", capabilities=set())
        self.assertEqual("read-only", prepared.bootstrap_argv[prepared.bootstrap_argv.index("-s") + 1])
        self.assertNotIn("-s", prepared.mutation_argv)
        self.assertIn('sandbox_mode="workspace-write"', prepared.mutation_argv)
        self.assertIn("sandbox_workspace_write.network_access=true", prepared.mutation_argv)

    def test_openai_review_role_without_live_reads_stays_read_only_on_resume(self) -> None:
        prepared = self.prepare(role_name="qa-reviewer", capabilities=set())
        self.assertNotIn("-s", prepared.mutation_argv)
        self.assertNotIn('sandbox_mode="workspace-write"', prepared.mutation_argv)
        self.assertIn('sandbox_mode="read-only"', prepared.mutation_argv)

    def test_openai_resume_argv_is_accepted_by_the_installed_codex_cli_parser(self) -> None:
        # A string-content assertion on argv cannot prove the actually installed
        # codex binary's resume parser accepts these exact flags; --help exits
        # after full argument parsing with no network call or live session, so
        # this would have caught the prior false green where a bare -s on
        # resume exits 2 with "unexpected argument '-s'".
        codex = shutil.which("codex")
        if not codex:
            self.skipTest("codex CLI not installed")
        placeholder_session = str(uuid.uuid4())
        for role_name in ("code-reviewer", "qa-reviewer"):
            prepared = self.prepare(
                role_name=role_name,
                capabilities=set(),
                worktree=self.worktree_root / f"parser-smoke-{role_name}",
            )
            argv = prepared.mutation_argv_for(placeholder_session) + ["--help"]
            result = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("unexpected argument", result.stderr)

    def test_run_bootstrap_fails_closed_when_read_only_worktree_mutates_before_ack(self) -> None:
        prepared = self.prepare(role_name="code-reviewer", capabilities=set())
        session_id = str(uuid.uuid4())
        ack = prepared.expected_ack(session_id)
        ack.pop("provider_session_id")

        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=openai_provider_output(session_id, ack), stderr="")

        (self.worktree / "stray.txt").write_text("mutated before ack\n")
        with tempfile.TemporaryDirectory() as codex_home:
            write_codex_rollout(Path(codex_home), session_id, model="gpt-5.6-sol", effort="high")
            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}):
                with self.assertRaisesRegex(GateError, "review-pass worktree"):
                    run_bootstrap(prepared, runner=runner)
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertFalse(readback["bootstrap"]["verified"])

    def test_run_mutation_fails_closed_when_read_only_worktree_mutates_after_resumed_pass(self) -> None:
        prepared = self.prepare(role_name="code-reviewer", capabilities=set())
        session_id = str(uuid.uuid4())
        ack = prepared.expected_ack(session_id)
        ack.pop("provider_session_id")

        def bootstrap_runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=openai_provider_output(session_id, ack), stderr="")

        with tempfile.TemporaryDirectory() as codex_home:
            write_codex_rollout(Path(codex_home), session_id, model="gpt-5.6-sol", effort="high")
            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}):
                returned_session = run_bootstrap(prepared, runner=bootstrap_runner)
        self.assertEqual(session_id, returned_session)

        (self.worktree / "stray.txt").write_text("mutated after resumed pass\n")

        def mutation_runner(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0, stdout=openai_provider_output(session_id, {"verdict": "clear"}), stderr="",
            )

        with self.assertRaisesRegex(GateError, "review-pass worktree"):
            run_mutation(prepared, session_id, "prompt", runner=mutation_runner)

    def test_run_bootstrap_fails_closed_when_openai_effective_identity_is_unprovable(self) -> None:
        prepared = self.prepare(role_name="code-reviewer", capabilities=set())
        session_id = str(uuid.uuid4())
        ack = prepared.expected_ack(session_id)
        ack.pop("provider_session_id")

        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=openai_provider_output(session_id, ack), stderr="")

        with tempfile.TemporaryDirectory() as codex_home:
            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}):
                with self.assertRaisesRegex(GateError, "codex effective identity"):
                    run_bootstrap(prepared, runner=runner)
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertFalse(readback["bootstrap"]["verified"])

    def test_run_bootstrap_fails_closed_when_openai_effective_identity_mismatches(self) -> None:
        prepared = self.prepare(role_name="code-reviewer", capabilities=set())
        session_id = str(uuid.uuid4())
        ack = prepared.expected_ack(session_id)
        ack.pop("provider_session_id")

        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=openai_provider_output(session_id, ack), stderr="")

        with tempfile.TemporaryDirectory() as codex_home:
            write_codex_rollout(Path(codex_home), session_id, model="gpt-4.1-mini", effort="high")
            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}):
                with self.assertRaisesRegex(GateError, "codex effective identity mismatch"):
                    run_bootstrap(prepared, runner=runner)
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertFalse(readback["bootstrap"]["verified"])

        with tempfile.TemporaryDirectory() as codex_home:
            write_codex_rollout(Path(codex_home), session_id, model="gpt-5.6-sol", effort="low")
            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}):
                with self.assertRaisesRegex(GateError, "codex effective identity mismatch"):
                    run_bootstrap(prepared, runner=runner)

    def test_run_bootstrap_succeeds_when_openai_effective_identity_is_proven(self) -> None:
        prepared = self.prepare(role_name="code-reviewer", capabilities=set())
        session_id = str(uuid.uuid4())
        ack = prepared.expected_ack(session_id)
        ack.pop("provider_session_id")

        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=openai_provider_output(session_id, ack), stderr="")

        with tempfile.TemporaryDirectory() as codex_home:
            write_codex_rollout(Path(codex_home), session_id, model="gpt-5.6-sol", effort="high")
            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}):
                returned_session = run_bootstrap(prepared, runner=runner)
        self.assertEqual(session_id, returned_session)
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertTrue(readback["bootstrap"]["verified"])

    def test_run_launch_fails_closed_when_mutation_call_returns_a_different_session(self) -> None:
        prepared = self.prepare()
        ack = prepared.expected_ack(self.spawn_id)
        ack.pop("provider_session_id")
        wrong_session = str(uuid.uuid4())
        calls = []

        def imposter_runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")
            role_result = {"head": "f" * 40, "blocked": False, "validation": "ok"}
            output = {"session_id": wrong_session, "result": json.dumps(role_result)}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        with self.assertRaisesRegex(GateError, "session mismatch"):
            run_launch(prepared, runner=imposter_runner)
        self.assertEqual(2, len(calls))
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertNotIn("result", readback)


class ReconcileLaunchBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.worktree_root = base / "worktrees"
        self.worktree = self.worktree_root / "sweep-1"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "AGENTS.md").write_text("# Target\n")
        spec = self.repo / "spec" / "domains" / "operating-model.spec.html"
        spec.parent.mkdir(parents=True)
        spec.write_text('<p data-anchor="x">Works.</p>\n')
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.head = self.git("rev-parse", "HEAD")
        self.spec_blob = self.git("hash-object", "spec/domains/operating-model.spec.html")

        self.linear = {"identifier": "TUR-1", "state": "Todo", "updatedAt": "2026-07-19T00:00:00Z"}
        self.pull = {
            "url": "https://github.com/org/repo/pull/6",
            "headRefOid": "a" * 40,
            "headRefName": "feature",
            "baseRefName": "main",
            "state": "OPEN",
            "reviewDecision": "",
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "conformance",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "startedAt": "2026-07-19T00:00:00Z",
                    "completedAt": "2026-07-19T00:01:00Z",
                    "detailsUrl": "https://github.com/org/repo/actions/runs/1",
                }
            ],
        }
        self.streams = [
            {
                "stream": "TUR-1",
                **fetch_stream_binding(
                    linear_issue="TUR-1", pr_repo="org/repo", pr_number=6,
                    read_linear=lambda _issue: self.linear,
                    read_pr=lambda _repo, _number: self.pull,
                ),
            }
        ]
        self.snapshot_path = base / "snapshot.md"
        self.snapshot_path.write_text("# snapshot\n")
        self.snapshot_digest = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    def prepare(self, **overrides):
        values = {
            "root": ROOT,
            "spawn_id": str(uuid.uuid4()),
            "parent": "operator-1",
            "reply_route": "operator-say",
            "repo": self.repo,
            "worktree_root": self.worktree_root,
            "worktree": self.worktree,
            "receipt_path": Path(self.temp.name) / "reconcile.toml",
            "execution_location": "remote",
            "operator_loopback": False,
            "review_delivery": "reachable_url_required",
            "expected_head": self.head,
            "snapshot_path": self.snapshot_path,
            "snapshot_digest": self.snapshot_digest,
            "streams": self.streams,
            "spec_blobs": [f"spec/domains/operating-model.spec.html:{self.spec_blob}"],
            "adr_blobs": [],
            "conversation_state_refs": ["status.md"],
            "read_linear": lambda _issue: self.linear,
            "read_pr": lambda _repo, _number: self.pull,
        }
        values.update(overrides)
        return prepare_reconcile_launch(**values)

    def test_prepare_reconcile_provisions_a_detached_worktree_never_the_control_checkout(self) -> None:
        prepared = self.prepare()
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertNotEqual(str(self.repo), receipt["workspace"]["worktree"])
        self.assertEqual(str(self.worktree), receipt["workspace"]["worktree"])
        self.assertTrue(self.worktree.is_dir())
        branch = subprocess.run(
            ["git", "-C", str(self.worktree), "branch", "--show-current"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual("", branch)
        top = subprocess.run(
            ["git", "-C", str(self.worktree), "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(str(self.worktree.resolve()), top)
        self.assertTrue(receipt["workspace"]["child_containment_verified"])

    def test_reconcile_worktree_escaping_allowed_root_fails_closed(self) -> None:
        outside = Path(self.temp.name) / "outside"
        with self.assertRaisesRegex(GateError, "escapes allowed root"):
            self.prepare(worktree=outside)

    def test_receipt_binds_snapshot_digest_spec_and_adr_blobs_control_head_and_stream_facts(self) -> None:
        prepared = self.prepare()
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        reconcile = receipt["reconcile"]
        self.assertEqual(self.snapshot_digest, reconcile["snapshot_digest"])
        self.assertEqual(self.head, reconcile["control_head"])
        self.assertEqual([f"spec/domains/operating-model.spec.html:{self.spec_blob}"], reconcile["spec_blobs"])
        self.assertEqual([], reconcile["adr_blobs"])
        self.assertEqual(["status.md"], reconcile["conversation_state_refs"])
        streams = json.loads(reconcile["streams_json"])
        self.assertEqual(1, len(streams))
        self.assertEqual("TUR-1", streams[0]["linear"]["identifier"])
        self.assertEqual(exact_fingerprint(self.linear), streams[0]["linear"]["fingerprint"])
        self.assertEqual("main", streams[0]["pull_request"]["base"])
        self.assertEqual("a" * 40, streams[0]["pull_request"]["head"])
        self.assertEqual("OPEN", streams[0]["pull_request"]["state"])
        self.assertEqual("", streams[0]["pull_request"]["review"])
        self.assertEqual(
            [{"name": "conformance", "status": "COMPLETED", "outcome": "SUCCESS"}],
            streams[0]["pull_request"]["status_checks"],
        )
        self.assertIn("launch_revision", receipt)
        self.assertEqual(launch_revision(receipt), receipt["launch_revision"])

    def test_stale_linear_input_fails_before_worktree_or_provider(self) -> None:
        changed_linear = dict(self.linear, state="In Progress")
        with self.assertRaisesRegex(GateError, "stale Linear input"):
            self.prepare(read_linear=lambda _issue: changed_linear)
        self.assertFalse(self.worktree.exists())

    def test_stale_pr_input_fails_before_worktree_or_provider(self) -> None:
        changed_pull = dict(self.pull, headRefOid="b" * 40)
        with self.assertRaisesRegex(GateError, "stale PR input"):
            self.prepare(read_pr=lambda _repo, _number: changed_pull)
        self.assertFalse(self.worktree.exists())

    def test_head_race_between_snapshot_capture_and_gateway_fails_before_worktree_or_provider(self) -> None:
        # expected_head is the target HEAD the sweep captured while building the
        # snapshot; a value that no longer matches the repo's actual current HEAD
        # simulates a commit landing on the target between snapshot capture and
        # gateway dispatch, and must fail before any source validation or
        # worktree creation, even though every declared blob is still valid at
        # the repo's real current HEAD.
        with self.assertRaisesRegex(GateError, "HEAD"):
            self.prepare(expected_head="f" * 40)
        self.assertFalse(self.worktree.exists())
        self.assertFalse(Path(self.temp.name, "reconcile.toml").exists())

    def test_stale_spec_blob_fails_before_worktree_or_provider(self) -> None:
        with self.assertRaisesRegex(GateError, "spec blob mismatch"):
            self.prepare(spec_blobs=[f"spec/domains/operating-model.spec.html:{'0' * 40}"])
        self.assertFalse(self.worktree.exists())

    def test_empty_declared_blobs_are_allowed(self) -> None:
        prepared = self.prepare(spec_blobs=[], adr_blobs=[])
        receipt = tomllib.loads(prepared.receipt_path.read_text())
        self.assertEqual([], receipt["reconcile"]["spec_blobs"])

    def test_missing_snapshot_source_fails_before_worktree_or_provider(self) -> None:
        missing = Path(self.temp.name) / "absent-snapshot.md"
        with self.assertRaisesRegex(GateError, "snapshot source missing"):
            self.prepare(snapshot_path=missing, snapshot_digest="0" * 64)
        self.assertFalse(self.worktree.exists())

    def test_snapshot_digest_mismatch_fails_before_worktree_or_provider(self) -> None:
        with self.assertRaisesRegex(GateError, "snapshot digest mismatch"):
            self.prepare(snapshot_digest="0" * 64)
        self.assertFalse(self.worktree.exists())

    def test_substituted_snapshot_content_fails_the_originally_claimed_digest(self) -> None:
        claimed_digest = self.snapshot_digest
        self.snapshot_path.write_text("# tampered\n")
        with self.assertRaisesRegex(GateError, "snapshot digest mismatch"):
            self.prepare(snapshot_digest=claimed_digest)
        self.assertFalse(self.worktree.exists())

    def test_snapshot_source_must_be_a_regular_contained_file_not_a_symlink(self) -> None:
        outside = Path(self.temp.name) / "outside-snapshot.md"
        outside.write_text("# snapshot\n")
        link = Path(self.temp.name) / "linked-snapshot.md"
        link.symlink_to(outside)
        digest = hashlib.sha256(outside.read_bytes()).hexdigest()
        with self.assertRaisesRegex(GateError, "snapshot source must be a regular file"):
            self.prepare(snapshot_path=link, snapshot_digest=digest)
        self.assertFalse(self.worktree.exists())

    def test_snapshot_source_escaping_allowed_root_fails_closed(self) -> None:
        outside_root = tempfile.TemporaryDirectory()
        self.addCleanup(outside_root.cleanup)
        outside = Path(outside_root.name) / "outside-snapshot.md"
        outside.write_text("# snapshot\n")
        digest = hashlib.sha256(outside.read_bytes()).hexdigest()
        with self.assertRaisesRegex(GateError, "snapshot path escapes allowed root"):
            self.prepare(snapshot_path=outside, snapshot_digest=digest)
        self.assertFalse(self.worktree.exists())

    def test_receipt_persistence_failure_after_snapshot_persistence_leaves_no_final_artifact(self) -> None:
        # The gateway persists snapshot.md before receipt.toml. A caught failure
        # while persisting the receipt, injected here after the snapshot write
        # already succeeded, must not leave the final snapshot, the receipt, or
        # the now-empty sweep directory behind, and must not swallow the
        # original exception. The caller-owned pending digest-verification
        # input (self.snapshot_path here) is never this gateway's to delete, so
        # it must be left exactly as the caller supplied it.
        sweep_dir = (Path(self.temp.name) / "sweeps" / "fp1").resolve()
        receipt_path = sweep_dir / "receipt.toml"
        persisted_snapshot_path = sweep_dir / "snapshot.md"
        real_atomic_write = launch_module._atomic_write

        def flaky_atomic_write(path: Path, content: str) -> None:
            if path == receipt_path:
                raise OSError("simulated receipt persistence failure")
            real_atomic_write(path, content)

        with mock.patch.object(launch_module, "_atomic_write", side_effect=flaky_atomic_write):
            with self.assertRaisesRegex(OSError, "simulated receipt persistence failure"):
                self.prepare(receipt_path=receipt_path)

        self.assertFalse(persisted_snapshot_path.exists())
        self.assertFalse(receipt_path.exists())
        self.assertFalse(sweep_dir.exists())
        self.assertTrue(self.snapshot_path.exists())

    def test_run_reconcile_launch_is_the_sole_bootstrap_and_mutation_entry_point(self) -> None:
        prepared = self.prepare()
        spawn_id = tomllib.loads(prepared.receipt_path.read_text())["spawn_id"]
        ack = prepared.expected_ack(spawn_id)
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")
            output = {"session_id": spawn_id, "result": "changed: TUR-1 PR head moved"}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        message = run_reconcile_launch(prepared, "Classify the snapshot.", runner=runner)
        self.assertEqual("changed: TUR-1 PR head moved", message)
        self.assertEqual(2, len(calls))
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertTrue(readback["bootstrap"]["verified"])
        self.assertTrue(readback["result"]["bound"])
        self.assertFalse(self.worktree.exists())

    def test_run_reconcile_launch_fails_closed_and_preserves_a_worktree_dirtied_before_bootstrap(self) -> None:
        # A read-only reconcile worktree must stay exactly as admitted; a stray
        # mutation found before bootstrap completes now fails the whole pass
        # closed instead of letting a dirty worktree reach a bound result.
        prepared = self.prepare()
        spawn_id = tomllib.loads(prepared.receipt_path.read_text())["spawn_id"]
        ack = prepared.expected_ack(spawn_id)
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            output = {"session_id": spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        (self.worktree / "stray.txt").write_text("uncommitted diagnostic residue\n")
        with self.assertRaisesRegex(GateError, "review-pass worktree status mutated"):
            run_reconcile_launch(prepared, "Classify the snapshot.", runner=runner)
        self.assertEqual(1, len(calls))
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertNotIn("result", readback)
        self.assertTrue(self.worktree.exists())
        self.assertTrue((self.worktree / "stray.txt").is_file())

    def test_run_reconcile_launch_fails_closed_on_resumed_session_mismatch(self) -> None:
        prepared = self.prepare()
        spawn_id = tomllib.loads(prepared.receipt_path.read_text())["spawn_id"]
        ack = prepared.expected_ack(spawn_id)
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")
            output = {"session_id": "spoofed", "result": "changed"}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        with self.assertRaisesRegex(GateError, "session mismatch"):
            run_reconcile_launch(prepared, "Classify the snapshot.", runner=runner)
        readback = tomllib.loads(prepared.receipt_path.read_text())
        self.assertNotIn("result", readback)
        self.assertTrue(self.worktree.exists())


if __name__ == "__main__":
    unittest.main()
