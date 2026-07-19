import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from octo_lite.runtime import (
    FAILURE_CATEGORIES,
    GateError,
    admit_workspace,
    append_trace,
    exact_fingerprint,
    herdr_label,
    normalize_launch_access,
    record_failure,
    safe_cleanup,
    initialize_stream,
    update_stream_brief,
    write_stream_status,
    transfer_owner,
    transition_linear,
    verdict_body,
)


class RuntimeContractTests(unittest.TestCase):
    def test_remote_access_defaults_closed(self):
        self.assertEqual(
            normalize_launch_access({}),
            {
                "execution_location": "unknown",
                "operator_loopback_access": False,
                "review_delivery": "reachable_url_required",
            },
        )
        with self.assertRaises(GateError):
            normalize_launch_access(
                {
                    "execution_location": "remote",
                    "operator_loopback_access": False,
                    "review_delivery": "loopback_allowed",
                }
            )

    def test_exact_fingerprint_ignores_mapping_order(self):
        self.assertEqual(
            exact_fingerprint({"state": "Todo", "id": "TUR-1"}),
            exact_fingerprint({"id": "TUR-1", "state": "Todo"}),
        )

    def test_owner_transfer_is_compare_and_swap(self):
        with tempfile.TemporaryDirectory() as td:
            owner = Path(td) / "operator-owner.toml"
            owner.write_text(
                'schema_version = 1\nowner_session = "old"\nhandoff_revision = 1\ncontrol_dir = "/control"\n'
            )
            handoff = Path(td) / "handoffs" / "0002.md"
            handoff.parent.mkdir()
            handoff.write_text("ready\n")
            transfer_owner(
                owner,
                "old",
                "new",
                2,
                "/control",
                caller="old",
                handoff=handoff,
                successor_ready=True,
            )
            current = owner.read_text()
            self.assertIn('owner_session = "new"', current)
            self.assertIn("handoff_revision = 2", current)
            with self.assertRaises(GateError):
                transfer_owner(
                    owner,
                    "old",
                    "other",
                    3,
                    "/control",
                    caller="old",
                    handoff=handoff,
                    successor_ready=True,
                )
            self.assertEqual(current, owner.read_text())

    def test_parent_owns_brief_and_child_owns_status(self):
        with tempfile.TemporaryDirectory() as td:
            stream = Path(td) / "streams/TUR-1"
            initialized = initialize_stream(
                stream,
                stream_id="TUR-1",
                parent_session="epic-opus",
                child_session="issue-opus",
                caller="epic-opus",
                brief="Build the shaped issue.\n",
            )
            self.assertEqual(1, initialized["brief_revision"])
            with self.assertRaises(GateError):
                update_stream_brief(stream, caller="issue-opus", expected_revision=1, brief="wrong\n")
            updated = update_stream_brief(
                stream, caller="epic-opus", expected_revision=1, brief="Build exact HEAD.\n"
            )
            self.assertEqual(2, updated["brief_revision"])
            status = write_stream_status(
                stream,
                caller="issue-opus",
                expected_revision=0,
                outcome="implementation ready",
                gate="code review",
                blocker="none",
                next_operator_action="none",
            )
            self.assertEqual(1, status["status_revision"])
            self.assertEqual(
                [
                    "Outcome: implementation ready",
                    "Gate: code review",
                    "Blocker: none",
                    "Next operator action: none",
                ],
                (stream / "status.md").read_text().splitlines(),
            )
            with self.assertRaises(GateError):
                write_stream_status(
                    stream,
                    caller="epic-opus",
                    expected_revision=1,
                    outcome="wrong writer",
                    gate="review",
                    blocker="none",
                    next_operator_action="none",
                )

    def test_transition_retry_does_not_repeat_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            progress = Path(td) / "transition.toml"
            calls = []
            state = {"value": "Todo"}
            notify_attempts = {"count": 0}

            def read():
                return {"identifier": "TUR-1", "state": state["value"]}

            def mutate(target):
                calls.append(("mutate", target))
                state["value"] = target

            def status(_issue):
                calls.append(("status", state["value"]))

            def notify(_issue):
                notify_attempts["count"] += 1
                if notify_attempts["count"] == 1:
                    raise RuntimeError("recipient unavailable")
                calls.append(("notify", state["value"]))

            with self.assertRaises(RuntimeError):
                transition_linear(
                    "TUR-1", "Todo", "In Progress", progress, read, mutate, status, notify
                )
            transition_linear(
                "TUR-1", "Todo", "In Progress", progress, read, mutate, status, notify
            )
            self.assertEqual(1, calls.count(("mutate", "In Progress")))
            self.assertEqual(1, calls.count(("status", "In Progress")))
            self.assertEqual(1, calls.count(("notify", "In Progress")))

    def test_failure_record_accepts_only_five_categories(self):
        self.assertEqual(5, len(FAILURE_CATEGORIES))
        record = record_failure(2, "boom", "environment", "commit abc", "opus", "retry")
        self.assertEqual("environment", record["category"])
        with self.assertRaises(GateError):
            record_failure(2, "boom", "timeout", "", "opus", "retry")

    def test_trace_rejects_payloads_and_degrades_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "trace.jsonl"
            status = Path(td) / "status.md"
            event = {
                "schema_version": 1,
                "session_id": "stream-1",
                "trace_id": "TUR-1@abc",
                "observation_id": "review-1",
                "kind": "verdict",
                "status": "clear",
                "time": "2026-07-18T00:00:00Z",
                "attributes": {"issue": "TUR-1", "head": "abc"},
                "artifacts": ["https://example.test/pr/1#comment"],
            }
            self.assertTrue(append_trace(trace, status, event))
            self.assertEqual(event, json.loads(trace.read_text()))
            bad = dict(event, raw_prompt="secret")
            with self.assertRaises(GateError):
                append_trace(trace, status, bad)
            blocked_parent = Path(td) / "not-a-dir"
            blocked_parent.write_text("x")
            self.assertFalse(append_trace(blocked_parent / "trace.jsonl", status, event))
            self.assertIn("trace degraded", status.read_text())

    def test_cleanup_preserves_dirty_or_unpushed_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "a").write_text("one\n")
            subprocess.run(["git", "-C", str(repo), "add", "a"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/pass", head], check=True
            )
            handoff = repo / ".handoff"
            handoff.write_text("done\n")
            subprocess.run(["git", "-C", str(repo), "add", ".handoff"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "handoff"], check=True)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/pass", head], check=True
            )
            (repo / "a").write_text("dirty\n")
            with self.assertRaises(GateError):
                safe_cleanup(repo, handoff=handoff, expected_head=head, remote_ref="origin/pass", remove=lambda _p: None)
            subprocess.run(["git", "-C", str(repo), "restore", "a"], check=True)
            with self.assertRaises(GateError):
                safe_cleanup(repo, handoff=handoff, expected_head=head, remote_ref="origin/missing", remove=lambda _p: None)
            removed = []
            safe_cleanup(repo, handoff=handoff, expected_head=head, remote_ref="origin/pass", remove=removed.append)
            self.assertEqual([repo], removed)

    def test_workspace_admission_rejects_escape_and_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "worktrees"
            root.mkdir()
            admitted = admit_workspace(
                root / "pass-1",
                root,
                disk_free_bytes=10_000,
                minimum_free_bytes=1_000,
                conflicts=[],
                provider_overloaded=False,
            )
            self.assertEqual((root / "pass-1").resolve(), admitted)
            with self.assertRaises(GateError):
                admit_workspace(
                    Path(td) / "escape",
                    root,
                    disk_free_bytes=10_000,
                    minimum_free_bytes=1_000,
                    conflicts=[],
                    provider_overloaded=False,
                )
            with self.assertRaises(GateError):
                admit_workspace(
                    root / "pass-2",
                    root,
                    disk_free_bytes=10_000,
                    minimum_free_bytes=1_000,
                    conflicts=["fixture:user-1"],
                    provider_overloaded=False,
                )

    def test_compact_herdr_label_contract(self):
        self.assertEqual("🧠 operator", herdr_label(kind="operator"))
        self.assertEqual("◆443/6 · operating model", herdr_label(kind="epic", issue=443, pr=6, outcome="operating model"))
        self.assertEqual("🎤 446/6 · modal messaging", herdr_label(kind="issue", issue=446, pr=6, outcome="modal messaging", direct=True))
        with self.assertRaises(GateError):
            herdr_label(kind="worker", issue=446, outcome="fix")

    def test_verdict_comment_is_exact_and_machine_readable(self):
        body = verdict_body(
            review_type="shaping",
            verdict="clear",
            head="abc",
            bound_inputs=["linear:123", "spec:456"],
            findings=[],
            receipt="session:reviewer",
        )
        self.assertIn("<!-- octo-lite-verdict:shaping -->", body)
        self.assertIn('head = "abc"', body)
        self.assertIn('bound_inputs = ["linear:123", "spec:456"]', body)
        with self.assertRaises(GateError):
            verdict_body("code", "ambiguous", "abc", [], [], "r")


if __name__ == "__main__":
    unittest.main()
