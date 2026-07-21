from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
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
TARGET_AGENTS_TEMPLATE = ROOT / "skills/octo-lite-issue-shaper/assets/repo-agents.md"


def _load_operator_sweep_module():
    loader = importlib.machinery.SourceFileLoader("operator_sweep", str(SWEEP))
    spec = importlib.util.spec_from_file_location("operator_sweep", SWEEP, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

# Fakes the two-phase reconciler launch: a --session-id call actually opens
# and hashes the receipt-bound reconcile.snapshot_path before answering a
# BOOTSTRAP_ACK, refusing (ready false, non-empty blocker) when that file is
# missing or its digest does not match reconcile.snapshot_digest, so a
# regression that persists the final snapshot late, corrupts its bytes, or
# leaves the pending digest-verification input behind is caught by every test
# that reuses this fake rather than only by assertions made after the sweep
# has already finished. A --resume call echoes the exact session it was
# resumed with in its own read-only judgment message, proving the resumed
# session is the exact bootstrap-verified one, never a self-attested or
# spoofed identity.
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
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path

receipt_path, session_id = sys.argv[1], sys.argv[2]
with open(receipt_path, "rb") as handle:
    receipt = tomllib.load(handle)
reconcile = receipt.get("reconcile", {})
snapshot_path = Path(reconcile["snapshot_path"])
expected_digest = reconcile["snapshot_digest"]

snapshot_exists = snapshot_path.is_file()
actual_digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest() if snapshot_exists else ""
snapshot_bytes_match = snapshot_exists and actual_digest == expected_digest

# The pending digest-verification input lives outside the final sweep
# directory as .sweep-pending-<digest>.md directly under the control dir
# (parents[2] of receipt.toml: sweeps/<digest>/receipt.toml), so bootstrap can
# independently observe whether the caller already removed it.
control_dir = Path(receipt_path).resolve().parents[2]
pending_files = sorted(str(path) for path in control_dir.glob(".sweep-pending-*.md"))

observations_file = os.environ.get("BOOTSTRAP_OBSERVATIONS_FILE")
if observations_file:
    Path(observations_file).write_text(json.dumps({
        "snapshot_exists": snapshot_exists,
        "snapshot_bytes_match": snapshot_bytes_match,
        "pending_files": pending_files,
    }))

ready = snapshot_bytes_match
blocker = "" if ready else "reconcile.snapshot_path missing or digest mismatch"
ack = {
    "schema_version": receipt["schema_version"],
    "spawn_id": receipt["spawn_id"],
    "provider_session_id": session_id,
    "launch_revision": receipt["launch_revision"],
    "role": receipt["role"]["name"],
    "worktree": receipt["workspace"]["worktree"],
    "starting_head": receipt["workspace"]["starting_head"],
    "ready": ready,
    "blocker": blocker,
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

    def test_target_init_template_declares_a_spec_and_an_adr_canonical_signal(self) -> None:
        # The issue shaper hand-copies this asset into a freshly initialized
        # target's root AGENTS.md; reusing the sweep's own signal parser (rather
        # than a bespoke count) proves the template cannot silently ship without
        # both canonical declarations the sweep will later require.
        module = _load_operator_sweep_module()
        text = TARGET_AGENTS_TEMPLATE.read_text()
        self.assertIn("Spec format:", text)
        self.assertEqual(1, len(module._signal_lines(text, module.CANONICAL_SPEC_SIGNAL)))
        self.assertEqual(1, len(module._signal_lines(text, module.CANONICAL_ADR_SIGNAL)))

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

    def test_sweep_receipt_snapshot_path_binds_the_final_persisted_snapshot_bootstrap_can_read(self) -> None:
        # Bootstrap only checks bound sources it can actually read. If the receipt
        # binds the temporary digest-verification input instead of the final
        # persisted snapshot, that path is already deleted by the time bootstrap
        # runs, so a real reconciler can neither verify nor honestly acknowledge it.
        # The fake bootstrap itself opens and hashes reconcile.snapshot_path and
        # records what it actually observed, at the exact moment it runs, into
        # BOOTSTRAP_OBSERVATIONS_FILE, so this proves the pre-bootstrap state
        # directly rather than inferring it from post-sweep filesystem probing.
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
            observations_file = base / "bootstrap-observations.json"
            for name, body in {
                "claude": FAKE_RECONCILER_CLAUDE,
                "operator-say": '#!/usr/bin/env bash\nprintf \'operator %s\\n\' "$*" >>"$CALL_LOG"\n',
            }.items():
                path = fake_bin / name
                path.write_text(body)
                path.chmod(0o755)
            env = dict(
                os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
                BOOTSTRAP_OBSERVATIONS_FILE=str(observations_file),
            )

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
            self.assertTrue(receipt["bootstrap"]["verified"])
            reconcile = receipt["reconcile"]

            final_snapshot = control / "sweeps" / fingerprint / "snapshot.md"
            self.assertEqual(str(final_snapshot), reconcile["snapshot_path"])
            self.assertTrue(final_snapshot.is_file(), "bootstrap-bound snapshot_path must exist before bootstrap starts")
            actual_digest = hashlib.sha256(final_snapshot.read_bytes()).hexdigest()
            self.assertEqual(reconcile["snapshot_digest"], actual_digest)

            observations = json.loads(observations_file.read_text())
            self.assertTrue(
                observations["snapshot_exists"],
                "fake bootstrap must observe the final snapshot already present when it runs",
            )
            self.assertTrue(
                observations["snapshot_bytes_match"],
                "fake bootstrap must independently hash matching bytes, not trust the receipt string",
            )
            self.assertEqual(
                [], observations["pending_files"],
                "the pending digest-verification input must already be gone when bootstrap runs",
            )

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

    def _sweep_env_and_command(self, base: Path, control: Path, repo: Path) -> tuple[dict, list[str], Path]:
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
        command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
        return env, command, log

    def test_sweep_accepts_none_as_sole_no_adr_declaration_and_binds_empty_adr_list(self) -> None:
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
                "- Canonical ADR paths: none\n"
            )
            spec = repo / "spec" / "domains" / "operating-model.spec.html"
            spec.parent.mkdir(parents=True)
            spec.write_text('<p data-anchor="x">Works.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            env, command, _log = self._sweep_env_and_command(base, control, repo)
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(result.stdout)["changed"])
            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            with open(state["receipt"], "rb") as handle:
                receipt = tomllib.load(handle)
            self.assertEqual([], receipt["reconcile"]["adr_blobs"])
            self.assertEqual(1, len(receipt["reconcile"]["spec_blobs"]))

    def test_sweep_fails_closed_on_a_sentinel_no_adr_value(self) -> None:
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
                "- Canonical ADR paths: None\n"
            )
            spec = repo / "spec" / "domains" / "operating-model.spec.html"
            spec.parent.mkdir(parents=True)
            spec.write_text('<p data-anchor="x">Works.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            env, command, log = self._sweep_env_and_command(base, control, repo)
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_fails_closed_on_mixed_none_and_path_adr_declaration(self) -> None:
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
                "- Canonical ADR paths: none, spec/adr/0001-operating-model-boundaries.spec.html\n"
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
            env, command, log = self._sweep_env_and_command(base, control, repo)
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_fails_closed_when_canonical_spec_declaration_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text(
                "# Target\n\n"
                "- Canonical spec paths: none\n"
                "- Canonical ADR paths: spec/adr/0001-operating-model-boundaries.spec.html\n"
            )
            adr = repo / "spec" / "adr" / "0001-operating-model-boundaries.spec.html"
            adr.parent.mkdir(parents=True)
            adr.write_text('<p data-anchor="x">Decided.</p>\n')
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "target"], check=True)

            control = base / "control"
            env, command, log = self._sweep_env_and_command(base, control, repo)
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_fails_closed_on_repeated_canonical_spec_declaration_lines_with_identical_values(self) -> None:
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
                "- Canonical spec paths: spec/domains/operating-model.spec.html\n"
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
            env, command, log = self._sweep_env_and_command(base, control, repo)
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

    def test_sweep_ignores_a_prefix_lookalike_line_and_succeeds_on_the_one_real_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "AGENTS.md").write_text(
                "# Target\n\n"
                "- Canonical spec paths (legacy, unused): see docs\n"
                "- Canonical spec paths: spec/domains/operating-model.spec.html\n"
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
            env, command, _log = self._sweep_env_and_command(base, control, repo)
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(result.stdout)["changed"])
            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            with open(state["receipt"], "rb") as handle:
                receipt = tomllib.load(handle)
            self.assertEqual(1, len(receipt["reconcile"]["spec_blobs"]))
            self.assertTrue(receipt["reconcile"]["spec_blobs"][0].startswith("spec/domains/operating-model.spec.html:"))

    def test_sweep_leaves_no_sweep_directory_when_gateway_validation_fails_after_canonical_sources_are_valid(self) -> None:
        # Canonical sources on AGENTS.md are entirely valid so canonical_blobs()
        # succeeds and the sweep proceeds to build snapshot.md; the declared
        # Linear stream then races between the snapshot-time fetch and the
        # gateway's own fresh re-fetch, so the failure surfaces only inside
        # prepare_reconcile_launch, after a naive implementation would already
        # have written snapshot.md to disk.
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
            (stream / "sources.toml").write_text('schema_version = 1\n\n[linear]\nissue = "TUR-1"\n')
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
            self.assertFalse((control / "sweeps").exists())
            leftover = [path for path in control.glob("**/*") if path.is_file()]
            self.assertEqual(
                {control / "streams/TUR-1/status.md", control / "streams/TUR-1/sources.toml"},
                set(leftover),
            )

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

    def test_sweep_fails_closed_before_any_provider_call_when_target_head_races_between_snapshot_and_gateway(self) -> None:
        # A thin git wrapper answers the exact literal `-C <repo> rev-parse HEAD`
        # call twice with two different commits, simulating a commit landing on
        # the target between the sweep's own head capture (used to build the
        # snapshot and canonical blobs) and the gateway's independent re-read of
        # the current repo HEAD, and delegates every other git invocation
        # (including worktree-internal ones) unchanged to the real binary.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            first_head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
            ).stdout.strip()
            (repo / "unrelated.txt").write_text("noise\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "unrelated"], check=True)
            second_head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
            ).stdout.strip()

            control = base / "control"
            env, command, log = self._sweep_env_and_command(base, control, repo)
            real_git_path = subprocess.run(["which", "git"], check=True, capture_output=True, text=True).stdout.strip()
            call_count_file = base / "head-call-count.txt"
            call_count_file.write_text("0")
            wrapper = base / "bin" / "git"
            wrapper.write_text(
                "#!/usr/bin/env bash\n"
                f'REAL_GIT="{real_git_path}"\n'
                f'REPO="{repo}"\n'
                'if [[ "$1" == "-C" && "$2" == "$REPO" && "$3" == "rev-parse" && "$4" == "HEAD" && "$#" -eq 4 ]]; then\n'
                '  count="$(cat "$HEAD_CALL_COUNT_FILE")"\n'
                '  count=$((count + 1))\n'
                '  echo -n "$count" >"$HEAD_CALL_COUNT_FILE"\n'
                f'  if [[ "$count" -eq 1 ]]; then echo "{first_head}"; else echo "{second_head}"; fi\n'
                "else\n"
                '  exec "$REAL_GIT" "$@"\n'
                "fi\n"
            )
            wrapper.chmod(0o755)
            env["HEAD_CALL_COUNT_FILE"] = str(call_count_file)

            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("head", result.stderr.lower())
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "worktrees").exists())
            self.assertFalse((control / "sweeps").exists())
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))
            self.assertFalse(any(line.startswith("operator ") for line in calls))

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

    def _write_shaping_receipt(
        self, path: Path, *, role: str, issue: str, caller: str,
        verified: bool = True, purpose: str = "shaping-review",
        repo: str = "org/repo", pr: int = 7, head: str = "deadbeef123",
        omit_revision: bool = False, omit_shaping: bool = False,
    ) -> None:
        from octo_lite.runtime import launch_revision
        receipt = {
            "schema_version": 1,
            "spawn_id": caller,
            "ready": True,
            "role": {"name": role},
            "issue": {"identifier": issue},
            "purpose": purpose,
            "bootstrap": {"verified": verified, "provider_session_id": caller},
        }
        if not omit_shaping:
            receipt["shaping"] = {"repo": repo, "pr": pr, "head": head}
        revision = launch_revision(receipt)
        lines = [
            "schema_version = 1",
            f'spawn_id = "{caller}"',
            "ready = true",
            f'purpose = "{purpose}"',
        ]
        if not omit_revision:
            lines.append(f'launch_revision = "{revision}"')
        lines += ["", f'[role]\nname = "{role}"', "", f'[issue]\nidentifier = "{issue}"']
        if not omit_shaping:
            lines += ["", f'[shaping]\nrepo = "{repo}"\npr = {pr}\nhead = "{head}"']
        lines += [
            "",
            "[bootstrap]",
            f"verified = {'true' if verified else 'false'}",
            f'provider_session_id = "{caller}"',
        ]
        path.write_text("\n".join(lines) + "\n")

    def test_linear_transition_to_shaped_requires_verified_shaping_review_receipt_authority(self) -> None:
        # Ideas or Todo -> Shaped must only ever move on receipt authority: a
        # verified bootstrap, the exact orchestrator role, the exact bound
        # issue and caller, purpose shaping-review, a valid launch_revision,
        # and shaping repo/PR/head inputs. Stream authority (used for the
        # existing delivery transitions) must never suffice for Shaped.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream, exact_fingerprint, verdict_body
            initialize_stream(
                stream, stream_id="TUR-1", parent_session="epic-opus", child_session="issue-opus",
                child_role="orchestrator", caller="epic-opus", brief="Build it.\n",
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            # Only the valid_shaping_review_receipt row must ever reach Linear or
            # GitHub: every other row is rejected by receipt authority first. These
            # fakes stay realistically executable for that row (driven by env-selected
            # state/response files) instead of always failing regardless of reason.
            (fake_bin / "linear").write_text(
                "#!/usr/bin/env bash\n"
                'if [[ -n "$STATE_FILE" && -f "$STATE_FILE" ]]; then\n'
                '  if [[ "$1 $2" == "issue view" ]]; then\n'
                '    state="$(cat "$STATE_FILE")"\n'
                "    cat <<JSON\n"
                '{"identifier": "TUR-1", "state": {"name": "$state"}, "updatedAt": "t1"}\n'
                "JSON\n"
                "    exit 0\n"
                '  elif [[ "$1 $2" == "issue update" ]]; then\n'
                '    echo -n "Shaped" >"$STATE_FILE"\n'
                "    exit 0\n"
                "  fi\n"
                "fi\n"
                "exit 99\n"
            )
            (fake_bin / "linear").chmod(0o755)
            (fake_bin / "gh").write_text(
                "#!/usr/bin/env bash\n"
                'if [[ -n "$GH_RESPONSE_FILE" && -f "$GH_RESPONSE_FILE" ]]; then\n'
                '  cat "$GH_RESPONSE_FILE"\n'
                "  exit 0\n"
                "fi\n"
                "exit 99\n"
            )
            (fake_bin / "gh").chmod(0o755)
            (fake_bin / "herdr-say").write_text("#!/usr/bin/env bash\nexit 0\n")
            (fake_bin / "herdr-say").chmod(0o755)
            base_env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")

            cases = [
                ("valid_shaping_review_receipt", {}, True),
                ("stream_authority_forbidden", {"use_stream": True}, False),
                ("wrong_purpose", {"purpose": "delivery"}, False),
                ("unverified_receipt", {"verified": False}, False),
                ("foreign_issue", {"issue": "TUR-999"}, False),
                ("foreign_caller", {"caller": "someone-else"}, False),
                ("wrong_role", {"role": "implementer"}, False),
                ("missing_launch_revision", {"omit_revision": True}, False),
                ("missing_shaping_inputs", {"omit_shaping": True}, False),
            ]
            for expected_state in ("Ideas", "Todo"):
                for name, overrides, should_succeed in cases:
                    with self.subTest(expected_state=expected_state, case=name):
                        receipt = base / f"{expected_state}-{name}.toml"
                        self._write_shaping_receipt(
                            receipt, role=overrides.get("role", "orchestrator"), issue=overrides.get("issue", "TUR-1"),
                            caller="issue-opus",
                            verified=overrides.get("verified", True),
                            purpose=overrides.get("purpose", "shaping-review"),
                            omit_revision=overrides.get("omit_revision", False),
                            omit_shaping=overrides.get("omit_shaping", False),
                        )
                        env = dict(base_env)
                        if name == "valid_shaping_review_receipt":
                            state_file = base / f"{expected_state}-{name}-state.txt"
                            state_file.write_text(expected_state)
                            normalized_issue = {
                                "identifier": "TUR-1", "state": expected_state, "updatedAt": "t1",
                            }
                            binding = f"linear:TUR-1:{exact_fingerprint(normalized_issue)}"
                            marker = verdict_body(
                                "shaping", "clear", "deadbeef123", [binding], [],
                                "reviewer-receipt-xyz",
                                conversation_log_references=["session-log-1"],
                                conversation_cutoff="2026-07-18T00:00:00Z",
                            )
                            response_file = base / f"{expected_state}-{name}-gh.json"
                            response_file.write_text(json.dumps({
                                "headRefOid": "deadbeef123",
                                "comments": [{"id": 1, "body": marker}],
                            }))
                            env["STATE_FILE"] = str(state_file)
                            env["GH_RESPONSE_FILE"] = str(response_file)
                        command = [
                            str(CONTROL), "linear-transition", "TUR-1",
                            "--expected", expected_state, "--target", "Shaped",
                            "--progress", str(base / f"{expected_state}-{name}-progress.toml"),
                            "--status", str(base / f"{expected_state}-{name}-status.md"),
                            "--parent", "epic-opus", "--outcome", "shaped", "--gate", "review",
                            "--caller", overrides.get("caller", "issue-opus"),
                        ]
                        if overrides.get("use_stream"):
                            command += ["--stream", str(stream)]
                        else:
                            command += ["--receipt", str(receipt)]
                        result = subprocess.run(command, env=env, capture_output=True, text=True)
                        if should_succeed:
                            self.assertEqual(0, result.returncode, result.stderr)
                        else:
                            self.assertNotEqual(0, result.returncode)

    def test_linear_transition_to_shaped_requires_one_exact_bound_shaping_marker(self) -> None:
        # After the compare Linear read, Shaped must refetch the exact live PR
        # head and comments and require exactly one shaping marker: parseable
        # TOML, review_type shaping, verdict clear, exact head, and an exact
        # linear:<issue>:<fingerprint of current normalized Linear read>
        # binding. Every other case rejects before any mutation; only the
        # exact-bound clear verdict permits one update, readback, status, and
        # notify, in that order. Existing delivery transitions stay allowed
        # and are not exercised here.
        from octo_lite.runtime import verdict_body, exact_fingerprint

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            live_head = "deadbeef123"
            raw_issue = {"identifier": "TUR-1", "state": {"name": "Todo"}, "updatedAt": "2026-07-19T00:00:00Z"}
            normalized_issue = dict(raw_issue)
            normalized_issue["state"] = "Todo"
            fingerprint = exact_fingerprint(normalized_issue)
            binding = f"linear:TUR-1:{fingerprint}"

            def marker(*, verdict="clear", head=live_head, bound_inputs=(binding,)):
                return verdict_body(
                    "shaping", verdict, head, list(bound_inputs), [], "reviewer-receipt-xyz",
                    conversation_log_references=["session-log-1"],
                    conversation_cutoff="2026-07-18T00:00:00Z",
                )

            unreadable_marker = "<!-- octo-lite-verdict:shaping -->\n```toml\nverdict = \n```"

            def wrong_review_type_marker():
                return (
                    "<!-- octo-lite-verdict:shaping -->\n```toml\n"
                    'schema_version = 1\n'
                    'review_type = "code"\n'
                    'verdict = "clear"\n'
                    f'head = "{live_head}"\n'
                    f'bound_inputs = ["{binding}"]\n'
                    '```'
                )

            scenarios = {
                "missing": [],
                "duplicate": [marker(), marker()],
                "unreadable": [unreadable_marker],
                "blocking": [marker(verdict="blocking")],
                "stale_head": [marker(head="stalehead000")],
                "live_head_mismatch": [marker()],
                "wrong_review_type": [wrong_review_type_marker()],
                "anonymous_binding": [marker(bound_inputs=("spec/domains/operating-model.spec.html:abc123",))],
                "foreign_binding": [marker(bound_inputs=(f"linear:TUR-999:{fingerprint}",))],
                "wrong_fingerprint": [marker(bound_inputs=(f"linear:TUR-1:{'0' * 64}",))],
                "valid": [marker()],
            }

            fake_bin = base / "bin"
            fake_bin.mkdir()
            (fake_bin / "linear").write_text(
                "#!/usr/bin/env bash\n"
                "printf 'linear %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                'if [[ "$1 $2" == "issue view" ]]; then\n'
                '  state="$(cat "$STATE_FILE")"\n'
                "  cat <<JSON\n"
                '{"identifier": "TUR-1", "state": {"name": "$state"}, "updatedAt": "2026-07-19T00:00:00Z"}\n'
                "JSON\n"
                'elif [[ "$1 $2" == "issue update" ]]; then\n'
                '  echo -n "Shaped" >"$STATE_FILE"\n'
                "fi\n"
            )
            (fake_bin / "linear").chmod(0o755)
            (fake_bin / "gh").write_text(
                "#!/usr/bin/env bash\n"
                "printf 'gh %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                'cat "$GH_RESPONSE_FILE"\n'
            )
            (fake_bin / "gh").chmod(0o755)
            (fake_bin / "herdr-say").write_text(
                "#!/usr/bin/env bash\nprintf 'herdr-say %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            )
            (fake_bin / "herdr-say").chmod(0o755)

            for name, comment_bodies in scenarios.items():
                with self.subTest(case=name):
                    state_file = base / f"{name}-state.txt"
                    state_file.write_text("Todo")
                    call_log = base / f"{name}-calls.log"
                    response_file = base / f"{name}-gh.json"
                    actual_head = "livehead999" if name == "live_head_mismatch" else live_head
                    response_file.write_text(json.dumps({
                        "url": "https://github.com/org/repo/pull/7",
                        "headRefOid": actual_head,
                        "headRefName": "shaping/TUR-1",
                        "baseRefName": "main",
                        "state": "OPEN",
                        "reviewDecision": "",
                        "statusCheckRollup": [],
                        "comments": [{"id": i, "body": body} for i, body in enumerate(comment_bodies)],
                    }))
                    receipt = base / f"{name}-receipt.toml"
                    self._write_shaping_receipt(
                        receipt, role="orchestrator", issue="TUR-1", caller="issue-opus",
                        repo="org/repo", pr=7, head=live_head,
                    )
                    env = dict(
                        os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                        STATE_FILE=str(state_file), CALL_LOG=str(call_log),
                        GH_RESPONSE_FILE=str(response_file),
                    )
                    result = subprocess.run(
                        [
                            str(CONTROL), "linear-transition", "TUR-1",
                            "--expected", "Todo", "--target", "Shaped",
                            "--progress", str(base / f"{name}-progress.toml"),
                            "--status", str(base / f"{name}-status.md"),
                            "--parent", "epic-opus", "--outcome", "shaped", "--gate", "review",
                            "--caller", "issue-opus", "--receipt", str(receipt),
                        ],
                        env=env, capture_output=True, text=True,
                    )
                    if name == "valid":
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertEqual("Shaped", state_file.read_text())
                        calls = call_log.read_text().splitlines()
                        self.assertEqual(5, len(calls), calls)
                        self.assertTrue(calls[0].startswith("linear issue view"), calls)
                        self.assertTrue(calls[1].startswith("gh "), calls)
                        self.assertTrue(calls[2].startswith("linear issue update"), calls)
                        self.assertTrue(calls[3].startswith("linear issue view"), calls)
                        self.assertTrue(calls[4].startswith("herdr-say "), calls)
                    else:
                        self.assertNotEqual(0, result.returncode, name)


if __name__ == "__main__":
    unittest.main()


class SweepStreamLivenessTests(unittest.TestCase):
    # sweep-stream-liveness and sweep-suspected-stuck (ruling-19, refined):
    # liveness derives from session transcript mtime plus pane state, never
    # status-file age alone; an ask older than subsequent session activity is
    # presumed consumed; outputs are stable mtimes so unchanged stays no-op.
    def test_stream_liveness_open_wait_consumed_ask_and_suspected_stuck(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            now = 1_000_000.0
            queue = base / "herdr-queue"
            queue.mkdir()

            waiting = base / "streams" / "tur-1"
            waiting.mkdir(parents=True)
            (waiting / "status.md").write_text("# s\n")
            os.utime(waiting / "status.md", (now - 9000, now - 9000))
            (waiting / "transcript.jsonl").write_text("{}\n")
            os.utime(waiting / "transcript.jsonl", (now - 600, now - 600))
            (waiting / "waiting.toml").write_text(
                'owner = "operator"\nask = "Please approve the suite at the served pages."\n'
            )
            os.utime(waiting / "waiting.toml", (now - 300, now - 300))
            (waiting / "inflight.toml").write_text('workflows = ["wf_abc123-def"]\n')
            (queue / "20260720T000001-tur-1.json").write_text("{}")

            live = module.stream_liveness(waiting, queue, idle_seconds=3600, now=now)
            # ask recorded AFTER the last session activity: open wait, verbatim ask.
            self.assertEqual("waiting", live["classification"])
            self.assertEqual("operator", live["wait_owner"])
            self.assertEqual("Please approve the suite at the served pages.", live["open_ask"])
            self.assertFalse(live["ask_consumed"])
            self.assertEqual(["wf_abc123-def"], live["inflight_workflows"])
            self.assertEqual(["20260720T000001-tur-1.json"], live["undelivered_queue"])
            self.assertEqual(int(now - 600), live["transcript_mtime"])
            self.assertIn("pane_activity", live)

            # session activity AFTER the recorded ask: presumed consumed, no open wait,
            # fresh transcript keeps the stream active despite an old status file.
            os.utime(waiting / "transcript.jsonl", (now - 60, now - 60))
            consumed = module.stream_liveness(waiting, queue, idle_seconds=3600, now=now)
            self.assertTrue(consumed["ask_consumed"])
            self.assertEqual("", consumed["wait_owner"])
            self.assertEqual("active", consumed["classification"])

            stuck = base / "streams" / "tur-2"
            stuck.mkdir(parents=True)
            (stuck / "status.md").write_text("# s\n")
            os.utime(stuck / "status.md", (now - 9000, now - 9000))
            live_stuck = module.stream_liveness(stuck, queue, idle_seconds=3600, now=now)
            self.assertEqual("suspected-stuck", live_stuck["classification"])
            self.assertEqual([], live_stuck["undelivered_queue"])

    def test_liveness_outputs_are_stable_between_runs_for_an_unchanged_stream(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            queue = base / "herdr-queue"
            stream = base / "streams" / "tur-3"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("# s\n")
            first = module.stream_liveness(stream, queue, idle_seconds=3600, now=2_000_000.0)
            second = module.stream_liveness(stream, queue, idle_seconds=3600, now=2_000_005.0)
            self.assertEqual(first, second)

    def test_snapshot_includes_the_stream_liveness_section(self) -> None:
        source = SWEEP.read_text()
        self.assertIn("## Stream liveness", source)
