from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from octo_lite import runtime  # noqa: E402

ACTIVATE = ROOT / "skills/launch-meta-operator/scripts/activate-codex-thread-operator.sh"

THREAD = "01a00d39-66b0-76b3-ab56-05cd3262e10e"
OTHER_THREAD = "0be7bb11-2222-4444-8888-999999999999"
WORKSPACE = "w1"
CODEX_MODE = "codex-thread"

# Every boundary the activation script crosses is faked here: the Herdr CLI
# read-only workspace lookup, and the Codex rollout session file that proves the
# host thread exists locally. No live Herdr, no systemd, no provider call.
FAKE_HERDR = r"""#!/usr/bin/env bash
printf 'herdr %s\n' "$*" >>"$CALL_LOG"
if [[ "$1 $2" == "workspace get" ]]; then
  if [[ "$3" == "w1" ]]; then
    printf '{"result":{"workspace":{"id":"w1"}}}\n'
    exit 0
  fi
  echo '{"error":{"code":"not_found"}}' >&2
  exit 1
fi
exit 64
"""

# Any invocation of background machinery is recorded and then fails loudly, so a
# script that reaches for a timer, unit, or daemon cannot pass silently.
FAKE_BACKGROUND = r"""#!/usr/bin/env bash
printf '%s %s\n' "$(basename "$0")" "$*" >>"$CALL_LOG"
exit 1
"""

# The live Linear and GitHub reads activation reconciliation performs before it
# reports authority (operator-control activation-authoritative-context).
FAKE_LINEAR = r"""#!/usr/bin/env bash
printf 'linear %s\n' "$*" >>"$CALL_LOG"
printf '{"identifier":"%s","state":{"name":"In Progress"}}\n' "$3"
"""

FAKE_GH = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$CALL_LOG"
printf '[{"number":83,"state":"OPEN"}]\n'
"""


def write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def owner_document(values: dict) -> str:
    return runtime._toml_document(values)


def fable_owner(path: Path, *, session="fable-session-1", route="operator-fable", control_dir="/tmp/control", revision=0) -> dict:
    values = {
        "schema_version": 1,
        "owner_session_id": session,
        "owner_route": route,
        "handoff_revision": revision,
        "control_dir": control_dir,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(owner_document(values))
    return values


def codex_owner(path: Path, *, thread=THREAD, workspace=WORKSPACE, control_dir="/tmp/control", revision=0) -> dict:
    values = {
        "schema_version": 1,
        "owner_session_id": thread,
        "owner_route": thread,
        "owner_mode": CODEX_MODE,
        "herdr_workspace": workspace,
        "handoff_revision": revision,
        "control_dir": control_dir,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(owner_document(values))
    return values


def full_context() -> dict:
    # Every authoritative reference binds one exact digest
    # (operator-control takeover-context-capture).
    return {
        source: f"{source}:reference#{runtime.exact_fingerprint(source)}"
        for source in runtime.CODEX_CONTEXT_SOURCES
    }


class ActivationScriptTest(unittest.TestCase):
    """Seam: the single current-thread entry point named by
    operator-control activation-entrypoint and activation-thread-identity."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.call_log = self.base / "calls.log"
        write_executable(self.bin / "herdr", FAKE_HERDR)
        write_executable(self.bin / "linear", FAKE_LINEAR)
        write_executable(self.bin / "gh", FAKE_GH)
        for name in ("systemd-run", "systemctl", "operator-timer"):
            write_executable(self.bin / name, FAKE_BACKGROUND)
        self.state = self.base / "state"
        self.codex_home = self.base / "codex"
        sessions = self.codex_home / "sessions" / "2026" / "08" / "17"
        sessions.mkdir(parents=True)
        # Codex's own session_meta record, the authoritative identity source.
        (sessions / f"rollout-2026-08-17T00-00-00-{THREAD}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": THREAD, "session_id": THREAD}}) + "\n"
        )
        # The INSTALLED profile guidance the activation loads from its installed
        # source before authority can act (role-runtime
        # launch-codex-activation-contract).
        (self.codex_home / "AGENTS.md").write_text("installed profile\n")
        # The source-tracked work, target instructions, and canonical spec set
        # activation reconciles.
        self.cwd = self.base / "repo"
        (self.cwd / "spec").mkdir(parents=True)
        (self.cwd / "spec" / "index.spec.html").write_text("<html></html>\n")
        (self.cwd / "AGENTS.md").write_text("target instructions\n")
        subprocess.run(["git", "-C", str(self.cwd), "init", "-q"], check=True)
        subprocess.run(
            ["git", "-C", str(self.cwd), "remote", "add", "origin",
             "https://github.com/example/repo.git"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.cwd), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.cwd), "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "seed"],
            check=True,
        )

    def run_activate(self, *args, thread=THREAD, env_extra=None):
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["CALL_LOG"] = str(self.call_log)
        env["XDG_STATE_HOME"] = str(self.state)
        env["CODEX_HOME"] = str(self.codex_home)
        env.pop("CODEX_THREAD_ID", None)
        if thread is not None:
            env["CODEX_THREAD_ID"] = thread
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [str(ACTIVATE), *args],
            capture_output=True,
            text=True,
            env=env,
        )

    @property
    def owner_path(self) -> Path:
        return self.state / "octo-lite" / "operator-owner.toml"

    def test_host_thread_identity_is_required_and_cannot_be_overridden(self) -> None:
        missing = self.run_activate("--workspace", WORKSPACE, "--cwd", str(self.cwd), thread=None)
        self.assertEqual(missing.returncode, 64, missing.stderr)
        self.assertIn("CODEX_THREAD_ID", missing.stderr)
        self.assertFalse(self.owner_path.exists())

        override = self.run_activate(
            "--workspace", WORKSPACE, "--cwd", str(self.cwd), "--thread-id", OTHER_THREAD
        )
        self.assertEqual(override.returncode, 64, override.stdout)
        self.assertFalse(self.owner_path.exists())

        unknown_session = self.run_activate(
            "--workspace", WORKSPACE, "--cwd", str(self.cwd), thread=OTHER_THREAD
        )
        self.assertEqual(unknown_session.returncode, 66, unknown_session.stdout)
        self.assertFalse(self.owner_path.exists())

    def test_workspace_is_read_verified_before_any_authority_write(self) -> None:
        result = self.run_activate("--workspace", "w-unknown", "--cwd", str(self.cwd))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.owner_path.exists())
        self.assertIn("herdr workspace get w-unknown", self.call_log.read_text())

    def test_codex_mode_creates_no_background_operator_machinery(self) -> None:
        result = self.run_activate("--workspace", WORKSPACE, "--cwd", str(self.cwd))
        self.assertEqual(result.returncode, 0, result.stderr)
        owner = tomllib.loads(self.owner_path.read_text())
        self.assertEqual(owner["owner_session_id"], THREAD)
        self.assertEqual(owner["owner_mode"], CODEX_MODE)
        self.assertEqual(owner["herdr_workspace"], WORKSPACE)

        calls = self.call_log.read_text()
        for machinery in ("systemd-run", "systemctl", "operator-timer"):
            self.assertNotIn(machinery, calls)
        control = Path(owner["control_dir"])
        self.assertTrue(control.is_dir())
        self.assertFalse((control / "timer.toml").exists())
        self.assertEqual(list(self.state.rglob("*.timer")), [])


class ActivationLawTest(unittest.TestCase):
    """Seam: the ownership law behind the entry point (operator-control
    activation-initial, activation-same-thread-resume, activation-workspace,
    activation-different-owner, activation-distinct-thread,
    activation-handoff-brief, activation-failure-ordinary)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.owner = self.base / "operator-owner.toml"
        self.control = str(self.base / "control")

    def activate(self, *, thread=THREAD, workspace=WORKSPACE, control_dir=None):
        return runtime.activate_codex_thread(
            self.owner,
            thread_id=thread,
            workspace=workspace,
            control_dir=control_dir or self.control,
            reconcile=lambda owner: full_context(),
        )

    def test_initial_owner_binding_is_atomic_and_exact(self) -> None:
        result = self.activate()
        self.assertEqual(result["outcome"], "activated")
        self.assertEqual(runtime.CODEX_OWNER_MODE, CODEX_MODE)
        stored = tomllib.loads(self.owner.read_text())
        self.assertEqual(
            stored,
            {
                "schema_version": 1,
                "owner_session_id": THREAD,
                "owner_route": THREAD,
                "owner_mode": CODEX_MODE,
                "herdr_workspace": WORKSPACE,
                "handoff_revision": 0,
                "control_dir": self.control,
            },
        )
        self.assertEqual(result["owner"], stored)

    def test_same_thread_reopen_is_idempotent_resume(self) -> None:
        self.activate()
        before = self.owner.read_bytes()
        resumed = self.activate()
        self.assertEqual(resumed["outcome"], "resumed")
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertEqual(resumed["owner"]["owner_session_id"], THREAD)

    def test_workspace_is_immutable_across_resume(self) -> None:
        self.activate()
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.activate(workspace="w-other")
        self.assertEqual(self.owner.read_bytes(), before)

    def test_distinct_thread_inherits_nothing(self) -> None:
        self.activate()
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.activate(thread=OTHER_THREAD)
        self.assertEqual(self.owner.read_bytes(), before)

    def test_active_fable_blocks_ordinary_or_parallel_activation(self) -> None:
        fable_owner(self.owner)
        before = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.activate()
        self.assertEqual(self.owner.read_bytes(), before)

    def test_handoff_brief_is_context_not_authority(self) -> None:
        fable_owner(self.owner)
        before = self.owner.read_bytes()
        brief = self.base / "brief.md"
        brief.write_text("compact context only\n")
        with self.assertRaises(runtime.GateError):
            runtime.activate_codex_thread(
                self.owner,
                thread_id=THREAD,
                workspace=WORKSPACE,
                control_dir=self.control,
                handoff=str(brief),
                reconcile=lambda owner: full_context(),
            )
        self.assertEqual(self.owner.read_bytes(), before)

    def test_activation_commit_failure_leaves_no_partial_state(self) -> None:
        blocker = self.base / "blocker"
        blocker.write_text("not a directory\n")
        self.owner = blocker / "operator-owner.toml"
        with self.assertRaises((runtime.GateError, OSError)):
            self.activate()
        self.assertFalse(self.owner.exists())
        self.assertEqual(blocker.read_text(), "not a directory\n")


class TransferRoutingTest(unittest.TestCase):
    """Seam: the existing atomic owner transfer binds the successor's own
    mode-specific routing (operator-control activation-workspace, handoff-owner,
    ADR 0005 decision-workspace-routing)."""

    def test_atomic_transfer_binds_a_declared_codex_successor_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            control = base / "control"
            (control / "handoffs").mkdir(parents=True)
            owner_path = base / "operator-owner.toml"
            codex_owner(owner_path, control_dir=str(control))
            handoff = control / "handoffs" / "0001.md"
            handoff.write_text("handoff\n")
            # The successor thread activates against the outgoing owner: that is
            # the only path that mints Codex successor readiness.
            readiness = Path(
                runtime.activate_codex_thread(
                    owner_path,
                    thread_id=OTHER_THREAD,
                    workspace=WORKSPACE,
                    control_dir=str(base / "successor-control"),
                    handoff=str(handoff),
                    reconcile=lambda owner: full_context(),
                )["successor_readiness"]
            )
            updated = runtime.transfer_owner(
                owner_path,
                THREAD,
                THREAD,
                0,
                OTHER_THREAD,
                OTHER_THREAD,
                1,
                str(control),
                caller=THREAD,
                handoff=handoff,
                successor_readiness_path=readiness,
                new_owner_mode=CODEX_MODE,
                new_workspace=WORKSPACE,
                # The live transfer-time routing boundary the owner-locked act crosses.
                workspace_lookup=lambda workspace: {"id": workspace},
                # The in-hold live re-reconciliation of the readiness references.
                reconcile=lambda owner: full_context(),
            )
            stored = tomllib.loads(owner_path.read_text())
            self.assertEqual(stored["owner_session_id"], OTHER_THREAD)
            self.assertEqual(stored.get("owner_mode"), CODEX_MODE)
            self.assertEqual(stored.get("herdr_workspace"), WORKSPACE)
            self.assertEqual(updated, stored)


class ForcedTakeoverTest(unittest.TestCase):
    """Seam: the human-only forced takeover sequence
    (operator-control codex-forced-takeover)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.control = self.base / "control"
        self.control.mkdir()
        self.owner = self.base / "operator-owner.toml"
        self.prior = fable_owner(self.owner, control_dir=str(self.control))
        self.retired: list[str] = []
        self.active_evidence = {"session_running": True, "route": "operator-fable"}
        self.fence_evidence = {"session_running": False, "timer_present": False}

    def verify_active_fable(self, owner):
        return dict(self.active_evidence)

    def retire_fable(self, owner):
        self.retired.append(owner["owner_route"])
        return dict(self.fence_evidence)

    def takeover(self, *, reason="operator directed control transfer", context=None, thread=THREAD):
        return runtime.force_takeover_codex_thread(
            self.owner,
            thread_id=thread,
            workspace=WORKSPACE,
            reason=reason,
            context=full_context() if context is None else context,
            verify_active_fable=self.verify_active_fable,
            retire_fable=self.retire_fable,
            now=lambda: "2026-08-17T01:00:00Z",
            reconcile=lambda owner: full_context(),
        )

    def test_forced_takeover_requires_reason_and_verified_active_fable(self) -> None:
        before = self.owner.read_bytes()

        with self.assertRaises(runtime.GateError):
            self.takeover(reason="   ")
        self.assertEqual(self.retired, [])

        self.active_evidence = {"session_running": False}
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertEqual(self.retired, [])

        self.active_evidence = {"session_running": True}
        codex_owner(self.owner, control_dir=str(self.control))
        codex_bytes = self.owner.read_bytes()
        with self.assertRaises(runtime.GateError):
            self.takeover(thread=OTHER_THREAD)
        self.assertEqual(self.owner.read_bytes(), codex_bytes)
        self.assertEqual(self.retired, [])

        self.owner.write_bytes(before)
        with self.assertRaises(runtime.GateError):
            self.takeover(context={"owner_record": "only-one"})
        self.assertEqual(self.retired, [])
        self.assertEqual(self.owner.read_bytes(), before)

    def test_fable_session_and_timer_are_verified_retired_before_owner_swap(self) -> None:
        before = self.owner.read_bytes()
        self.fence_evidence = {"session_running": False, "timer_present": True}
        with self.assertRaises(runtime.GateError):
            self.takeover()
        self.assertEqual(self.retired, ["operator-fable"])
        self.assertEqual(self.owner.read_bytes(), before)
        self.assertFalse((self.control / "takeovers").exists())

    def test_failed_forced_takeover_preserves_prior_owner_bytes(self) -> None:
        # A concurrent owner change between candidate validation and the atomic
        # commit must fail the locked exact compare, leaving the prior owner
        # record byte-identical (takeover-failure).
        before = self.owner.read_bytes()

        def racing_retire(owner):
            self.retired.append(owner["owner_route"])
            self.owner.write_text(owner_document({**self.prior, "handoff_revision": 7}))
            return dict(self.fence_evidence)

        with self.assertRaises(runtime.GateError):
            runtime.force_takeover_codex_thread(
                self.owner,
                thread_id=THREAD,
                workspace=WORKSPACE,
                reason="operator directed",
                context=full_context(),
                verify_active_fable=self.verify_active_fable,
                retire_fable=racing_retire,
                now=lambda: "2026-08-17T01:00:00Z",
                reconcile=lambda owner: full_context(),
            )
        raced = self.owner.read_bytes()
        self.assertNotEqual(raced, before)
        self.assertEqual(tomllib.loads(raced.decode())["owner_session_id"], self.prior["owner_session_id"])
        self.assertNotIn("owner_mode", tomllib.loads(raced.decode()))

    def test_takeover_receipt_binds_prior_owner_reason_time_context_and_new_owner(self) -> None:
        result = self.takeover(reason="operator directed control transfer")
        receipt_path = Path(result["owner"]["takeover_receipt"])
        self.assertEqual(receipt_path, self.control / "takeovers" / "0001.toml")
        receipt = tomllib.loads(receipt_path.read_text())
        self.assertEqual(receipt["prior_owner_session_id"], self.prior["owner_session_id"])
        self.assertEqual(receipt["prior_owner_route"], self.prior["owner_route"])
        self.assertEqual(receipt["new_owner_session_id"], THREAD)
        self.assertEqual(receipt["reason"], "operator directed control transfer")
        self.assertEqual(receipt["requested_at"], "2026-08-17T01:00:00Z")
        self.assertEqual(receipt["context_digest"], runtime.exact_fingerprint(full_context()))
        self.assertEqual(receipt["context_sources"], list(runtime.CODEX_CONTEXT_SOURCES))
        self.assertIs(receipt["fence_session_running"], False)
        self.assertIs(receipt["fence_timer_present"], False)
        self.assertEqual(receipt["verification_outcome"], "verified")
        self.assertNotIn("conversation", receipt_path.read_text().lower())

        owner = tomllib.loads(self.owner.read_text())
        self.assertEqual(owner["owner_session_id"], THREAD)
        self.assertEqual(owner["owner_mode"], CODEX_MODE)
        self.assertEqual(owner["herdr_workspace"], WORKSPACE)
        self.assertEqual(owner["handoff_revision"], 1)
        self.assertEqual(owner["takeover_receipt"], str(receipt_path))
        self.assertEqual(
            owner["takeover_receipt_digest"],
            runtime.exact_fingerprint(receipt_path.read_text()),
        )

    def test_successful_takeover_reconciles_complete_context_and_capabilities(self) -> None:
        result = self.takeover()
        self.assertEqual(result["outcome"], "takeover")
        self.assertEqual(result["context_sources"], list(runtime.CODEX_CONTEXT_SOURCES))
        self.assertEqual(result["capabilities"], list(runtime.CODEX_META_OPERATOR_CAPABILITIES))

        activated_owner = self.base / "fresh-owner.toml"
        activated = runtime.activate_codex_thread(
            activated_owner,
            thread_id=THREAD,
            workspace=WORKSPACE,
            control_dir=str(self.control),
            reconcile=lambda owner: full_context(),
        )
        self.assertEqual(result["capabilities"], activated["capabilities"])
        self.assertEqual(result["context_sources"], activated["context_sources"])


if __name__ == "__main__":
    unittest.main()
