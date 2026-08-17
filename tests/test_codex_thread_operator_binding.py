"""Regression reds for the TUR-641 code-review findings.

Every test here pins one spec-named seam that the first delivery pass left
unbound: the exact active-Fable proof, the provenance of captured context, the
handoff successor path, mode-specific routing, the control-directory readback,
and the host identity and workspace proofs.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import unittest.mock
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from octo_lite import runtime  # noqa: E402

ACTIVATE = ROOT / "skills/launch-meta-operator/scripts/activate-codex-thread-operator.sh"
OPERATOR_SAY = ROOT / "skills/herdr-comms/assets/operator-say"

THREAD = "01a00d39-66b0-76b3-ab56-05cd3262e10e"
OTHER_THREAD = "0be7bb11-2222-4444-8888-999999999999"
WORKSPACE = "w1"
CODEX_MODE = "codex-thread"
FABLE_SESSION = "fable-session-1"
FABLE_ROUTE = "operator-fable"

# One fake Herdr CLI for every boundary these seams cross: the read-only
# workspace lookup, the structured agent record, and the agent stop that must be
# reached only after the exact active-Fable proof succeeds.
FAKE_HERDR = r"""#!/usr/bin/env bash
printf 'herdr %s\n' "$*" >>"$CALL_LOG"
case "$1 $2" in
  "agent get")
    [[ -f "$STOPPED_MARK" ]] && exit 1
    [[ -n "${AGENT_JSON:-}" ]] || exit 1
    printf '%s\n' "$AGENT_JSON"
    exit 0
    ;;
  "agent stop")
    : >"$STOPPED_MARK"
    exit 0
    ;;
  "workspace get")
    printf '%s\n' "${WORKSPACE_JSON:-}"
    exit "${WORKSPACE_STATUS:-0}"
    ;;
esac
exit 64
"""

FAKE_SYSTEMCTL = r"""#!/usr/bin/env bash
exit 1
"""

FAKE_HERDR_SAY = r"""#!/usr/bin/env bash
printf 'herdr-say %s\n' "$*" >>"$CALL_LOG"
exit 0
"""


def write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def load_octo_control():
    loader = importlib.machinery.SourceFileLoader(
        "octo_control_binding_cli", str(ROOT / "scripts/octo-control")
    )
    spec = importlib.util.spec_from_loader("octo_control_binding_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


OCTO_CONTROL = load_octo_control()


def fable_owner(path: Path, control_dir: Path, *, revision: int = 0) -> dict:
    values = {
        "schema_version": 1,
        "owner_session_id": FABLE_SESSION,
        "owner_route": FABLE_ROUTE,
        "handoff_revision": revision,
        "control_dir": str(control_dir),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(runtime._toml_document(values))
    return values


def codex_owner(path: Path, control_dir: Path, *, thread: str = THREAD, workspace: str = WORKSPACE, revision: int = 0) -> dict:
    values = {
        "schema_version": 1,
        "owner_session_id": thread,
        "owner_route": thread,
        "owner_mode": CODEX_MODE,
        "herdr_workspace": workspace,
        "handoff_revision": revision,
        "control_dir": str(control_dir),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(runtime._toml_document(values))
    return values


def digest_context() -> dict:
    # Every authoritative reference binds one exact digest, exactly as the
    # helper derives it (operator-control takeover-context-capture).
    return {
        source: f"{source}:reference#{runtime.exact_fingerprint(source)}"
        for source in runtime.CODEX_CONTEXT_SOURCES
    }


class TakeoverCliSeamTest(unittest.TestCase):
    """Seam: octo-control codex-activate --force-takeover, the only caller of the
    forced-takeover law (operator-control takeover-live-fable-only,
    takeover-context-capture, takeover-fence)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.call_log = self.base / "calls.log"
        self.stopped = self.base / "stopped.mark"
        write_executable(self.bin / "herdr", FAKE_HERDR)
        write_executable(self.bin / "systemctl", FAKE_SYSTEMCTL)

        self.prior_control = self.base / "prior-control"
        (self.prior_control / "streams").mkdir(parents=True)
        (self.prior_control / "status.md").write_text("prior owner status\n")
        self.receipt(FABLE_SESSION)

        self.candidate_control = self.base / "codex-control"
        self.owner_path = self.base / "operator-owner.toml"
        self.prior = fable_owner(self.owner_path, self.prior_control)

        self.repo = self.base / "repo"
        (self.repo / "spec").mkdir(parents=True)
        (self.repo / "spec" / "index.spec.html").write_text("<html></html>\n")
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "seed"],
            check=True,
        )

        self.agent = {"name": FABLE_ROUTE, "agent_status": "idle"}
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "OCTO_HERDR": str(self.bin / "herdr"),
            "CALL_LOG": str(self.call_log),
            "STOPPED_MARK": str(self.stopped),
        }

    def receipt(self, session_id: str) -> None:
        (self.prior_control / "receipt.toml").write_text(
            f'schema_version = 1\n\n[bootstrap]\nprovider_session_id = "{session_id}"\n'
        )

    def calls(self) -> str:
        return self.call_log.read_text() if self.call_log.exists() else ""

    def takeover(self, *, context_refs=None, repo=None, workspace=WORKSPACE):
        # The three sources the helper cannot derive locally are supplied by the
        # operator as digest-bound references; everything else is derived.
        refs = [
            f"{source}=https://example.invalid/{source}#{runtime.exact_fingerprint(source)}"
            for source in ("linear_issue_state", "github_pull_request_state", "child_stream_status")
        ]
        args = Namespace(
            owner_file=str(self.owner_path),
            workspace=workspace,
            control_dir=str(self.candidate_control),
            repo=str(repo or self.repo),
            handoff="",
            force_takeover=True,
            reason="operator directed control transfer",
            context_ref=refs + list(context_refs or []),
        )
        env = dict(self.env)
        env["AGENT_JSON"] = json.dumps({"result": {"agent": self.agent}})
        env["CODEX_THREAD_ID"] = THREAD
        env["CODEX_HOME"] = str(self.codex_home())
        with unittest.mock.patch.dict(os.environ, env):
            return OCTO_CONTROL.command_codex_activate(args)

    def codex_home(self) -> Path:
        home = self.base / "codex"
        sessions = home / "sessions" / "2026" / "08" / "17"
        if not sessions.exists():
            sessions.mkdir(parents=True)
            (sessions / f"rollout-2026-08-17T00-00-00-{THREAD}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": THREAD, "session_id": THREAD}}) + "\n"
            )
        return home

    def test_active_fable_proof_binds_route_status_and_launch_receipt(self) -> None:
        # An agent record that does not resolve to the exact prior owner route,
        # carries no canonical agent_status, or is not bound to the prior owner
        # session by its own launch receipt is not proof of an active Fable, so
        # the takeover must refuse before it ever stops anything.
        unbound = [
            {"name": "some-other-route", "agent_status": "idle"},
            {"name": FABLE_ROUTE},
            {"name": FABLE_ROUTE, "agent_status": ""},
            {"name": FABLE_ROUTE, "agent_status": "stopped"},
        ]
        before = self.owner_path.read_bytes()
        for agent in unbound:
            with self.subTest(agent=agent):
                self.agent = agent
                with self.assertRaises(runtime.GateError):
                    self.takeover()
                self.assertNotIn("agent stop", self.calls())
                self.assertEqual(self.owner_path.read_bytes(), before)

        self.agent = {"name": FABLE_ROUTE, "agent_status": "idle"}
        self.receipt("a-different-session")
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertNotIn("agent stop", self.calls())
        self.assertEqual(self.owner_path.read_bytes(), before)

        # Fully bound: the same route, a canonical live status, and a launch
        # receipt naming the exact prior owner session. Only now may fencing run.
        self.receipt(FABLE_SESSION)
        result = self.takeover()
        self.assertIn("agent stop", self.calls())
        self.assertEqual(result["outcome"], "takeover")

    def test_context_is_captured_from_the_prior_owner_control_tree(self) -> None:
        result = self.takeover()
        receipt = tomllib.loads(Path(result["owner"]["takeover_receipt"]).read_text())
        captured = dict(zip(receipt["context_sources"], receipt["context_references"]))
        self.assertIn(str(self.prior_control), captured["control_records"])
        self.assertNotIn(str(self.candidate_control), captured["control_records"])
        self.assertIn(str(self.prior_control), captured["transfer_artifact"])
        self.assertNotIn(str(self.candidate_control), captured["transfer_artifact"])

    def test_absent_or_unreadable_source_refuses_before_fencing(self) -> None:
        before = self.owner_path.read_bytes()
        missing_repo = self.base / "no-such-repo"
        with self.assertRaises(runtime.GateError):
            self.takeover(repo=missing_repo)
        self.assertNotIn("agent stop", self.calls())
        self.assertEqual(self.owner_path.read_bytes(), before)

        shutil.rmtree(self.repo / "spec")
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertNotIn("agent stop", self.calls())
        self.assertEqual(self.owner_path.read_bytes(), before)

    def test_context_ref_cannot_override_derived_evidence(self) -> None:
        before = self.owner_path.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover(context_refs=[f"owner_record=fabricated#{'0' * 64}"])
        self.assertNotIn("agent stop", self.calls())
        self.assertEqual(self.owner_path.read_bytes(), before)


class ContextDigestTest(unittest.TestCase):
    """Seam: force_takeover_codex_thread context validation
    (operator-control takeover-context-capture)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        self.control.mkdir()
        self.owner = self.base / "operator-owner.toml"
        fable_owner(self.owner, self.control)

    def takeover(self, context):
        return runtime.force_takeover_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            reason="operator directed",
            context=context,
            verify_active_fable=lambda owner: {"session_running": True},
            retire_fable=lambda owner: {"session_running": False, "timer_present": False},
            now=lambda: "2026-08-17T01:00:00Z",
        )

    def test_every_context_reference_must_bind_an_exact_digest(self) -> None:
        before = self.owner.read_bytes()
        for bad in ("prose only", "path#absent", "path#unreadable", "path#", "#" + "a" * 64):
            with self.subTest(bad=bad):
                context = digest_context()
                context["source_tracked_work"] = bad
                with self.assertRaises(runtime.GateError):
                    self.takeover(context)
                self.assertEqual(self.owner.read_bytes(), before)

        self.assertEqual(self.takeover(digest_context())["outcome"], "takeover")


class HandoffSuccessorTest(unittest.TestCase):
    """Seam: activate_codex_thread under a different owner
    (operator-control activation-different-owner, activation-handoff-brief,
    role-runtime launch-codex-activation-revalidate)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        (self.control / "handoffs").mkdir(parents=True)
        self.owner = self.base / "operator-owner.toml"

    def test_valid_next_revision_handoff_yields_the_pending_successor_path(self) -> None:
        fable_owner(self.owner, self.control, revision=3)
        before = self.owner.read_bytes()
        handoff = self.control / "handoffs" / "0004.md"
        handoff.write_text("brief\n")
        result = runtime.activate_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            control_dir=str(self.control),
            handoff=str(handoff),
        )
        self.assertEqual(result["outcome"], "pending")
        self.assertEqual(result["handoff_revision"], 4)
        self.assertEqual(result["successor_session_id"], THREAD)
        self.assertEqual(self.owner.read_bytes(), before)

        # A brief that is not the exact next immutable revision grants nothing.
        stale = self.control / "handoffs" / "0002.md"
        stale.write_text("stale\n")
        with self.assertRaises(runtime.GateError):
            runtime.activate_codex_thread(
                self.owner,
                thread_id=THREAD,
                workspace=WORKSPACE,
                control_dir=str(self.control),
                handoff=str(stale),
            )
        self.assertEqual(self.owner.read_bytes(), before)

    def test_resume_fails_closed_when_durable_state_is_unreadable(self) -> None:
        gone = self.base / "vanished-control"
        codex_owner(self.owner, gone)
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            runtime.activate_codex_thread(
                self.owner,
                thread_id=THREAD,
                workspace=WORKSPACE,
                control_dir=str(gone),
            )
        self.assertEqual(self.owner.read_bytes(), before)


class OwnerModeRoutingTest(unittest.TestCase):
    """Seam: the atomic owner transfer's mode-specific routing
    (operator-control handoff-owner, handoff-routing, activation-workspace)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        (self.control / "handoffs").mkdir(parents=True)
        self.owner = self.base / "operator-owner.toml"
        codex_owner(self.owner, self.control)
        self.handoff = self.control / "handoffs" / "0001.md"
        self.handoff.write_text("handoff\n")
        self.readiness = self.base / "successor-ready.toml"

    def transfer(self, new_owner, new_route, **kwargs):
        runtime.declare_successor_ready(
            self.readiness, caller=new_owner, session_id=new_owner, handoff_revision=1
        )
        return runtime.transfer_owner(
            self.owner,
            THREAD,
            THREAD,
            0,
            new_owner,
            new_route,
            1,
            str(self.control),
            caller=THREAD,
            handoff=self.handoff,
            successor_readiness_path=self.readiness,
            **kwargs,
        )

    def test_fable_successor_inherits_no_codex_routing(self) -> None:
        # handoff-meta-operator.sh transfers to a dedicated Fable successor with
        # a routable Herdr owner route and no workspace: it must not silently
        # inherit the retiring Codex thread's mode or workspace.
        updated = self.transfer("fable-session-2", "operator-fable-2")
        stored = tomllib.loads(self.owner.read_text())
        self.assertEqual(updated, stored)
        self.assertNotIn("owner_mode", stored)
        self.assertNotIn("herdr_workspace", stored)

    def test_declared_codex_successor_reuses_the_exact_verified_workspace(self) -> None:
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(
                OTHER_THREAD, OTHER_THREAD, new_owner_mode=CODEX_MODE, new_workspace="w-other"
            )
        self.assertEqual(self.owner.read_bytes(), before)

        updated = self.transfer(
            OTHER_THREAD, OTHER_THREAD, new_owner_mode=CODEX_MODE, new_workspace=WORKSPACE
        )
        self.assertEqual(updated["owner_mode"], CODEX_MODE)
        self.assertEqual(updated["herdr_workspace"], WORKSPACE)


class OperatorSayRoutingTest(unittest.TestCase):
    """Seam: operator-say owner routing (operator-control handoff-routing,
    activation-outbound-only)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bin = self.base / "assets"
        self.bin.mkdir()
        shutil.copy(OPERATOR_SAY, self.bin / "operator-say")
        (self.bin / "operator-say").chmod(0o755)
        write_executable(self.bin / "herdr-say", FAKE_HERDR_SAY)
        self.call_log = self.base / "calls.log"
        self.owner = self.base / "operator-owner.toml"

    def run_say(self) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["OCTO_OPERATOR_OWNER"] = str(self.owner)
        env["CALL_LOG"] = str(self.call_log)
        return subprocess.run(
            [str(self.bin / "operator-say"), "hello"], capture_output=True, text=True, env=env
        )

    def test_codex_thread_owner_has_no_fabricated_herdr_route(self) -> None:
        codex_owner(self.owner, self.base / "control")
        result = self.run_say()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.call_log.exists(), "no Herdr delivery may be fabricated to an app thread")

    def test_dedicated_fable_owner_still_routes_through_herdr(self) -> None:
        fable_owner(self.owner, self.base / "control")
        result = self.run_say()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(FABLE_ROUTE, self.call_log.read_text())


class ControlDirectoryReadbackTest(unittest.TestCase):
    """Seam: activation readbacks (operator-control activation-initial,
    role-runtime launch-codex-activation-failure)."""

    def test_control_directory_failure_leaves_no_codex_owner_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            blocker = base / "blocker"
            blocker.write_text("not a directory\n")
            owner = base / "operator-owner.toml"
            with self.assertRaises((runtime.GateError, OSError)):
                runtime.activate_codex_thread(
                    owner,
                    thread_id=THREAD,
                    workspace=WORKSPACE,
                    control_dir=str(blocker / "control"),
                )
            self.assertFalse(owner.exists(), "no Codex owner record may survive a failed activation")


class HostIdentityProofTest(unittest.TestCase):
    """Seam: the activation entry point's identity and workspace proofs
    (role-runtime launch-codex-activation-host-identity,
    launch-codex-activation-workspace)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.call_log = self.base / "calls.log"
        write_executable(self.bin / "herdr", FAKE_HERDR)
        self.state = self.base / "state"
        self.codex_home = self.base / "codex"
        self.sessions = self.codex_home / "sessions" / "2026" / "08" / "17"
        self.sessions.mkdir(parents=True)
        self.rollout = self.sessions / f"rollout-2026-08-17T00-00-00-{THREAD}.jsonl"
        self.write_meta(THREAD)
        self.cwd = self.base / "repo"
        self.cwd.mkdir()

    def write_meta(self, session_id: str) -> None:
        self.rollout.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": session_id, "session_id": session_id}}) + "\n"
        )

    @property
    def owner_path(self) -> Path:
        return self.state / "octo-lite" / "operator-owner.toml"

    def run_activate(self, *args, workspace_json=None, workspace_status="0"):
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["CALL_LOG"] = str(self.call_log)
        env["XDG_STATE_HOME"] = str(self.state)
        env["CODEX_HOME"] = str(self.codex_home)
        env["CODEX_THREAD_ID"] = THREAD
        env["STOPPED_MARK"] = str(self.base / "unused.mark")
        env["WORKSPACE_JSON"] = workspace_json if workspace_json is not None else json.dumps(
            {"result": {"workspace": {"id": WORKSPACE}}}
        )
        env["WORKSPACE_STATUS"] = workspace_status
        return subprocess.run([str(ACTIVATE), *args], capture_output=True, text=True, env=env)

    def test_rollout_session_metadata_must_name_the_same_thread(self) -> None:
        # A filename is not identity: only the session's own metadata proves the
        # local Codex session is this exact thread.
        self.write_meta(OTHER_THREAD)
        result = self.run_activate("--workspace", WORKSPACE, "--cwd", str(self.cwd))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.owner_path.exists())

        with unittest.mock.patch.dict(
            os.environ, {"CODEX_THREAD_ID": THREAD, "CODEX_HOME": str(self.codex_home)}
        ):
            with self.assertRaises(runtime.GateError):
                OCTO_CONTROL._codex_thread_id()

    def test_workspace_lookup_must_return_the_requested_workspace_id(self) -> None:
        result = self.run_activate(
            "--workspace", WORKSPACE, "--cwd", str(self.cwd),
            workspace_json=json.dumps({"result": {"workspace": {"id": "w-other"}}}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.owner_path.exists())

        empty = self.run_activate("--workspace", WORKSPACE, "--cwd", str(self.cwd), workspace_json="{}")
        self.assertNotEqual(empty.returncode, 0)
        self.assertFalse(self.owner_path.exists())


if __name__ == "__main__":
    unittest.main()
