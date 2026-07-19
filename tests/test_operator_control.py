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

# Fakes the two-phase reconciler launch: a --session-id call answers a bound
# BOOTSTRAP_ACK computed from the exact receipt on disk; a --resume call echoes
# the exact session it was resumed with in its own read-only judgment message,
# proving the resumed session is the exact bootstrap-verified one, never a
# self-attested or spoofed identity.
FAKE_RECONCILER_CLAUDE = r"""#!/usr/bin/env bash
printf 'claude %s\n' "$*" >>"$CALL_LOG"
printf 'worktree-check %s|%s|%s\n' "$(pwd)" "$(git rev-parse --show-toplevel)" "$(git branch --show-current)" >>"$CALL_LOG"
prompt="$(cat)"
if [[ "$*" == *"--resume"* ]]; then
  args=("$@")
  session=""
  for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "--resume" ]]; then
      session="${args[$((i+1))]}"
    fi
  done
  python3 -c 'import json, sys; print(json.dumps({"session_id": sys.argv[1], "result": "changed"}))' "$session"
else
  receipt_path="$(printf '%s' "$prompt" | grep -oE '/[^ ]*receipt\.toml' | head -1)"
  args=("$@")
  session=""
  for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "--session-id" ]]; then
      session="${args[$((i+1))]}"
    fi
  done
  python3 - "$receipt_path" "$session" <<'PY'
import json
import sys
import tomllib

receipt_path, session_id = sys.argv[1], sys.argv[2]
with open(receipt_path, "rb") as handle:
    receipt = tomllib.load(handle)
ack = {
    "schema_version": receipt["schema_version"],
    "spawn_id": receipt["spawn_id"],
    "provider_session_id": session_id,
    "launch_revision": receipt["launch_revision"],
    "role": receipt["role"]["name"],
    "worktree": receipt["workspace"]["worktree"],
    "starting_head": receipt["workspace"]["starting_head"],
    "ready": True,
    "blocker": "",
}
print(json.dumps({"session_id": session_id, "result": json.dumps(ack)}))
PY
fi
"""


# Same two-phase shape as FAKE_RECONCILER_CLAUDE, but the resumed judgment call
# reports a fixed spoofed session_id instead of the exact session it was resumed
# with. Proves the sweep never accepts a mutation response from an unverified
# or mismatched session, matching octo-launch's own run_launch identity check.
FAKE_RECONCILER_CLAUDE_SPOOFED_RESUME = r"""#!/usr/bin/env bash
printf 'claude %s\n' "$*" >>"$CALL_LOG"
prompt="$(cat)"
if [[ "$*" == *"--resume"* ]]; then
  cat <<'JSON'
{"session_id": "spoofed-session-not-the-resumed-one", "result": "changed"}
JSON
else
  receipt_path="$(printf '%s' "$prompt" | grep -oE '/[^ ]*receipt\.toml' | head -1)"
  args=("$@")
  session=""
  for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "--session-id" ]]; then
      session="${args[$((i+1))]}"
    fi
  done
  python3 - "$receipt_path" "$session" <<'PY'
import json
import sys
import tomllib

receipt_path, session_id = sys.argv[1], sys.argv[2]
with open(receipt_path, "rb") as handle:
    receipt = tomllib.load(handle)
ack = {
    "schema_version": receipt["schema_version"],
    "spawn_id": receipt["spawn_id"],
    "provider_session_id": session_id,
    "launch_revision": receipt["launch_revision"],
    "role": receipt["role"]["name"],
    "worktree": receipt["workspace"]["worktree"],
    "starting_head": receipt["workspace"]["starting_head"],
    "ready": True,
    "blocker": "",
}
print(json.dumps({"session_id": session_id, "result": json.dumps(ack)}))
PY
fi
"""


def _init_target_repo(
    repo: Path,
    *,
    with_canonical_sources: bool = True,
    spec_path: str = "spec/domains/operating-model.spec.html",
    adr_path: str = "spec/adr/0001-operating-model-boundaries.spec.html",
) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    if with_canonical_sources:
        (repo / "AGENTS.md").write_text(
            f"# Target\n\n- Canonical spec paths: {spec_path}\n- Canonical ADR paths: {adr_path}\n"
        )
        spec = repo / spec_path
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text('<p data-anchor="x">Works.</p>\n')
        adr = repo / adr_path
        adr.parent.mkdir(parents=True, exist_ok=True)
        adr.write_text('<p data-anchor="x">Decided.</p>\n')
    else:
        (repo / "AGENTS.md").write_text("# Target\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)


class OperatorControlTests(unittest.TestCase):
    def test_sweep_imports_only_the_shared_reconcile_gateway_never_low_level_launch_helpers(self) -> None:
        source = SWEEP.read_text()
        launch_import = next(line for line in source.splitlines() if line.startswith("from octo_lite.launch import"))
        imported = {name.strip() for name in launch_import.split("import", 1)[1].split("#")[0].split(",")}
        self.assertEqual({"fetch_stream_binding", "prepare_reconcile_launch", "run_reconcile_launch"}, imported)
        for forbidden in (
            "prepared_from_receipt", "run_bootstrap", "run_mutation",
            "build_launch_receipt", "resolve_role", "load_registry",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("worktree=repo", source)

    def test_timer_only_wakes_current_operator_through_operator_say(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "control"
            repo = base / "repo"
            control.mkdir()
            repo.mkdir()
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
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
            _init_target_repo(repo)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            claude_calls = [line for line in calls if line.startswith("claude ")]
            self.assertEqual(2, len(claude_calls))
            self.assertEqual(1, sum(line.startswith("operator ") for line in calls))
            self.assertIn("--session-id", claude_calls[0])
            self.assertIn("--resume", claude_calls[1])
            self.assertIn("--model claude-sonnet-5", claude_calls[0])
            self.assertIn("--tools Read", claude_calls[0])
            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            self.assertEqual("operator-1", state["owner_route"])
            with open(state["receipt"], "rb") as handle:
                receipt = tomllib.load(handle)
            self.assertTrue(receipt["bootstrap"]["verified"])
            self.assertTrue(receipt["result"]["bound"])

    def test_sweep_fails_closed_when_resumed_judgment_reports_a_different_session(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE_SPOOFED_RESUME,
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
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse(any((control / "sweeps").rglob("result.md")))
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("operator ") for line in calls))

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

    def test_sweep_refetches_declared_linear_and_pr_facts_with_verified_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)

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
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            linear_state_file = base / "linear-state.txt"
            linear_state_file.write_text("Todo")
            (fake_bin / "claude").write_text(FAKE_RECONCILER_CLAUDE)
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
                '{"url": "https://github.com/org/repo/pull/6", "headRefOid": "abc123", '
                '"headRefName": "feature", "baseRefName": "main", '
                '"state": "OPEN", "reviewDecision": "", "statusCheckRollup": []}\n'
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
            self.assertEqual(receipt["spawn_id"], receipt["bootstrap"]["provider_session_id"])
            self.assertTrue(receipt["result"]["bound"])

            second = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertFalse(json.loads(second.stdout)["changed"])

            log.write_text("")
            linear_state_file.write_text("In Progress")
            third = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(third.stdout)["changed"])

    def test_sweep_runs_the_reconciler_in_a_detached_worktree_never_the_control_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            subprocess.run(command, env=env, check=True, capture_output=True, text=True)

            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            with open(state["receipt"], "rb") as handle:
                receipt = tomllib.load(handle)

            # The worktree is a genuine detached checkout in worktree_root, never the
            # control checkout, while the reconciler pass runs inside it; a successful
            # pass then removes it, so its live state is captured from the fake
            # reconciler's own worktree-check log line rather than probed afterward.
            worktree = Path(receipt["workspace"]["worktree"])
            self.assertNotEqual(str(repo), receipt["workspace"]["worktree"])
            self.assertEqual(str((control / "worktrees").resolve()), str(worktree.resolve().parent))
            self.assertTrue(receipt["workspace"]["child_containment_verified"])
            checks = [line for line in log.read_text().splitlines() if line.startswith("worktree-check ")]
            self.assertTrue(checks)
            for check in checks:
                pwd, top, branch = check.removeprefix("worktree-check ").split("|")
                self.assertEqual(str(worktree.resolve()), pwd)
                self.assertEqual(str(worktree.resolve()), top)
                self.assertEqual("", branch)
            self.assertFalse(worktree.exists())

    def test_sweep_receipt_binds_snapshot_digest_control_head_and_canonical_spec_adr_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
            ).stdout.strip()
            spec_blob = subprocess.run(
                ["git", "-C", str(repo), "hash-object", "spec/domains/operating-model.spec.html"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            adr_blob = subprocess.run(
                ["git", "-C", str(repo), "hash-object", "spec/adr/0001-operating-model-boundaries.spec.html"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            fingerprint = json.loads(result.stdout)["fingerprint"]

            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            with open(state["receipt"], "rb") as handle:
                receipt = tomllib.load(handle)
            reconcile = receipt["reconcile"]
            self.assertEqual(fingerprint, reconcile["snapshot_digest"])
            self.assertEqual(head, reconcile["control_head"])
            self.assertEqual([f"spec/domains/operating-model.spec.html:{spec_blob}"], reconcile["spec_blobs"])
            self.assertEqual([f"spec/adr/0001-operating-model-boundaries.spec.html:{adr_blob}"], reconcile["adr_blobs"])
            self.assertIn("streams/TUR-1/status.md", reconcile["conversation_state_refs"])

    def test_sweep_fails_closed_when_a_declared_canonical_source_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo, with_canonical_sources=False)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "worktrees").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))
            self.assertFalse(any(line.startswith("operator ") for line in calls))

    def test_sweep_fails_closed_when_a_declared_canonical_path_is_not_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text(
                "# Target\n\n"
                "- Canonical spec paths: spec/domains/operating-model.spec.html\n"
                "- Canonical ADR paths: spec/adr/0001-operating-model-boundaries.spec.html\n"
            )
            # The declared canonical spec path resolves to a tree object, not a blob.
            bogus = repo / "spec" / "domains" / "operating-model.spec.html"
            bogus.mkdir(parents=True)
            (bogus / "inner.html").write_text("<p>not the real file</p>\n")
            adr = repo / "spec" / "adr" / "0001-operating-model-boundaries.spec.html"
            adr.parent.mkdir(parents=True)
            adr.write_text('<p data-anchor="x">Decided.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_discovers_target_owned_canonical_paths_declared_in_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(
                repo,
                spec_path="docs/behavior.spec.html",
                adr_path="docs/decisions/0001.spec.html",
            )

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(result.stdout)["changed"])

            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            with open(state["receipt"], "rb") as handle:
                receipt = tomllib.load(handle)
            reconcile = receipt["reconcile"]
            self.assertEqual(1, len(reconcile["spec_blobs"]))
            self.assertTrue(reconcile["spec_blobs"][0].startswith("docs/behavior.spec.html:"))
            self.assertEqual(1, len(reconcile["adr_blobs"]))
            self.assertTrue(reconcile["adr_blobs"][0].startswith("docs/decisions/0001.spec.html:"))

    def test_sweep_fails_closed_on_a_symlinked_canonical_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text(
                "# Target\n\n"
                "- Canonical spec paths: spec/domains/operating-model.spec.html\n"
                "- Canonical ADR paths: spec/adr/0001-operating-model-boundaries.spec.html\n"
            )
            real = repo / "spec" / "domains" / "real.spec.html"
            real.parent.mkdir(parents=True)
            real.write_text('<p data-anchor="x">Works.</p>\n')
            link = repo / "spec" / "domains" / "operating-model.spec.html"
            link.symlink_to("real.spec.html")
            adr = repo / "spec" / "adr" / "0001-operating-model-boundaries.spec.html"
            adr.parent.mkdir(parents=True)
            adr.write_text('<p data-anchor="x">Decided.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_fails_closed_on_an_empty_canonical_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text(
                "# Target\n\n"
                "- Canonical spec paths: spec/domains/operating-model.spec.html\n"
                "- Canonical ADR paths: spec/adr/0001-operating-model-boundaries.spec.html\n"
            )
            spec = repo / "spec" / "domains" / "operating-model.spec.html"
            spec.parent.mkdir(parents=True)
            spec.write_text("")
            adr = repo / "spec" / "adr" / "0001-operating-model-boundaries.spec.html"
            adr.parent.mkdir(parents=True)
            adr.write_text('<p data-anchor="x">Decided.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_fails_closed_on_duplicate_canonical_path_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text(
                "# Target\n\n"
                "- Canonical spec paths: spec/domains/operating-model.spec.html, "
                "spec/domains/operating-model.spec.html\n"
                "- Canonical ADR paths: spec/adr/0001-operating-model-boundaries.spec.html\n"
            )
            spec = repo / "spec" / "domains" / "operating-model.spec.html"
            spec.parent.mkdir(parents=True)
            spec.write_text('<p data-anchor="x">Works.</p>\n')
            adr = repo / "spec" / "adr" / "0001-operating-model-boundaries.spec.html"
            adr.parent.mkdir(parents=True)
            adr.write_text('<p data-anchor="x">Decided.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_fails_closed_on_an_escaped_canonical_path_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text(
                "# Target\n\n"
                "- Canonical spec paths: ../outside.spec.html\n"
                "- Canonical ADR paths: spec/adr/0001-operating-model-boundaries.spec.html\n"
            )
            # A valid file at octo-lite's own default spec path proves the sweep
            # honors and rejects the escaped declaration rather than coincidentally
            # falling back to a hardcoded default it never actually reads.
            decoy = repo / "spec" / "domains" / "operating-model.spec.html"
            decoy.parent.mkdir(parents=True)
            decoy.write_text('<p data-anchor="x">Works.</p>\n')
            adr = repo / "spec" / "adr" / "0001-operating-model-boundaries.spec.html"
            adr.parent.mkdir(parents=True)
            adr.write_text('<p data-anchor="x">Decided.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_detects_changed_target_head_even_when_linear_and_pr_facts_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
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
            self.assertTrue(json.loads(first.stdout)["changed"])

            # A trivial commit moves the target HEAD without touching Linear, PR,
            # stream status, or canonical spec/ADR blob content at all.
            (repo / "unrelated.txt").write_text("noise\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "unrelated"], check=True)

            second = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(second.stdout)["changed"])
            self.assertNotEqual(
                json.loads(first.stdout)["fingerprint"], json.loads(second.stdout)["fingerprint"]
            )

    def test_sweep_fails_closed_before_any_provider_call_when_linear_state_races_between_snapshot_and_gateway(self) -> None:
        # declared_stream_facts() and prepare_reconcile_launch()'s own fresh
        # re-verification each call the fake `linear` binary once for TUR-1's issue
        # view. Returning a different state on the second call simulates the exact
        # race the gateway's final source comparison must catch before any provider
        # call: a snapshot input that went stale between capture and dispatch.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)

            control = base / "control"
            stream = control / "streams/TUR-1"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text(
                "Outcome: ready\nGate: review\nBlocker: none\nNext operator action: inspect\n"
            )
            (stream / "sources.toml").write_text(
                'schema_version = 1\n\n[linear]\nissue = "TUR-1"\n'
            )
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            call_count_file = base / "linear-call-count.txt"
            call_count_file.write_text("0")
            (fake_bin / "claude").write_text(FAKE_RECONCILER_CLAUDE)
            (fake_bin / "operator-say").write_text(
                "#!/usr/bin/env bash\nprintf 'operator %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            )
            (fake_bin / "linear").write_text(
                "#!/usr/bin/env bash\n"
                "printf 'linear %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                'count="$(cat "$CALL_COUNT_FILE")"\n'
                'count=$((count + 1))\n'
                'echo -n "$count" >"$CALL_COUNT_FILE"\n'
                'if [[ "$count" -eq 1 ]]; then state="Todo"; else state="In Progress"; fi\n'
                "cat <<JSON\n"
                '{"identifier": "TUR-1", "state": {"name": "$state"}, "updatedAt": "2026-07-19T00:00:00Z"}\n'
                "JSON\n"
            )
            for name in ("claude", "operator-say", "linear"):
                (fake_bin / name).chmod(0o755)
            env = dict(
                os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
                CALL_COUNT_FILE=str(call_count_file),
            )

            command = [
                str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo),
            ]
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("stale Linear input", result.stderr)
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "worktrees").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))
            self.assertEqual(2, sum(line.startswith("linear ") for line in calls))

    def _write_receipt(self, path: Path, *, role: str, issue: str, provider_session_id: str, verified: bool = True) -> None:
        path.write_text(
            "schema_version = 1\n"
            f'spawn_id = "{provider_session_id}"\n'
            "ready = true\n\n"
            f'[role]\nname = "{role}"\n\n'
            f'[issue]\nidentifier = "{issue}"\n\n'
            "[bootstrap]\n"
            f"verified = {'true' if verified else 'false'}\n"
            f'provider_session_id = "{provider_session_id}"\n'
        )

    def test_linear_transition_allows_exact_issue_orchestrator_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            receipt = base / "receipt.toml"
            self._write_receipt(receipt, role="orchestrator", issue="TUR-1", provider_session_id="orch-session-1")
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
                    "--caller", "orch-session-1", "--receipt", str(receipt),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("In Progress", state_file.read_text())

    def test_linear_transition_denies_every_non_orchestrator_role_and_stale_or_foreign_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fake_bin = base / "bin"
            fake_bin.mkdir()
            (fake_bin / "linear").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "linear").chmod(0o755)
            (fake_bin / "herdr-say").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "herdr-say").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")

            for role in ("implementer", "qa-capture", "code-reviewer", "qa-reviewer", "reconciler"):
                receipt = base / f"{role}.toml"
                self._write_receipt(receipt, role=role, issue="TUR-1", provider_session_id=f"{role}-session")
                result = subprocess.run(
                    [
                        str(CONTROL), "linear-transition", "TUR-1",
                        "--expected", "Todo", "--target", "In Progress",
                        "--progress", str(base / f"{role}-progress.toml"), "--status", str(base / "status.md"),
                        "--parent", "epic-opus", "--outcome", "x", "--gate", "y",
                        "--caller", f"{role}-session", "--receipt", str(receipt),
                    ],
                    env=env, capture_output=True, text=True,
                )
                self.assertNotEqual(0, result.returncode, role)
                self.assertIn("orchestrator", result.stderr.lower(), role)

            # An orchestrator receipt bound to a different issue, such as an epic
            # orchestrator or an issue orchestrator for another stream, cannot mutate.
            other_issue = base / "other-issue.toml"
            self._write_receipt(other_issue, role="orchestrator", issue="TUR-999", provider_session_id="epic-session")
            result = subprocess.run(
                [
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", "Todo", "--target", "In Progress",
                    "--progress", str(base / "other-progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "epic-opus", "--outcome", "x", "--gate", "y",
                    "--caller", "epic-session", "--receipt", str(other_issue),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)

            # An unverified (stale) bootstrap cannot mutate even with the right role and issue.
            stale = base / "stale.toml"
            self._write_receipt(stale, role="orchestrator", issue="TUR-1", provider_session_id="stale-session", verified=False)
            result = subprocess.run(
                [
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", "Todo", "--target", "In Progress",
                    "--progress", str(base / "stale-progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "epic-opus", "--outcome", "x", "--gate", "y",
                    "--caller", "stale-session", "--receipt", str(stale),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)

    def test_linear_transition_denies_a_stream_not_owned_by_the_orchestrator_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="TUR-1", parent_session="epic-opus", child_session="qa-1",
                child_role="qa-capture", caller="epic-opus", brief="Build it.\n",
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
                    "--caller", "qa-1", "--stream", str(stream),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("orchestrator", result.stderr.lower())

    def test_linear_transition_denies_a_foreign_issue_from_the_exact_stream_owner(self) -> None:
        # The exact stream owner for TUR-1 must never authorize a transition for a
        # different issue: role and caller checks alone are not stream authority.
        # A fake `linear` that logs any call before exiting nonzero proves rejection
        # happens before any Linear read or mutation is attempted.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="TUR-1", parent_session="epic-opus", child_session="issue-opus",
                child_role="orchestrator", caller="epic-opus", brief="Build it.\n",
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            call_log = base / "calls.log"
            (fake_bin / "linear").write_text(
                f"#!/usr/bin/env bash\nprintf 'linear %s\\n' \"$*\" >>\"{call_log}\"\nexit 99\n"
            )
            (fake_bin / "linear").chmod(0o755)
            (fake_bin / "herdr-say").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "herdr-say").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")

            result = subprocess.run(
                [
                    str(CONTROL), "linear-transition", "TUR-999",
                    "--expected", "Todo", "--target", "In Progress",
                    "--progress", str(base / "progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "epic-opus", "--outcome", "started", "--gate", "implement",
                    "--caller", "issue-opus", "--stream", str(stream),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("stream_id", result.stderr.lower())
            self.assertFalse(call_log.exists())

    def test_linear_transition_rejects_wrong_caller_before_any_linear_call(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="TUR-1", parent_session="epic-opus", child_session="issue-opus",
                child_role="orchestrator", caller="epic-opus", brief="Build it.\n",
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
                child_role="orchestrator", caller="epic-opus", brief="Build it.\n",
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

    def test_linear_transition_routes_top_level_notification_through_operator_say(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            receipt = base / "receipt.toml"
            self._write_receipt(receipt, role="orchestrator", issue="TUR-1", provider_session_id="orch-session-1")
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
            call_log = base / "calls.log"
            (fake_bin / "operator-say").write_text(
                '#!/usr/bin/env bash\nprintf \'operator-say %s\\n\' "$*" >>"$CALL_LOG"\n'
            )
            (fake_bin / "operator-say").chmod(0o755)
            # A static parent route is never called for a top-level notification: this
            # binary would exit nonzero if invoked, proving no fallback to herdr-say.
            (fake_bin / "herdr-say").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "herdr-say").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", STATE_FILE=str(state_file), CALL_LOG=str(call_log))

            result = subprocess.run(
                [
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", "Todo", "--target", "In Progress",
                    "--progress", str(base / "progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "operator", "--outcome", "started", "--gate", "implement",
                    "--caller", "orch-session-1", "--receipt", str(receipt),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("operator-say", call_log.read_text())

    def test_stream_status_routes_top_level_notification_through_operator_say(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="TUR-1", parent_session="operator", child_session="issue-opus",
                child_role="orchestrator", caller="operator", brief="Build it.\n",
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            call_log = base / "calls.log"
            (fake_bin / "operator-say").write_text(
                '#!/usr/bin/env bash\nprintf \'operator-say %s\\n\' "$*" >>"$CALL_LOG"\n'
            )
            (fake_bin / "operator-say").chmod(0o755)
            (fake_bin / "herdr-say").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "herdr-say").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(call_log))

            result = subprocess.run(
                [
                    str(CONTROL), "stream-status", "--path", str(stream), "--caller", "issue-opus",
                    "--expected-revision", "0", "--outcome", "ready", "--gate", "review",
                    "--blocker", "none", "--next-action", "none",
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("operator-say", call_log.read_text())

    def test_owner_transfer_requires_durable_successor_readiness_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            owner = base / "operator-owner.toml"
            owner.write_text(
                'schema_version = 1\nowner_session_id = "old-session"\nowner_route = "old-route"\n'
                'handoff_revision = 1\ncontrol_dir = "/control"\n'
            )
            handoff = base / "handoffs" / "0002.md"
            handoff.parent.mkdir()
            handoff.write_text("ready\n")

            wrong_ready = subprocess.run(
                [
                    str(CONTROL), "successor-ready", "--path", str(base / "ready.toml"),
                    "--caller", "someone-else", "--session-id", "new-session", "--handoff-revision", "2",
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, wrong_ready.returncode)

            right_ready = subprocess.run(
                [
                    str(CONTROL), "successor-ready", "--path", str(base / "ready.toml"),
                    "--caller", "new-session", "--session-id", "new-session", "--handoff-revision", "2",
                ],
                check=True, capture_output=True, text=True,
            )
            self.assertTrue(json.loads(right_ready.stdout)["session_id"] == "new-session")

            transfer = subprocess.run(
                [
                    str(CONTROL), "owner-transfer", "--owner-file", str(owner),
                    "--expected-owner", "old-session", "--expected-route", "old-route", "--expected-revision", "1",
                    "--caller", "old-session", "--new-owner", "new-session", "--new-route", "new-route",
                    "--revision", "2", "--control-dir", "/control", "--handoff", str(handoff),
                    "--successor-readiness", str(base / "ready.toml"),
                ],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual("new-session", json.loads(transfer.stdout)["owner_session_id"])
            self.assertEqual("new-route", json.loads(transfer.stdout)["owner_route"])

    def test_owner_recover_command_is_absent_from_octo_control(self) -> None:
        # Dead-owner recovery is not an agent-callable command. Any attempt to run
        # it is an argparse usage error, not a runtime authorization decision.
        result = subprocess.run(
            [str(CONTROL), "owner-recover", "--owner-file", "/tmp/owner.toml"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("invalid choice", result.stderr.lower())
        self.assertIn("owner-recover", result.stderr)

        help_result = subprocess.run([str(CONTROL), "--help"], capture_output=True, text=True)
        self.assertNotIn("owner-recover", help_result.stdout)

    def test_recover_dead_owner_and_liveness_probes_no_longer_exist(self) -> None:
        from octo_lite import runtime as runtime_module

        self.assertFalse(hasattr(runtime_module, "recover_dead_owner"))
        self.assertFalse(hasattr(runtime_module, "_require_proven_absent"))

    def test_dead_owner_record_blocks_every_transfer_attempt_and_stays_unchanged(self) -> None:
        # With no recovery command, the only remaining owner-mutation surface is
        # owner-transfer, which requires the caller to be the exact recorded owner.
        # A dead owner (no live caller can ever again be that exact session) leaves
        # the record permanently blocked; only a manual, out-of-band edit of
        # operator-owner.toml (outside any role or command authority) can move it.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            owner = base / "operator-owner.toml"
            original = (
                'schema_version = 1\nowner_session_id = "dead-session"\nowner_route = "dead-route"\n'
                'handoff_revision = 1\ncontrol_dir = "/control"\n'
            )
            owner.write_text(original)
            handoff = base / "handoffs" / "0002.md"
            handoff.parent.mkdir()
            handoff.write_text("ready\n")
            subprocess.run(
                [
                    str(CONTROL), "successor-ready", "--path", str(base / "ready.toml"),
                    "--caller", "successor", "--session-id", "successor", "--handoff-revision", "2",
                ],
                check=True, capture_output=True, text=True,
            )
            result = subprocess.run(
                [
                    str(CONTROL), "owner-transfer", "--owner-file", str(owner),
                    "--expected-owner", "dead-session", "--expected-route", "dead-route", "--expected-revision", "1",
                    "--caller", "successor", "--new-owner", "successor", "--new-route", "new-route",
                    "--revision", "2", "--control-dir", "/control", "--handoff", str(handoff),
                    "--successor-readiness", str(base / "ready.toml"),
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("caller", result.stderr.lower())
            self.assertEqual(original, owner.read_text())

    def test_acceptance_record_never_infers_and_verifies_operator_caller(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            owner = base / "operator-owner.toml"
            owner.write_text(
                'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "/control"\n'
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
                    "--caller", "operator-1-session", "--issue", "TUR-1", "--pr", "https://example.test/pr/1",
                    "--head", "abc", "--verdict-reference", "https://example.test/pr/1#c1", "--decision", "maybe",
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, invalid_decision.returncode)

            accepted = subprocess.run(
                [
                    str(CONTROL), "accept", "--path", str(record_path), "--owner-file", str(owner),
                    "--caller", "operator-1-session", "--issue", "TUR-1", "--pr", "https://example.test/pr/1",
                    "--head", "abc", "--verdict-reference", "https://example.test/pr/1#c1", "--decision", "accept",
                ],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual("accept", json.loads(accepted.stdout)["decision"])
            with record_path.open("rb") as handle:
                stored = tomllib.load(handle)
            self.assertEqual("abc", stored["head"])
            self.assertEqual("operator-1-session", stored["decided_by"])

    def test_sweep_rejects_wrong_control_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "control"
            control.mkdir()
            owner = base / "operator-owner.toml"
            owner.write_text(
                'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "/wrong"\n'
            )
            result = subprocess.run(
                [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(base)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
