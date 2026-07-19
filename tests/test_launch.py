from __future__ import annotations

import json
import subprocess
import tempfile
import tomllib
import unittest
import uuid
from pathlib import Path

from octo_lite.launch import GateError, mutation_prompt, prepare_launch, run_launch, verify_bootstrap
from octo_lite.runtime import exact_fingerprint, verdict_body


ROOT = Path(__file__).resolve().parents[1]


class LaunchBoundaryTests(unittest.TestCase):
    def test_foreground_cli_exposes_prepare_launch_and_verify(self) -> None:
        result = subprocess.run(
            [str(ROOT / "scripts" / "octo-launch"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("{prepare,launch,verify}", result.stdout)

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

    def test_delivery_purpose_still_requires_clear_verdict(self) -> None:
        envelope = dict(self.envelope, shaping_verdict="blocking")
        with self.assertRaisesRegex(GateError, "shaping verdict not clear"):
            self.prepare(envelope=envelope)

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

        def clear_runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

        run_launch(prepared, runner=clear_runner)
        self.assertEqual(2, len(calls))
        self.assertIn(self.spawn_id, calls[1])
        self.assertNotIn("--last", calls[1])


if __name__ == "__main__":
    unittest.main()
