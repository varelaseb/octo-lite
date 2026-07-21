from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from octo_lite.runtime import GateError


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
# and hashes the journal-bound reconcile.snapshot_path before answering a
# BOOTSTRAP_ACK, echoing the actual observed digest and refusing (ready false,
# non-empty blocker) when that file is missing or its digest does not match
# reconcile.snapshot_digest, so a regression that persists the final snapshot
# late, corrupts its bytes, or leaves the pending digest-verification input
# behind is caught by every test that reuses this fake rather than only by
# assertions made after the sweep has already finished. A --resume call echoes
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
  journal_path="$(printf '%s' "$prompt" | grep -oE '/[^ ]*journal\.json' | head -1)"
  args=("$@")
  session=""
  for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "--session-id" ]]; then
      session="${args[$((i+1))]}"
    fi
  done
  python3 - "$journal_path" "$session" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

journal_path, session_id = sys.argv[1], sys.argv[2]
with open(journal_path) as handle:
    journal = json.load(handle)
reconcile = journal.get("reconcile", {})
snapshot_path = Path(reconcile["snapshot_path"])
expected_digest = reconcile["snapshot_digest"]

snapshot_exists = snapshot_path.is_file()
actual_digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest() if snapshot_exists else ""
snapshot_bytes_match = snapshot_exists and actual_digest == expected_digest

# The pending digest-verification input lives outside the final sweep
# directory as .sweep-pending-<digest>.md directly under the control dir
# (parents[2] of journal.json: sweeps/<digest>/journal.json), so bootstrap can
# independently observe whether the caller already removed it.
control_dir = Path(journal_path).resolve().parents[2]
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
    "schema_version": journal["schema_version"],
    "spawn_id": journal["spawn_id"],
    "provider_session_id": session_id,
    "launch_revision": journal["launch_revision"],
    "role": journal["role"]["name"],
    "worktree": journal["workspace"]["worktree"],
    "starting_head": journal["workspace"]["starting_head"],
    "snapshot_path": str(snapshot_path),
    "snapshot_digest": actual_digest if snapshot_exists else expected_digest,
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
# or mismatched session, matching the reconcile gateway's own identity check.
FAKE_RECONCILER_CLAUDE_SPOOFED_RESUME = r"""#!/usr/bin/env bash
printf 'claude %s\n' "$*" >>"$CALL_LOG"
prompt="$(cat)"
if [[ "$*" == *"--resume"* ]]; then
  cat <<'JSON'
{"session_id": "spoofed-session-not-the-resumed-one", "result": "changed"}
JSON
else
  journal_path="$(printf '%s' "$prompt" | grep -oE '/[^ ]*journal\.json' | head -1)"
  args=("$@")
  session=""
  for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "--session-id" ]]; then
      session="${args[$((i+1))]}"
    fi
  done
  python3 - "$journal_path" "$session" <<'PY'
import json
import sys

journal_path, session_id = sys.argv[1], sys.argv[2]
with open(journal_path) as handle:
    journal = json.load(handle)
reconcile = journal.get("reconcile", {})
ack = {
    "schema_version": journal["schema_version"],
    "spawn_id": journal["spawn_id"],
    "provider_session_id": session_id,
    "launch_revision": journal["launch_revision"],
    "role": journal["role"]["name"],
    "worktree": journal["workspace"]["worktree"],
    "starting_head": journal["workspace"]["starting_head"],
    "snapshot_path": reconcile["snapshot_path"],
    "snapshot_digest": reconcile["snapshot_digest"],
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

    def test_timer_runs_the_sweep_directly_and_never_messages_a_periodic_wake(self) -> None:
        # Operator directive: no periodic wake messages; the timer runs the
        # deterministic sweep itself (primed with --on-active so it fires
        # before any manual start), and only a changed sweep messages the
        # operator through operator-sweep's own delta path.
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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(call_log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            self.assertIn("operator-sweep", call)
            self.assertIn(f"--control-dir {control}", call)
            self.assertIn(f"--owner-file {owner}", call)
            self.assertIn(f"--repo {repo}", call)
            self.assertIn("--on-active", call)
            self.assertIn("--on-unit-active", call)
            # systemd user services get a bare PATH lacking ~/.local/bin (live
            # FileNotFoundError evidence 02:28); the installer passes the
            # installing shell PATH into the unit.
            self.assertIn("--setenv=PATH=", call)
            self.assertNotIn("operator-say --kind info sweep", call)

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            journal = json.loads(Path(state["journal"]).read_text())
            self.assertTrue(journal["bootstrap"]["verified"])
            self.assertTrue(journal["result"]["bound"])

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
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
            journal = json.loads(Path(state["journal"]).read_text())
            self.assertTrue(journal["bootstrap"]["verified"])
            self.assertEqual(journal["spawn_id"], journal["bootstrap"]["provider_session_id"])
            self.assertTrue(journal["result"]["bound"])

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

            command = [
                str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner),
                "--repo", str(repo),
            ]
            subprocess.run(command, env=env, check=True, capture_output=True, text=True)

            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            journal = json.loads(Path(state["journal"]).read_text())

            # The worktree is a genuine detached checkout in worktree_root, never the
            # control checkout, while the reconciler pass runs inside it; a successful
            # pass then removes it, so its live state is captured from the fake
            # reconciler's own worktree-check log line rather than probed afterward.
            worktree = Path(journal["workspace"]["worktree"])
            self.assertNotEqual(str(repo), journal["workspace"]["worktree"])
            self.assertEqual(str((control / "worktrees").resolve()), str(worktree.resolve().parent))
            self.assertTrue(journal["workspace"]["child_containment_verified"])
            checks = [line for line in log.read_text().splitlines() if line.startswith("worktree-check ")]
            self.assertTrue(checks)
            for check in checks:
                pwd, top, branch = check.removeprefix("worktree-check ").split("|")
                self.assertEqual(str(worktree.resolve()), pwd)
                self.assertEqual(str(worktree.resolve()), top)
                self.assertEqual("", branch)
            self.assertFalse(worktree.exists())

    def test_completed_changed_sweep_persists_a_journal_entry_with_exact_bindings_and_no_reconcile_receipt(self) -> None:
        # Unit I (launch-receipt-manifest-shapes, role-reconciler-snapshot-receipt-binding,
        # decision-109-binding): the reconcile binding artifact is <sweep>/journal.json
        # carrying role reconciler, purpose reconcile with read-restricted access, the
        # final persisted snapshot path plus digest, the expected control HEAD, spec and
        # ADR blobs, and streams; no reconcile receipt.toml is written anywhere.
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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

            command = [
                str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner),
                "--repo", str(repo),
            ]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            fingerprint = json.loads(result.stdout)["fingerprint"]

            sweep_dir = control / "sweeps" / fingerprint
            journal_path = sweep_dir / "journal.json"
            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            self.assertEqual(str(journal_path), state["journal"])
            journal = json.loads(journal_path.read_text())
            self.assertEqual("worker-journal", journal["manifest_shape"])
            self.assertEqual("reconcile", journal["purpose"])
            self.assertIs(True, journal["read_restricted"])
            self.assertEqual("reconciler", journal["role"]["name"])
            reconcile = journal["reconcile"]
            self.assertEqual(str(sweep_dir / "snapshot.md"), reconcile["snapshot_path"])
            self.assertEqual(fingerprint, reconcile["snapshot_digest"])
            self.assertEqual(head, reconcile["control_head"])
            self.assertEqual([f"spec/domains/operating-model.spec.html:{spec_blob}"], reconcile["spec_blobs"])
            self.assertEqual([f"spec/adr/0001-operating-model-boundaries.spec.html:{adr_blob}"], reconcile["adr_blobs"])
            self.assertIn("streams/TUR-1/status.md", reconcile["conversation_state_refs"])
            self.assertFalse((sweep_dir / "receipt.toml").exists())
            self.assertEqual([], list(sweep_dir.glob("*.toml")))
            self.assertEqual([], list(control.rglob("receipt.toml")))

    def test_sweep_journal_snapshot_path_binds_the_final_persisted_snapshot_bootstrap_can_read(self) -> None:
        # Bootstrap only checks bound sources it can actually read. If the journal
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
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
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
            journal = json.loads(Path(state["journal"]).read_text())
            self.assertTrue(journal["bootstrap"]["verified"])
            reconcile = journal["reconcile"]

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

            command = [
                str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner),
                "--repo", str(repo),
            ]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(result.stdout)["changed"])

            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            reconcile = json.loads(Path(state["journal"]).read_text())["reconcile"]
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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
        env = dict(
            os.environ,
            PATH=f"{fake_bin}:{os.environ['PATH']}",
            CALL_LOG=str(log),
            OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
        )
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
            reconcile = json.loads(Path(state["journal"]).read_text())["reconcile"]
            self.assertEqual([], reconcile["adr_blobs"])
            self.assertEqual(1, len(reconcile["spec_blobs"]))

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
            reconcile = json.loads(Path(state["journal"]).read_text())["reconcile"]
            self.assertEqual(1, len(reconcile["spec_blobs"]))
            self.assertTrue(reconcile["spec_blobs"][0].startswith("spec/domains/operating-model.spec.html:"))

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
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
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
            # A failed sweep leaves no journal entry, no reconcile receipt, and no
            # sweep directory behind (workspace-cleanup-clean-abort plus Unit I).
            self.assertEqual([], list(control.rglob("journal.json")))
            self.assertEqual([], list(control.rglob("receipt.toml")))
            leftover = [path for path in control.glob("**/*") if path.is_file()]
            self.assertEqual(
                {control / "streams/TUR-1/status.md", control / "streams/TUR-1/sources.toml"},
                set(leftover),
            )
            # explicit liveness-cleanup red (v16 finding 2): a failed gateway
            # removes the pre-written liveness report with everything else.
            self.assertFalse((control / "liveness.json").exists())

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
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

    def test_sweep_defers_reconcile_before_any_provider_call_when_target_head_races_between_snapshot_and_gateway(self) -> None:
        # TUR-489: a thin git wrapper answers the exact literal `-C <repo> rev-parse
        # HEAD` call with two different commits (first the captured head, then a
        # newer one), simulating a commit landing on the target between the sweep's
        # own head capture and the gateway's independent re-read of the current repo
        # HEAD. The gateway fails closed inside prepare_reconcile_launch with a
        # 'target HEAD changed' GateError. Previously that GateError PROPAGATED and
        # crashed the whole timer sweep (real crash 08:56:06). The sweep now DEFERS
        # the reconcile for this pass instead: it makes NO provider call, persists
        # NO sweep state (so the next pass retries against a stable HEAD), leaves NO
        # sweep artifact behind, emits the distinct deferred note, and exits 0.
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
            # Deferred, not crashed: clean exit 0.
            self.assertEqual(0, result.returncode, result.stderr)
            # The distinct deferred-reconcile note is surfaced.
            self.assertIn("SWEEP NOTE (deferred reconcile):", result.stdout)
            payload = _sweep_stdout_json(result.stdout)
            self.assertTrue(payload.get("deferred_reconcile"))
            # No provider call, no persisted state, no sweep artifact directory:
            # the next pass retries the reconcile against a stable HEAD.
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertFalse((control / "worktrees").exists())
            self.assertFalse((control / "sweeps").exists())
            self.assertEqual([], list(control.glob(".sweep-pending-*.md")))
            calls = log.read_text().splitlines() if log.exists() else []
            self.assertFalse(any(line.startswith("claude ") for line in calls))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", STATE_FILE=str(state_file), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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

    def test_linear_transition_allows_shaped_to_todo_loop_fire(self) -> None:
        # delivery-lifecycle linear-loop-fire-transition and delivery-entry-gate,
        # role-runtime launch-loop-fire-first-act: loop fire is the one mechanical
        # Shaped -> Todo transition, admitted with the existing compare, mutate,
        # readback, notify mechanics.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            receipt = base / "receipt.toml"
            self._write_receipt(receipt, role="orchestrator", issue="TUR-1", provider_session_id="orch-session-1")
            fake_bin = base / "bin"
            fake_bin.mkdir()
            state_file = base / "linear-state.txt"
            state_file.write_text("Shaped")
            call_log = base / "calls.log"
            (fake_bin / "linear").write_text(
                "#!/usr/bin/env bash\n"
                'printf \'linear %s\\n\' "$*" >>"$CALL_LOG"\n'
                'if [[ "$1 $2" == "issue view" ]]; then\n'
                '  state="$(cat "$STATE_FILE")"\n'
                "  cat <<JSON\n"
                '{"identifier": "TUR-1", "state": {"name": "$state"}, "updatedAt": "t1"}\n'
                "JSON\n"
                'elif [[ "$1 $2" == "issue update" ]]; then\n'
                '  echo -n "Todo" >"$STATE_FILE"\n'
                "fi\n"
            )
            (fake_bin / "linear").chmod(0o755)
            (fake_bin / "herdr-say").write_text(
                '#!/usr/bin/env bash\nprintf \'herdr-say %s\\n\' "$*" >>"$CALL_LOG"\nexit 0\n'
            )
            (fake_bin / "herdr-say").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", STATE_FILE=str(state_file), CALL_LOG=str(call_log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

            result = subprocess.run(
                [
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", "Shaped", "--target", "Todo",
                    "--progress", str(base / "progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "epic-opus", "--outcome", "loop-fire", "--gate", "delivery-entry",
                    "--caller", "orch-session-1", "--receipt", str(receipt),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("Todo", state_file.read_text())
            calls = call_log.read_text().splitlines()
            # Compare read, mutation, readback, then notify, in that exact order.
            self.assertEqual(
                [
                    "linear issue view TUR-1 --json --no-download",
                    "linear issue update TUR-1 --state Todo",
                    "linear issue view TUR-1 --json --no-download",
                ],
                [line for line in calls if line.startswith("linear ")],
            )
            self.assertTrue(calls[-1].startswith("herdr-say "))
            self.assertIn("TUR-1 entered Todo", calls[-1])

    def test_linear_transition_never_admits_shaped_to_in_progress(self) -> None:
        # Companion to loop fire: Shaped never moves directly to In Progress
        # (linear-loop-fire-transition, launch-loop-fire-first-act), and the
        # rejection lands before any Linear call.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            receipt = base / "receipt.toml"
            self._write_receipt(receipt, role="orchestrator", issue="TUR-1", provider_session_id="orch-session-1")
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
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", "Shaped", "--target", "In Progress",
                    "--progress", str(base / "progress.toml"), "--status", str(base / "status.md"),
                    "--parent", "epic-opus", "--outcome", "x", "--gate", "y",
                    "--caller", "orch-session-1", "--receipt", str(receipt),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("not allowed", result.stderr.lower())
            self.assertFalse(call_log.exists())

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", STATE_FILE=str(state_file), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", STATE_FILE=str(state_file), CALL_LOG=str(call_log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(call_log), OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"))

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

    # Unit J shaped-transition authority migration (role-runtime
    # launch-shaping-authority, launch-shaping-authority-issue,
    # launch-receipt-persistent; delivery-lifecycle
    # shaping-operator-approval-order; operating-model decision-109-binding):
    # a Shaped transition binds to the verified generic persistent
    # issue-orchestrator receipt whose launcher-resolved skill set includes
    # shaping, the journalled clear shaping verdict carrying relay-verbatim
    # rollout-record provenance at the exact issue, repo, PR, and fresh PR
    # head, and the Unit L operator-intent record stamping that same head.
    # The retired worker shaping-review receipt and the interim
    # published-verdict ack-echo path (tur-416 style) carry no authority.

    def _write_persistent_orchestrator_receipt(
        self, path: Path, *, caller: str, role: str = "orchestrator",
        issue: str | None = "TUR-1", verified: bool = True,
        capabilities: tuple[str, ...] = ("shaping",),
        omit_revision: bool = False, purpose: str | None = None,
        shaping: dict | None = None,
    ) -> None:
        from octo_lite.runtime import launch_revision
        resolved = ["herdr-comms"] + (
            ["octo-lite-issue-shaper", "grill-with-docs"] if "shaping" in capabilities else []
        )
        receipt: dict = {
            "schema_version": 1,
            "spawn_id": caller,
            "ready": True,
            "role": {"name": role},
            "skills": {"resolved": resolved, "matched_capabilities": list(capabilities)},
            "bootstrap": {"verified": verified, "provider_session_id": caller},
        }
        if purpose is not None:
            receipt["purpose"] = purpose
        if issue is not None:
            receipt["issue"] = {"identifier": issue}
        if shaping is not None:
            receipt["shaping"] = dict(shaping)
        revision = launch_revision(receipt)
        lines = ["schema_version = 1", f'spawn_id = "{caller}"', "ready = true"]
        if purpose is not None:
            lines.append(f'purpose = "{purpose}"')
        if not omit_revision:
            lines.append(f'launch_revision = "{revision}"')
        lines += ["", "[role]", f'name = "{role}"']
        lines += [
            "", "[skills]",
            f"resolved = {json.dumps(resolved)}",
            f"matched_capabilities = {json.dumps(list(capabilities))}",
        ]
        if issue is not None:
            lines += ["", "[issue]", f'identifier = "{issue}"']
        if shaping is not None:
            lines += [
                "", "[shaping]", f'repo = "{shaping["repo"]}"',
                f"pr = {shaping['pr']}", f'head = "{shaping["head"]}"',
            ]
        lines += [
            "", "[bootstrap]",
            f"verified = {'true' if verified else 'false'}",
            f'provider_session_id = "{caller}"',
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def _write_verdict_journal(
        self, path: Path, *, head: str, issue: str = "TUR-1", repo: str = "org/repo",
        pr: int = 7, verdict: str = "clear", provenance: bool = True,
        ack_echo: bool = False,
    ) -> None:
        entry: dict = {
            "schema_version": 1, "review_type": "shaping", "verdict": verdict,
            "issue": issue, "repo": repo, "pr": pr, "head": head,
        }
        if provenance:
            entry.update({
                "codex_session_id": "codex-session-1",
                "verdict_sha256": "a" * 64,
                "provenance": "relay-verbatim-rollout",
            })
        if ack_echo:
            entry.update({
                "bound_inputs": [f"linear:{issue}:{'0' * 64}"],
                "ack_echo": "verified",
            })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry))

    def _install_shaped_fakes(self, fake_bin: Path) -> None:
        fake_bin.mkdir(parents=True, exist_ok=True)
        (fake_bin / "linear").write_text(
            "#!/usr/bin/env bash\n"
            'if [[ -n "$CALL_LOG" ]]; then printf \'linear %s\\n\' "$*" >>"$CALL_LOG"; fi\n'
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
        # The stateful gh intent fake answers pr view (from GH_HEAD) and the
        # issue-comment lifecycle (from GH_COMMENTS), so the command-published
        # operator-intent surface actually exists for Unit J to re-read.
        _install_gh_intent_fake(fake_bin)
        (fake_bin / "herdr-say").write_text(
            "#!/usr/bin/env bash\n"
            'if [[ -n "$CALL_LOG" ]]; then printf \'herdr-say %s\\n\' "$*" >>"$CALL_LOG"; fi\n'
            "exit 0\n"
        )
        (fake_bin / "herdr-say").chmod(0o755)

    def test_linear_transition_to_shaped_requires_persistent_orchestrator_authority(self) -> None:
        # Ideas or Todo -> Shaped moves only on the migrated authority tuple:
        # the verified generic persistent issue-orchestrator receipt (no pass
        # purpose, exact caller session, valid launch revision, resolved
        # shaping capability) at streams/<name>/receipt.toml claiming this
        # exact issue in the live registry, the journalled clear shaping
        # verdict with rollout-record provenance, and the Unit L
        # operator-intent record stamping that same head. Every rejection
        # happens before any Linear or GitHub call.
        from octo_lite.runtime import exact_fingerprint, verdict_body

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)

            def repo_head() -> str:
                return subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", "HEAD"],
                    check=True, capture_output=True, text=True,
                ).stdout.strip()

            fake_bin = base / "bin"
            self._install_shaped_fakes(fake_bin)
            base_env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")
            caller = "issue-opus"

            def produce_intent(directory: Path, *, at_head: str, store: Path) -> str:
                # Publish the operator-intent surface to the shared PR store so
                # a command-produced record has a matching live comment; the
                # returned local TOML is command-authored, not forged.
                env = dict(base_env, GH_HEAD=at_head, GH_COMMENTS=str(store))
                produced = subprocess.run(
                    [
                        str(CONTROL), "intent-record", "--stream-dir", str(directory),
                        "--intent-ref", "ruling-15", "--repo", str(repo), "--pr", "7",
                    ],
                    capture_output=True, text=True, env=env,
                )
                self.assertEqual(0, produced.returncode, produced.stderr)
                return (directory / "intent-record.toml").read_text()

            stale_head = repo_head()
            stale_store = base / "stale-comments.json"
            stale_intent = produce_intent(base / "intent-stale", at_head=stale_head, store=stale_store)
            (repo / "advance.md").write_text("advance\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "advance"], check=True)
            head = repo_head()

            def prepare_case(
                name: str, *, receipt_kwargs: dict | None = None,
                verdict_kwargs: dict | None = None, write_verdict: bool = True,
                produce_fresh: bool = True, intent_text: str | None = None,
                intent_store_from: Path | None = None,
                other_stream_issue: str | None = None,
            ) -> tuple[Path, Path, Path]:
                case = base / "cases" / name
                stream = case / "streams" / "TUR-1"
                store = case / "comments.json"
                kwargs: dict = {"caller": caller}
                kwargs.update(receipt_kwargs or {})
                self._write_persistent_orchestrator_receipt(stream / "receipt.toml", **kwargs)
                if other_stream_issue is not None:
                    self._write_persistent_orchestrator_receipt(
                        case / "streams" / other_stream_issue.lower() / "receipt.toml",
                        caller=caller, issue=other_stream_issue,
                    )
                if write_verdict:
                    values: dict = {"head": head, "repo": str(repo)}
                    values.update(verdict_kwargs or {})
                    self._write_verdict_journal(case / "verdict.json", **values)
                if produce_fresh:
                    # Command-published fresh surface into this case's own store.
                    produce_intent(stream, at_head=head, store=store)
                elif intent_store_from is not None:
                    shutil.copyfile(intent_store_from, store)
                if intent_text is not None:
                    (stream / "intent-record.toml").write_text(intent_text)
                return case, stream / "receipt.toml", store

            def transition(
                case: Path, receipt: Path, *, expected_state: str = "Todo",
                use_stream: Path | None = None, include_new_flags: bool = True,
                env: dict | None = None,
            ):
                argv = [
                    str(CONTROL), "linear-transition", "TUR-1",
                    "--expected", expected_state, "--target", "Shaped",
                    "--progress", str(case / "progress.toml"),
                    "--status", str(case / "status.md"),
                    "--parent", "epic-opus", "--outcome", "shaped", "--gate", "review",
                    "--caller", caller,
                ]
                if use_stream is not None:
                    argv += ["--stream", str(use_stream)]
                else:
                    argv += ["--receipt", str(receipt)]
                if include_new_flags:
                    argv += ["--verdict-journal", str(case / "verdict.json"), "--repo", str(repo)]
                return subprocess.run(argv, env=env or base_env, capture_output=True, text=True)

            # Accept path: the full authority tuple admits exactly one
            # transition from each shaping entry state.
            for expected_state in ("Ideas", "Todo"):
                with self.subTest(case=f"valid-{expected_state}"):
                    case, receipt, store = prepare_case(f"valid-{expected_state}")
                    state_file = case / "state.txt"
                    state_file.write_text(expected_state)
                    call_log = case / "calls.log"
                    env = dict(
                        base_env, STATE_FILE=str(state_file),
                        GH_HEAD=head, GH_COMMENTS=str(store), CALL_LOG=str(call_log),
                    )
                    result = transition(case, receipt, expected_state=expected_state, env=env)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("Shaped", state_file.read_text())

            # Retired worker-receipt path: purpose shaping-review plus a
            # [shaping] table is the retired shape and is rejected even when
            # the old published-marker verdict it used to consume is live.
            with self.subTest(case="retired_worker_receipt"):
                case, receipt, store = prepare_case(
                    "retired_worker_receipt",
                    receipt_kwargs={
                        "purpose": "shaping-review",
                        "shaping": {"repo": "org/repo", "pr": 7, "head": head},
                    },
                    write_verdict=False, produce_fresh=False,
                )
                normalized_issue = {"identifier": "TUR-1", "state": "Todo", "updatedAt": "t1"}
                binding = f"linear:TUR-1:{exact_fingerprint(normalized_issue)}"
                marker = verdict_body(
                    "shaping", "clear", head, [binding], [], "reviewer-receipt-xyz",
                    conversation_log_references=["session-log-1"],
                    conversation_cutoff="2026-07-18T00:00:00Z",
                )
                store.write_text(json.dumps([{"id": 1, "body": marker}]))
                state_file = case / "state.txt"
                state_file.write_text("Todo")
                call_log = case / "calls.log"
                env = dict(
                    base_env, STATE_FILE=str(state_file),
                    GH_HEAD=head, GH_COMMENTS=str(store), CALL_LOG=str(call_log),
                )
                result = transition(case, receipt, include_new_flags=False, env=env)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("retired", result.stderr)
                self.assertEqual("Todo", state_file.read_text())
                self.assertFalse(call_log.exists())

            module = _load_octo_control_module()

            def forged_record(*, head_value: str, repo_value: str, pr_value: int) -> str:
                # A hand-authored valid-head record whose surface_sha256 is a
                # correct self-digest, but with NO matching live PR comment.
                recorded_at = "2026-07-21T00:00:00+00:00"
                body = module._intent_surface_body(
                    repo=repo_value, pr=pr_value, head=head_value,
                    intent_ref="ruling-15", recorded_at=recorded_at,
                )
                digest = module._surface_digest(body)
                return (
                    'schema_version = 1\nintent_ref = "ruling-15"\n'
                    f'head = "{head_value}"\nrecorded_at = "{recorded_at}"\n'
                    f'repo = {json.dumps(repo_value)}\npr = {pr_value}\n'
                    f'surface_sha256 = "{digest}"\n'
                )

            forged_valid_head = forged_record(head_value=head, repo_value=str(repo), pr_value=7)

            # Group 1: rejections that fail before any external call, so no
            # Linear or GitHub call is logged.
            pre_call_rejections = [
                ("stream_authority_forbidden", {"use_stream": True}, "persistent receipt authority"),
                ("unverified_receipt", {"receipt_kwargs": {"verified": False}}, "bootstrap not verified"),
                ("wrong_role", {"receipt_kwargs": {"role": "implementer"}}, "issue-orchestrator role"),
                ("foreign_caller", {"receipt_kwargs": {"caller": "someone-else"}}, "receipt-bound session"),
                ("missing_launch_revision", {"receipt_kwargs": {"omit_revision": True}}, "launch revision"),
                ("pass_purpose_receipt", {"receipt_kwargs": {"purpose": "delivery"}}, "pass purpose"),
                ("orchestrator_without_shaping", {"receipt_kwargs": {"capabilities": ()}}, "lack shaping"),
                ("epic_orchestrator", {"receipt_kwargs": {"issue": None}}, "epic orchestrator"),
                ("other_issue_receipt", {"receipt_kwargs": {"issue": "TUR-999"}}, "another issue"),
                ("registered_to_other_issue", {"other_stream_issue": "TUR-2"}, "live stream registry"),
                ("missing_new_flags", {"include_new_flags": False}, "--verdict-journal"),
                ("missing_verdict_journal", {"write_verdict": False}, "journalled shaping verdict missing"),
                ("blocking_verdict", {"verdict_kwargs": {"verdict": "blocking"}}, "not clear"),
                ("verdict_issue_mismatch", {"verdict_kwargs": {"issue": "TUR-999"}}, "verdict issue mismatch"),
                (
                    "interim_ack_echo_verdict",
                    {"verdict_kwargs": {"provenance": False, "ack_echo": True}},
                    "rollout-record provenance",
                ),
                # Repo-arg bind: a clear verdict for a different repo than the
                # CLI repo argument is rejected before any GitHub call.
                (
                    "verdict_repo_ne_cli_repo",
                    {"verdict_kwargs": {"repo": "org/other"}},
                    "does not match CLI repo argument",
                ),
                # Missing/fabricated-shape intent records fail on read before
                # the live-surface fetch.
                ("missing_intent_record", {"produce_fresh": False, "intent_text": None}, "intent record missing"),
                (
                    "shape_forged_intent_record",
                    {
                        "produce_fresh": False,
                        "intent_text": (
                            'schema_version = 1\nintent_ref = "ruling-15"\n'
                            f'head = "{"f" * 40}"\nrecorded_at = "2026-07-21T00:00:00+00:00"\n'
                        ),
                    },
                    "repo missing",
                ),
            ]
            for name, overrides, fragment in pre_call_rejections:
                with self.subTest(case=name):
                    overrides = dict(overrides)
                    cmd_stream = overrides.pop("use_stream", False)
                    include_flags = overrides.pop("include_new_flags", True)
                    overrides.setdefault("produce_fresh", False)
                    overrides.setdefault("intent_text", forged_valid_head)
                    case, receipt, store = prepare_case(name, **overrides)
                    call_log = case / "calls.log"
                    env = dict(base_env, GH_HEAD=head, GH_COMMENTS=str(store), CALL_LOG=str(call_log))
                    result = transition(
                        case, receipt,
                        use_stream=(case / "streams" / "TUR-1") if cmd_stream else None,
                        include_new_flags=include_flags, env=env,
                    )
                    self.assertNotEqual(0, result.returncode, name)
                    self.assertIn(fragment, result.stderr, result.stderr)
                    self.assertFalse(call_log.exists(), name)

            # Group 2: intent-record rejections that legitimately reach the
            # gh surface fetch; they must reject and never mutate Linear.
            surface_rejections = [
                # CORE forgery distinction: a valid-head, correctly self-
                # digested local record with NO matching command-published PR
                # surface is rejected.
                (
                    "forged_valid_head_no_published_surface",
                    {"produce_fresh": False, "intent_text": forged_valid_head},
                    "no command-published surface",
                ),
                # A wrong-head command-produced record (its own live surface
                # exists) is rejected against the journalled verdict head.
                (
                    "wrong_head_intent_record",
                    {
                        "produce_fresh": False, "intent_text": stale_intent,
                        "intent_store_from": stale_store,
                    },
                    "head mismatch with journalled verdict",
                ),
            ]
            for name, overrides, fragment in surface_rejections:
                with self.subTest(case=name):
                    case, receipt, store = prepare_case(name, **overrides)
                    state_file = case / "state.txt"
                    state_file.write_text("Todo")
                    env = dict(base_env, STATE_FILE=str(state_file), GH_HEAD=head, GH_COMMENTS=str(store))
                    result = transition(case, receipt, env=env)
                    self.assertNotEqual(0, result.returncode, name)
                    self.assertIn(fragment, result.stderr, result.stderr)
                    self.assertEqual("Todo", state_file.read_text(), name)

    def test_linear_transition_to_shaped_verifies_fresh_pr_head_then_mutates_reads_back_and_notifies(self) -> None:
        # After the compare Linear read, Shaped refetches the exact live PR
        # head and requires it to equal the journalled verdict head, so a
        # stale journalled verdict rejects before any mutation; the exact
        # fresh-head clear verdict permits one update, readback, status, and
        # notify, in that order (compare, mutate, readback, notify preserved).
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            fake_bin = base / "bin"
            self._install_shaped_fakes(fake_bin)

            for name, live_head, expect_ok in (
                ("valid", head, True),
                ("stale_journalled_verdict", "1" * 40, False),
            ):
                with self.subTest(case=name):
                    case = base / "cases" / name
                    stream = case / "streams" / "TUR-1"
                    receipt = stream / "receipt.toml"
                    store = case / "comments.json"
                    self._write_persistent_orchestrator_receipt(receipt, caller="issue-opus")
                    self._write_verdict_journal(case / "verdict.json", head=head, repo=str(repo))
                    # Publish the command surface into the case store (no call
                    # log) so the later verify finds the live PR comment.
                    produced = subprocess.run(
                        [
                            str(CONTROL), "intent-record", "--stream-dir", str(stream),
                            "--intent-ref", "ruling-15", "--repo", str(repo), "--pr", "7",
                        ],
                        capture_output=True, text=True,
                        env=dict(
                            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                            GH_HEAD=head, GH_COMMENTS=str(store),
                        ),
                    )
                    self.assertEqual(0, produced.returncode, produced.stderr)
                    state_file = case / "state.txt"
                    state_file.write_text("Todo")
                    call_log = case / "calls.log"
                    env = dict(
                        os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                        STATE_FILE=str(state_file), CALL_LOG=str(call_log),
                        GH_HEAD=live_head, GH_COMMENTS=str(store),
                    )
                    result = subprocess.run(
                        [
                            str(CONTROL), "linear-transition", "TUR-1",
                            "--expected", "Todo", "--target", "Shaped",
                            "--progress", str(case / "progress.toml"),
                            "--status", str(case / "status.md"),
                            "--parent", "epic-opus", "--outcome", "shaped", "--gate", "review",
                            "--caller", "issue-opus", "--receipt", str(receipt),
                            "--verdict-journal", str(case / "verdict.json"), "--repo", str(repo),
                        ],
                        env=env, capture_output=True, text=True,
                    )
                    calls = call_log.read_text().splitlines() if call_log.exists() else []
                    # The operator-intent surface fetch precedes the compare
                    # read, then fresh-head, mutate, readback, notify.
                    self.assertTrue(calls[0].startswith("gh api"), calls)
                    self.assertIn("/comments", calls[0])
                    if expect_ok:
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertEqual("Shaped", state_file.read_text())
                        self.assertEqual(6, len(calls), calls)
                        self.assertTrue(calls[1].startswith("linear issue view"), calls)
                        self.assertTrue(calls[2].startswith("gh pr view 7"), calls)
                        self.assertIn("headRefOid", calls[2])
                        self.assertTrue(calls[3].startswith("linear issue update"), calls)
                        self.assertTrue(calls[4].startswith("linear issue view"), calls)
                        self.assertTrue(calls[5].startswith("herdr-say "), calls)
                    else:
                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual("Todo", state_file.read_text())
                        self.assertEqual(3, len(calls), calls)
                        self.assertTrue(calls[1].startswith("linear issue view"), calls)
                        self.assertTrue(calls[2].startswith("gh pr view 7"), calls)


if __name__ == "__main__":
    unittest.main()


class SweepStreamLivenessTests(unittest.TestCase):
    # Simple liveness law: real surfaces only (receipt-derived transcript
    # mtimes, status gate lines, XDG inbox and message state); classification
    # is advisory and never enters the digested reconcile snapshot.
    def _stream_with_receipt(self, base: Path, name: str, projects: Path, now: float) -> tuple[Path, Path]:
        stream = base / "streams" / name
        stream.mkdir(parents=True)
        worktree = base / "wt" / name
        worktree.mkdir(parents=True)
        session_id = f"sess-{name}"
        (stream / "receipt.toml").write_text(
            f'[workspace]\nworktree = "{worktree}"\n[bootstrap]\nprovider_session_id = "{session_id}"\n'
        )
        module = _load_operator_sweep_module()
        sanitized = module.sanitize_project_dir(str(worktree))
        transcript_dir = projects / sanitized
        transcript_dir.mkdir(parents=True)
        transcript = transcript_dir / f"{session_id}.jsonl"
        transcript.write_text("{}\n")
        return stream, transcript

    def test_liveness_reports_from_real_surfaces_only(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            now = 1_000_000.0
            projects = base / "projects"
            inbox_root = base / "inbox"
            messages = base / "messages"
            messages.mkdir()
            stream, transcript = self._stream_with_receipt(base, "tur-1", projects, now)
            os.utime(transcript, (now - 600, now - 600))
            (stream / "status.md").write_text(
                "# s\n- waiting-on: operator: Please approve.\n- wf_abc123-def running.\n"
            )
            os.utime(stream / "status.md", (now - 300, now - 300))
            (messages / "m1.toml").write_text(
                'message_id = "m1"\ntarget = "tur-1"\nstatus = "pending"\n'
            )
            live = module.stream_liveness(
                stream, inbox_root, messages, idle_seconds=3600, now=now, projects_root=projects
            )
            self.assertEqual("waiting", live["classification"])
            self.assertEqual("operator", live["wait_owner"])
            self.assertEqual("Please approve.", live["open_ask"])
            self.assertEqual(["wf_abc123-def"], live["inflight_workflows"])
            self.assertEqual(["m1"], live["undelivered_queue"])
            # newest receipt wins; ask consumed once session activity postdates it
            os.utime(transcript, (now - 60, now - 60))
            consumed = module.stream_liveness(
                stream, inbox_root, messages, idle_seconds=3600, now=now, projects_root=projects
            )
            self.assertTrue(consumed["ask_consumed"])
            self.assertEqual("active", consumed["classification"])

    def test_idle_stream_without_wait_owner_is_suspected_stuck_and_status_age_never_counts(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            now = 1_000_000.0
            projects = base / "projects"
            stream, transcript = self._stream_with_receipt(base, "tur-2", projects, now)
            os.utime(transcript, (now - 9000, now - 9000))
            (stream / "status.md").write_text("# fresh status, no gate lines\n")
            os.utime(stream / "status.md", (now - 5, now - 5))
            live = module.stream_liveness(
                stream, base / "inbox", base / "messages", idle_seconds=3600, now=now, projects_root=projects
            )
            self.assertEqual("suspected-stuck", live["classification"])

    def test_reconciler_reads_current_liveness_at_launch_time(self) -> None:
        # v15 finding red: on a changed sweep, liveness.json must exist with
        # CURRENT bytes when the reconciler runs, and a failed run leaves no
        # liveness artifact. The fake reconciler snapshots the file it can read.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/TUR-9"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("- waiting-on: operator: Approve please.\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "s"\nowner_route = "r"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            probe = FAKE_RECONCILER_CLAUDE.replace(
                "prompt=\"$(cat)\"",
                "cat \"$LIVENESS_PROBE\" >>\"$CALL_LOG\" 2>/dev/null || printf 'liveness-missing\\n' >>\"$CALL_LOG\"\nprompt=\"$(cat)\"",
            )
            (fake_bin / "claude").write_text(probe)
            (fake_bin / "claude").chmod(0o755)
            (fake_bin / "operator-say").write_text("#!/usr/bin/env bash\nexit 0\n")
            (fake_bin / "operator-say").chmod(0o755)
            env = dict(
                os.environ,
                PATH=f"{fake_bin}:{os.environ['PATH']}",
                CALL_LOG=str(log),
                LIVENESS_PROBE=str(control / "liveness.json"),
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
            )
            result = subprocess.run(
                [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            calls = log.read_text()
            self.assertNotIn("liveness-missing", calls)
            self.assertIn('"wait_owner": "operator"', calls)
            self.assertIn("Approve please.", calls)

    def test_sweep_invokes_operator_say_by_absolute_path(self) -> None:
        # Live defect: timer-run sweep crashed with FileNotFoundError because
        # operator-say was invoked by bare name under systemd's bare PATH. The
        # sweep resolves the helper from its own root, overridable for tests
        # via OCTO_OPERATOR_SAY.
        source = SWEEP.read_text()
        self.assertNotIn('"operator-say", "--kind"', source)
        self.assertIn("OCTO_OPERATOR_SAY", source)
        self.assertIn('skills/herdr-comms/assets/operator-say', source)

    def test_liveness_never_enters_the_digested_snapshot(self) -> None:
        source = SWEEP.read_text()
        # the digested snapshot is parts + declared facts only; liveness goes to
        # stdout and control/liveness.json, so digests verify and never churn.
        self.assertIn('"# Stream snapshot\\n\\n" + "\\n".join(parts)', source.replace("\\n","\\n"))
        self.assertNotIn("stream_liveness", source.split("normalized_facts = json.dumps")[1].split("fingerprint")[0])
        self.assertIn('control / "liveness.json"', source)
        for phantom in ("waiting.toml", "inflight.toml", "pane-activity.txt", "herdr-queue", "observations"):
            self.assertNotIn(phantom, source)


def _load_octo_control_module():
    loader = importlib.machinery.SourceFileLoader("octo_control", str(CONTROL))
    spec = importlib.util.spec_from_file_location("octo_control", CONTROL, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# A stateful gh fake for the intent-record PR/status surface (TUR-447 F5,
# Units J and L): it persists issue comments in $GH_COMMENTS as a JSON list so
# a POST/PATCH publication is actually readable back on a later paginate or
# single-comment read, mirrors the exact gh api shapes octo-control invokes,
# and answers pr view --json headRefOid from $GH_HEAD. This lets a real
# command-published surface exist for verification while a hand-authored local
# record has no matching live comment.
_GH_INTENT_FAKE = r"""#!/usr/bin/env python3
import json
import os
import sys

argv = sys.argv[1:]
log = os.environ.get("CALL_LOG")
if log:
    with open(log, "a") as handle:
        handle.write("gh " + " ".join(argv) + "\n")
store = os.environ["GH_COMMENTS"]


def load():
    if not os.path.exists(store):
        return []
    with open(store) as handle:
        text = handle.read().strip()
    return json.loads(text) if text else []


def save(items):
    with open(store, "w") as handle:
        handle.write(json.dumps(items))


def field(flag):
    for value in argv:
        if value.startswith(flag + "="):
            return value.split("=", 1)[1]
    return None


if argv[:2] == ["pr", "view"]:
    print(json.dumps({"headRefOid": os.environ.get("GH_HEAD", "")}))
    sys.exit(0)

if argv[0] == "api":
    method = None
    if "--method" in argv:
        method = argv[argv.index("--method") + 1]
    # endpoint is the first bare token after api/flags
    endpoint = None
    skip = {"api", "--method", "-f", "--paginate"}
    idx = 1
    while idx < len(argv):
        token = argv[idx]
        if token == "--method":
            idx += 2
            continue
        if token == "-f":
            idx += 2
            continue
        if token == "--paginate":
            idx += 1
            continue
        endpoint = token
        break
    parts = endpoint.split("/")
    if endpoint.endswith("/comments") and (method is None or method == "GET"):
        print(json.dumps(load()))
        sys.exit(0)
    if endpoint.endswith("/comments") and method == "POST":
        items = load()
        new = {"id": len(items) + 1, "body": field("body"),
               "html_url": "https://example/comment/%d" % (len(items) + 1)}
        items.append(new)
        save(items)
        print(json.dumps(new))
        sys.exit(0)
    if "/comments/" in endpoint and method == "PATCH":
        cid = int(parts[-1])
        items = load()
        for item in items:
            if item["id"] == cid:
                item["body"] = field("body")
                save(items)
                print(json.dumps(item))
                sys.exit(0)
        sys.exit(3)
    if "/comments/" in endpoint and method is None:
        cid = int(parts[-1])
        for item in load():
            if item["id"] == cid:
                print(json.dumps(item))
                sys.exit(0)
        sys.exit(4)
sys.exit(9)
"""


def _install_gh_intent_fake(fake_bin: Path) -> None:
    fake_bin.mkdir(parents=True, exist_ok=True)
    gh = fake_bin / "gh"
    gh.write_text(_GH_INTENT_FAKE)
    gh.chmod(0o755)


class IntentRecordTests(unittest.TestCase):
    # Unit L operator-intent record producer (delivery-lifecycle
    # shaping-operator-approval and shaping-operator-approval-binding,
    # operator-control supervision-operator-gate-no-hashes and
    # supervision-default-action, role-runtime launch-shaping-authority):
    # tooling stamps the exact head automatically at action time under prior
    # explicit operator intent and records the binding on machine surfaces,
    # never inside an operator notification.

    def _init_repo(self, repo: Path) -> str:
        _init_target_repo(repo)
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def _surface_env(self, base: Path, head: str) -> dict:
        fake_bin = base / "bin"
        _install_gh_intent_fake(fake_bin)
        return dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
            GH_HEAD=head, GH_COMMENTS=str(base / "comments.json"),
        )

    def test_intent_record_stamps_the_current_exact_head_at_action_time(self) -> None:
        # shaping-operator-approval-binding: tooling captures the head itself;
        # the record binds intent reference, exact head, a timestamp, and the
        # command-published surface repo/PR/digest, and success reports the
        # record path plus bound head machine-readably.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            env = self._surface_env(base, head)
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record",
                    "--stream-dir", str(stream), "--intent-ref", "ruling-15",
                    "--repo", str(repo), "--pr", "7",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            record_path = stream / "intent-record.toml"
            self.assertEqual(str(record_path.resolve()), payload["record"])
            self.assertEqual(head, payload["head"])
            with record_path.open("rb") as handle:
                record = tomllib.load(handle)
            self.assertEqual(1, record["schema_version"])
            self.assertEqual("ruling-15", record["intent_ref"])
            self.assertEqual(head, record["head"])
            self.assertEqual(str(repo), record["repo"])
            self.assertEqual(7, record["pr"])
            self.assertRegex(record["surface_sha256"], r"^[0-9a-f]{64}$")
            from datetime import datetime
            datetime.fromisoformat(record["recorded_at"])

    def test_intent_record_rejects_missing_or_empty_intent_ref(self) -> None:
        # shaping-operator-approval: the durable operator-intent decision is
        # the authorization; a record without an intent reference records no
        # prior explicit operator intent and must not exist.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            self._init_repo(repo)
            stream = base / "stream"
            missing = subprocess.run(
                [str(CONTROL), "intent-record", "--stream-dir", str(stream), "--repo", str(repo)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, missing.returncode)
            self.assertFalse((stream / "intent-record.toml").exists())
            for empty_ref in ("", "   "):
                result = subprocess.run(
                    [
                        str(CONTROL), "intent-record", "--stream-dir", str(stream),
                        "--intent-ref", empty_ref, "--repo", str(repo),
                    ],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(0, result.returncode, empty_ref)
                self.assertFalse((stream / "intent-record.toml").exists())

    def test_intent_record_has_no_head_flag_so_a_manual_head_is_never_accepted(self) -> None:
        # supervision-operator-gate-no-hashes: no human or agent supplies the
        # head; only the tool stamps it at action time, so --head cannot exist.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            self._init_repo(repo)
            stream = base / "stream"
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(repo),
                    "--head", "0" * 40,
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("--head", result.stderr)
            self.assertFalse((stream / "intent-record.toml").exists())

    def test_intent_record_replaces_a_partial_or_corrupt_record_atomically(self) -> None:
        # A partial or corrupt existing record is replaced whole via the
        # atomic-write pattern, never appended, and no temporary file remains.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            stream.mkdir()
            (stream / "intent-record.toml").write_text('intent_ref = "trunc')
            env = self._surface_env(base, head)
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--pr", "7",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            with (stream / "intent-record.toml").open("rb") as handle:
                record = tomllib.load(handle)
            self.assertEqual(head, record["head"])
            self.assertNotIn("trunc", (stream / "intent-record.toml").read_text())
            self.assertEqual(["intent-record.toml"], sorted(p.name for p in stream.iterdir()))

    def test_intent_record_readback_mismatch_fails_nonzero(self) -> None:
        # Compare, act, readback: success is reported only after the persisted
        # bytes are read back and verified; a divergent persisted record fails.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            fake_bin = base / "bin"
            _install_gh_intent_fake(fake_bin)
            module = _load_octo_control_module()
            original = module._atomic_write_text

            def corrupting_write(path, text):
                original(path, text.replace(head, "0" * 40))

            module._atomic_write_text = corrupting_write
            args = type("Args", (), {
                "stream_dir": str(stream), "intent_ref": "ruling-15",
                "repo": str(repo), "pr": 7, "verify": False,
            })()
            saved = dict(os.environ)
            os.environ["PATH"] = f"{fake_bin}:{os.environ['PATH']}"
            os.environ["GH_HEAD"] = head
            os.environ["GH_COMMENTS"] = str(base / "comments.json")
            try:
                with self.assertRaises(module.GateError):
                    module.command_intent_record(args)
            finally:
                os.environ.clear()
                os.environ.update(saved)

    def test_intent_record_verify_rejects_fabricated_records(self) -> None:
        # Consumer red for Unit J (launch-shaping-authority): a missing,
        # fabricated, or wrong-head operator-intent record carries no shaping
        # authority; fabrication without the command fails the verify path.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            stream.mkdir()
            record_path = stream / "intent-record.toml"
            verify = [
                str(CONTROL), "intent-record", "--verify",
                "--stream-dir", str(stream), "--repo", str(repo),
            ]

            missing = subprocess.run(verify, capture_output=True, text=True)
            self.assertNotEqual(0, missing.returncode)

            record_path.write_text(
                'schema_version = 1\nintent_ref = "ruling-15"\n'
                f'head = "{head}"\n'
            )
            no_timestamp = subprocess.run(verify, capture_output=True, text=True)
            self.assertNotEqual(0, no_timestamp.returncode)

            record_path.write_text(
                'schema_version = 1\nintent_ref = "ruling-15"\n'
                f'head = "{"f" * 40}"\nrecorded_at = "2026-07-21T00:00:00+00:00"\n'
            )
            unknown_head = subprocess.run(verify, capture_output=True, text=True)
            self.assertNotEqual(0, unknown_head.returncode)

    def test_intent_record_verify_accepts_a_command_produced_record(self) -> None:
        # The verify path Unit J calls accepts exactly the record the producer
        # wrote, re-reading the live command-published PR surface and echoing
        # the bound head machine-readably.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            env = self._surface_env(base, head)
            produced = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--pr", "7",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, produced.returncode, produced.stderr)
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(head, payload["head"])
            self.assertEqual(7, payload["pr"])
            self.assertEqual(str((stream / "intent-record.toml").resolve()), payload["record"])


# A per-issue Linear fake: reads a JSON map {issue_id: state} from
# LINEAR_STATE_MAP and echoes the exact carried issue's state, logging each
# `linear issue view <id>` call so a test can assert every carried issue was
# read (multi-issue binding), not just one bound issue.
FAKE_PER_ISSUE_LINEAR = (
    "#!/usr/bin/env bash\n"
    "printf 'linear %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
    'issue=""\n'
    'for a in "$@"; do case "$a" in TUR-*|OCTO-*) issue="$a" ;; esac; done\n'
    'state="$(python3 -c \'import json,os,sys; print(json.load(open(os.environ[\"LINEAR_STATE_MAP\"])).get(sys.argv[1], \"Todo\"))\' "$issue")"\n'
    "python3 -c 'import json,sys; print(json.dumps({\"identifier\": sys.argv[1], \"state\": {\"name\": sys.argv[2]}, \"updatedAt\": \"2026-07-19T00:00:00Z\"}))' \"$issue\" \"$state\"\n"
)


def _sweep_stdout_json(stdout: str) -> dict:
    # Operator-gate lines are plain lines printed before the machine-readable
    # JSON, so the JSON is always the last non-empty stdout line.
    lines = [line for line in stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


class OperatorGateTests(unittest.TestCase):
    """TUR-489: sweep must loudly, unsuppressibly surface operator-gated Linear
    states (Source A) and open operator asks (Source B)."""

    def _write_owner(self, base: Path, control: Path) -> Path:
        owner = base / "operator-owner.toml"
        owner.write_text(
            f'schema_version = 1\nowner_session_id = "operator-1-session"\n'
            f'owner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
        )
        return owner

    def _fake_bins(self, base: Path, *, per_issue_linear: bool = True) -> tuple[Path, Path, dict]:
        fake_bin = base / "bin"
        fake_bin.mkdir()
        log = base / "calls.jsonl"
        (fake_bin / "claude").write_text(FAKE_RECONCILER_CLAUDE)
        (fake_bin / "operator-say").write_text(
            "#!/usr/bin/env bash\n"
            "printf 'operator %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            'for a in "$@"; do prev="${prev:-}"; if [[ "$prev" == "--artifact" ]]; then cat "$a" >>"$CALL_LOG"; fi; prev="$a"; done\n'
        )
        if per_issue_linear:
            (fake_bin / "linear").write_text(FAKE_PER_ISSUE_LINEAR)
        (fake_bin / "gh").write_text(
            "#!/usr/bin/env bash\nprintf 'gh %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            "cat <<'JSON'\n"
            '{"url": "https://github.com/org/repo/pull/6", "headRefOid": "abc123", '
            '"headRefName": "feature", "baseRefName": "main", '
            '"state": "OPEN", "reviewDecision": "", "statusCheckRollup": []}\n'
            "JSON\n"
        )
        for name in ("claude", "operator-say", "linear", "gh"):
            path = fake_bin / name
            if path.exists():
                path.chmod(0o755)
        env = dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
            OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
        )
        return fake_bin, log, env

    def test_t1_multi_issue_carried_states_are_all_read(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-carrier"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text(
                'schema_version = 1\n\n[linear]\nissues = ["TUR-454", "TUR-479"]\n'
            )
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-454": "Todo", "TUR-479": "Live"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            calls = log.read_text().splitlines()
            self.assertTrue(any("TUR-454" in line and line.startswith("linear ") for line in calls))
            self.assertTrue(any("TUR-479" in line and line.startswith("linear ") for line in calls))

    def test_t2_source_a_loud_line_for_gated_states(self) -> None:
        for gated_state, issue in (("In Staging", "TUR-479"), ("Awaiting Accept", "TUR-454")):
            with self.subTest(state=gated_state):
                with tempfile.TemporaryDirectory() as td:
                    base = Path(td)
                    repo = base / "repo"
                    _init_target_repo(repo)
                    control = base / "control"
                    stream = control / "streams/tf-carrier"
                    stream.mkdir(parents=True)
                    (stream / "status.md").write_text("Outcome: ready\n")
                    (stream / "sources.toml").write_text(
                        f'schema_version = 1\n\n[linear]\nissue = "{issue}"\n'
                    )
                    owner = self._write_owner(base, control)
                    fake_bin, log, env = self._fake_bins(base)
                    state_map = base / "state-map.json"
                    state_map.write_text(json.dumps({issue: gated_state}))
                    env["LINEAR_STATE_MAP"] = str(state_map)
                    command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
                    result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
                    self.assertIn(
                        f"OPERATOR ACTION NEEDED: {issue} {gated_state}", result.stdout
                    )
                    # delivered to the operator too (operator-say artifact echoed to log)
                    self.assertIn(
                        f"OPERATOR ACTION NEEDED: {issue} {gated_state}", log.read_text()
                    )

    def test_t3_gate_line_survives_unchanged_fingerprint_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-carrier"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text('schema_version = 1\n\n[linear]\nissue = "TUR-479"\n')
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            first = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            second = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertFalse(_sweep_stdout_json(second.stdout)["changed"])
            # Even though the fingerprint is unchanged (noop path), the loud
            # operator-gate line is STILL surfaced.
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", second.stdout)

    def test_t4_gated_stream_classifies_waiting_on_operator_despite_busy_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-carrier"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text('schema_version = 1\n\n[linear]\nissue = "TUR-454"\n')
            # A fresh (busy) transcript: build a receipt + a live transcript file.
            projects = base / "projects"
            worktree = base / "wt"
            worktree.mkdir()
            session = "sess-busy"
            sanitized = __import__("re").sub(r"[^A-Za-z0-9]", "-", str(worktree))
            tpath = projects / sanitized / f"{session}.jsonl"
            tpath.parent.mkdir(parents=True)
            tpath.write_text("{}\n")
            (stream / "receipt.toml").write_text(
                'schema_version = 1\n\n[bootstrap]\nprovider_session_id = '
                f'"{session}"\n\n[workspace]\nworktree = "{worktree}"\n'
            )
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-454": "Awaiting Accept"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["HOME"] = str(base)  # keep default projects root away from real home
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            liveness = json.loads((control / "liveness.json").read_text())
            self.assertEqual("waiting-on-operator", liveness["tf-carrier"]["classification"])

    def test_t4b_source_a_gate_wait_carries_operator_owner_and_gate_reason(self) -> None:
        # RULING-46 / ruling-46 (TUR-489): a Source-A-ONLY gated stream (carried
        # issue in an operator-gated Linear state, NO operator-waits stamp, NO
        # status waiting-on line) must ALSO carry wait_owner=operator and an
        # open_ask holding the gate reason, so every waiting-on-operator stream
        # shares one taxonomy and the reconciler stops flagging empty wait_owner.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/src-a-only"
            stream.mkdir(parents=True)
            # No waiting-on line; the operator gate is derived purely from state.
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text('schema_version = 1\n\n[linear]\nissue = "TUR-479"\n')
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["HOME"] = str(base)
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            entry = json.loads((control / "liveness.json").read_text())["src-a-only"]
            self.assertEqual("waiting-on-operator", entry["classification"])
            self.assertEqual("operator", entry["wait_owner"])
            self.assertIn("TUR-479", entry["open_ask"])
            self.assertIn("In Staging", entry["open_ask"])
            self.assertFalse(entry["ask_consumed"])
            # The loud operator-gate lines are unchanged by the taxonomy fix.
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", result.stdout)

    def test_t4c_source_b_ask_and_non_gated_stream_taxonomy_unchanged(self) -> None:
        # Regression: a Source-B stamped stream keeps wait_owner=operator with its
        # verbatim ask, and a non-gated active stream keeps wait_owner='' with its
        # normal (non-operator) classification.
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            now = 1_000_000.0
            projects = base / "projects"
            projects.mkdir()
            inbox = base / "inbox"
            messages = base / "messages"
            messages.mkdir()

            # Source-B stamped stream: verbatim status ask preserved, owner operator.
            stream_b = control_stream = base / "streams" / "src-b"
            stream_b.mkdir(parents=True)
            (stream_b / "status.md").write_text("- waiting-on: operator: Approve promotion of TUR-479?\n")
            os.utime(stream_b / "status.md", (now - 60, now - 60))
            live_b = module.stream_liveness(
                stream_b, inbox, messages, idle_seconds=3600, now=now,
                projects_root=projects, operator_gated=True,
                operator_gate_reason="TUR-479 In Staging - verify staging then promote or hold",
            )
            self.assertEqual("waiting-on-operator", live_b["classification"])
            self.assertEqual("operator", live_b["wait_owner"])
            # A real Source-B/status open ask is preferred over the gate reason.
            self.assertEqual("Approve promotion of TUR-479?", live_b["open_ask"])

            # Non-gated active stream: no operator owner, normal classification.
            stream_c = base / "streams" / "src-c"
            stream_c.mkdir(parents=True)
            (stream_c / "status.md").write_text("Outcome: working\n")
            os.utime(stream_c / "status.md", (now - 30, now - 30))
            live_c = module.stream_liveness(
                stream_c, inbox, messages, idle_seconds=3600, now=now,
                projects_root=projects, operator_gated=False,
            )
            self.assertEqual("", live_c["wait_owner"])
            self.assertEqual("", live_c["open_ask"])
            self.assertIn(live_c["classification"], {"active", "suspected-stuck"})

    def test_t5_source_b_operator_ask_surfaces_then_clears_on_ack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/scratch-ask"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: working\n")
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base, per_issue_linear=False)

            xdg = base / "xdg"
            env["XDG_STATE_HOME"] = str(xdg)
            env["HOME"] = str(base)

            # A fake herdr resolves the operator pane and accepts the send, so
            # herdr-say follows its normal transport path and leaves a pending
            # message record the operator answer relay (herdr-ack) later processes.
            (fake_bin / "herdr").write_text(
                "#!/usr/bin/env bash\n"
                'case "$1 $2" in\n'
                '  "agent get") echo \'{"result":{"agent":{"pane_id":"%1:p0"}}}\' ;;\n'
                '  "pane read") echo "" ;;\n'
                "  *) exit 0 ;;\n"
                "esac\n"
            )
            (fake_bin / "herdr").chmod(0o755)

            # The lane operator-ask path stamps a mechanical per-stream wait.
            herdr_say = ROOT / "skills/herdr-comms/assets/herdr-say"
            ask = "Approve promotion of TUR-479 to Live?"
            stamp_env = dict(env, OCTO_STREAM="scratch-ask")
            said = subprocess.run(
                [str(herdr_say), "--kind", "question", "operator-1", ask],
                env=stamp_env, capture_output=True, text=True,
            )
            # herdr-say may not resolve a real pane; the stamp must be written
            # regardless (mechanical, pre-transport).
            waits_dir = xdg / "octo-lite" / "operator-waits"
            self.assertTrue((waits_dir / "scratch-ask.toml").is_file(), said.stderr)
            with (waits_dir / "scratch-ask.toml").open("rb") as handle:
                stamp = tomllib.load(handle)
            self.assertEqual("operator", stamp["owner"])
            self.assertEqual(ask, stamp["ask"])
            message_id = stamp["message_id"]

            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertIn(f"OPERATOR ACTION NEEDED: scratch-ask asks: {ask}", result.stdout)

            # Operator answer relay: ack of that exact ask clears the stamp.
            herdr_ack = ROOT / "skills/herdr-comms/assets/herdr-ack"
            subprocess.run(
                [str(herdr_ack), message_id, "acknowledged", "--by", "operator-1"],
                env=env, capture_output=True, text=True, check=True,
            )
            self.assertFalse((waits_dir / "scratch-ask.toml").is_file())
            after = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertNotIn("OPERATOR ACTION NEEDED: scratch-ask asks:", after.stdout)

    # TUR-489 real-stream shape: production streams have NO sources.toml and NO
    # receipt [issue] table. Carried issues are DERIVED from the stream's other
    # structured declarations (review/delivery envelopes and the status Issues
    # line). These tests reproduce the exact tf-password-reset shape that the
    # sources.toml-only Source A missed live.

    def test_RT_status_line_derives_carried_issues_from_status_issues_line(self) -> None:
        # Exact tf-password-reset shape: no sources.toml, no receipt [issue],
        # only an anchored `Issues:` line carrying TUR-454 + TUR-479. TUR-479 is
        # In Staging (operator-gated) and must surface loudly.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-password-reset"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text(
                "# tf-password-reset\n\n"
                "Outcome: shaping\n"
                "Issues: TUR-454 (Todo, PARKED behind infra) - TUR-479 (Shaped -> In Staging)\n"
            )
            # A receipt exists but carries NO [issue] table (confirmed real shape).
            (stream / "receipt.toml").write_text(
                'schema_version = 1\n\n[bootstrap]\nprovider_session_id = "sess-x"\n'
                '\n[workspace]\nworktree = "/nonexistent/wt"\n'
            )
            self.assertFalse((stream / "sources.toml").exists())
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-454": "Todo", "TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["HOME"] = str(base)
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            calls = log.read_text().splitlines()
            # BOTH carried issues are read from Linear.
            self.assertTrue(any("TUR-454" in line and line.startswith("linear ") for line in calls))
            self.assertTrue(any("TUR-479" in line and line.startswith("linear ") for line in calls))
            # TUR-479 In Staging surfaces loudly.
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", result.stdout)
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", log.read_text())

    def test_RT_envelope_derives_carried_issue_from_review_envelope(self) -> None:
        # A stream with a shaping-review-envelope.toml top-level issue and NO
        # sources.toml: the envelope's issue is derived and read.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-envelope"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: shaping\n")
            (stream / "shaping-review-envelope.toml").write_text(
                'schema_version = 1\nissue = "TUR-456"\npurpose = "shaping-review"\n'
            )
            self.assertFalse((stream / "sources.toml").exists())
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-456": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["HOME"] = str(base)
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            calls = log.read_text().splitlines()
            self.assertTrue(any("TUR-456" in line and line.startswith("linear ") for line in calls))
            self.assertIn("OPERATOR ACTION NEEDED: TUR-456 In Staging", result.stdout)

    def test_RT_noise_guard_prose_tur_ids_never_surface(self) -> None:
        # A status.md that mentions many TUR-ids in PROSE (roadmap narrative),
        # none on an anchored `Issues:` line: NONE of them are derived or read,
        # so the stream contributes NO operator-gate line.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-roadmap"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text(
                "# Roadmap status\n\n"
                "This quarter touches TUR-101, TUR-107, and later TUR-222.\n"
                "Prior work in TUR-303 and TUR-404 informs TUR-505 planning.\n"
            )
            self.assertFalse((stream / "sources.toml").exists())
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            # Even if these ids WERE gated, they must never be read.
            state_map.write_text(json.dumps({
                "TUR-101": "In Staging", "TUR-107": "In Staging",
                "TUR-222": "In Staging", "TUR-303": "In Staging",
                "TUR-404": "In Staging", "TUR-505": "In Staging",
            }))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["HOME"] = str(base)
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertNotIn("OPERATOR ACTION NEEDED", result.stdout)
            gate = _sweep_stdout_json(result.stdout).get("operator_gate", [])
            self.assertEqual([], gate)
            # No prose TUR-id was ever read from Linear.
            for pid in ("TUR-101", "TUR-107", "TUR-222", "TUR-303", "TUR-404", "TUR-505"):
                self.assertFalse(
                    any(pid in line and line.startswith("linear ") for line in log.read_text().splitlines()),
                    f"{pid} must not be read from Linear",
                )


# A per-issue linear fake that FAILS (exits nonzero) for a specific issue id read
# from LINEAR_FAIL_ISSUE, and otherwise echoes the mapped state. Reproduces the
# live crash cause: one carried-issue Linear read raising CalledProcessError.
FAKE_LINEAR_FAILS_FOR_ISSUE = (
    "#!/usr/bin/env bash\n"
    "printf 'linear %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
    'issue=""\n'
    'for a in "$@"; do case "$a" in TUR-*|OCTO-*) issue="$a" ;; esac; done\n'
    'if [[ "$issue" == "${LINEAR_FAIL_ISSUE:-}" ]]; then\n'
    '  echo "linear: read failed for $issue" >&2\n'
    "  exit 7\n"
    "fi\n"
    'state="$(python3 -c \'import json,os,sys; print(json.load(open(os.environ[\"LINEAR_STATE_MAP\"])).get(sys.argv[1], \"Todo\"))\' "$issue")"\n'
    "python3 -c 'import json,sys; print(json.dumps({\"identifier\": sys.argv[1], \"state\": {\"name\": sys.argv[2]}, \"updatedAt\": \"2026-07-19T00:00:00Z\"}))' \"$issue\" \"$state\"\n"
)


class SweepGracefulDegradationTests(unittest.TestCase):
    """TUR-489: a single carried-issue Linear read failure must NEVER crash the
    whole sweep (it took down the live timer). The failing issue is skipped and
    noted; every successfully-read operator-gated issue still surfaces."""

    def _write_owner(self, base: Path, control: Path) -> Path:
        owner = base / "operator-owner.toml"
        owner.write_text(
            f'schema_version = 1\nowner_session_id = "operator-1-session"\n'
            f'owner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
        )
        return owner

    def _fake_bins(self, base: Path) -> tuple[Path, Path, dict]:
        fake_bin = base / "bin"
        fake_bin.mkdir()
        log = base / "calls.jsonl"
        (fake_bin / "claude").write_text(FAKE_RECONCILER_CLAUDE)
        (fake_bin / "operator-say").write_text(
            "#!/usr/bin/env bash\n"
            "printf 'operator %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            'for a in "$@"; do prev="${prev:-}"; if [[ "$prev" == "--artifact" ]]; then cat "$a" >>"$CALL_LOG"; fi; prev="$a"; done\n'
        )
        (fake_bin / "linear").write_text(FAKE_LINEAR_FAILS_FOR_ISSUE)
        for name in ("claude", "operator-say", "linear"):
            (fake_bin / name).chmod(0o755)
        env = dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
            OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
        )
        return fake_bin, log, env

    def test_first_carried_read_failure_never_crashes_and_other_issue_surfaces(self) -> None:
        # Two carried issues; the FIRST (primary) read FAILS. The sweep must still
        # exit 0, still surface the second issue's operator-gate line, and skip +
        # note the failing one - never emit a gate line for the failing read.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-carrier"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text(
                'schema_version = 1\n\n[linear]\nissues = ["TUR-BAD", "TUR-479"]\n'
            )
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["LINEAR_FAIL_ISSUE"] = "TUR-BAD"
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            # No crash: exit 0.
            self.assertEqual(0, result.returncode, result.stderr)
            # The good carried issue still surfaces loudly.
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", result.stdout)
            # The failing issue was attempted (read) and then skipped + noted.
            calls = log.read_text().splitlines()
            self.assertTrue(any("TUR-BAD" in line and line.startswith("linear ") for line in calls))
            self.assertNotIn("OPERATOR ACTION NEEDED: TUR-BAD", result.stdout)
            payload = _sweep_stdout_json(result.stdout)
            self.assertTrue(
                any("TUR-BAD" in note for note in payload.get("degraded_reads", [])),
                payload,
            )
            self.assertTrue(
                all("OPERATOR ACTION NEEDED" not in note for note in payload.get("degraded_reads", [])),
            )

    def test_only_carried_read_failure_completes_cleanly_with_no_gate_line(self) -> None:
        # The ONLY carried issue's read fails: the sweep still completes cleanly
        # (exit 0), surfaces NO gate line for it, and notes the degraded read.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-solo"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text(
                'schema_version = 1\n\n[linear]\nissue = "TUR-BAD"\n'
            )
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["LINEAR_FAIL_ISSUE"] = "TUR-BAD"
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("OPERATOR ACTION NEEDED", result.stdout)
            payload = _sweep_stdout_json(result.stdout)
            self.assertTrue(
                any("TUR-BAD" in note for note in payload.get("degraded_reads", [])),
                payload,
            )


class SweepDeferredReconcileTests(unittest.TestCase):
    """TUR-489: a target commit landing MID-RUN (the sweep runs from a control dir
    another lane actively commits to) makes prepare_reconcile_launch fail closed
    with a 'target HEAD changed' GateError. That GateError must NOT crash the whole
    timer sweep (real crash observed 08:56:06): the sweep defers the reconcile for
    this pass, still surfaces the loud operator-gate block, notes the defer, and
    does NOT persist sweep-state.toml so the next pass retries. A NON-HEAD GateError
    (HEAD unchanged) still propagates / fails closed."""

    def _write_owner(self, base: Path, control: Path) -> Path:
        owner = base / "operator-owner.toml"
        owner.write_text(
            f'schema_version = 1\nowner_session_id = "operator-1-session"\n'
            f'owner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
        )
        return owner

    def _fake_bins(self, base: Path) -> tuple[Path, Path, dict]:
        fake_bin = base / "bin"
        fake_bin.mkdir()
        log = base / "calls.jsonl"
        (fake_bin / "claude").write_text(FAKE_RECONCILER_CLAUDE)
        (fake_bin / "operator-say").write_text(
            "#!/usr/bin/env bash\n"
            "printf 'operator %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            'for a in "$@"; do prev="${prev:-}"; if [[ "$prev" == "--artifact" ]]; then cat "$a" >>"$CALL_LOG"; fi; prev="$a"; done\n'
        )
        (fake_bin / "linear").write_text(FAKE_PER_ISSUE_LINEAR)
        for name in ("claude", "operator-say", "linear"):
            (fake_bin / name).chmod(0o755)
        env = dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
            OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
        )
        return fake_bin, log, env

    def _run_main(self, module, control: Path, owner: Path, repo: Path, env: dict):
        """Run module.main() in-process (so prepare_reconcile_launch can be
        monkeypatched) with argv + os.environ swapped and stdout captured."""
        import contextlib
        import io
        import sys as _sys

        old_argv = _sys.argv
        old_environ = dict(os.environ)
        buffer = io.StringIO()
        _sys.argv = [
            "operator-sweep", "--control-dir", str(control),
            "--owner-file", str(owner), "--repo", str(repo),
        ]
        os.environ.clear()
        os.environ.update(env)
        try:
            with contextlib.redirect_stdout(buffer):
                rc = module.main()
        finally:
            _sys.argv = old_argv
            os.environ.clear()
            os.environ.update(old_environ)
        return rc, buffer.getvalue()

    def test_mid_run_head_change_defers_reconcile_and_never_crashes(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-carrier"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text('schema_version = 1\n\n[linear]\nissue = "TUR-479"\n')
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["HOME"] = str(base)

            real_prepare = module.prepare_reconcile_launch

            def racing_prepare(**kwargs):
                # Simulate the live race: a land advances the control HEAD AFTER the
                # sweep captured `head`, then the gateway's own recheck fails closed.
                expected = kwargs["expected_head"]
                subprocess.run(
                    ["git", "-C", str(repo), "commit", "--allow-empty", "-qm", "mid-run land"],
                    check=True,
                )
                new = module.repo_head(repo)
                assert new != expected
                raise GateError(f"target HEAD changed: expected {expected}, found {new}")

            module.prepare_reconcile_launch = racing_prepare
            try:
                rc, stdout = self._run_main(module, control, owner, repo, env)
            finally:
                module.prepare_reconcile_launch = real_prepare

            # No crash: clean exit 0, GateError did NOT propagate.
            self.assertEqual(0, rc)
            # The captured head genuinely no longer matches the current repo HEAD,
            # exercising the repo_head(repo) != head branch of the handler.
            # The trust-critical operator-gate line still surfaces on stdout.
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", stdout)
            # ...and was delivered via operator-say too.
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", log.read_text())
            # The distinct deferred-reconcile note is emitted (not a gate line).
            self.assertIn("SWEEP NOTE (deferred reconcile):", stdout)
            self.assertNotIn("OPERATOR ACTION NEEDED: SWEEP NOTE", stdout)
            # sweep-state.toml is NOT written, so the next pass retries the reconcile.
            self.assertFalse((control / "sweep-state.toml").exists())
            # The pending snapshot artifact was cleaned up.
            self.assertEqual([], list(control.glob(".sweep-pending-*.md")))
            # Machine-readable JSON is still the last stdout line and marks the defer.
            payload = _sweep_stdout_json(stdout)
            self.assertTrue(payload.get("deferred_reconcile"))
            self.assertTrue(any(
                "OPERATOR ACTION NEEDED: TUR-479 In Staging" in line
                for line in payload.get("operator_gate", [])
            ), payload)

    def test_non_head_gate_error_still_fails_closed(self) -> None:
        # Regression: a GateError with the HEAD UNCHANGED (e.g. spec/ADR/PR drift)
        # must NOT be swallowed - it propagates so the deliberate fail-closed
        # behavior is preserved and no stale state is left behind.
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tf-carrier"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: ready\n")
            (stream / "sources.toml").write_text('schema_version = 1\n\n[linear]\nissue = "TUR-479"\n')
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            env["HOME"] = str(base)

            real_prepare = module.prepare_reconcile_launch

            def drift_prepare(**kwargs):
                # HEAD is left UNCHANGED; only a non-HEAD gateway check fails.
                raise GateError("stale Linear input: tf-carrier")

            module.prepare_reconcile_launch = drift_prepare
            try:
                with self.assertRaises(GateError) as caught:
                    self._run_main(module, control, owner, repo, env)
            finally:
                module.prepare_reconcile_launch = real_prepare
            self.assertIn("stale Linear input", str(caught.exception))
            # Fail-closed: no state persisted and no pending snapshot left behind.
            self.assertFalse((control / "sweep-state.toml").exists())
            self.assertEqual([], list(control.glob(".sweep-pending-*.md")))


class TimerLinearAuthTests(unittest.TestCase):
    """TUR-489: a fresh timer install must pass LINEAR_API_KEY to the transient
    unit so the timer-run sweep's Source A `linear issue view` works without a
    manual systemd drop-in."""

    def _install(self, base: Path, env: dict) -> tuple[Path, subprocess.CompletedProcess]:
        control = base / "control"
        repo = base / "repo"
        control.mkdir()
        repo.mkdir()
        owner = base / "operator-owner.toml"
        owner.write_text(
            f'schema_version = 1\nowner_session_id = "operator-1-session"\n'
            f'owner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
        )
        fake_bin = base / "bin"
        fake_bin.mkdir()
        call_log = base / "systemd-run.txt"
        runner = fake_bin / "systemd-run"
        runner.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >"$CALL_LOG"\n')
        runner.chmod(0o755)
        run_env = dict(
            env,
            PATH=f"{fake_bin}:{os.environ['PATH']}",
            CALL_LOG=str(call_log),
            OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
        )
        result = subprocess.run(
            [
                str(TIMER), "install", "--name", "operator-1",
                "--control-dir", str(control), "--owner-file", str(owner),
                "--repo", str(repo),
            ],
            env=run_env,
            capture_output=True,
            text=True,
        )
        return call_log, result

    def test_install_passes_linear_api_key_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            linear_env = base / ".linear.env"
            linear_env.write_text("export LINEAR_API_KEY='lin_test_KEY'\n")
            env = dict(os.environ)
            env.pop("LINEAR_API_KEY", None)
            env["OCTO_LINEAR_ENV_FILE"] = str(linear_env)
            call_log, result = self._install(base, env)
            self.assertEqual(0, result.returncode, result.stderr)
            call = call_log.read_text()
            self.assertIn("--setenv=LINEAR_API_KEY=lin_test_KEY", call)
            self.assertIn("--setenv=PATH=", call)
            self.assertIn("--setenv=OCTO_OPERATOR_OWNER=", call)

    def test_install_prefers_already_set_linear_api_key_over_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            linear_env = base / ".linear.env"
            linear_env.write_text("export LINEAR_API_KEY='lin_file_value'\n")
            env = dict(os.environ)
            env["LINEAR_API_KEY"] = "lin_env_value"
            env["OCTO_LINEAR_ENV_FILE"] = str(linear_env)
            call_log, result = self._install(base, env)
            self.assertEqual(0, result.returncode, result.stderr)
            call = call_log.read_text()
            self.assertIn("--setenv=LINEAR_API_KEY=lin_env_value", call)

    def test_install_handles_double_quoted_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            linear_env = base / ".linear.env"
            linear_env.write_text('export LINEAR_API_KEY="lin_double_quoted"\n')
            env = dict(os.environ)
            env.pop("LINEAR_API_KEY", None)
            env["OCTO_LINEAR_ENV_FILE"] = str(linear_env)
            call_log, result = self._install(base, env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("--setenv=LINEAR_API_KEY=lin_double_quoted", call_log.read_text())

    def test_install_succeeds_without_env_file_or_key_and_omits_setenv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            missing = base / "does-not-exist.env"
            env = dict(os.environ)
            env.pop("LINEAR_API_KEY", None)
            env["OCTO_LINEAR_ENV_FILE"] = str(missing)
            call_log, result = self._install(base, env)
            # Install still succeeds (graceful): no crash.
            self.assertEqual(0, result.returncode, result.stderr)
            call = call_log.read_text()
            self.assertNotIn("--setenv=LINEAR_API_KEY", call)
            # PATH and owner are still passed as before.
            self.assertIn("--setenv=PATH=", call)
            self.assertIn("--setenv=OCTO_OPERATOR_OWNER=", call)


class IntentRecordSurfaceForgeryTests(unittest.TestCase):
    # TUR-447 F5 (Units J and L, code-review finding F5): Shaped authority
    # could not distinguish a command-produced operator-intent record from
    # fabricated TOML, because verification accepted any nonempty intent_ref +
    # recorded_at + any existing commit. The producer now publishes and reads
    # back the binding on the PR/status surface, and the consumer re-reads the
    # live surface so a forged valid-head local TOML without the matching
    # command-published surface is rejected (delivery-lifecycle
    # shaping-operator-approval-binding; operator-control
    # supervision-operator-gate-no-hashes; role-runtime launch-shaping-authority).

    def _init_repo(self, repo: Path) -> str:
        _init_target_repo(repo)
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def _env(self, base: Path, head: str, store: Path | None = None) -> dict:
        fake_bin = base / "bin"
        _install_gh_intent_fake(fake_bin)
        return dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
            GH_HEAD=head, GH_COMMENTS=str(store or (base / "comments.json")),
        )

    def test_producer_requires_pr_for_surface_publication(self) -> None:
        # Unit L: the binding must be recorded on the PR/status surface, so a
        # producer run without --pr cannot publish and is rejected before any
        # local record is written.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(repo),
                ],
                capture_output=True, text=True, env=self._env(base, head),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("--pr", result.stderr)
            self.assertFalse((stream / "intent-record.toml").exists())

    def test_producer_failed_surface_readback_aborts_before_writing_record(self) -> None:
        # Unit L red: a failed surface readback (the live comment does not echo
        # exactly what was published) aborts and no local record is written.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            fake_bin = base / "bin"
            fake_bin.mkdir()
            # A gh fake that publishes but reads back a corrupted body on the
            # single-comment GET, so producer readback must fail.
            (fake_bin / "gh").write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "argv = sys.argv[1:]\n"
                "store = os.environ['GH_COMMENTS']\n"
                "def load():\n"
                "    return json.load(open(store)) if os.path.exists(store) else []\n"
                "if argv[:2] == ['pr', 'view']:\n"
                "    print(json.dumps({'headRefOid': os.environ.get('GH_HEAD', '')})); sys.exit(0)\n"
                "method = argv[argv.index('--method')+1] if '--method' in argv else None\n"
                "endpoint = [t for i, t in enumerate(argv) if i>0 and argv[i-1] not in ('--method','-f') and t not in ('--paginate','--method','-f','api')][0]\n"
                "def field(f):\n"
                "    return next((v.split('=',1)[1] for v in argv if v.startswith(f+'=')), None)\n"
                "if endpoint.endswith('/comments') and method is None:\n"
                "    print(json.dumps(load())); sys.exit(0)\n"
                "if endpoint.endswith('/comments') and method == 'POST':\n"
                "    items = load(); new = {'id': len(items)+1, 'body': field('body'), 'html_url': 'u'}\n"
                "    items.append(new); json.dump(items, open(store, 'w')); print(json.dumps(new)); sys.exit(0)\n"
                "if '/comments/' in endpoint and method is None:\n"
                "    cid = int(endpoint.split('/')[-1])\n"
                "    for it in load():\n"
                "        if it['id'] == cid:\n"
                "            corrupt = dict(it); corrupt['body'] = 'TAMPERED'\n"
                "            print(json.dumps(corrupt)); sys.exit(0)\n"
                "sys.exit(9)\n"
            )
            (fake_bin / "gh").chmod(0o755)
            env = dict(
                os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                GH_HEAD=head, GH_COMMENTS=str(base / "comments.json"),
            )
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--pr", "7",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("surface readback mismatch", result.stderr)
            self.assertFalse((stream / "intent-record.toml").exists())

    def test_verify_rejects_forged_valid_head_record_without_published_surface(self) -> None:
        # CORE F5 red: a hand-authored record with a valid head, correct repo
        # and PR, and a correct self-digest, but NO matching command-published
        # PR surface, is rejected as forged.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            stream.mkdir()
            module = _load_octo_control_module()
            body = module._intent_surface_body(
                repo=str(repo), pr=7, head=head, intent_ref="ruling-15",
                recorded_at="2026-07-21T00:00:00+00:00",
            )
            digest = module._surface_digest(body)
            (stream / "intent-record.toml").write_text(
                'schema_version = 1\nintent_ref = "ruling-15"\n'
                f'head = "{head}"\nrecorded_at = "2026-07-21T00:00:00+00:00"\n'
                f'repo = {json.dumps(str(repo))}\npr = 7\n'
                f'surface_sha256 = "{digest}"\n'
            )
            # Empty live surface store: no command ever published this record.
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                ],
                capture_output=True, text=True, env=self._env(base, head),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("no command-published surface", result.stderr)

    def test_verify_rejects_record_whose_repo_differs_from_cli_repo_argument(self) -> None:
        # Repo-arg bind at the record level: a record produced against another
        # repo than the CLI repo argument carries no authority here.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            other = base / "other"
            repo = base / "repo"
            head_other = self._init_repo(other)
            self._init_repo(repo)
            stream = base / "stream"
            store = base / "comments.json"
            produced = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(other), "--pr", "7",
                ],
                capture_output=True, text=True, env=self._env(base, head_other, store),
            )
            self.assertEqual(0, produced.returncode, produced.stderr)
            # Verify against a DIFFERENT CLI repo argument than the record binds.
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                ],
                capture_output=True, text=True, env=self._env(base, head_other, store),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("repo mismatch with CLI repo argument", result.stderr)

    def test_verify_rejects_surface_digest_that_does_not_bind_its_own_fields(self) -> None:
        # A record carrying a surface_sha256 that is not the digest of its own
        # head/intent/repo/pr is self-inconsistent and rejected before the
        # live fetch: the digest cannot be borrowed from an unrelated surface.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            stream.mkdir()
            (stream / "intent-record.toml").write_text(
                'schema_version = 1\nintent_ref = "ruling-15"\n'
                f'head = "{head}"\nrecorded_at = "2026-07-21T00:00:00+00:00"\n'
                f'repo = {json.dumps(str(repo))}\npr = 7\n'
                f'surface_sha256 = "{"0" * 64}"\n'
            )
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                ],
                capture_output=True, text=True, env=self._env(base, head),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("does not bind its own fields", result.stderr)

    def test_producer_replaces_partial_record_atomically_leaving_no_temp(self) -> None:
        # Non-atomic partial write red: a truncated prior record is replaced
        # whole via the atomic pattern and no temporary file remains.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            stream.mkdir()
            (stream / "intent-record.toml").write_text('intent_ref = "trunc')
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--pr", "7",
                ],
                capture_output=True, text=True, env=self._env(base, head),
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                ["intent-record.toml"], sorted(p.name for p in stream.iterdir())
            )
            with (stream / "intent-record.toml").open("rb") as handle:
                record = tomllib.load(handle)
            self.assertEqual(head, record["head"])
            self.assertRegex(record["surface_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
