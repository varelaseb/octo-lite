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
from unittest import mock

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

# The lean heartbeat (#23) spawns NO reconciler subprocess. Surviving tests
# install this decoy `claude` bin only to prove it is NEVER invoked: any call
# is logged so a regression that reintroduces a reconcile spawn is caught.
FAKE_RECONCILER_CLAUDE = (
    "#!/usr/bin/env bash\n"
    "printf 'claude %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
)


# TUR-447 F5: a canonical owner/repo slug (gh identity) distinct from the local
# repo filesystem path (git -C identity), and the trusted command-publisher
# comment author identity the intent surface is posted under.
SLUG = "org/repo"
PUBLISHER = "octo-lite-bot"


def _write_codex_rollout(
    codex_home: Path, session_id: str, *, model: str, effort: str,
    final_message: str, provider: str = "openai",
) -> None:
    # Mirror the codex rollout record shape (octo_lite.launch._read_codex_rollout_record):
    # a session_meta provider, a turn_context model/effort, and a final
    # assistant message, so verify_relay_verbatim can prove the verdict came
    # from an actual rollout under CODEX_HOME/sessions.
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "21"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rollout = sessions_dir / f"rollout-2026-07-21T00-00-00-{session_id}.jsonl"
    lines = [
        json.dumps({"type": "session_meta", "payload": {"session_id": session_id, "model_provider": provider}}),
        json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort}}),
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": final_message}],
            },
        }),
    ]
    rollout.write_text("\n".join(lines) + "\n")


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
    def test_heartbeat_imports_only_the_fact_read_never_reconcile_or_low_level_launch_helpers(self) -> None:
        # #23 STRIP: the lean heartbeat spawns no reconciler subprocess and binds
        # no target canonical specs, so it imports ONLY the non-reconcile Linear
        # fact read (fetch_stream_binding) - never prepare_reconcile_launch /
        # run_reconcile_launch or any low-level launch helper.
        source = SWEEP.read_text()
        launch_import = next(line for line in source.splitlines() if line.startswith("from octo_lite.launch import"))
        imported = {name.strip() for name in launch_import.split("import", 1)[1].split("#")[0].split(",")}
        self.assertEqual({"fetch_stream_binding"}, imported)
        for forbidden in (
            "prepare_reconcile_launch", "run_reconcile_launch",
            "prepared_from_receipt", "run_bootstrap", "run_mutation",
            "build_launch_receipt", "resolve_role", "load_registry",
            # No canonical spec/ADR binding (the live crash cause) survives.
            "CANONICAL_SPEC_SIGNAL", "CANONICAL_ADR_SIGNAL", "canonical_blobs",
            "no canonical", "GateError",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("worktree=repo", source)

    def test_target_init_template_declares_a_spec_and_an_adr_canonical_signal(self) -> None:
        # The issue shaper hand-copies this asset into a freshly initialized
        # target's root AGENTS.md; reusing the sweep's own signal parser (rather
        # than a bespoke count) proves the template cannot silently ship without
        # both canonical declarations the sweep will later require.
        # The heartbeat no longer parses canonical signals (they were the live
        # crash), but the shaper template must still ship both declarations for
        # spec-chat targets; assert directly on the template text.
        def _signal_lines(text: str, signal: str) -> list[str]:
            values = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    stripped = stripped[2:].strip()
                if stripped.startswith(signal):
                    values.append(stripped[len(signal):].strip())
            return values

        text = TARGET_AGENTS_TEMPLATE.read_text()
        self.assertIn("Spec format:", text)
        self.assertEqual(1, len(_signal_lines(text, "Canonical spec paths:")))
        self.assertEqual(1, len(_signal_lines(text, "Canonical ADR paths:")))

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

    def test_heartbeat_is_fresh_and_unchanged_wake_is_noop_and_spawns_no_reconciler(self) -> None:
        # #23 heartbeat-fresh-snapshot: a wake regenerates a fresh snapshot and
        # reports changed on the first wake, noop when nothing moved. It spawns NO
        # reconciler subprocess (no `claude` call) and binds NO canonical specs, so
        # a Markdown/no-canonical target never crashes it.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo, with_canonical_sources=False)

            control = base / "control"
            status = control / "streams/TUR-1/status.md"
            status.parent.mkdir(parents=True)
            status.write_text("Outcome: ready\nNext operator action: inspect\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\nowner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )

            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            # A `claude` fake that would LOG any invocation: the heartbeat must
            # never call it. operator-say still logs pane pushes.
            (fake_bin / "claude").write_text(
                '#!/usr/bin/env bash\nprintf \'claude %s\\n\' "$*" >>"$CALL_LOG"\n'
            )
            (fake_bin / "operator-say").write_text(
                '#!/usr/bin/env bash\nprintf \'operator %s\\n\' "$*" >>"$CALL_LOG"\n'
            )
            for name in ("claude", "operator-say"):
                (fake_bin / name).chmod(0o755)
            xdg = base / "xdg"
            env = dict(
                os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"), XDG_STATE_HOME=str(xdg),
                HOME=str(base),
            )

            command = [
                str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner),
                "--repo", str(repo),
            ]
            first = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            second = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(_sweep_stdout_json(first.stdout)["changed"])
            self.assertFalse(_sweep_stdout_json(second.stdout)["changed"])
            calls = log.read_text().splitlines() if log.exists() else []
            # No reconciler subprocess ever spawned.
            self.assertFalse(any(line.startswith("claude ") for line in calls))
            # The fresh snapshot lives in one control-level file (heartbeat-outside-digest).
            self.assertTrue((control / "snapshot.json").is_file())
            with (control / "sweep-state.toml").open("rb") as handle:
                state = tomllib.load(handle)
            self.assertEqual("operator-1", state["owner_route"])
            # No persisted authoritative current-state record: no reconcile journal,
            # no sweeps/ tree, no worktrees.
            self.assertFalse((control / "sweeps").exists())
            self.assertFalse((control / "worktrees").exists())

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

    def _write_receipt(self, path: Path, *, role: str, issue: str, provider_session_id: str, verified: bool = True) -> None:
        from octo_lite.runtime import launch_revision
        # launch_revision is the unkeyed self-digest the octo-control gate now
        # requires (#13 c1a2dcc): compute it from the exact receipt the TOML
        # parses to, mirroring _write_persistent_orchestrator_receipt.
        receipt = {
            "schema_version": 1,
            "spawn_id": provider_session_id,
            "ready": True,
            "role": {"name": role},
            "issue": {"identifier": issue},
            "bootstrap": {"verified": verified, "provider_session_id": provider_session_id},
        }
        revision = launch_revision(receipt)
        path.write_text(
            "schema_version = 1\n"
            f'spawn_id = "{provider_session_id}"\n'
            "ready = true\n"
            f'launch_revision = "{revision}"\n\n'
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
                child_role="orchestrator", caller="epic-opus", brief="Build it.\n", issue="TUR-1",
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
            self.assertIn("issue", result.stderr.lower())
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
                child_role="orchestrator", caller="epic-opus", brief="Build it.\n", issue="TUR-1",
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

    def test_linear_transition_authorizes_a_name_keyed_owned_stream_by_registry_issue(self) -> None:
        # AC1 (delivery-lifecycle linear-transition-issue-binding, operator-control
        # stream-issue-binding): a DESCRIPTIVELY-named stream whose host-owned
        # registry entry binds it to issue TUR-1 must reach compare-mutate-readback
        # for TUR-1, even though stream_id != "TUR-1". The prior authority (stream_id
        # == issue) rejected exactly this case; the fix authorizes on the registry
        # `issue` field plus exact owner/role.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="onb-chips-default", parent_session="epic-opus",
                child_session="issue-opus", child_role="orchestrator", caller="epic-opus",
                brief="Build it.\n", issue="TUR-1",
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

    def test_linear_transition_denies_a_foreign_issue_by_registry_issue_binding(self) -> None:
        # AC1: the exact owner of a name-keyed stream bound to TUR-1 must NOT be
        # able to drive a different issue (TUR-999): authority is the registry
        # `issue` field, not the descriptive stream_id. A fake `linear` that logs
        # any call before exiting nonzero proves rejection happens before any read.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stream = base / "stream"
            from octo_lite.runtime import initialize_stream
            initialize_stream(
                stream, stream_id="onb-chips-default", parent_session="epic-opus",
                child_session="issue-opus", child_role="orchestrator", caller="epic-opus",
                brief="Build it.\n", issue="TUR-1",
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
            self.assertIn("issue", result.stderr.lower())
            self.assertFalse(call_log.exists())

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
        self, path: Path, *, head: str, issue: str = "TUR-1", repo: str = SLUG,
        pr: int = 7, verdict: str = "clear", provenance: bool = True,
        ack_echo: bool = False, codex_home: Path | None = None,
        session_id: str = "codex-session-1", model: str = "gpt-5.6-sol",
        effort: str = "xhigh", write_rollout: bool = True,
        rollout_provider: str = "openai", rollout_model: str | None = None,
        rollout_effort: str | None = None, payload: str | None = None,
    ) -> None:
        # F5-r2 fix 3: the reviewer rollout final message (== verdict payload)
        # must COMMIT to this exact clear verdict on this issue, PR, and HEAD.
        if payload is None:
            payload = f"SHAPING VERDICT clear for {issue} PR {pr} at exact head {head}"
        entry: dict = {
            "schema_version": 1, "review_type": "shaping", "verdict": verdict,
            "issue": issue, "repo": repo, "pr": pr, "head": head,
        }
        if provenance:
            entry.update({
                "codex_session_id": session_id,
                "verdict_payload": payload,
                "verdict_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "codex_model": model,
                "codex_effort": effort,
                "provenance": "relay-verbatim-rollout",
            })
            # A real rollout record backs the declared session id, so an
            # arbitrary session/hash with no resolvable record fails closed.
            if codex_home is not None and write_rollout:
                _write_codex_rollout(
                    codex_home, session_id,
                    model=rollout_model or model, effort=rollout_effort or effort,
                    final_message=payload, provider=rollout_provider,
                )
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
            codex_home = base / "codex-home"
            # Repo split: --repo is the local path, SLUG is the gh identity; the
            # command publishes the intent surface under the trusted PUBLISHER.
            base_env = dict(
                os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                CODEX_HOME=str(codex_home), GH_PUBLISHER=PUBLISHER,
            )
            caller = "issue-opus"

            def produce_intent(directory: Path, *, at_head: str, store: Path) -> str:
                # Publish the operator-intent surface to the shared PR store so
                # a command-produced record has a matching live comment; the
                # returned local TOML is command-authored, not forged.
                env = dict(base_env, GH_HEAD=at_head, GH_COMMENTS=str(store))
                produced = subprocess.run(
                    [
                        str(CONTROL), "intent-record", "--stream-dir", str(directory),
                        "--intent-ref", "ruling-15", "--repo", str(repo),
                        "--repo-slug", SLUG, "--pr", "7",
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
                    values: dict = {"head": head, "repo": SLUG, "codex_home": codex_home}
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
                    argv += [
                        "--verdict-journal", str(case / "verdict.json"),
                        "--repo", str(repo), "--repo-slug", SLUG,
                        "--trusted-publisher", PUBLISHER,
                    ]
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
                # A hand-authored valid-head record with full shape (correct
                # self-digest, a fabricated comment_id, and the trusted
                # publisher name), but with NO matching live PR comment: the
                # consumer fetches the bound comment id and rejects.
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
                    f'comment_id = 999\npublisher = {json.dumps(PUBLISHER)}\n'
                )

            forged_valid_head = forged_record(head_value=head, repo_value=SLUG, pr_value=7)

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
                # Repo-arg bind: a clear verdict for a different canonical repo
                # slug than the CLI repo slug is rejected before any GitHub call.
                (
                    "verdict_repo_ne_cli_repo",
                    {"verdict_kwargs": {"repo": "org/other"}},
                    "does not match CLI repo slug",
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
            codex_home = base / "codex-home"

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
                    self._write_verdict_journal(
                        case / "verdict.json", head=head, repo=SLUG, codex_home=codex_home
                    )
                    # Publish the command surface into the case store (no call
                    # log) so the later verify finds the live PR comment.
                    produced = subprocess.run(
                        [
                            str(CONTROL), "intent-record", "--stream-dir", str(stream),
                            "--intent-ref", "ruling-15", "--repo", str(repo),
                            "--repo-slug", SLUG, "--pr", "7",
                        ],
                        capture_output=True, text=True,
                        env=dict(
                            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                            GH_HEAD=head, GH_COMMENTS=str(store), GH_PUBLISHER=PUBLISHER,
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
                        GH_PUBLISHER=PUBLISHER, CODEX_HOME=str(codex_home),
                    )
                    result = subprocess.run(
                        [
                            str(CONTROL), "linear-transition", "TUR-1",
                            "--expected", "Todo", "--target", "Shaped",
                            "--progress", str(case / "progress.toml"),
                            "--status", str(case / "status.md"),
                            "--parent", "epic-opus", "--outcome", "shaped", "--gate", "review",
                            "--caller", "issue-opus", "--receipt", str(receipt),
                            "--verdict-journal", str(case / "verdict.json"),
                            "--repo", str(repo), "--repo-slug", SLUG,
                            "--trusted-publisher", PUBLISHER,
                        ],
                        env=env, capture_output=True, text=True,
                    )
                    calls = call_log.read_text().splitlines() if call_log.exists() else []
                    # F5-r2 fix 1: the trusted publisher is derived from the
                    # authenticated gh actor (gh api user) before the intent
                    # comment fetch, so the intent verification opens with that
                    # derivation, then the surface fetch, then the compare read,
                    # fresh-head, mutate, readback, notify.
                    self.assertEqual("gh api user", calls[0], calls)
                    self.assertTrue(calls[1].startswith("gh api"), calls)
                    self.assertIn("/comments", calls[1])
                    if expect_ok:
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertEqual("Shaped", state_file.read_text())
                        self.assertEqual(7, len(calls), calls)
                        self.assertTrue(calls[2].startswith("linear issue view"), calls)
                        self.assertTrue(calls[3].startswith("gh pr view 7"), calls)
                        self.assertIn("headRefOid", calls[3])
                        self.assertTrue(calls[4].startswith("linear issue update"), calls)
                        self.assertTrue(calls[5].startswith("linear issue view"), calls)
                        self.assertTrue(calls[6].startswith("herdr-say "), calls)
                    else:
                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual("Todo", state_file.read_text())
                        self.assertEqual(4, len(calls), calls)
                        self.assertTrue(calls[2].startswith("linear issue view"), calls)
                        self.assertTrue(calls[3].startswith("gh pr view 7"), calls)



class HeartbeatSnapshotTests(unittest.TestCase):
    """#23 (rulings 1/3/10/11): the lean heartbeat regenerates a FRESH per-stream
    snapshot from current facts (heartbeat-fresh-snapshot) reporting one layer
    down only (heartbeat-one-layer) - stream name, last delivery OR forward-
    progress marker, and any operator-gated state - and carries NO worker-level
    liveness classification of its own (heartbeat-judgment-in-roles). It probes no
    workers and binds no target canonical specs, so a Markdown/no-canonical target
    never crashes it."""

    def _stream_with_receipt(self, base: Path, name: str, projects: Path) -> tuple[Path, Path]:
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

    def test_snapshot_reports_forward_progress_and_delivery_from_real_observables_only(self) -> None:
        # heartbeat-one-layer: forward progress is derived from a REAL observable
        # (the receipt-derived session transcript mtime) and the last-delivery
        # marker from the status.md anchored delivery line - never a probe or a
        # persisted classification.
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            projects = base / "projects"
            stream, transcript = self._stream_with_receipt(base, "tur-1", projects)
            os.utime(transcript, (1_000_000.0, 1_000_000.0))
            (stream / "status.md").write_text(
                "# tur-1\nLast delivery: implementer green at abc123\nOutcome: working\n"
            )
            snap = module.stream_snapshot(stream, {}, base / "waits", projects_root=projects)
            self.assertEqual("tur-1", snap["stream"])
            self.assertEqual(1_000_000, snap["forward_progress_mtime"])
            self.assertEqual("implementer green at abc123", snap["last_delivery"])
            self.assertEqual([], snap["operator_gate"])
            # heartbeat-judgment-in-roles: the snapshot carries NO classification.
            self.assertNotIn("classification", snap)
            self.assertNotIn("agent_running", snap)
            self.assertNotIn("agent_status", snap)

    def test_snapshot_carries_operator_gate_state_but_no_worker_liveness_classification(self) -> None:
        # heartbeat-operator-gate: an operator-gated carried state surfaces in the
        # snapshot's operator_gate list; heartbeat-judgment-in-roles: the snapshot
        # never probes workers or classifies liveness (no dead/stuck/active).
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            projects = base / "projects"
            stream, _ = self._stream_with_receipt(base, "tur-2", projects)
            (stream / "status.md").write_text("Outcome: shipping\n")
            facts = {"tur-2": {"carried_linear": [{"identifier": "TUR-479", "state": "In Staging"}]}}
            snap = module.stream_snapshot(stream, facts, base / "waits", projects_root=projects)
            self.assertEqual(1, len(snap["operator_gate"]))
            self.assertIn("TUR-479 In Staging", snap["operator_gate"][0])
            # No worker/dead-agent liveness classification is emitted anywhere.
            for banned in ("classification", "agent_running", "agent_status", "watchdog_error"):
                self.assertNotIn(banned, snap)

    def test_heartbeat_never_probes_workers_or_binds_canonical_specs(self) -> None:
        # #23 STRIP: the dead-agent watchdog probe (herdr agent get), the
        # classification engine, and canonical-spec binding are all removed - none
        # of their source markers survive in the lean heartbeat.
        source = SWEEP.read_text()
        for banned in (
            "herdr_agent_probe", "agent get", "def stream_liveness", "_HERDR_AGENT_GONE_CODES",
            "suspected-stuck", "waiting-on-operator",
            '"classification"', "canonical_blobs", "spec_blobs", "adr_blobs",
            "prepare_reconcile_launch", "run_reconcile_launch",
        ):
            self.assertNotIn(banned, source, f"stripped marker {banned!r} must not survive")

    def test_heartbeat_runs_clean_against_a_markdown_no_canonical_target(self) -> None:
        # REPRO of the live crash (operator-sweep ~line 267 SystemExit "no
        # canonical ... paths declared"): a target with a Markdown / no-declaration
        # AGENTS.md must run the heartbeat cleanly and exit 0, never SystemExit.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo, with_canonical_sources=False)
            control = base / "control"
            (control / "streams").mkdir(parents=True)
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_route = "operator-1"\ncontrol_dir = "{control}"\n'
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            (fake_bin / "operator-say").write_text("#!/usr/bin/env bash\nexit 0\n")
            (fake_bin / "operator-say").chmod(0o755)
            xdg = base / "xdg"
            env = dict(
                os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
                XDG_STATE_HOME=str(xdg), HOME=str(base),
            )
            result = subprocess.run(
                [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("no canonical", result.stderr)
            self.assertNotIn("SystemExit", result.stderr)

    def test_sweep_invokes_operator_say_by_absolute_path(self) -> None:
        # Live defect: timer-run sweep crashed with FileNotFoundError because
        # operator-say was invoked by bare name under systemd's bare PATH. The
        # heartbeat resolves the helper from its own root, overridable via
        # OCTO_OPERATOR_SAY.
        source = SWEEP.read_text()
        self.assertNotIn('"operator-say", "--kind"', source)
        self.assertIn("OCTO_OPERATOR_SAY", source)
        self.assertIn('skills/herdr-comms/assets/operator-say', source)

    def test_snapshot_lives_in_output_and_one_control_file_never_a_persisted_current_state_record(self) -> None:
        # heartbeat-outside-digest: the snapshot is an operator report in the
        # heartbeat output and exactly one control-level file (snapshot.json),
        # never a persisted authoritative current-state record downstream roles
        # read (no liveness.json digest, no reconcile journal).
        source = SWEEP.read_text()
        self.assertIn('control / "snapshot.json"', source)
        for phantom in (
            "liveness.json", "journal.json", "sweep-pending",
            "waiting.toml", "inflight.toml", "pane-activity.txt", "observations",
        ):
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

if argv[:2] == ["api", "user"]:
    print(json.dumps({"login": os.environ.get("GH_ACTOR", os.environ.get("GH_PUBLISHER", "octo-lite-bot"))}))
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
               "user": {"login": os.environ.get("GH_PUBLISHER", "octo-lite-bot")},
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
            GH_PUBLISHER=PUBLISHER,
        )

    def test_intent_record_stamps_the_current_exact_head_at_action_time(self) -> None:
        # shaping-operator-approval-binding: tooling captures the head itself;
        # the record binds intent reference, exact head, a timestamp, and the
        # command-published surface repo/PR/digest, and success reports the
        # record path plus bound head machine-readably. Repo split: --repo is
        # the local path, --repo-slug the canonical gh identity the record binds.
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
                    "--repo", str(repo), "--repo-slug", SLUG, "--pr", "7",
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
            self.assertEqual(SLUG, record["repo"])
            self.assertEqual(7, record["pr"])
            self.assertRegex(record["surface_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(PUBLISHER, record["publisher"])
            self.assertIsInstance(record["comment_id"], int)
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
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--repo", str(repo), "--repo-slug", SLUG,
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, missing.returncode)
            self.assertFalse((stream / "intent-record.toml").exists())
            for empty_ref in ("", "   "):
                result = subprocess.run(
                    [
                        str(CONTROL), "intent-record", "--stream-dir", str(stream),
                        "--intent-ref", empty_ref, "--repo", str(repo), "--repo-slug", SLUG,
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
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--repo-slug", SLUG,
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
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--repo-slug", SLUG, "--pr", "7",
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
                "repo": str(repo), "repo_slug": SLUG, "pr": 7, "verify": False,
                "trusted_publisher": PUBLISHER,
            })()
            saved = dict(os.environ)
            os.environ["PATH"] = f"{fake_bin}:{os.environ['PATH']}"
            os.environ["GH_HEAD"] = head
            os.environ["GH_COMMENTS"] = str(base / "comments.json")
            os.environ["GH_PUBLISHER"] = PUBLISHER
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
                "--repo-slug", SLUG, "--trusted-publisher", PUBLISHER,
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
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--repo-slug", SLUG, "--pr", "7",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, produced.returncode, produced.stderr)
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                    "--repo-slug", SLUG, "--trusted-publisher", PUBLISHER,
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(head, payload["head"])
            self.assertEqual(7, payload["pr"])
            self.assertEqual(PUBLISHER, payload["publisher"])
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
            # No prose TUR-id was ever read from Linear (with no gated read the
            # heartbeat never touches linear/operator-say, so the log may not exist).
            log_lines = log.read_text().splitlines() if log.exists() else []
            for pid in ("TUR-101", "TUR-107", "TUR-222", "TUR-303", "TUR-404", "TUR-505"):
                self.assertFalse(
                    any(pid in line and line.startswith("linear ") for line in log_lines),
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


class TransportLifecycleSweepTests(unittest.TestCase):
    """TUR-505 phase-1 reader/repair laws: E1 undelivered derivation, P1
    publication repair, S3 stalled surfacing, G2-lite registry advisories,
    and the operator-timer env propagation (ruling-87 folds)."""

    MSG = "20260722T000000-11-111"

    def _seed_message(self, messages: Path, id_: str, *, target="tur-1", status="pending",
                      kind="command", path="deferred", attempts=None):
        messages.mkdir(parents=True, exist_ok=True)
        lines = [
            "schema_version = 1",
            f'message_id = "{id_}"',
            f'target = "{target}"',
            f'kind = "{kind}"',
            f'status = "{status}"',
        ]
        if path is not None:
            lines.append(f'delivery_path = "{path}"')
        if attempts is not None:
            lines.append(f"transport_attempts = {attempts}")
        lines += ['artifact = ""', 'message = "do work"', 'created_at = "2026-07-22T00:00:00Z"']
        state = messages / f"{id_}.toml"
        state.write_text("\n".join(lines) + "\n")
        return state

    def test_t23_publication_repair_matrix(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            messages = base / "messages"
            inbox_root = base / "inbox"
            locks = base / "locks"
            now = 1_000_000.0

            old = "20260722T000010-1-1"
            self._seed_message(messages, old, status="pending", path="deferred")
            os.utime(messages / f"{old}.toml", (now - 600, now - 600))

            fresh = "20260722T000011-2-2"
            self._seed_message(messages, fresh, status="pending", path="modal-queued")
            os.utime(messages / f"{fresh}.toml", (now - 5, now - 5))

            direct = "20260722T000012-3-3"
            self._seed_message(messages, direct, status="pending", path="direct")
            os.utime(messages / f"{direct}.toml", (now - 600, now - 600))

            ask = "20260722T000013-4-4"
            self._seed_message(messages, ask, status="pending", path="unresolved-ask")
            os.utime(messages / f"{ask}.toml", (now - 600, now - 600))

            legacy = "20260722T000014-5-5"
            self._seed_message(messages, legacy, status="pending", path=None)
            os.utime(messages / f"{legacy}.toml", (now - 600, now - 600))

            report = module.transport_message_report(messages, inbox_root, locks, now=now)
            # Old retryable itemless: repaired, item content = id.
            repaired_item = inbox_root / "tur-1" / old
            self.assertTrue(repaired_item.is_file())
            self.assertEqual(old, repaired_item.read_text().strip())
            self.assertTrue(any(old in note for note in report["repair_notes"]))
            # Fresh mtime: not yet (boundary case both sides).
            self.assertFalse((inbox_root / "tur-1" / fresh).exists())
            # direct and unresolved-ask: never repaired.
            self.assertFalse((inbox_root / "tur-1" / direct).exists())
            self.assertFalse((inbox_root / "tur-1" / ask).exists())
            # Legacy: never guess-repaired, noted undelivered-unknown-legacy.
            self.assertFalse((inbox_root / "tur-1" / legacy).exists())
            self.assertTrue(any("undelivered-unknown-legacy" in note and legacy in note
                                for note in report["legacy_notes"]))

    def test_tr87c_p1_rejects_the_escape_target_and_derives_no_path(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            messages = base / "messages"
            inbox_root = base / "inbox"
            inbox_root.mkdir()
            locks = base / "locks"
            now = 1_000_000.0
            bad = "20260722T000015-6-6"
            self._seed_message(messages, bad, target="../../escape:p1", status="pending", path="deferred")
            os.utime(messages / f"{bad}.toml", (now - 600, now - 600))
            report = module.transport_message_report(messages, inbox_root, locks, now=now)
            # Containment: nothing outside the inbox root is ever derived.
            self.assertEqual([], [p for p in inbox_root.rglob("*")])
            self.assertFalse((base / "escape").exists())
            self.assertFalse((base.parent / "escape").exists())
            self.assertTrue(any("target" in note and bad in note for note in report["repair_notes"] + report["legacy_notes"]))

    def test_tl4_p1_repair_respects_a_held_message_lock(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            messages = base / "messages"
            inbox_root = base / "inbox"
            locks = base / "locks"
            locks.mkdir()
            now = 1_000_000.0
            old = "20260722T000016-7-7"
            self._seed_message(messages, old, status="pending", path="deferred")
            os.utime(messages / f"{old}.toml", (now - 600, now - 600))
            lock_path = locks / f"{old}.lock"
            holder = subprocess.Popen(["flock", str(lock_path), "sleep", "30"], start_new_session=True)
            try:
                for _ in range(50):
                    if lock_path.exists():
                        probe = subprocess.run(["flock", "-n", str(lock_path), "true"], capture_output=True)
                        if probe.returncode != 0:
                            break
                    __import__("time").sleep(0.1)
                module.transport_message_report(messages, inbox_root, locks, now=now)
                self.assertFalse((inbox_root / "tur-1" / old).exists())
            finally:
                os.killpg(holder.pid, __import__("signal").SIGTERM)
                holder.wait()
            module.transport_message_report(messages, inbox_root, locks, now=now)
            self.assertTrue((inbox_root / "tur-1" / old).is_file())

    # --- T22f / S3: loud stalled line every cycle ---------------------------

    def test_t22f_stalled_line_persists_across_consecutive_sweep_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            stream = control / "streams/tur-1"
            stream.mkdir(parents=True)
            (stream / "status.md").write_text("Outcome: working\n")
            owner = base / "operator-owner.toml"
            owner.write_text(
                f'schema_version = 1\nowner_session_id = "operator-1-session"\n'
                f'owner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
            )
            fake_bin = base / "bin"
            fake_bin.mkdir()
            log = base / "calls.jsonl"
            (fake_bin / "claude").write_text(FAKE_RECONCILER_CLAUDE)
            (fake_bin / "operator-say").write_text("#!/usr/bin/env bash\nexit 0\n")
            for name in ("claude", "operator-say"):
                (fake_bin / name).chmod(0o755)
            xdg = base / "xdg"
            messages = xdg / "octo-lite" / "messages"
            self._seed_message(messages, self.MSG, target="tur-1", status="stalled",
                               path="deferred", attempts=3)
            env = dict(
                os.environ,
                PATH=f"{fake_bin}:{os.environ['PATH']}",
                CALL_LOG=str(log),
                OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
                XDG_STATE_HOME=str(xdg),
                OCTO_HERDR=str(base / "no-such-herdr"),
            )
            command = [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]
            first = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertIn("TRANSPORT STALLED", first.stdout)
            self.assertIn(self.MSG, first.stdout)
            # Second cycle (unchanged fingerprint noop path): still loud.
            second = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertIn("TRANSPORT STALLED", second.stdout)
            self.assertIn(self.MSG, second.stdout)

    # --- T22g: invalid repair-seconds env -----------------------------------

    def test_t22g_invalid_publication_repair_seconds_defaults_with_warning(self) -> None:
        module = _load_operator_sweep_module()
        with mock.patch.dict(os.environ, {"OCTO_PUBLICATION_REPAIR_SECONDS": "soon"}):
            value, warning = module._positive_int_env("OCTO_PUBLICATION_REPAIR_SECONDS", 180)
        self.assertEqual(180, value)
        self.assertIn("OCTO_PUBLICATION_REPAIR_SECONDS", warning)
        with mock.patch.dict(os.environ, {"OCTO_PUBLICATION_REPAIR_SECONDS": "240"}):
            value, warning = module._positive_int_env("OCTO_PUBLICATION_REPAIR_SECONDS", 180)
        self.assertEqual(240, value)
        self.assertEqual("", warning)

    # --- T31-lite: G2-lite registry advisories ------------------------------

    def _fake_agent_list_herdr(self, base: Path, payload: str) -> Path:
        fake = base / "fake-herdr"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >>\"$HERDR_CALL_LOG\"\n"
            'if [[ "$1 $2" == "agent list" ]]; then\n'
            f"  cat <<'JSON'\n{payload}\nJSON\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n"
        )
        fake.chmod(0o755)
        return fake

    def test_t31_lite_advisory_for_unregistered_live_agents(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "control"
            registered = control / "streams" / "tur-1"
            registered.mkdir(parents=True)
            (registered / "stream.toml").write_text("schema_version = 1\n")
            call_log = base / "herdr-calls"
            payload = json.dumps({"result": {"agents": [
                {"name": "tur-1"}, {"name": "rogue-agent"},
                {"name": "operator-1"}, {"name": "exempt-agent"},
            ]}})
            fake = self._fake_agent_list_herdr(base, payload)
            with mock.patch.dict(os.environ, {
                "OCTO_HERDR": str(fake),
                "HERDR_CALL_LOG": str(call_log),
                "OCTO_REGISTRY_EXEMPT": "exempt-agent",
            }):
                advisories = module.registry_lite_advisories(control, "operator-1")
            self.assertEqual(1, len(advisories), advisories)
            self.assertTrue(advisories[0].startswith("ADVISORY (registry-lite):"), advisories)
            self.assertIn("rogue-agent", advisories[0])
            # NEVER an operator-action line (exempt from the gate law).
            self.assertNotIn("OPERATOR ACTION", advisories[0])
            # Exactly one agent-list call per sweep.
            self.assertEqual(["agent list"], call_log.read_text().splitlines())

    def test_t31_lite_degrades_gracefully_when_agent_list_fails(self) -> None:
        module = _load_operator_sweep_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "control"
            (control / "streams").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"OCTO_HERDR": str(base / "no-such-herdr")}):
                advisories = module.registry_lite_advisories(control, "operator-1")
            self.assertEqual([], advisories)

    # --- T-R87d: operator-timer env propagation -----------------------------

    def test_tr87d_timer_propagates_transport_env_into_the_unit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
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
            env = dict(
                os.environ,
                PATH=f"{fake_bin}:{os.environ['PATH']}",
                CALL_LOG=str(call_log),
                OCTO_REGISTRY_EXEMPT="exempt-agent,other",
                OCTO_PUBLICATION_REPAIR_SECONDS="240",
                OCTO_TRANSPORT_ATTEMPT_CAP="5",
            )
            result = subprocess.run(
                [
                    str(TIMER), "install", "--name", "operator-1",
                    "--control-dir", str(control), "--owner-file", str(owner),
                    "--repo", str(repo),
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            call = call_log.read_text()
            # Same --setenv mechanism as the LINEAR_API_KEY propagation.
            self.assertIn("--setenv=OCTO_REGISTRY_EXEMPT=exempt-agent,other", call)
            self.assertIn("--setenv=OCTO_PUBLICATION_REPAIR_SECONDS=240", call)
            self.assertIn("--setenv=OCTO_TRANSPORT_ATTEMPT_CAP=5", call)
            self.assertIn("--setenv=PATH=", call)


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
            GH_PUBLISHER=PUBLISHER,
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
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--repo-slug", SLUG,
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
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--repo-slug", SLUG, "--pr", "7",
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
                repo=SLUG, pr=7, head=head, intent_ref="ruling-15",
                recorded_at="2026-07-21T00:00:00+00:00",
            )
            digest = module._surface_digest(body)
            # Full-shape forged record (self-digest correct, a fabricated
            # comment_id, the trusted publisher name), but no live comment.
            (stream / "intent-record.toml").write_text(
                'schema_version = 1\nintent_ref = "ruling-15"\n'
                f'head = "{head}"\nrecorded_at = "2026-07-21T00:00:00+00:00"\n'
                f'repo = {json.dumps(SLUG)}\npr = 7\n'
                f'surface_sha256 = "{digest}"\n'
                f'comment_id = 999\npublisher = {json.dumps(PUBLISHER)}\n'
            )
            # Empty live surface store: no command ever published this record.
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                    "--repo-slug", SLUG, "--trusted-publisher", PUBLISHER,
                ],
                capture_output=True, text=True, env=self._env(base, head),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("no command-published surface", result.stderr)

    def test_verify_rejects_record_whose_repo_differs_from_cli_repo_argument(self) -> None:
        # Repo-arg bind at the record level: a record produced against one
        # canonical repo slug carries no authority when verified against a
        # different CLI repo slug, even with the same local path.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = self._init_repo(repo)
            stream = base / "stream"
            store = base / "comments.json"
            produced = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--stream-dir", str(stream),
                    "--intent-ref", "ruling-15", "--repo", str(repo),
                    "--repo-slug", "org/repo", "--pr", "7",
                ],
                capture_output=True, text=True, env=self._env(base, head, store),
            )
            self.assertEqual(0, produced.returncode, produced.stderr)
            # Verify against a DIFFERENT canonical repo slug than the record binds.
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                    "--repo-slug", "org/other", "--trusted-publisher", PUBLISHER,
                ],
                capture_output=True, text=True, env=self._env(base, head, store),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("repo mismatch with CLI repo slug", result.stderr)

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
                f'repo = {json.dumps(SLUG)}\npr = 7\n'
                f'surface_sha256 = "{"0" * 64}"\n'
                f'comment_id = 999\npublisher = {json.dumps(PUBLISHER)}\n'
            )
            result = subprocess.run(
                [
                    str(CONTROL), "intent-record", "--verify",
                    "--stream-dir", str(stream), "--repo", str(repo),
                    "--repo-slug", SLUG, "--trusted-publisher", PUBLISHER,
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
                    "--intent-ref", "ruling-15", "--repo", str(repo), "--repo-slug", SLUG, "--pr", "7",
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


class OperatorGateEdgeTriggerTests(unittest.TestCase):
    """TUR-489 (ruling-58 / ruling-60): the loud operator-gate block stays on
    stdout EVERY cycle (sweep-operator-gate-unsuppressible), but the OPERATOR
    PANE ping via operator-say is EDGE-TRIGGERED - it fires once per new/changed
    gate SET (sha256 over the sorted gate lines, persisted at
    <control>/.operator-gate-last), does not re-flood while the set is unchanged,
    re-arms when the set clears, and (on a hard send failure with rc not in
    {0,75}) leaves the marker unwritten so the next pass retries rather than
    silently dropping a NEW gate. These tests retro-cover the emergency hot-fix
    at 3c8607f that shipped without spec-derived TDD."""

    MARKER_NAME = ".operator-gate-last"

    def _write_owner(self, base: Path, control: Path) -> Path:
        owner = base / "operator-owner.toml"
        owner.write_text(
            f'schema_version = 1\nowner_session_id = "operator-1-session"\n'
            f'owner_route = "operator-1"\nhandoff_revision = 0\ncontrol_dir = "{control}"\n'
        )
        return owner

    def _fake_bins(self, base: Path) -> tuple[Path, Path, dict]:
        """Fake bin harness whose operator-say (a) appends one 'ping' marker line
        per 'Operator gate' pane push to CALL_LOG so a test can COUNT pane pings,
        (b) still echoes the artifact so stdout-delivery assertions hold, and
        (c) exits with ${OPERATOR_SAY_RC:-0} so a test can force a hard-fail send."""
        fake_bin = base / "bin"
        fake_bin.mkdir()
        log = base / "calls.jsonl"
        (fake_bin / "claude").write_text(FAKE_RECONCILER_CLAUDE)
        (fake_bin / "operator-say").write_text(
            "#!/usr/bin/env bash\n"
            "printf 'operator %s\\n' \"$*\" >>\"$CALL_LOG\"\n"
            'for a in "$@"; do prev="${prev:-}"; if [[ "$prev" == "--artifact" ]]; then cat "$a" >>"$CALL_LOG"; fi; prev="$a"; done\n'
            'gate=0\n'
            'for a in "$@"; do if [[ "$a" == "Operator gate" ]]; then gate=1; fi; done\n'
            # The edge-trigger pane push is the "Operator gate" message; count it
            # and let a test force ITS rc via GATE_SAY_RC. Every other operator-say
            # (e.g. the reconcile "Sweep delta ready" delivery) always succeeds so
            # the CHANGED reconcile path is never wedged by the fault injection.
            'if [[ "$gate" == "1" ]]; then printf \'gate-pane-ping\\n\' >>"$CALL_LOG"; exit "${GATE_SAY_RC:-0}"; fi\n'
            'exit 0\n'
        )
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
            (fake_bin / name).chmod(0o755)
        env = dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", CALL_LOG=str(log),
            OCTO_OPERATOR_SAY=str(fake_bin / "operator-say"),
        )
        return fake_bin, log, env

    def _ping_count(self, log: Path) -> int:
        if not log.exists():
            return 0
        return sum(1 for line in log.read_text().splitlines() if line == "gate-pane-ping")

    def _stream(self, control: Path) -> Path:
        stream = control / "streams/tf-carrier"
        stream.mkdir(parents=True)
        (stream / "status.md").write_text("Outcome: ready\n")
        (stream / "sources.toml").write_text('schema_version = 1\n\n[linear]\nissue = "TUR-479"\n')
        return stream

    def _sweep_cmd(self, control: Path, owner: Path, repo: Path) -> list[str]:
        return [str(SWEEP), "--control-dir", str(control), "--owner-file", str(owner), "--repo", str(repo)]

    def _run_to_noop(self, command: list[str], env: dict, *, max_runs: int = 4) -> subprocess.CompletedProcess:
        """Run the sweep until it reaches the unchanged-fingerprint noop path
        (changed == False). The FIRST run after any fact change is a CHANGED
        reconcile whose gate surfaces through the reconcile result push; the
        edge-triggered _emit_operator_gate pane ping only runs on the noop path,
        so the tests observe edge behavior from the settled (noop) state."""
        last = None
        for _ in range(max_runs):
            last = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            if not _sweep_stdout_json(last.stdout)["changed"]:
                return last
        raise AssertionError(f"sweep never settled to noop:\n{last.stdout if last else ''}")

    def test_edge_unchanged_set_pings_once(self) -> None:
        # Persistent gate set (TUR-479 In Staging) driven repeatedly on the
        # unchanged-fingerprint noop path: the pane ping fires EXACTLY ONCE (the
        # marker suppresses the re-ping on every subsequent pass), while the loud
        # gate line is on stdout on EVERY run (unsuppressible preserved).
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            self._stream(control)
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            command = self._sweep_cmd(control, owner, repo)

            outputs = []
            for _ in range(3):
                result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
                outputs.append(result.stdout)

            # Unsuppressible: the loud line is on stdout on EVERY run.
            for stdout in outputs:
                self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", stdout)
            # Run 1 is the CHANGED reconcile; runs 2 and 3 hit the noop path.
            self.assertTrue(_sweep_stdout_json(outputs[0])["changed"])
            self.assertFalse(_sweep_stdout_json(outputs[1])["changed"])
            self.assertFalse(_sweep_stdout_json(outputs[2])["changed"])
            # Edge-triggered: exactly ONE pane ping across the noop passes.
            self.assertEqual(1, self._ping_count(log))
            self.assertTrue((control / self.MARKER_NAME).is_file())

    def test_edge_changed_set_repings(self) -> None:
        # Gate set A (In Staging) settles -> 1 pane ping (marker = fingerprint A);
        # the set then CHANGES (In Preprod: a different gate line) -> once the new
        # set settles on the noop path, a NEW ping fires because the marker holds
        # the stale fingerprint A.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            self._stream(control)
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            command = self._sweep_cmd(control, owner, repo)

            settled_a = self._run_to_noop(command, env)
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", settled_a.stdout)
            self.assertEqual(1, self._ping_count(log))

            # The gate SET changes: TUR-479 moves to a different gated state.
            state_map.write_text(json.dumps({"TUR-479": "In Preprod"}))
            settled_b = self._run_to_noop(command, env)
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Preprod", settled_b.stdout)
            # Changed fingerprint -> a NEW (second) pane ping fired.
            self.assertEqual(2, self._ping_count(log))

    def test_edge_clear_rearms(self) -> None:
        # Gate present, settled (1 ping, marker written) -> gate set becomes EMPTY
        # (issue no longer gated): the marker is unlinked (re-arm), no new ping ->
        # the gate returns and settles -> it re-pings (re-arm proven).
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            self._stream(control)
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            command = self._sweep_cmd(control, owner, repo)
            marker = control / self.MARKER_NAME

            self._run_to_noop(command, env)
            self.assertEqual(1, self._ping_count(log))
            self.assertTrue(marker.is_file())

            # Gate clears: TUR-479 moves to a non-gated state -> gate_lines empty.
            state_map.write_text(json.dumps({"TUR-479": "Live"}))
            cleared = self._run_to_noop(command, env)
            self.assertNotIn("OPERATOR ACTION NEEDED", cleared.stdout)
            # Marker unlinked on the empty set (re-arm); no new ping while clear.
            self.assertFalse(marker.is_file())
            self.assertEqual(1, self._ping_count(log))

            # Gate returns: a fresh, re-armed pane ping fires.
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            back = self._run_to_noop(command, env)
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", back.stdout)
            self.assertEqual(2, self._ping_count(log))
            self.assertTrue(marker.is_file())

    def test_edge_hardfail_retries(self) -> None:
        # sweep-operator-gate-edge-retry: a hard send failure (rc not in {0,75})
        # must NOT write the marker, so a NEW gate is never silently dropped: the
        # next pass RE-PINGS. Once the send succeeds (rc 0) the marker persists and
        # a repeat does not re-ping. The lean heartbeat emits the edge ping on
        # EVERY wake, so a single wake fires exactly one ping attempt.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            _init_target_repo(repo)
            control = base / "control"
            self._stream(control)
            owner = self._write_owner(base, control)
            fake_bin, log, env = self._fake_bins(base)
            state_map = base / "state-map.json"
            state_map.write_text(json.dumps({"TUR-479": "In Staging"}))
            env["LINEAR_STATE_MAP"] = str(state_map)
            command = self._sweep_cmd(control, owner, repo)
            marker = control / self.MARKER_NAME

            # One wake with the gate pane push HARD-FAILING (rc 1): the ping is
            # attempted but the marker is NOT written.
            fail_env = dict(env, GATE_SAY_RC="1")
            first = subprocess.run(command, env=fail_env, check=True, capture_output=True, text=True)
            self.assertIn("OPERATOR ACTION NEEDED: TUR-479 In Staging", first.stdout)
            self.assertEqual(1, self._ping_count(log))
            self.assertFalse(marker.is_file())

            # Retry (still failing): the unchanged set RE-PINGS because the marker
            # was never persisted; the gate is not silently dropped.
            second = subprocess.run(command, env=fail_env, check=True, capture_output=True, text=True)
            self.assertFalse(_sweep_stdout_json(second.stdout)["changed"])
            self.assertEqual(2, self._ping_count(log))
            self.assertFalse(marker.is_file())

            # Send now succeeds (rc 0): the ping fires once more and the marker persists.
            third = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertFalse(_sweep_stdout_json(third.stdout)["changed"])
            self.assertEqual(3, self._ping_count(log))
            self.assertTrue(marker.is_file())

            # Unchanged set with a healthy sender: no re-ping (edge holds).
            fourth = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
            self.assertFalse(_sweep_stdout_json(fourth.stdout)["changed"])
            self.assertEqual(3, self._ping_count(log))


class WorkspaceAdmitProvisionCliTests(unittest.TestCase):
    # gh#8 host-provisioned isolated worktree RED-9: `octo-control workspace-admit`
    # PROVISIONS the lane worktree (not admit-only) and emits the out-of-tree
    # provisioning record path; stdout JSON carries the frozen record.

    def _init_control_repo(self, repo: Path, remote: str) -> str:
        # A full self-contained copy of the real octo-lite source tree, so the
        # REAL scripts/install-octo-lite the default install_check invokes has
        # every source path it needs (link_one requires each source to exist
        # even in --check mode).
        shutil.copytree(
            ROOT, repo,
            ignore=shutil.ignore_patterns(".git", "tests", "docs", "spec", "__pycache__", "*.pyc"),
        )
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_workspace_admit_cli_provisions_and_emits_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control_repo = base / "control"
            slug = "acme/widgets"
            head = self._init_control_repo(control_repo, f"https://github.com/{slug}.git")
            worktree_root = base / "worktrees"
            worktree = worktree_root / "lane-1"
            prefix = base / "prefix"
            subprocess.run(
                [str(control_repo / "scripts" / "install-octo-lite"), "--prefix", str(prefix)],
                check=True, capture_output=True, text=True,
            )
            env = dict(os.environ, HOME=str(prefix))
            result = subprocess.run(
                [
                    str(CONTROL), "workspace-admit",
                    "--control-repo", str(control_repo),
                    "--worktree-root", str(worktree_root),
                    "--worktree", str(worktree),
                    "--lane", "lane-1",
                    "--branch", "octo-lite/lane-1",
                    "--starting-commit", head,
                    "--repo-slug", slug,
                    "--minimum-free-bytes", "1",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["admitted"])
            self.assertEqual(str(worktree.resolve()), payload["worktree"])
            record_path = Path(payload["record_path"])
            self.assertFalse(str(record_path).startswith(str(worktree) + os.sep))
            self.assertTrue(record_path.is_file())
            record = payload["record"]
            self.assertEqual("host-provisioned-worktree", record["source"])
            self.assertEqual("lane-1", record["lane"])
            self.assertEqual(head, record["starting_head"])
            self.assertEqual(json.loads(record_path.read_text()), record)

    # REG-4 (code-review finding 4, octo-control:959): the frozen
    # `--starting-commit <ref>` flag name must be honored by the CLI, and an
    # abbreviated sha must be RESOLVED to the full commit sha before it is
    # compared and recorded.
    def test_workspace_admit_cli_honors_frozen_starting_commit_flag_and_resolves_ref(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control_repo = base / "control"
            slug = "acme/widgets"
            head = self._init_control_repo(control_repo, f"https://github.com/{slug}.git")
            worktree_root = base / "worktrees"
            worktree = worktree_root / "lane-2"
            prefix = base / "prefix"
            subprocess.run(
                [str(control_repo / "scripts" / "install-octo-lite"), "--prefix", str(prefix)],
                check=True, capture_output=True, text=True,
            )
            env = dict(os.environ, HOME=str(prefix))
            result = subprocess.run(
                [
                    str(CONTROL), "workspace-admit",
                    "--control-repo", str(control_repo),
                    "--worktree-root", str(worktree_root),
                    "--worktree", str(worktree),
                    "--lane", "lane-2",
                    "--branch", "octo-lite/lane-2",
                    "--starting-commit", head[:10],
                    "--repo-slug", slug,
                    "--minimum-free-bytes", "1",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(head, payload["record"]["starting_head"])

    # REG-8 (code-review finding 8, octo-control:782): the CLI must SURFACE
    # install_check_owner_route (route the drift owner signal), not discard it.
    def test_workspace_admit_cli_surfaces_install_check_owner_route_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control_repo = base / "control"
            slug = "acme/widgets"
            head = self._init_control_repo(control_repo, f"https://github.com/{slug}.git")
            worktree_root = base / "worktrees"
            worktree = worktree_root / "lane-3"
            prefix = base / "prefix"
            subprocess.run(
                [str(control_repo / "scripts" / "install-octo-lite"), "--prefix", str(prefix)],
                check=True, capture_output=True, text=True,
            )
            # Seed a genuine foreign-owned drift the installer refuses to repair.
            target = prefix / ".codex" / "AGENTS.md"
            target.unlink()
            foreign = prefix / "elsewhere.md"
            foreign.write_text("foreign\n")
            target.symlink_to(foreign)
            env = dict(os.environ, HOME=str(prefix))
            result = subprocess.run(
                [
                    str(CONTROL), "workspace-admit",
                    "--control-repo", str(control_repo),
                    "--worktree-root", str(worktree_root),
                    "--worktree", str(worktree),
                    "--lane", "lane-3",
                    "--branch", "octo-lite/lane-3",
                    "--starting-commit", head,
                    "--repo-slug", slug,
                    "--minimum-free-bytes", "1",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("drifted", payload["record"]["install_check"])
            self.assertEqual("installed-surface-owner", payload.get("install_check_owner_route"))

    # REG-9 (code-review finding 9, octo-control:953): admit-only backward
    # compat. Every prior admit-only caller (no provisioning flags) must
    # still function unchanged.
    def test_workspace_admit_cli_admit_only_backward_compat_without_provisioning_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            worktree_root = base / "worktrees"
            worktree_root.mkdir()
            worktree = worktree_root / "plain-admit"
            result = subprocess.run(
                [
                    str(CONTROL), "workspace-admit",
                    "--worktree", str(worktree),
                    "--worktree-root", str(worktree_root),
                    "--minimum-free-bytes", "1",
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual({"admitted": True, "worktree": str(worktree.resolve())}, payload)


if __name__ == "__main__":
    unittest.main()
