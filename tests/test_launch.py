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
    bind_reconcile_workflow_journal,
    bind_reconcile_workflow_result,
    bootstrap_from_receipt,
    fetch_stream_binding,
    prepare_reconcile_launch,
    read_pull_request,
    render_receipt,
    run_reconcile_launch,
    verify_bootstrap,
    verify_reconcile_workflow_ack,
    verify_relay_verbatim,
)
from octo_lite.runtime import exact_fingerprint, launch_revision, verdict_body


ROOT = Path(__file__).resolve().parents[1]


def openai_provider_output(session_id: str, message: dict) -> str:
    lines = [
        json.dumps({"type": "thread.started", "thread_id": session_id}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(message)}}),
    ]
    return "\n".join(lines)


def write_codex_rollout(
    codex_home: Path,
    session_id: str,
    *,
    model: str,
    effort: str,
    provider: str = "openai",
    final_message: str | None = None,
) -> None:
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "19"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rollout = sessions_dir / f"rollout-2026-07-19T00-00-00-{session_id}.jsonl"
    lines = [
        json.dumps({"type": "session_meta", "payload": {"session_id": session_id, "model_provider": provider}}),
        json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort}}),
    ]
    if final_message is not None:
        lines.append(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": final_message}],
                    },
                }
            )
        )
    rollout.write_text("\n".join(lines) + "\n")


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


class PersistentReceiptRevalidationTests(unittest.TestCase):
    # Unit K (launch-entrypoint-revalidation, launch-receipt-manifest-shapes,
    # launch-receipt-persistent): the retained persistent-session bootstrap
    # revalidates the receipt's manifest shape (generic persistent, role
    # meta-operator or orchestrator, no pass purpose, no retired shaping or
    # reconcile table) and launch revision immediately after receipt readback
    # and before any provider process starts, and again before any ready or
    # bootstrap-verified mutation, so a stale, malformed, role-substituted, or
    # purpose-injected persistent receipt starts no provider.

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "AGENTS.md").write_text("# Target\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.role_repo = base / "role-src"
        subprocess.run(["git", "init", "-q", str(self.role_repo)], check=True)
        (self.role_repo / "roles").mkdir()
        for role in ("meta-operator", "orchestrator", "implementer"):
            (self.role_repo / "roles" / f"{role}.md").write_text(f"# {role}\nContract.\n")
        self.receipt_path = base / "persistent.toml"
        self.spawn_id = str(uuid.uuid4())

    def _persistent_receipt(self, role: str = "orchestrator") -> dict:
        contract_path = f"roles/{role}.md"
        blob = subprocess.run(
            ["git", "-C", str(self.role_repo), "hash-object", "--no-filters", contract_path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        instructions_blob = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "AGENTS.md"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        receipt = {
            "schema_version": 1,
            "spawn_id": self.spawn_id,
            "parent": "meta-operator",
            "reply_route": "herdr:meta-operator",
            "ready": True,
            "role": {
                "name": role,
                "root": str(self.role_repo),
                "contract_path": contract_path,
                "contract_blob": blob,
                "mapping_revision": "map-1",
            },
            "runtime": {
                "provider": "anthropic", "model": "claude-sonnet-5", "effort": "xhigh",
                "mode": "auto", "session": "persistent", "service_tier": "default",
                "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "Skill"],
            },
            "skills": {"resolved": [], "matched_capabilities": [], "paths": [], "blobs": []},
            "workspace": {
                "repo": str(self.repo), "worktree": str(self.repo),
                "starting_head": self.head, "instructions_path": "AGENTS.md",
                "instructions_blob": instructions_blob,
            },
            "access": {
                "execution_location": "remote", "operator_loopback": False,
                "review_delivery": "reachable_url_required",
            },
            "bootstrap": {"verified": False, "provider_session_id": ""},
        }
        receipt["launch_revision"] = launch_revision(receipt)
        return receipt

    def _write(self, receipt: dict) -> None:
        self.receipt_path.write_text(render_receipt(receipt))

    def _ack(self, receipt: dict) -> dict:
        return {
            "schema_version": 1,
            "spawn_id": receipt["spawn_id"],
            "provider_session_id": receipt["spawn_id"],
            "launch_revision": receipt["launch_revision"],
            "role": receipt["role"]["name"],
            "worktree": receipt["workspace"]["worktree"],
            "starting_head": receipt["workspace"]["starting_head"],
            "ready": True,
            "blocker": "",
        }

    def _recording_runner(self, receipt: dict):
        ack = self._ack(receipt)
        calls: list[list[str]] = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            output = {"session_id": receipt["spawn_id"], "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        return runner, calls

    def test_purpose_injected_persistent_receipt_starts_no_provider(self) -> None:
        # The injector recomputes launch_revision so only the manifest-shape
        # check can catch the injected pass purpose.
        receipt = self._persistent_receipt()
        receipt["purpose"] = "delivery"
        receipt["launch_revision"] = launch_revision(receipt)
        self._write(receipt)
        runner, calls = self._recording_runner(receipt)
        with self.assertRaisesRegex(GateError, "no pass purpose"):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertEqual([], calls)
        readback = tomllib.loads(self.receipt_path.read_text())
        self.assertFalse(readback["bootstrap"]["verified"])

    def test_retired_shaping_or_reconcile_table_on_persistent_receipt_starts_no_provider(self) -> None:
        for table, values in (
            ("shaping", {"repo": "org/repo", "pr": 6, "head": "a" * 40}),
            ("reconcile", {"snapshot_path": "snapshot.json"}),
        ):
            with self.subTest(table=table):
                receipt = self._persistent_receipt()
                receipt[table] = values
                receipt["launch_revision"] = launch_revision(receipt)
                self._write(receipt)
                runner, calls = self._recording_runner(receipt)
                with self.assertRaisesRegex(GateError, f"retired {table} table"):
                    bootstrap_from_receipt(self.receipt_path, runner=runner)
                self.assertEqual([], calls)

    def test_role_substituted_persistent_receipt_starts_no_provider(self) -> None:
        receipt = self._persistent_receipt(role="implementer")
        self._write(receipt)
        runner, calls = self._recording_runner(receipt)
        with self.assertRaisesRegex(GateError, "meta-operator or orchestrator"):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertEqual([], calls)

    def test_stale_launch_revision_starts_no_provider(self) -> None:
        receipt = self._persistent_receipt()
        receipt["reply_route"] = "herdr:substituted-parent"
        self._write(receipt)
        runner, calls = self._recording_runner(receipt)
        with self.assertRaisesRegex(GateError, "revision mismatch"):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertEqual([], calls)

    def test_verify_bootstrap_rejects_invalid_persistent_receipt_before_ready_mutation(self) -> None:
        purpose_injected = self._persistent_receipt()
        purpose_injected["purpose"] = "delivery"
        purpose_injected["launch_revision"] = launch_revision(purpose_injected)
        role_substituted = self._persistent_receipt(role="implementer")
        stale = self._persistent_receipt()
        stale["reply_route"] = "herdr:substituted-parent"
        for label, receipt in (
            ("purpose-injected", purpose_injected),
            ("role-substituted", role_substituted),
            ("stale-revision", stale),
        ):
            with self.subTest(label=label):
                self._write(receipt)
                before = self.receipt_path.read_text()
                with self.assertRaises(GateError):
                    verify_bootstrap(self.receipt_path, self._ack(receipt))
                self.assertEqual(before, self.receipt_path.read_text())

    def test_valid_persistent_receipt_still_bootstraps(self) -> None:
        for role in ("orchestrator", "meta-operator"):
            with self.subTest(role=role):
                receipt = self._persistent_receipt(role=role)
                self._write(receipt)
                runner, calls = self._recording_runner(receipt)
                session = bootstrap_from_receipt(self.receipt_path, runner=runner)
                self.assertEqual(receipt["spawn_id"], session)
                self.assertEqual(1, len(calls))
                readback = tomllib.loads(self.receipt_path.read_text())
                self.assertTrue(readback["ready"])
                self.assertTrue(readback["bootstrap"]["verified"])

    def test_retired_octo_lite_pass_manifest_is_rejected_and_starts_no_provider(self) -> None:
        # TUR-447 F4a (decision-109-workflow-native, launch-receipt-manifest-shapes):
        # the worker-pass launcher is retired, so the durable octo-lite-pass receipt
        # shape it wrote is no longer an admitted manifest_type. A receipt presenting
        # manifest_type "octo-lite-pass" is rejected by revalidate_launch_receipt and
        # never reaches the provider runner, while the generic persistent receipt
        # (empty manifest_type) still bootstraps (Unit K intact).
        receipt = self._persistent_receipt()
        receipt["manifest_type"] = "octo-lite-pass"
        receipt["launch_revision"] = launch_revision(receipt)
        with self.assertRaisesRegex(GateError, "unknown launch receipt manifest type"):
            launch_module.revalidate_launch_receipt(receipt)
        self._write(receipt)
        runner, calls = self._recording_runner(receipt)
        with self.assertRaises(GateError):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertEqual([], calls)


class BootstrapReverifyTests(unittest.TestCase):
    # TUR-447 d2 (launch-bootstrap-reverify-idempotent,
    # launch-entrypoint-revalidation): a receipt already marked
    # bootstrap.verified=true with a recorded provider session is accepted
    # idempotently on the re-verify path, re-confirming the SAME recorded provider
    # session and acknowledgment facts, never forced through a fresh full
    # --session-id create the real provider refuses as a duplicate session.
    # The stub runner emulates that real provider refusal exactly.

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "AGENTS.md").write_text("# Target\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.role_repo = base / "role-src"
        subprocess.run(["git", "init", "-q", str(self.role_repo)], check=True)
        (self.role_repo / "roles").mkdir()
        (self.role_repo / "roles" / "orchestrator.md").write_text("# orchestrator\nContract.\n")
        self.receipt_path = base / "persistent.toml"
        self.spawn_id = str(uuid.uuid4())

    def _verified_receipt(self) -> dict:
        contract_path = "roles/orchestrator.md"
        blob = subprocess.run(
            ["git", "-C", str(self.role_repo), "hash-object", "--no-filters", contract_path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        instructions_blob = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "AGENTS.md"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        receipt = {
            "schema_version": 1,
            "spawn_id": self.spawn_id,
            "parent": "meta-operator",
            "reply_route": "herdr:meta-operator",
            "ready": True,
            "role": {
                "name": "orchestrator",
                "root": str(self.role_repo),
                "contract_path": contract_path,
                "contract_blob": blob,
                "mapping_revision": "map-1",
            },
            "runtime": {
                "provider": "anthropic", "model": "claude-sonnet-5", "effort": "xhigh",
                "mode": "auto", "session": "persistent", "service_tier": "default",
                "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "Skill"],
            },
            "skills": {"resolved": [], "matched_capabilities": [], "paths": [], "blobs": []},
            "workspace": {
                "repo": str(self.repo), "worktree": str(self.repo),
                "starting_head": self.head, "instructions_path": "AGENTS.md",
                "instructions_blob": instructions_blob,
            },
            "access": {
                "execution_location": "remote", "operator_loopback": False,
                "review_delivery": "reachable_url_required",
            },
            # The receipt is ALREADY bootstrap-verified with its recorded provider
            # session: the exact shape the re-verify path receives.
            "bootstrap": {"verified": True, "provider_session_id": self.spawn_id},
        }
        receipt["launch_revision"] = launch_revision(receipt)
        return receipt

    def _write(self, receipt: dict) -> None:
        self.receipt_path.write_text(render_receipt(receipt))

    def _ack(self, receipt: dict) -> dict:
        return {
            "schema_version": 1,
            "spawn_id": receipt["spawn_id"],
            "provider_session_id": receipt["spawn_id"],
            "launch_revision": receipt["launch_revision"],
            "role": receipt["role"]["name"],
            "worktree": receipt["workspace"]["worktree"],
            "starting_head": receipt["workspace"]["starting_head"],
            "ready": True,
            "blocker": "",
        }

    def _provider_faithful_runner(self, receipt: dict, ack_overrides: dict | None = None):
        # Emulates the REAL provider: a fresh --session-id create for an existing
        # session is refused as a duplicate; a --resume of the recorded session
        # answers with the bound acknowledgment facts.
        ack = self._ack(receipt)
        ack.update(ack_overrides or {})
        calls: list[list[str]] = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            if "--session-id" in argv:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="",
                    stderr=f"Error: Session ID {receipt['spawn_id']} is already in use.",
                )
            output = {"session_id": receipt["spawn_id"], "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        return runner, calls

    def test_bootstrap_reverify_accepts_already_verified_receipt(self) -> None:
        receipt = self._verified_receipt()
        self._write(receipt)
        runner, calls = self._provider_faithful_runner(receipt)

        session = bootstrap_from_receipt(self.receipt_path, runner=runner)

        self.assertEqual(self.spawn_id, session)
        # Idempotent re-verify: exactly one provider call, resuming the SAME
        # recorded session, never a forced fresh full session resolve.
        self.assertEqual(1, len(calls))
        self.assertNotIn("--session-id", calls[0])
        self.assertIn("--resume", calls[0])
        self.assertIn(self.spawn_id, calls[0])
        readback = tomllib.loads(self.receipt_path.read_text())
        self.assertTrue(readback["ready"])
        self.assertTrue(readback["bootstrap"]["verified"])
        self.assertEqual(self.spawn_id, readback["bootstrap"]["provider_session_id"])

    def test_bootstrap_reverify_still_revalidates(self) -> None:
        # A tampered already-verified receipt is still rejected before any
        # provider call (launch-entrypoint-revalidation is NOT weakened).
        tampered = self._verified_receipt()
        tampered["reply_route"] = "herdr:substituted-parent"
        self._write(tampered)
        runner, calls = self._provider_faithful_runner(tampered)
        with self.assertRaisesRegex(GateError, "revision mismatch"):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertEqual([], calls)

        # The acknowledgment facts are still re-checked on the re-verify path: a
        # session whose echo reports a different starting head never re-verifies,
        # and the durable receipt is left byte-identical.
        receipt = self._verified_receipt()
        self._write(receipt)
        runner, calls = self._provider_faithful_runner(receipt, {"starting_head": "f" * 40})
        before = self.receipt_path.read_text()
        with self.assertRaises(GateError):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertEqual(before, self.receipt_path.read_text())


class BootstrapInconsistentStateTests(unittest.TestCase):
    # TUR-447 cycle-2 P1-1 (launch-bootstrap-reverify-idempotent,
    # workspace-cleanup-clean-abort): a receipt claiming bootstrap.verified=true
    # with a MISSING or BLANK provider_session_id is INCONSISTENT, the exact
    # partially-written shape a crashed prior run leaves behind. It must be
    # rejected fail-closed BEFORE any provider invocation, never misclassified
    # as FRESH into a duplicate-refused new session, and a verified=true
    # receipt's previously-verified worktree is NEVER clean-abort-removed on a
    # later failed attempt, even though a matching host-provision record owns it.

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.repo = base / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "AGENTS.md").write_text("# Target\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        # The session's PREVIOUSLY-VERIFIED worktree: a genuine worktree of the
        # bound repo, pristine at the exact starting head, with a fully matching
        # host-provision record beside it, so the clean-abort path WOULD remove
        # it if (wrongly) authorized.
        self.worktree_root = base / "worktrees"
        self.worktree_root.mkdir()
        self.worktree = self.worktree_root / "lane-1"
        subprocess.run(
            [
                "git", "-C", str(self.repo), "worktree", "add", "-q",
                "-b", "octo-lite/lane-1", str(self.worktree), self.head,
            ],
            check=True, capture_output=True, text=True,
        )
        records_dir = self.worktree_root / ".octo-provisions"
        records_dir.mkdir()
        self.record_path = records_dir / "lane-1.json"
        self.record_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": "host-provisioned-worktree",
                    "lane": "lane-1",
                    "control_repo": str(self.repo),
                    "worktree": str(self.worktree),
                    "worktree_root": str(self.worktree_root),
                    "repo_slug": "acme/target",
                    "branch": "octo-lite/lane-1",
                    "starting_head": self.head,
                    "resolver_root": str(self.worktree),
                    "install_check": "clean",
                    "provisioned_at": "2026-07-21T00:00:00+00:00",
                },
                indent=2,
            )
            + "\n"
        )
        env_patch = mock.patch.dict(os.environ)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop("OCTO_PROVISION_RECORD", None)
        self.role_repo = base / "role-src"
        subprocess.run(["git", "init", "-q", str(self.role_repo)], check=True)
        (self.role_repo / "roles").mkdir()
        (self.role_repo / "roles" / "orchestrator.md").write_text("# orchestrator\nContract.\n")
        self.receipt_path = base / "persistent.toml"
        self.spawn_id = str(uuid.uuid4())

    def _receipt(self, bootstrap: dict) -> dict:
        contract_path = "roles/orchestrator.md"
        blob = subprocess.run(
            ["git", "-C", str(self.role_repo), "hash-object", "--no-filters", contract_path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        instructions_blob = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "AGENTS.md"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        receipt = {
            "schema_version": 1,
            "spawn_id": self.spawn_id,
            "parent": "meta-operator",
            "reply_route": "herdr:meta-operator",
            "ready": True,
            "role": {
                "name": "orchestrator",
                "root": str(self.role_repo),
                "contract_path": contract_path,
                "contract_blob": blob,
                "mapping_revision": "map-1",
            },
            "runtime": {
                "provider": "anthropic", "model": "claude-sonnet-5", "effort": "xhigh",
                "mode": "auto", "session": "persistent", "service_tier": "default",
                "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "Skill"],
            },
            "skills": {"resolved": [], "matched_capabilities": [], "paths": [], "blobs": []},
            "workspace": {
                "repo": str(self.repo), "worktree": str(self.worktree),
                "starting_head": self.head, "instructions_path": "AGENTS.md",
                "instructions_blob": instructions_blob,
            },
            "access": {
                "execution_location": "remote", "operator_loopback": False,
                "review_delivery": "reachable_url_required",
            },
            "bootstrap": dict(bootstrap),
        }
        receipt["launch_revision"] = launch_revision(receipt)
        return receipt

    def _write(self, receipt: dict) -> None:
        self.receipt_path.write_text(render_receipt(receipt))

    def _duplicate_refusal_runner(self):
        # Emulates the REAL provider refusing a fresh create for an existing
        # session: the exact duplicate-refusal the misclassified FRESH path hits.
        calls: list[list[str]] = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(
                argv, 1, stdout="",
                stderr=f"Error: Session ID {self.spawn_id} is already in use.",
            )

        return runner, calls

    def _worktree_listed(self) -> bool:
        listing = subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "list", "--porcelain"],
            check=True, capture_output=True, text=True,
        ).stdout
        return f"worktree {self.worktree}" in listing

    def test_inconsistent_verified_blank_session_rejected_before_provider(self) -> None:
        # P1-1a: verified=true with a BLANK provider_session_id is rejected
        # fail-closed BEFORE any provider argv runs: no fresh-session attempt,
        # no duplicate refusal, and no cleanup removal.
        receipt = self._receipt({"verified": True, "provider_session_id": ""})
        self._write(receipt)
        runner, calls = self._duplicate_refusal_runner()
        with self.assertRaisesRegex(GateError, "inconsistent bootstrap state"):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertEqual([], calls, "provider was invoked despite inconsistent bootstrap state")
        self.assertTrue(self.worktree.is_dir(), "previously-verified worktree was removed")
        self.assertTrue(self._worktree_listed(), "previously-verified worktree unregistered")

    def test_prior_verified_receipt_never_clean_abort_removed(self) -> None:
        # P1-1b: ANY failure path on a receipt claiming prior verification
        # preserves the worktree for inspection. First the missing-key
        # crashed-run shape: provider_session_id absent entirely.
        receipt = self._receipt({"verified": True})
        self._write(receipt)
        runner, calls = self._duplicate_refusal_runner()
        with self.assertRaises(GateError):
            bootstrap_from_receipt(self.receipt_path, runner=runner)
        self.assertTrue(
            self.worktree.is_dir(),
            "previously-verified worktree clean-abort-removed (missing session key)",
        )
        self.assertTrue(self._worktree_listed(), "previously-verified worktree unregistered")

        # Then a genuine re-verify FAILURE (recorded session, acknowledgment
        # fact mismatch after the provider answered) also preserves it.
        receipt = self._receipt({"verified": True, "provider_session_id": self.spawn_id})
        self._write(receipt)
        ack = {
            "schema_version": 1,
            "spawn_id": receipt["spawn_id"],
            "provider_session_id": self.spawn_id,
            "launch_revision": receipt["launch_revision"],
            "role": "orchestrator",
            "worktree": str(self.worktree),
            "starting_head": "f" * 40,
            "ready": True,
            "blocker": "",
        }

        def reverify_runner(argv, **kwargs):
            output = {"session_id": self.spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        with self.assertRaises(GateError):
            bootstrap_from_receipt(self.receipt_path, runner=reverify_runner)
        self.assertTrue(
            self.worktree.is_dir(),
            "re-verify failure removed the previously-verified worktree",
        )


class RetiredWorkerPassLauncherTests(unittest.TestCase):
    # TUR-447 F4a (decision-109-workflow-native, role-worker-migration,
    # launch-correctness-path): the octo-launch worker-pass launcher is retired.
    # The Claude Workflow subagent path (Unit G) is the sole WORKER spawn
    # mechanism, so the prepare-and-run worker-pass functions no longer exist and
    # the octo-launch CLI no longer prepares or runs a worker pass.
    def test_worker_pass_launch_functions_no_longer_exist(self) -> None:
        for name in ("prepare_launch", "run_launch", "mutation_prompt"):
            self.assertFalse(
                hasattr(launch_module, name),
                f"retired worker-pass symbol still present: {name}",
            )

    def test_octo_launch_cli_no_longer_prepares_or_runs_a_worker_pass(self) -> None:
        result = subprocess.run(
            [str(ROOT / "scripts" / "octo-launch"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        # The advertised subcommand set no longer includes the worker-pass
        # prepare/launch commands; only the retained persistent bootstrap surface.
        self.assertIn("{bootstrap,verify}", result.stdout)
        # The retired worker-pass subcommands are not invocable.
        for sub in ("prepare", "launch"):
            rejected = subprocess.run(
                [str(ROOT / "scripts" / "octo-launch"), sub, "--receipt", "x"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("invalid choice", rejected.stderr)


class ReconcileLaunchBoundaryTests(unittest.TestCase):
    # Unit I (role-worker-migration, decision-109-workflow-native,
    # launch-receipt-manifest-shapes, role-reconciler-snapshot-receipt-binding,
    # workspace-cleanup-reconcile): the reconcile gateway binds through a plain
    # JSON journal entry under the sweep dir, never a reconcile receipt.toml.
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
        self.snapshot_path = base / "pending-snapshot.md"
        self.snapshot_path.write_text("# snapshot\n")
        self.snapshot_digest = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        self.sweep_dir = base / "sweeps" / "fp1"
        self.journal_path = self.sweep_dir / "journal.json"

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    def read_journal(self) -> dict:
        return json.loads(self.journal_path.read_text())

    def prepare(self, **overrides):
        values = {
            "root": ROOT,
            "spawn_id": str(uuid.uuid4()),
            "parent": "operator-1",
            "reply_route": "operator-say",
            "repo": self.repo,
            "worktree_root": self.worktree_root,
            "worktree": self.worktree,
            "journal_path": self.journal_path,
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
        journal = json.loads(prepared.journal_path.read_text())
        self.assertNotEqual(str(self.repo), journal["workspace"]["worktree"])
        self.assertEqual(str(self.worktree), journal["workspace"]["worktree"])
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
        self.assertTrue(journal["workspace"]["child_containment_verified"])

    def test_reconcile_worktree_escaping_allowed_root_fails_closed(self) -> None:
        outside = Path(self.temp.name) / "outside"
        with self.assertRaisesRegex(GateError, "escapes allowed root"):
            self.prepare(worktree=outside)

    def test_journal_binds_snapshot_digest_spec_and_adr_blobs_control_head_and_stream_facts(self) -> None:
        # role-reconciler-snapshot-receipt-binding plus launch-receipt-manifest-shapes:
        # the journal entry carries the exact bindings and no reconcile receipt.toml
        # exists anywhere under the sweep dir.
        prepared = self.prepare()
        journal = self.read_journal()
        self.assertEqual("worker-journal", journal["manifest_shape"])
        self.assertEqual("reconcile", journal["purpose"])
        self.assertIs(True, journal["read_restricted"])
        self.assertEqual("reconciler", journal["role"]["name"])
        reconcile = journal["reconcile"]
        self.assertEqual(self.snapshot_digest, reconcile["snapshot_digest"])
        self.assertEqual(str(self.sweep_dir / "snapshot.md"), reconcile["snapshot_path"])
        self.assertEqual(self.head, reconcile["control_head"])
        self.assertEqual([f"spec/domains/operating-model.spec.html:{self.spec_blob}"], reconcile["spec_blobs"])
        self.assertEqual([], reconcile["adr_blobs"])
        self.assertEqual(["status.md"], reconcile["conversation_state_refs"])
        streams = reconcile["streams"]
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
        self.assertIn("launch_revision", journal)
        self.assertFalse((self.sweep_dir / "receipt.toml").exists())
        self.assertEqual([], list(self.sweep_dir.glob("*.toml")))
        self.assertEqual(prepared.journal_path, self.journal_path.resolve())

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
        self.assertFalse(self.journal_path.exists())
        self.assertFalse(self.sweep_dir.exists())

    def test_stale_spec_blob_fails_before_worktree_or_provider(self) -> None:
        with self.assertRaisesRegex(GateError, "spec blob mismatch"):
            self.prepare(spec_blobs=[f"spec/domains/operating-model.spec.html:{'0' * 40}"])
        self.assertFalse(self.worktree.exists())

    def test_empty_declared_blobs_are_allowed(self) -> None:
        self.prepare(spec_blobs=[], adr_blobs=[])
        self.assertEqual([], self.read_journal()["reconcile"]["spec_blobs"])

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

    def test_journal_persistence_failure_after_snapshot_persistence_leaves_no_final_artifact(self) -> None:
        # The gateway persists snapshot.md before journal.json. A caught failure
        # while persisting the journal, injected here after the snapshot write
        # already succeeded, must not leave the final snapshot, the journal, a
        # receipt, or the now-empty sweep directory behind, and must not swallow
        # the original exception. The caller-owned pending digest-verification
        # input (self.snapshot_path here) is never this gateway's to delete, so
        # it must be left exactly as the caller supplied it.
        journal_path = self.journal_path.resolve()
        persisted_snapshot_path = journal_path.parent / "snapshot.md"
        real_atomic_write = launch_module._atomic_write

        def flaky_atomic_write(path: Path, content: str) -> None:
            if path == journal_path:
                raise OSError("simulated journal persistence failure")
            real_atomic_write(path, content)

        with mock.patch.object(launch_module, "_atomic_write", side_effect=flaky_atomic_write):
            with self.assertRaisesRegex(OSError, "simulated journal persistence failure"):
                self.prepare(journal_path=journal_path)

        self.assertFalse(persisted_snapshot_path.exists())
        self.assertFalse(journal_path.exists())
        self.assertFalse((journal_path.parent / "receipt.toml").exists())
        self.assertFalse(journal_path.parent.exists())
        self.assertTrue(self.snapshot_path.exists())

    def test_run_reconcile_launch_is_the_sole_bootstrap_and_mutation_entry_point(self) -> None:
        prepared = self.prepare()
        spawn_id = self.read_journal()["spawn_id"]
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
        readback = self.read_journal()
        self.assertTrue(readback["bootstrap"]["verified"])
        self.assertTrue(readback["result"]["bound"])
        self.assertFalse(self.worktree.exists())
        self.assertFalse((self.sweep_dir / "receipt.toml").exists())

    def test_bootstrap_ack_fails_closed_when_journal_bound_snapshot_digest_mismatches(self) -> None:
        # role-reconciler-snapshot-receipt-binding: the acknowledgment echo carries
        # the journal-bound snapshot path and digest; an honest reconciler that
        # hashes corrupted persisted snapshot bytes echoes the actual digest and a
        # non-ready blocker, and the host rejects the mismatch before any judgment
        # call. The pre-ack failure removes the still-pristine worktree.
        prepared = self.prepare()
        journal = self.read_journal()
        spawn_id = journal["spawn_id"]
        persisted = Path(journal["reconcile"]["snapshot_path"])
        persisted.write_text("# corrupted after journal persistence\n")
        actual_digest = hashlib.sha256(persisted.read_bytes()).hexdigest()
        ack = prepared.expected_ack(spawn_id)
        ack["snapshot_digest"] = actual_digest
        ack["ready"] = False
        ack["blocker"] = "journal-bound snapshot digest mismatch"
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            output = {"session_id": spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        with self.assertRaisesRegex(GateError, "acknowledgment mismatch.*snapshot_digest"):
            run_reconcile_launch(prepared, "Classify the snapshot.", runner=runner)
        self.assertEqual(1, len(calls))
        self.assertNotIn("result", self.read_journal())
        self.assertFalse(self.worktree.exists())

    def test_presenting_a_retired_reconcile_receipt_shape_is_rejected(self) -> None:
        # launch-receipt-manifest-shapes: the old octo-lite-reconcile receipt shape
        # is rejected wherever presented, before any provider call.
        prepared = self.prepare()
        prepared.journal_path.write_text(
            'schema_version = 1\nspawn_id = "spawn-1"\nready = false\n'
            'manifest_type = "octo-lite-reconcile"\nlaunch_revision = "abc"\n\n'
            '[role]\nname = "reconciler"\n\n'
            f'[reconcile]\nsnapshot_path = "{self.sweep_dir / "snapshot.md"}"\n'
            f'snapshot_digest = "{self.snapshot_digest}"\n'
        )
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            raise AssertionError("no provider call may follow a retired receipt shape")

        with self.assertRaisesRegex(GateError, "retired reconcile receipt shape rejected"):
            run_reconcile_launch(prepared, "Classify the snapshot.", runner=runner)
        self.assertEqual(0, len(calls))
        with self.assertRaisesRegex(GateError, "retired reconcile receipt shape rejected"):
            launch_module.load_reconcile_journal(prepared.journal_path)

    def test_reconcile_cleanup_keys_on_the_durably_persisted_journal_entry(self) -> None:
        # workspace-cleanup-reconcile: the completed worktree is removed only after
        # the journal entry with its bound result is durably persisted; a journal
        # that vanished before result binding fails closed and preserves the
        # worktree for inspection.
        prepared = self.prepare()
        spawn_id = self.read_journal()["spawn_id"]
        ack = prepared.expected_ack(spawn_id)
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")
            prepared.journal_path.unlink()
            output = {"session_id": spawn_id, "result": "changed"}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        with self.assertRaisesRegex(GateError, "reconcile journal missing"):
            run_reconcile_launch(prepared, "Classify the snapshot.", runner=runner)
        self.assertEqual(2, len(calls))
        self.assertTrue(self.worktree.exists())

    def test_run_reconcile_launch_fails_closed_and_preserves_a_worktree_dirtied_before_bootstrap(self) -> None:
        # A read-only reconcile worktree must stay exactly as admitted; a stray
        # mutation found before bootstrap completes now fails the whole pass
        # closed instead of letting a dirty worktree reach a bound result.
        prepared = self.prepare()
        spawn_id = self.read_journal()["spawn_id"]
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
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())
        self.assertTrue((self.worktree / "stray.txt").is_file())

    def test_run_reconcile_launch_fails_closed_on_resumed_session_mismatch(self) -> None:
        prepared = self.prepare()
        spawn_id = self.read_journal()["spawn_id"]
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
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())


class ReconcileWorkflowSubagentTests(unittest.TestCase):
    """TUR-447 F4b-A Unit I: the NEW reconciler-as-Workflow-subagent entry point
    (role-worker-migration, role-claude-native, decision-109-workflow-native).

    The reconciler migrates to a Read-restricted Claude Workflow subagent spawned
    through the loop's agent() mechanism, not the provider-argv subprocess path. Its
    durable journal entry binds the final persisted snapshot path, bytes, and digest
    BEFORE the spawn (role-reconciler-snapshot-receipt-binding), it writes NO reconcile
    TOML receipt (launch-receipt-manifest-shapes), and the reconcile worktree cleanup
    keys on the durable journal entry (workspace-cleanup-reconcile). The retired
    octo-lite-reconcile receipt shape is rejected. The prior behavior proofs are
    preserved: snapshot integrity, PR-fact fingerprinting, and needs_fable escalation
    (role-reconciler-escalation)."""

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
        self.snapshot_path = base / "pending-snapshot.md"
        self.snapshot_path.write_text("# snapshot\n")
        self.snapshot_digest = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        self.sweep_dir = base / "sweeps" / "fp1"
        self.journal_path = self.sweep_dir / "journal.json"

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    def read_journal(self) -> dict:
        return json.loads(self.journal_path.read_text())

    def bind(self, **overrides):
        values = {
            "root": ROOT,
            "spawn_id": str(uuid.uuid4()),
            "parent": "operator-1",
            "reply_route": "operator-say",
            "repo": self.repo,
            "worktree_root": self.worktree_root,
            "worktree": self.worktree,
            "journal_path": self.journal_path,
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
        return bind_reconcile_workflow_journal(**values)

    def workflow_ack(self, prepared) -> dict:
        journal = self.read_journal()
        return {
            "schema_version": journal["schema_version"],
            "spawn_id": journal["spawn_id"],
            "launch_revision": journal["launch_revision"],
            "role": "reconciler",
            "worktree": journal["workspace"]["worktree"],
            "starting_head": journal["workspace"]["starting_head"],
            "snapshot_path": journal["reconcile"]["snapshot_path"],
            "snapshot_digest": journal["reconcile"]["snapshot_digest"],
            "ready": True,
            "blocker": "",
        }

    # RED 1: the new entry point binds the snapshot path+bytes+digest in the journal
    # BEFORE spawn, keyed to the final persisted snapshot.md, not a provider-argv path.
    def test_workflow_journal_binds_snapshot_path_bytes_and_digest_before_spawn(self) -> None:
        prepared = self.bind()
        journal = self.read_journal()
        self.assertEqual("worker-journal", journal["manifest_shape"])
        self.assertEqual("reconcile", journal["purpose"])
        self.assertIs(True, journal["read_restricted"])
        self.assertEqual("reconciler", journal["role"]["name"])
        reconcile = journal["reconcile"]
        persisted = Path(reconcile["snapshot_path"])
        self.assertEqual(str(self.sweep_dir / "snapshot.md"), reconcile["snapshot_path"])
        self.assertTrue(persisted.is_file())
        self.assertEqual("# snapshot\n", persisted.read_text())
        self.assertEqual(self.snapshot_digest, hashlib.sha256(persisted.read_bytes()).hexdigest())
        self.assertEqual(self.snapshot_digest, reconcile["snapshot_digest"])
        self.assertEqual(self.head, reconcile["control_head"])
        # The Workflow-native prepared shape carries the journal binding for the loop's
        # agent() spawn; it carries no provider-argv, because agent() spawns the subagent.
        self.assertEqual(self.journal_path.resolve(), prepared.journal_path)
        self.assertFalse(hasattr(prepared, "bootstrap_argv"))

    # RED 2: the new entry point writes NO reconcile TOML receipt.
    def test_workflow_entry_point_writes_no_reconcile_toml_receipt(self) -> None:
        self.bind()
        self.assertFalse((self.sweep_dir / "receipt.toml").exists())
        self.assertEqual([], list(self.sweep_dir.glob("*.toml")))
        self.assertTrue(self.journal_path.exists())

    # RED 3: reconcile worktree cleanup keys on the durable journal entry; a journal
    # that vanished before result binding fails closed and preserves the worktree.
    def test_workflow_cleanup_keys_on_the_durable_journal_entry(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        self.assertTrue(self.worktree.exists())
        # Result binding + cleanup requires the durable journal entry, not a receipt.
        bind_reconcile_workflow_result(prepared.journal_path, self._classified(prepared))
        bound = self.read_journal()
        self.assertTrue(bound["result"]["bound"])
        self.assertEqual("changed", bound["result"]["classification"])
        self.assertFalse(self.worktree.exists())

    def test_workflow_cleanup_fails_closed_when_journal_vanished(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        classified = self._classified(prepared)
        prepared.journal_path.unlink()
        with self.assertRaisesRegex(GateError, "reconcile journal missing"):
            bind_reconcile_workflow_result(prepared.journal_path, classified)
        self.assertTrue(self.worktree.exists())

    # RED 4: the new path rejects the retired octo-lite-reconcile receipt shape.
    def test_workflow_path_rejects_the_retired_reconcile_receipt_shape(self) -> None:
        prepared = self.bind()
        ack = self.workflow_ack(prepared)
        prepared.journal_path.write_text(
            'schema_version = 1\nspawn_id = "spawn-1"\nready = false\n'
            'manifest_type = "octo-lite-reconcile"\nlaunch_revision = "abc"\n\n'
            '[role]\nname = "reconciler"\n\n'
            f'[reconcile]\nsnapshot_path = "{self.sweep_dir / "snapshot.md"}"\n'
            f'snapshot_digest = "{self.snapshot_digest}"\n'
        )
        with self.assertRaisesRegex(GateError, "retired reconcile receipt shape rejected"):
            verify_reconcile_workflow_ack(prepared.journal_path, ack)
        with self.assertRaisesRegex(GateError, "retired reconcile receipt shape rejected"):
            bind_reconcile_workflow_result(
                prepared.journal_path, {"classification": "changed", "needs_fable": False, "deltas": []},
            )

    # RED 5a (behavior proof: snapshot integrity): a digest-mismatched snapshot fails
    # closed before any journal, worktree, or subagent spawn under the new path too.
    def test_workflow_preserves_snapshot_integrity_proof(self) -> None:
        with self.assertRaisesRegex(GateError, "snapshot digest mismatch"):
            self.bind(snapshot_digest="0" * 64)
        self.assertFalse(self.worktree.exists())
        self.assertFalse(self.journal_path.exists())

    # RED 5b (behavior proof: PR-fact fingerprinting): a stale declared PR fact fails
    # closed before any spawn; the bound streams carry the normalized PR facts so a
    # change in any of them would change the snapshot fingerprint.
    def test_workflow_preserves_pr_fact_fingerprinting_proof(self) -> None:
        changed_pull = dict(self.pull, headRefOid="b" * 40)
        with self.assertRaisesRegex(GateError, "stale PR input"):
            self.bind(read_pr=lambda _repo, _number: changed_pull)
        self.assertFalse(self.worktree.exists())
        prepared = self.bind()
        pr = self.read_journal()["reconcile"]["streams"][0]["pull_request"]
        self.assertEqual("a" * 40, pr["head"])
        self.assertEqual("main", pr["base"])
        self.assertEqual("OPEN", pr["state"])
        self.assertEqual(
            [{"name": "conformance", "status": "COMPLETED", "outcome": "SUCCESS"}], pr["status_checks"],
        )
        del prepared

    # RED 5c (behavior proof: needs_fable escalation): the reconciler's classification
    # can escalate to Fable on missing, unparseable, or ambiguous input, and that
    # escalation binds durably into the journal result (role-reconciler-escalation).
    def test_workflow_binds_needs_fable_escalation(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        bind_reconcile_workflow_result(
            prepared.journal_path,
            self._classified(
                prepared, classification="needs_fable", needs_fable=True,
                deltas=["ambiguous: TUR-1 contradictory state"],
            ),
        )
        bound = self.read_journal()
        self.assertTrue(bound["result"]["bound"])
        self.assertTrue(bound["result"]["needs_fable"])
        self.assertEqual("needs_fable", bound["result"]["classification"])
        # An escalated pass is a completed, journal-bound read-only sweep, so its worktree
        # is still cleaned up keyed on the durable journal entry.
        self.assertFalse(self.worktree.exists())

    # The subagent snapshot-proof echo (role-reconciler-bootstrap-snapshot-proof): a
    # mismatched journal-bound snapshot digest in the ack fails closed before any result.
    def test_workflow_ack_fails_closed_on_snapshot_digest_mismatch(self) -> None:
        prepared = self.bind()
        ack = self.workflow_ack(prepared)
        ack["snapshot_digest"] = "0" * 64
        with self.assertRaisesRegex(GateError, "snapshot_digest"):
            verify_reconcile_workflow_ack(prepared.journal_path, ack)
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())

    # TUR-447 cycle1 pass3 reconcile binding (role-reconciler-snapshot-receipt-binding,
    # role-reconciler-snapshot-integrity, role-reconciler-authority). The gpt-5.6-sol high
    # finding: the Python binder accepted ANY nonempty classification once bootstrap was
    # marked verified, without checking the acknowledgment, the snapshot digest, the enum,
    # or needs_fable consistency. The binder now cross-checks the reconciler classification
    # against the durable journal-bound snapshot proof before it binds.
    def _classified(self, prepared, **overrides) -> dict:
        # A genuine classifier re-echoes the verified ack (which carries the journal-bound
        # snapshot_path + snapshot_digest) alongside the classification, so the binder can
        # prove the classification came from the ack-verified, journal-bound snapshot.
        journal = self.read_journal()
        base = {
            "classification": "changed",
            "needs_fable": False,
            "deltas": ["TUR-1 PR head moved"],
            "ack": self.workflow_ack(prepared),
            "snapshot_digest": journal["reconcile"]["snapshot_digest"],
        }
        base.update(overrides)
        return base

    # RED (result must carry the ack; a MISSING/failed ack is rejected, ack not discarded).
    def test_result_binding_rejects_a_classification_with_no_verified_ack(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        classified = self._classified(prepared)
        del classified["ack"]
        with self.assertRaisesRegex(GateError, "reconcile result ack"):
            bind_reconcile_workflow_result(prepared.journal_path, classified)
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())

    def test_result_binding_rejects_a_classification_whose_ack_snapshot_digest_mismatches(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        bad_ack = self.workflow_ack(prepared)
        bad_ack["snapshot_digest"] = "0" * 64
        classified = self._classified(prepared, ack=bad_ack, snapshot_digest="0" * 64)
        with self.assertRaisesRegex(GateError, "snapshot_digest"):
            bind_reconcile_workflow_result(prepared.journal_path, classified)
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())

    def test_result_binding_rejects_a_classification_whose_result_digest_mismatches_the_journal(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        # The ack is intact but the result's own snapshot_digest field disagrees with the
        # journal-bound digest: the classification is not bound to the verified snapshot.
        classified = self._classified(prepared, snapshot_digest="0" * 64)
        with self.assertRaisesRegex(GateError, "snapshot_digest"):
            bind_reconcile_workflow_result(prepared.journal_path, classified)
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())

    def test_result_binding_rejects_a_non_enum_classification(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        classified = self._classified(prepared, classification="fabricated")
        with self.assertRaisesRegex(GateError, "reconcile classification"):
            bind_reconcile_workflow_result(prepared.journal_path, classified)
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())

    def test_result_binding_rejects_needs_fable_inconsistent_with_classification(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        # classification says needs_fable but the needs_fable flag is false: inconsistent.
        classified = self._classified(prepared, classification="needs_fable", needs_fable=False)
        with self.assertRaisesRegex(GateError, "needs_fable"):
            bind_reconcile_workflow_result(prepared.journal_path, classified)
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())

    def test_result_binding_accepts_a_genuine_ack_verified_digest_matching_enum_valid_classification(self) -> None:
        prepared = self.bind()
        verify_reconcile_workflow_ack(prepared.journal_path, self.workflow_ack(prepared))
        result = bind_reconcile_workflow_result(prepared.journal_path, self._classified(prepared))
        self.assertTrue(result["bound"])
        self.assertEqual("changed", result["classification"])
        self.assertFalse(result["needs_fable"])
        bound = self.read_journal()
        self.assertTrue(bound["result"]["bound"])
        self.assertEqual("changed", bound["result"]["classification"])
        self.assertFalse(self.worktree.exists())

    def test_result_binding_still_fails_closed_before_ack_verification(self) -> None:
        # Even a perfectly-shaped classification with a matching digest must not bind if the
        # journal bootstrap was never verified (ack never enforced).
        prepared = self.bind()
        with self.assertRaisesRegex(GateError, "bootstrap not verified"):
            bind_reconcile_workflow_result(prepared.journal_path, self._classified(prepared))
        self.assertNotIn("result", self.read_journal())
        self.assertTrue(self.worktree.exists())


class RelayVerbatimTests(unittest.TestCase):
    """Unit C: relay-verbatim proof from codex's OWN rollout record under CODEX_HOME/sessions.

    Spec: role-openai-relay, role-openai-fail-closed, decision-identity-source. The
    independent verifier never consults relay-supplied artifacts; provenance is the
    rollout record alone."""

    MODEL = "gpt-5.6-sol"
    EFFORT = "high"
    MESSAGE = '{"verdict": "clear", "head": "' + "a" * 40 + '"}'

    def _home(self, td: str, session_id: str, **overrides) -> Path:
        codex_home = Path(td)
        write_codex_rollout(
            codex_home,
            session_id,
            model=overrides.get("model", self.MODEL),
            effort=overrides.get("effort", self.EFFORT),
            provider=overrides.get("provider", "openai"),
            final_message=overrides.get("final_message", self.MESSAGE),
        )
        return codex_home

    def _sha(self, payload: str) -> str:
        return hashlib.sha256(payload.encode()).hexdigest()

    def test_relay_verbatim_accepts_exact_rollout_derived_payload(self) -> None:
        session_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as td:
            codex_home = self._home(td, session_id)
            proven = verify_relay_verbatim(
                session_id, self.MESSAGE, self._sha(self.MESSAGE), self.MODEL, self.EFFORT, codex_home=codex_home
            )
        self.assertEqual("openai", proven["provider"])
        self.assertEqual(self.MODEL, proven["model"])
        self.assertEqual(self.EFFORT, proven["effort"])
        self.assertEqual(self.MESSAGE, proven["final_message"])

    def test_relay_verbatim_rejects_relay_edited_payload(self) -> None:
        # A relay that authors or edits prose fails because the rollout-derived message differs.
        session_id = str(uuid.uuid4())
        edited = self.MESSAGE.replace("clear", "blocking")
        with tempfile.TemporaryDirectory() as td:
            codex_home = self._home(td, session_id)
            with self.assertRaisesRegex(GateError, "payload mismatch"):
                verify_relay_verbatim(
                    session_id, edited, self._sha(edited), self.MODEL, self.EFFORT, codex_home=codex_home
                )

    def test_relay_verbatim_rejects_claimed_hash_not_matching_claimed_payload(self) -> None:
        session_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as td:
            codex_home = self._home(td, session_id)
            with self.assertRaisesRegex(GateError, "payload mismatch"):
                verify_relay_verbatim(
                    session_id, self.MESSAGE, self._sha("tampered"), self.MODEL, self.EFFORT, codex_home=codex_home
                )

    def test_relay_verbatim_fails_closed_without_a_resolvable_rollout_record(self) -> None:
        # A session id without a resolvable rollout record fails closed; relay-persisted
        # artifacts alone are explicitly insufficient.
        session_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(GateError, "no rollout session file"):
                verify_relay_verbatim(
                    session_id, self.MESSAGE, self._sha(self.MESSAGE), self.MODEL, self.EFFORT, codex_home=Path(td)
                )

    def test_relay_verbatim_rejects_model_mismatch(self) -> None:
        session_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as td:
            codex_home = self._home(td, session_id, model="gpt-4.1-mini")
            with self.assertRaisesRegex(GateError, "model"):
                verify_relay_verbatim(
                    session_id, self.MESSAGE, self._sha(self.MESSAGE), self.MODEL, self.EFFORT, codex_home=codex_home
                )

    def test_relay_verbatim_rejects_effort_mismatch(self) -> None:
        session_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as td:
            codex_home = self._home(td, session_id, effort="low")
            with self.assertRaisesRegex(GateError, "effort"):
                verify_relay_verbatim(
                    session_id, self.MESSAGE, self._sha(self.MESSAGE), self.MODEL, self.EFFORT, codex_home=codex_home
                )

    def test_relay_verbatim_rejects_provider_substitution(self) -> None:
        # A rollout record from any provider other than the exact OpenAI runtime is rejected.
        session_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as td:
            codex_home = self._home(td, session_id, provider="anthropic")
            with self.assertRaisesRegex(GateError, "provider"):
                verify_relay_verbatim(
                    session_id, self.MESSAGE, self._sha(self.MESSAGE), self.MODEL, self.EFFORT, codex_home=codex_home
                )

    def test_relay_verbatim_fails_closed_when_rollout_record_has_no_assistant_message(self) -> None:
        session_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as td:
            codex_home = self._home(td, session_id, final_message=None)
            with self.assertRaisesRegex(GateError, "final assistant message"):
                verify_relay_verbatim(
                    session_id, self.MESSAGE, self._sha(self.MESSAGE), self.MODEL, self.EFFORT, codex_home=codex_home
                )


class ReconcileInstanceBindingTests(unittest.TestCase):
    # TUR-447 c4 F1b (workspace-cleanup-clean-abort, workspace-cleanup-reconcile):
    # the reconcile gateway's ownership-free deletion bypass (the retired
    # gateway_provisioned boolean) is gone. The gateway stamps octo.instanceId
    # into the worktree it creates at a required-absent path, records that
    # instance id in its journal, and EVERY reconcile cleanup verifies the LIVE
    # worktree stamp equals the journal-recorded id before removal; a wrong or
    # missing stamp preserves. A stale reusable journal replayed against a
    # hand-recreated worktree at the same path can therefore never remove it.

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
        self.head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.spec_blob = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "spec/domains/operating-model.spec.html"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.linear = {"identifier": "TUR-1", "state": "Todo", "updatedAt": "2026-07-19T00:00:00Z"}
        self.pull = {
            "url": "https://github.com/org/repo/pull/6",
            "headRefOid": "a" * 40,
            "headRefName": "feature",
            "baseRefName": "main",
            "state": "OPEN",
            "reviewDecision": "",
            "statusCheckRollup": [],
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
        self.snapshot_path = base / "pending-snapshot.md"
        self.snapshot_path.write_text("# snapshot\n")
        self.snapshot_digest = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        self.sweep_dir = base / "sweeps" / "fp1"
        self.journal_path = self.sweep_dir / "journal.json"

    def prepare(self, **overrides):
        values = {
            "root": ROOT,
            "spawn_id": str(uuid.uuid4()),
            "parent": "operator-1",
            "reply_route": "operator-say",
            "repo": self.repo,
            "worktree_root": self.worktree_root,
            "worktree": self.worktree,
            "journal_path": self.journal_path,
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

    def read_stamp(self, worktree: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(worktree), "config", "--worktree", "--get", "octo.instanceId"],
            capture_output=True, text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def run_pass(self, prepared, journal_path: Path) -> str:
        journal = json.loads(journal_path.read_text())
        spawn_id = journal["spawn_id"]
        ack = prepared.expected_ack(spawn_id)
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            if len(calls) == 1:
                output = {"session_id": spawn_id, "result": json.dumps({"BOOTSTRAP_ACK": ack})}
            else:
                output = {"session_id": spawn_id, "result": "unchanged"}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(output), stderr="")

        return run_reconcile_launch(prepared, "Classify the snapshot.", runner=runner)

    def test_reconcile_cleanup_requires_instance_match(self) -> None:
        # The prepare stamps the created worktree with the journal-recorded
        # instance id; a LIVE stamp overwritten to a DIFFERENT id (a foreign
        # provision instance at the same path) preserves the worktree even
        # though the pass itself completes and binds its result.
        prepared = self.prepare()
        journal = json.loads(self.journal_path.read_text())
        instance_id = journal["workspace"]["provision_instance_id"]
        uuid.UUID(instance_id)
        self.assertEqual(instance_id, self.read_stamp(self.worktree))
        subprocess.run(
            ["git", "-C", str(self.worktree), "config", "--worktree", "octo.instanceId", str(uuid.uuid4())],
            check=True, capture_output=True, text=True,
        )

        message = self.run_pass(prepared, self.journal_path)
        self.assertEqual("unchanged", message)
        self.assertTrue(self.worktree.is_dir(), "mismatched instance stamp must preserve the worktree")

        # A MISSING live stamp (unset before cleanup) equally preserves.
        worktree2 = self.worktree_root / "sweep-2"
        journal_path2 = Path(self.temp.name) / "sweeps" / "fp2" / "journal.json"
        prepared2 = self.prepare(worktree=worktree2, journal_path=journal_path2)
        subprocess.run(
            ["git", "-C", str(worktree2), "config", "--worktree", "--unset", "octo.instanceId"],
            check=True, capture_output=True, text=True,
        )
        message2 = self.run_pass(prepared2, journal_path2)
        self.assertEqual("unchanged", message2)
        self.assertTrue(worktree2.is_dir(), "missing instance stamp must preserve the worktree")

        # With the MATCHING stamp left intact, the legit path still removes.
        worktree3 = self.worktree_root / "sweep-3"
        journal_path3 = Path(self.temp.name) / "sweeps" / "fp3" / "journal.json"
        prepared3 = self.prepare(worktree=worktree3, journal_path=journal_path3)
        message3 = self.run_pass(prepared3, journal_path3)
        self.assertEqual("unchanged", message3)
        self.assertFalse(worktree3.exists(), "matching instance stamp must still allow removal")

    def test_stale_journal_replay_preserves_foreign_worktree(self) -> None:
        # A completed reconcile removed its own worktree, but its journal (with
        # result bound) remains reusable on disk. Replaying cleanup from that
        # stale journal against a hand-recreated worktree at the same path,
        # detached at the same control head and clean, must PRESERVE it: the
        # recreation carries no instance stamp.
        prepared = self.prepare()
        message = self.run_pass(prepared, self.journal_path)
        self.assertEqual("unchanged", message)
        self.assertFalse(self.worktree.exists(), "completed reconcile removes its own worktree")
        bound = json.loads(self.journal_path.read_text())
        self.assertIs(True, bound["result"]["bound"], "stale-journal precondition: result bound")

        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "--detach", str(self.worktree), self.head],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual("", self.read_stamp(self.worktree))

        launch_module._cleanup_reconcile_worktree(self.journal_path)

        self.assertTrue(self.worktree.is_dir(), "stale journal replay removed a recreated foreign worktree")


if __name__ == "__main__":
    unittest.main()
