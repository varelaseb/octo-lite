from __future__ import annotations

import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / "scripts/operator-sweep"
TIMER = ROOT / "scripts/operator-timer"
CONTROL = ROOT / "scripts/octo-control"


class OperatorControlTests(unittest.TestCase):
    def test_timer_only_wakes_current_operator_through_operator_say(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "control"
            repo = base / "repo"
            control.mkdir()
            repo.mkdir()
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            call_log = base / "systemd-run.txt"
            runner = fake_bin / "systemd-run"
            runner.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >"$CALL_LOG"\n')
            runner.chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(call_log))

            subprocess.run(
                [
                    str(TIMER), "install", "--name", "operator-1",
                    "--control-dir", str(control), "--owner-file", str(owner),
                    "--repo", str(repo),
                ],
                env=env,
                check=True,
            )

            call = call_log.read_text()
            self.assertIn("operator-say --kind info sweep", call)
            self.assertIn(f"OCTO_OPERATOR_OWNER={owner}", call)
            self.assertNotIn("operator-sweep", call)

    def test_changed_sweep_is_fresh_and_unchanged_sweep_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text("# Target\n")
            subprocess.run(["git", "-C", str(repo), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": (
                    "#!/usr/bin/env bash\n"
                    "printf 'claude %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                    "cat <<'JSON'\n"
                    '{"session_id": "reconciler-session-1", "result": "changed"}\n'
                    "JSON\n"
                ),
                "operator-say": '#!/usr/bin/env bash\nprintf \'operator %s\\n\' "$*" >>"$CALL_LOG"\n',
            }.items():
                path = fake_bin / name
                path.write_text(body)
                path.chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log))

            command = [
                str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner),
                "--repo", str(repo),
            ]
            first = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            second = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(first.stdout)["changed"])
            self.assertFalse(json.loads(second.stdout)["changed"])
            calls = log.read_text().splitlines()
            self.assertEqual(1, sum(line.startswith("claude ") for line in calls))
            self.assertEqual(1, sum(line.startswith("operator ") for line in calls))
            self.assertIn("--model claude-sonnet-5", calls[0])
            self.assertIn("--agent reconciler", calls[0])
            with (control / "sweep-state.toml").open("rb") as handle:
                self.assertEqual("operator-1", tomllib.load(handle)["owner_session"])

    def test_result_bind_produces_exact_output_binding_for_verified_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            receipt = base / "launch.toml"
            receipt.write_text(
                'schema_version = 1\nspawn_id = "spawn-1"\nready = true\n\n'
                '[role]\nname = "implementer"\n\n[bootstrap]\nverified = true\n'
                'provider_session_id = "provider-1"\n'
            )
            result_file = base / "result.json"
            result_file.write_text(json.dumps({"head": "def", "receipt": "spawn-1"}))
            command = subprocess.run(
                [str(CONTROL), "result-bind", "--receipt", str(receipt), "--role", "implementer", "--result", str(result_file)],
                check=True,
                capture_output=True,
                text=True,
            )
            output = json.loads(command.stdout)
            self.assertRegex(output["binding"], r"^[0-9a-f]{64}$")
            with receipt.open("rb") as handle:
                self.assertEqual(output["binding"], tomllib.load(handle)["result"]["binding"])

            wrong_role = subprocess.run(
                [str(CONTROL), "result-bind", "--receipt", str(receipt), "--role", "code-reviewer", "--result", str(result_file)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, wrong_role.returncode)

    def test_bootstrap_ack_durably_verifies_persistent_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            receipt = Path(td) / "launch.toml"
            receipt.write_text(
                'schema_version = 1\nspawn_id = "operator-1"\nready = true\n\n'
                '[role]\nname = "meta-operator"\n\n[bootstrap]\nverified = false\n'
                'provider_session_id = ""\n'
            )
            result = subprocess.run(
                [str(CONTROL), "bootstrap-ack", "--receipt", str(receipt), "--provider-session-id", "provider-1"],
                check=True,
                capture_output=True,
                text=True,
            )
            output = json.loads(result.stdout)
            self.assertTrue(output["verified"])
            with receipt.open("rb") as handle:
                self.assertTrue(tomllib.load(handle)["bootstrap"]["verified"])

            missing = subprocess.run(
                [str(CONTROL), "bootstrap-ack", "--receipt", str(receipt), "--provider-session-id", ""],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, missing.returncode)

    def test_sweep_refetches_declared_linear_and_pr_facts_with_verified_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text("# Target\n")
            subprocess.run(["git", "-C", str(repo), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            stream = control / "streams/TUR-1"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text(
                "Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n"
            )
            (stream / "sources.toml").write_text(
                'schema_version = 1\n\n[linear]\nissue = "TUR-1"\n\n'
                '[pull_request]\nrepo = "org/repo"\nnumber = 6\n'
            )
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            linear_state_file = base / "linear-state.txt"
            linear_state_file.write_text("Todo")
            (fake_bin / "claude").write_text(
                "#!/usr/bin/env bash\n"
                "printf 'claude %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                "cat <<'JSON'\n"
                '{"session_id": "reconciler-session-1", "result": "changed"}\n'
                "JSON\n"
            )
            (fake_bin / "operator-say").write_text(
                "#!/usr/bin/env bash\nprintf 'operator %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            )
            (fake_bin / "linear").write_text(
                "#!/usr/bin/env bash\n"
                "printf 'linear %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                'state="$(cat "$LINEAR_STATE_FILE")"\n'
                "cat <<JSON\n"
                '{"identifier": "TUR-1", "state": {"name": "$state"}, "updatedAt": "2026-07-19T00:00:00Z"}\n'
                "JSON\n"
            )
            (fake_bin / "gh").write_text(
                "#!/usr/bin/env bash\n"
                "printf 'gh %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                "cat <<'JSON'\n"
                '{"headRefOid": "abc123", "state": "OPEN", "reviewDecision": "", "statusCheckRollup": []}\n'
                "JSON\n"
            )
            for name in ("claude", "operator-say", "linear", "gh"):
                (fake_bin / name).chmod(0o755)
            env = dict(
                os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
                LINEAR_STATE_FILE=str(linear_state_file),
            )

            command = [
                str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo),
            ]
            first = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(first.stdout)["changed"])
            calls = log.read_text().splitlines()
            self.assertTrue(any(line.startswith("linear ") for line in calls))
            self.assertTrue(any(line.startswith("gh ") for line in calls))

            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            with open(state["receipt"], "rb") as handle:
                receipt = tomllib.load(handle)
            self.assertTrue(receipt["bootstrap"]["verified"])
            self.assertEqual("reconciler-session-1", receipt["bootstrap"]["provider_session_id"])

            second = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertFalse(json.loads(second.stdout)["changed"])

            log.write_text("")
            linear_state_file.write_text("In Progress")
            third = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(third.stdout)["changed"])

    def test_linear_transition_rejects_wrong_caller_before_any_linear_call(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="TUR-1", parent_session="epic-opus", child_session="issue-opus",
                caller="epic-opus", brief="Build it.\n",
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            (fake_bin / "linear").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "linear").chmod(0o755)
            (fake_bin / "herdr-say").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "herdr-say").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")

            result = subprocess.run(
                [
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", "Todo", "--target", "In Progress",
                    "--progress", str(base / "progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "epic-opus", "--outcome", "started", "--gate", "implement",
                    "--caller", "wrong-session", "--stream", str(stream),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("caller", result.stderr.lower())

    def test_linear_transition_accepts_exact_stream_owner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="TUR-1", parent_session="epic-opus", child_session="issue-opus",
                caller="epic-opus", brief="Build it.\n",
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            state_file = base / "linear-state.txt"
            state_file.write_text("Todo")
            (fake_bin / "linear").write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "$1 $2" == "issue view" ]]; then\n'
                '  state="$(cat "$STATE_FILE")"\n'
                "  cat <<JSON\n"
                '{"identifier": "TUR-1", "state": {"name": "$state"}, "updatedAt": "t1"}\n'
                "JSON\n"
                'elif [[ "$1 $2" == "issue update" ]]; then\n'
                '  echo -n "In Progress" >"$STATE_FILE"\n'
                "fi\n"
            )
            (fake_bin / "linear").chmod(0o755)
            (fake_bin / "herdr-say").write_text("#!/usr/bin/env bash\nexit 0\n")
            (fake_bin / "herdr-say").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", STATE_FILE=str(state_file))

            result = subprocess.run(
                [
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", "Todo", "--target", "In Progress",
                    "--progress", str(base / "progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "epic-opus", "--outcome", "started", "--gate", "implement",
                    "--caller", "issue-opus", "--stream", str(stream),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("In Progress", state_file.read_text())

    def test_owner_transfer_requires_durable_successor_readiness_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            owner = base / "operator-owner.toml"
            owner.write_text(
                'schema_version = 1\nowner_session = "old"\nhandoff_revision = 1\ncontrol_dir = "/control"\n'
            )
            handoff = base / "handoffs" / "0002.md"
            handoff.parent.mkdir()
            handoff.write_text("ready\n")

            wrong_ready = subprocess.run(
                [
                    str(CONTROL), "successor-ready", "--path", str(base / "ready.toml"),
                    "--caller", "someone-else", "--session-id", "new", "--handoff-revision", "2",
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, wrong_ready.returncode)

            right_ready = subprocess.run(
                [
                    str(CONTROL), "successor-ready", "--path", str(base / "ready.toml"),
                    "--caller", "new", "--session-id", "new", "--handoff-revision", "2",
                ],
                check=True, capture_output=True, text=True,
            )
            self.assertTrue(json.loads(right_ready.stdout)["session_id"] == "new")

            transfer = subprocess.run(
                [
                    str(CONTROL), "owner-transfer", "--owner-file", str(owner),
                    "--expected-owner", "old", "--caller", "old", "--new-owner", "new",
                    "--revision", "2", "--control-dir", "/control", "--handoff", str(handoff),
                    "--successor-readiness", str(base / "ready.toml"),
                ],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual("new", json.loads(transfer.stdout)["owner_session"])

    def test_acceptance_record_never_infers_and_verifies_operator_caller(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            owner = base / "operator-owner.toml"
            owner.write_text(
                'schema_version = 1\nowner_session = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "/control"\n'
            )
            record_path = base / "acceptance.toml"

            wrong_caller = subprocess.run(
                [
                    str(CONTROL), "accept", "--path", str(record_path), "--owner-file", str(owner),
                    "--caller", "not-the-operator", "--issue", "TUR-1", "--pr", "https://example.test/pr/1",
                    "--head", "abc", "--verdict-reference", "https://example.test/pr/1#c1", "--decision", "accept",
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, wrong_caller.returncode)
            self.assertFalse(record_path.exists())

            invalid_decision = subprocess.run(
                [
                    str(CONTROL), "accept", "--path", str(record_path), "--owner-file", str(owner),
                    "--caller", "operator-1", "--issue", "TUR-1", "--pr", "https://example.test/pr/1",
                    "--head", "abc", "--verdict-reference", "https://example.test/pr/1#c1", "--decision", "maybe",
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, invalid_decision.returncode)

            accepted = subprocess.run(
                [
                    str(CONTROL), "accept", "--path", str(record_path), "--owner-file", str(owner),
                    "--caller", "operator-1", "--issue", "TUR-1", "--pr", "https://example.test/pr/1",
                    "--head", "abc", "--verdict-reference", "https://example.test/pr/1#c1", "--decision", "accept",
                ],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual("accept", json.loads(accepted.stdout)["decision"])
            with record_path.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("abc", stored["head"])
            self.assertEqual("operator-1", stored["decided_by"])

    def test_sweep_rejects_wrong_control_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "control"
            control.mkdir()
            owner = base / "operator-owner.toml"
            owner.write_text(
                'schema_version = 1\nowner_session = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "/wrong"\n'
            )
            result = subprocess.run(
                [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(base)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
