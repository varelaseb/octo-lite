"""Regression reds for the TUR-641 code-review findings.

Every test here pins one spec-named seam that the first delivery pass left
unbound: the exact active-Fable proof, the provenance of captured context, the
handoff successor path, mode-specific routing, the control-directory readback,
and the host identity and workspace proofs.
"""

from __future__ import annotations

import fcntl
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
# reached only after the exact active-Fable proof succeeds. Retirement is proved
# by a structured POST-STOP answer, never by a failed lookup, so this fake keeps
# answering after the stop unless a test deliberately breaks the lookup.
FAKE_HERDR = r"""#!/usr/bin/env bash
printf 'herdr %s\n' "$*" >>"$CALL_LOG"
case "$1 $2" in
  "agent get")
    if [[ -f "$STOPPED_MARK" ]]; then
      exit_code="${AGENT_GET_AFTER_STOP_STATUS:-0}"
      [[ "$exit_code" == 0 ]] || exit "$exit_code"
      printf '%s\n' "${AGENT_AFTER_STOP_JSON:-}"
      exit 0
    fi
    [[ -n "${AGENT_JSON:-}" ]] || exit 1
    printf '%s\n' "$AGENT_JSON"
    exit 0
    ;;
  "agent stop")
    : >"$STOPPED_MARK"
    exit "${STOP_STATUS:-0}"
    ;;
  "workspace get")
    printf '%s\n' "${WORKSPACE_JSON:-}"
    exit "${WORKSPACE_STATUS:-0}"
    ;;
esac
exit 64
"""

# systemctl answers `is-active` with a state word; a broken or absent systemctl
# answers nothing at all. Retirement must tell those two apart.
FAKE_SYSTEMCTL = r"""#!/usr/bin/env bash
[[ -n "${SYSTEMCTL_BROKEN:-}" ]] && exit 127
state="${SYSTEMCTL_STATE:-inactive}"
printf '%s\n' "$state"
[[ "$state" == active ]] && exit 0
exit 3
"""

# The live Linear and GitHub reads the reconciliation must actually perform.
FAKE_LINEAR = r"""#!/usr/bin/env bash
printf 'linear %s\n' "$*" >>"$CALL_LOG"
[[ "${LINEAR_STATUS:-0}" == 0 ]] || exit "${LINEAR_STATUS}"
printf '{"identifier":"%s","state":{"name":"In Progress"}}\n' "$3"
"""

FAKE_GH = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$CALL_LOG"
[[ "${GH_STATUS:-0}" == 0 ]] || exit "${GH_STATUS}"
printf '[{"number":83,"state":"OPEN","headRefOid":"%s"}]\n' "${GH_HEAD:-0000000000000000000000000000000000000000}"
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


class TakeoverCliHarness(unittest.TestCase):
    """Shared harness for the octo-control codex-activate --force-takeover seam:
    a fake Herdr CLI, systemctl, Linear CLI, GitHub CLI, prior Fable control
    tree, and local Codex session record. It declares no test of its own."""

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
        write_executable(self.bin / "linear", FAKE_LINEAR)
        write_executable(self.bin / "gh", FAKE_GH)

        self.prior_control = self.base / "prior-control"
        (self.prior_control / "streams" / "tur-641").mkdir(parents=True)
        (self.prior_control / "streams" / "tur-641" / "stream.toml").write_text(
            'schema_version = 1\nstream_id = "tur-641"\nissue = "TUR-641"\n'
        )
        (self.prior_control / "streams" / "tur-641" / "status.md").write_text("child status\n")
        (self.prior_control / "status.md").write_text("prior owner status\n")
        self.receipt(FABLE_SESSION)

        self.candidate_control = self.base / "codex-control"
        self.owner_path = self.base / "operator-owner.toml"
        self.prior = fable_owner(self.owner_path, self.prior_control)

        self.repo = self.base / "repo"
        (self.repo / "spec").mkdir(parents=True)
        (self.repo / "spec" / "index.spec.html").write_text("<html></html>\n")
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "remote", "add", "origin",
             "https://github.com/example/repo.git"],
            check=True,
        )
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
            "AGENT_AFTER_STOP_JSON": json.dumps(
                {"result": {"agent": {"name": FABLE_ROUTE, "agent_status": "stopped"}}}
            ),
            "WORKSPACE_JSON": json.dumps({"result": {"workspace": {"id": WORKSPACE}}}),
        }

    def receipt(
        self,
        session_id: str,
        *,
        minimal: bool = False,
        role_name: str = "meta-operator",
        verified: bool = True,
        contract_blob: str = "5aae5b88cbeb8e666e4285e12ee846d26486d731",
        provider: str = "anthropic",
        model: str = "claude-fable-5",
        stale_revision: bool = False,
    ) -> None:
        """The prior owner's persistent launch receipt.

        The full shape is what a real dedicated Fable launch writes: the
        resolver-built persistent meta-operator receipt, self-bound by its own
        launch revision and bootstrap-verified to the exact provider session.
        """
        path = self.prior_control / "receipt.toml"
        if minimal:
            path.write_text(
                f'schema_version = 1\n\n[bootstrap]\nprovider_session_id = "{session_id}"\n'
            )
            return
        values = {
            "schema_version": 1,
            "spawn_id": "11111111-1111-1111-1111-111111111111",
            "parent": "operator",
            "reply_route": "operator",
            "ready": True,
            "role": {
                "name": role_name,
                "root": str(ROOT),
                "contract_path": f"roles/{role_name}.md",
                "contract_blob": contract_blob,
                "mapping_revision": "1e2dddae1d5303afaa7ba2f8035279bc4df61904",
            },
            "runtime": {
                "provider": provider,
                "model": model,
                "effort": "xhigh",
                "mode": "auto",
                "session": "persistent",
            },
            "workspace": {
                "repo": str(self.base / "repo"),
                "worktree": str(self.base / "repo"),
                "starting_head": "0" * 40,
            },
        }
        values["launch_revision"] = (
            "0" * 64 if stale_revision else runtime.launch_revision(values)
        )
        values["bootstrap"] = {"verified": verified, "provider_session_id": session_id}
        path.write_text(runtime._render_full_receipt(values))

    def calls(self) -> str:
        return self.call_log.read_text() if self.call_log.exists() else ""

    def takeover(self, *, repo=None, workspace=WORKSPACE, env_extra=None):
        # Every authoritative source is read live by the helper itself; the caller
        # supplies no context reference at all (operator-control
        # takeover-context-capture, activation-authoritative-context).
        args = Namespace(
            owner_file=str(self.owner_path),
            workspace=workspace,
            control_dir=str(self.candidate_control),
            repo=str(repo or self.repo),
            handoff="",
            force_takeover=True,
            reason="operator directed control transfer",
            # Legacy caller-supplied references, kept only so these seams still
            # exercise the pre-fix helper; the fixed helper reads every source
            # itself and never consults them.
            context_ref=[
                f"{source}=https://example.invalid/{source}#{runtime.exact_fingerprint(source)}"
                for source in ("linear_issue_state", "github_pull_request_state", "child_stream_status")
            ],
        )
        env = dict(self.env)
        env.update(env_extra or {})
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

class TakeoverCliSeamTest(TakeoverCliHarness):
    """Seam: octo-control codex-activate --force-takeover, the only caller of the
    forced-takeover law (operator-control takeover-live-fable-only,
    takeover-context-capture, takeover-fence)."""

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

    def test_no_caller_supplied_context_reference_exists(self) -> None:
        # A caller-supplied reference could only ever be syntax-checked, so the
        # entry point exposes none: every source is read evidence.
        with self.assertRaises(SystemExit):
            OCTO_CONTROL.parser().parse_args([
                "codex-activate",
                "--owner-file", str(self.owner_path),
                "--workspace", WORKSPACE,
                "--control-dir", str(self.candidate_control),
                "--force-takeover", "--reason", "operator directed",
                "--context-ref", f"owner_record=fabricated#{'0' * 64}",
            ])


class FableRetirementProofTest(TakeoverCliHarness):
    """Seam: the fence phase of octo-control codex-activate --force-takeover
    (operator-control takeover-fence, takeover-failure). Retirement is proved by
    a successful stop plus a structured non-running and timer-absent answer; an
    ignored result, a failed lookup, or an unanswerable timer check is never
    retirement evidence."""

    def assert_refused(self, **kwargs) -> None:
        before = self.owner_path.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover(**kwargs)
        self.assertEqual(self.owner_path.read_bytes(), before)
        self.assertFalse((self.prior_control / "takeovers").exists())

    def test_failed_fable_stop_is_not_retirement(self) -> None:
        self.assert_refused(env_extra={"STOP_STATUS": "1"})

    def test_unreadable_post_stop_lookup_is_not_retirement(self) -> None:
        # A Herdr lookup that errors proves nothing about the session; it must
        # never read as a retired Fable.
        self.assert_refused(env_extra={"AGENT_GET_AFTER_STOP_STATUS": "1"})

    def test_still_running_fable_after_stop_is_not_retirement(self) -> None:
        self.assert_refused(env_extra={
            "AGENT_AFTER_STOP_JSON": json.dumps(
                {"result": {"agent": {"name": FABLE_ROUTE, "agent_status": "idle"}}}
            )
        })

    def test_unanswerable_timer_check_is_not_timer_absence(self) -> None:
        self.assert_refused(env_extra={"SYSTEMCTL_BROKEN": "1"})

    def test_still_active_timer_blocks_the_owner_commit(self) -> None:
        self.assert_refused(env_extra={"SYSTEMCTL_STATE": "active"})

    def test_verified_retirement_commits_the_owner_swap(self) -> None:
        result = self.takeover()
        self.assertEqual(result["outcome"], "takeover")
        self.assertIn("agent stop", self.calls())
        receipt = tomllib.loads(Path(result["owner"]["takeover_receipt"]).read_text())
        self.assertIs(receipt["fence_session_running"], False)
        self.assertIs(receipt["fence_timer_present"], False)


class LiveReconciliationTest(TakeoverCliHarness):
    """Seam: the authoritative durable context an activated or takeover-committed
    Codex owner reads (operator-control activation-authoritative-context,
    activation-same-thread-resume, takeover-context-capture, takeover-success;
    role-runtime launch-codex-activation-complete). The helper reads every source
    live and reports the exact references it read, never static source names."""

    def activate(self, **kwargs):
        args = Namespace(
            owner_file=str(self.owner_path),
            workspace=WORKSPACE,
            control_dir=str(self.candidate_control),
            repo=str(self.repo),
            handoff="",
            force_takeover=False,
            reason="",
            context_ref=[],
        )
        for key, value in kwargs.items():
            setattr(args, key, value)
        env = dict(self.env)
        env["AGENT_JSON"] = json.dumps({"result": {"agent": self.agent}})
        env["CODEX_THREAD_ID"] = THREAD
        env["CODEX_HOME"] = str(self.codex_home())
        with unittest.mock.patch.dict(os.environ, env):
            return OCTO_CONTROL.command_codex_activate(args)

    def assert_reconciled(self, result) -> None:
        self.assertEqual(result["context_sources"], list(runtime.CODEX_CONTEXT_SOURCES))
        references = dict(zip(result["context_sources"], result.get("context_references", [])))
        for source in runtime.CODEX_CONTEXT_SOURCES:
            with self.subTest(source=source):
                self.assertTrue(
                    runtime._is_digest_reference(references.get(source, "")),
                    f"{source} must bind an exact digest: {references.get(source)!r}",
                )

    def test_takeover_reads_every_authoritative_source_live(self) -> None:
        result = self.takeover()
        calls = self.calls()
        self.assertIn("linear issue view TUR-641", calls)
        self.assertIn("gh pr list", calls)
        self.assertIn(f"herdr workspace get {WORKSPACE}", calls)
        self.assert_reconciled(result)

    def test_takeover_reconciles_again_after_the_owner_commit(self) -> None:
        result = self.takeover()
        owner = tomllib.loads(self.owner_path.read_text())
        self.assertEqual(result["owner"], owner, "the committed owner must be read back")
        references = dict(zip(result["context_sources"], result.get("context_references", [])))
        self.assertIn(str(self.owner_path), references.get("owner_record", ""))
        self.assertEqual(
            references["owner_record"].rpartition("#")[2],
            runtime.exact_fingerprint(self.owner_path.read_text()),
            "post-commit reconciliation must bind the committed owner record",
        )

    def test_unreadable_live_source_refuses_before_fencing(self) -> None:
        before = self.owner_path.read_bytes()
        for broken in ({"LINEAR_STATUS": "1"}, {"GH_STATUS": "1"}, {"WORKSPACE_STATUS": "1"}):
            with self.subTest(broken=broken):
                with self.assertRaises(runtime.GateError):
                    self.takeover(env_extra=broken)
                self.assertNotIn("agent stop", self.calls())
                self.assertEqual(self.owner_path.read_bytes(), before)

    def test_activation_and_resume_reconcile_the_same_live_sources(self) -> None:
        # A Codex owner with one child stream: its issue is live Linear state the
        # thread must re-read on every wake, not a remembered fact.
        (self.candidate_control / "streams" / "tur-641").mkdir(parents=True)
        (self.candidate_control / "streams" / "tur-641" / "stream.toml").write_text(
            'schema_version = 1\nstream_id = "tur-641"\nissue = "TUR-641"\n'
        )
        self.owner_path.unlink()
        activated = self.activate()
        self.assertEqual(activated["outcome"], "activated")
        self.assert_reconciled(activated)

        self.call_log.unlink()
        resumed = self.activate()
        self.assertEqual(resumed["outcome"], "resumed")
        self.assert_reconciled(resumed)
        self.assertIn("linear issue view", self.calls())
        self.assertIn("gh pr list", self.calls())


class SuccessorWorkspaceBindingTest(unittest.TestCase):
    """Seam: the Codex successor readiness record that binds the verified
    workspace to the atomic owner transfer (operator-control
    activation-workspace, activation-different-owner, activation-handoff-brief;
    ADR 0005 decision-workspace-routing)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        (self.control / "handoffs").mkdir(parents=True)
        self.candidate_control = self.base / "codex-control"
        self.owner = self.base / "operator-owner.toml"
        self.prior = fable_owner(self.owner, self.control)
        self.handoff = self.control / "handoffs" / "0001.md"
        self.handoff.write_text("compact brief\n")

    def pending(self, workspace=WORKSPACE):
        return runtime.activate_codex_thread(
            self.owner,
            thread_id=THREAD,
            workspace=workspace,
            control_dir=str(self.candidate_control),
            handoff=str(self.handoff),
            reconcile=lambda owner: digest_context(),
        )

    def transfer(self, readiness, new_workspace):
        return runtime.transfer_owner(
            self.owner,
            FABLE_SESSION,
            FABLE_ROUTE,
            0,
            THREAD,
            THREAD,
            1,
            str(self.control),
            caller=FABLE_SESSION,
            handoff=self.handoff,
            successor_readiness_path=Path(readiness),
            new_owner_mode=CODEX_MODE,
            new_workspace=new_workspace,
        )

    def test_pending_successor_readiness_binds_the_verified_workspace(self) -> None:
        before = self.owner.read_bytes()
        result = self.pending()
        self.assertEqual(result["outcome"], "pending")
        self.assertEqual(self.owner.read_bytes(), before)
        readiness = tomllib.loads(Path(result["successor_readiness"]).read_text())
        self.assertEqual(readiness["session_id"], THREAD)
        self.assertEqual(readiness["handoff_revision"], 1)
        self.assertEqual(readiness["owner_mode"], CODEX_MODE)
        self.assertEqual(readiness["herdr_workspace"], WORKSPACE)

    def test_transfer_refuses_a_substituted_workspace(self) -> None:
        readiness = self.pending()["successor_readiness"]
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(readiness, "w-substituted")
        self.assertEqual(self.owner.read_bytes(), before)

        updated = self.transfer(readiness, WORKSPACE)
        self.assertEqual(updated["owner_session_id"], THREAD)
        self.assertEqual(updated["herdr_workspace"], WORKSPACE)

    def test_transfer_refuses_a_readiness_record_that_declares_no_codex_routing(self) -> None:
        readiness = self.base / "bare-ready.toml"
        runtime.declare_successor_ready(
            readiness, caller=THREAD, session_id=THREAD, handoff_revision=1,
            handoff=self.handoff,
        )
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.transfer(readiness, WORKSPACE)
        self.assertEqual(self.owner.read_bytes(), before)


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
            reconcile=lambda owner: digest_context(),
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
            reconcile=lambda owner: digest_context(),
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
                reconcile=lambda owner: digest_context(),
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
                reconcile=lambda owner: digest_context(),
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
        # A Codex successor becomes ready only by activating: activation is the
        # only path that read-verifies the workspace and reconciles durable
        # context. A dedicated Fable successor declares its own readiness.
        if kwargs.get("new_owner_mode") == CODEX_MODE:
            self.readiness = Path(
                runtime.activate_codex_thread(
                    self.owner,
                    thread_id=new_owner,
                    workspace=kwargs.get("new_workspace", ""),
                    control_dir=str(self.base / f"succ-{new_owner}"),
                    handoff=str(self.handoff),
                    reconcile=lambda owner: digest_context(),
                )["successor_readiness"]
            )
        else:
            runtime.declare_successor_ready(
                self.readiness,
                caller=new_owner,
                session_id=new_owner,
                handoff_revision=1,
                handoff=self.handoff,
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
                    reconcile=lambda owner: digest_context(),
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


class TakeoverReceiptShapeTest(TakeoverCliHarness):
    """Seam: octo-control codex-activate --force-takeover candidate admission
    (operator-control takeover-live-fable-only). The active-Fable proof must
    resolve the prior owner to one STRUCTURED VERIFIED dedicated Fable, so it
    validates the prior owner's full persistent receipt shape, not route,
    status, and a bare session string. A minimal, role-substituted, unverified,
    self-inconsistent, or unbound receipt proves no dedicated Fable and refuses
    before anything is stopped."""

    def assert_refused(self) -> None:
        before = self.owner_path.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertNotIn("agent stop", self.calls())
        self.assertEqual(self.owner_path.read_bytes(), before)
        self.assertFalse((self.prior_control / "takeovers").exists())

    def test_minimal_receipt_is_not_a_verified_dedicated_fable(self) -> None:
        # Route plus live status plus a bootstrap session id is the whole of the
        # old proof; a receipt carrying nothing else names no role, no contract,
        # and no runtime, so it never proves a dedicated Fable.
        self.receipt(FABLE_SESSION, minimal=True)
        self.assert_refused()

    def test_role_substituted_receipt_refuses(self) -> None:
        self.receipt(FABLE_SESSION, role_name="orchestrator")
        self.assert_refused()

    def test_unverified_bootstrap_refuses(self) -> None:
        self.receipt(FABLE_SESSION, verified=False)
        self.assert_refused()

    def test_receipt_not_bound_by_its_own_launch_revision_refuses(self) -> None:
        self.receipt(FABLE_SESSION, stale_revision=True)
        self.assert_refused()

    def test_receipt_without_contract_or_runtime_binding_refuses(self) -> None:
        for kwargs in ({"contract_blob": ""}, {"provider": ""}, {"model": ""}):
            with self.subTest(**kwargs):
                self.receipt(FABLE_SESSION, **kwargs)
                self.assert_refused()

    def test_full_verified_meta_operator_receipt_admits_the_takeover(self) -> None:
        self.receipt(FABLE_SESSION)
        result = self.takeover()
        self.assertEqual(result["outcome"], "takeover")
        self.assertIn("agent stop", self.calls())


class TakeoverReceiptExclusivityTest(unittest.TestCase):
    """Seam: force_takeover_codex_thread receipt creation
    (operator-control takeover-receipt, takeover-atomic, takeover-failure).
    The immutable receipt is created EXCLUSIVELY and INSIDE the same owner lock
    that commits the swap, so two authorized attempts can never overwrite a
    receipt or commit an owner whose receipt digest or new-owner binding
    disagrees with the receipt on disk."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        self.control.mkdir()
        self.owner = self.base / "operator-owner.toml"
        fable_owner(self.owner, self.control)
        self.receipt_path = self.control / "takeovers" / "0001.toml"

    def takeover(self, *, thread: str = THREAD, now=lambda: "2026-08-17T01:00:00Z"):
        return runtime.force_takeover_codex_thread(
            self.owner,
            thread_id=thread,
            workspace=WORKSPACE,
            reason="operator directed",
            context=digest_context(),
            verify_active_fable=lambda owner: {"session_running": True},
            retire_fable=lambda owner: {"session_running": False, "timer_present": False},
            now=now,
            reconcile=lambda owner: digest_context(),
        )

    def owner_lock_held(self) -> bool:
        # The owner lock is the sole authority-commit lock for this record. A
        # separate descriptor can take it only while nobody else holds it.
        lock_path = self.owner.with_suffix(self.owner.suffix + ".lock")
        if not lock_path.exists():
            return False
        with lock_path.open("a+", encoding="utf-8") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(probe, fcntl.LOCK_UN)
        return False

    def test_receipt_is_written_inside_the_owner_commit_lock(self) -> None:
        held: list[bool] = []

        def now() -> str:
            held.append(self.owner_lock_held())
            return "2026-08-17T01:00:00Z"

        self.assertEqual(self.takeover(now=now)["outcome"], "takeover")
        self.assertEqual(held, [True])

    def test_a_concurrent_receipt_is_never_overwritten_and_commits_no_owner(self) -> None:
        # A second authorized attempt lands its receipt for the same revision
        # between this attempt's checks and its own write. Exclusive creation is
        # the only thing that can tell those two apart, so this attempt must
        # abort with the other receipt's bytes and the prior owner intact.
        rival = 'schema_version = 1\nnew_owner_session_id = "rival-thread"\n'

        def now() -> str:
            self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
            self.receipt_path.write_text(rival)
            return "2026-08-17T01:00:00Z"

        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover(now=now)
        self.assertEqual(self.receipt_path.read_text(), rival)
        self.assertEqual(self.owner.read_bytes(), before)

    def test_a_committed_owner_always_names_the_receipt_bytes_on_disk(self) -> None:
        result = self.takeover()
        owner = result["owner"]
        self.assertEqual(owner["takeover_receipt"], str(self.receipt_path))
        receipt = tomllib.loads(self.receipt_path.read_text())
        self.assertEqual(receipt["new_owner_session_id"], THREAD)
        self.assertEqual(
            owner["takeover_receipt_digest"],
            runtime.exact_fingerprint(self.receipt_path.read_text()),
        )


if __name__ == "__main__":
    unittest.main()
