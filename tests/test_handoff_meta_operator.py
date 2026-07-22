from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "skills/launch-meta-operator/scripts/handoff-meta-operator.sh"
OCTO_CONTROL = ROOT / "scripts/octo-control"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Fakes only the two boundaries the launcher crosses through herdr-spawn: the
# read-only bootstrap provider call (claude) and the herdr CLI. The fake claude
# echoes an ack whose provider_session_id equals the --session-id it is given
# (which octo-launch derives from the receipt spawn_id), exactly like the launch
# test. No live Herdr, no systemd, no owner-liveness probe.
FAKE_BOOTSTRAP_CLAUDE = r"""#!/usr/bin/env bash
printf 'claude %s\n' "$*" >>"$CALL_LOG"
prompt="$(cat)"
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
"""

FAKE_HERDR = r"""#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
if [[ "$1 $2" == "tab create" ]]; then
  echo '{"result":{"tab":{"tab_id":"w1:t1"},"root_pane":{"pane_id":"w1:p0"}}}'
elif [[ "$1 $2" == "agent get" ]]; then
  echo '{"result":{"agent":{"pane_id":"w1:p1"}}}'
elif [[ "$1 $2" == "pane read" ]]; then
  printf 'ready\n'
fi
"""

FAKE_SYSTEMD_RUN = "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >>\"$CALL_LOG\"\n"

# Any liveness probe of the current owner (ps/kill/pane-read of the owner)
# is forbidden. These fakes record a marker if the launcher ever calls them so
# the never-probes test can assert their absence.
FAKE_PS = "#!/usr/bin/env bash\nprintf 'PROBE ps %s\\n' \"$*\" >>\"$PROBE_LOG\"\nexit 0\n"
FAKE_KILL = "#!/usr/bin/env bash\nprintf 'PROBE kill %s\\n' \"$*\" >>\"$PROBE_LOG\"\nexit 0\n"


class HandoffMetaOperatorTests(unittest.TestCase):
    CURRENT_OWNER_SID = "sid-current-owner-0001"
    CURRENT_ROUTE = "operator-current"

    def environment(self, td, *, revision=3, seed_owner=True, seed_handoff=True):
        base = Path(td)
        repo = base / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
        (repo / "AGENTS.md").write_text("# Target\n")
        subprocess.run(["git", "-C", str(repo), "add", "AGENTS.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)

        fake_bin = base / "bin"
        fake_bin.mkdir()
        log = base / "calls.log"
        probe_log = base / "probe.log"
        for name, body in (
            ("claude", FAKE_BOOTSTRAP_CLAUDE),
            ("herdr", FAKE_HERDR),
            ("systemd-run", FAKE_SYSTEMD_RUN),
            ("ps", FAKE_PS),
            ("kill", FAKE_KILL),
        ):
            (fake_bin / name).write_text(body)
            (fake_bin / name).chmod(0o755)

        state_home = base / "state"
        state_root = state_home / "octo-lite"
        control_dir = state_root / "operators" / self.CURRENT_ROUTE
        owner_path = state_root / "operator-owner.toml"

        if seed_owner:
            control_dir.mkdir(parents=True)
            (control_dir / "handoffs").mkdir()
            owner_path.parent.mkdir(parents=True, exist_ok=True)
            owner_path.write_text(
                "schema_version = 1\n"
                f'owner_session_id = "{self.CURRENT_OWNER_SID}"\n'
                f'owner_route = "{self.CURRENT_ROUTE}"\n'
                f"handoff_revision = {revision}\n"
                f'control_dir = "{control_dir}"\n'
            )
        handoff_doc = control_dir / "handoffs" / f"{revision + 1:04d}.md"
        if seed_owner and seed_handoff:
            handoff_doc.write_text(f"# handoff revision {revision + 1}\n")

        env = dict(
            os.environ,
            PATH=f"{fake_bin}:{ROOT / 'scripts'}:{os.environ['PATH']}",
            XDG_STATE_HOME=str(state_home),
            FAKE_LOG=str(log),
            CALL_LOG=str(log),
            PROBE_LOG=str(probe_log),
            HERDR_SPAWN_BOOTSTRAP_RETRIES="2",
        )
        return {
            "repo": repo,
            "state_root": state_root,
            "control_dir": control_dir,
            "owner_path": owner_path,
            "handoff_doc": handoff_doc,
            "revision": revision,
            "env": env,
            "probe_log": probe_log,
        }

    def run_launcher(self, ctx, *extra, name="operator-next"):
        return subprocess.run(
            [
                "bash", str(HANDOFF),
                "--workspace", "w1",
                "--cwd", str(ctx["repo"]),
                "--name", name,
                "--handoff", str(ctx["handoff_doc"]),
                *extra,
            ],
            env=ctx["env"], capture_output=True, text=True,
        )

    def successor_dir(self, ctx, name="operator-next"):
        return ctx["state_root"] / "operators" / name

    def owner_transfer_line(self, stdout):
        for line in stdout.splitlines():
            if "octo-control owner-transfer" in line:
                return line
        return None

    def successor_ready_line(self, stdout):
        for line in stdout.splitlines():
            if "octo-control successor-ready" in line:
                return line
        return None

    def flags(self, line):
        # Return the mapping of --flag -> value for the octo-control invocation
        # embedded in an emitted command line.
        tokens = shlex.split(line)
        start = next(i for i, t in enumerate(tokens) if t.endswith("octo-control"))
        args = tokens[start + 1 :]
        out = {}
        i = 0
        while i < len(args):
            if args[i].startswith("--"):
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    out[args[i]] = args[i + 1]
                    i += 2
                else:
                    out[args[i]] = True
                    i += 1
            else:
                i += 1
        return out

    def test_live_handoff_writes_successor_receipt_and_leaves_owner_and_timer_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            owner_before = ctx["owner_path"].read_text()
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)

            succ = self.successor_dir(ctx)
            receipt_path = succ / "receipt.toml"
            self.assertTrue(receipt_path.is_file(), result.stdout)
            with receipt_path.open("rb") as handle:
                receipt = tomllib.load(handle)
            self.assertEqual("meta-operator", receipt["role"]["name"])
            self.assertRegex(receipt["spawn_id"], UUID_RE)

            # Owner file is untouched: no owner write by the launcher.
            self.assertEqual(owner_before, ctx["owner_path"].read_text())

            # No timer install: systemd-run / operator-timer never invoked.
            calls = Path(ctx["env"]["CALL_LOG"]).read_text() if Path(ctx["env"]["CALL_LOG"]).exists() else ""
            self.assertNotIn("systemd-run", calls)
            self.assertNotIn("timer install", calls)
            fake = Path(ctx["env"]["FAKE_LOG"]).read_text() if Path(ctx["env"]["FAKE_LOG"]).exists() else ""
            self.assertNotIn("timer install", fake)

    def test_emitted_owner_transfer_command_carries_all_eleven_args_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)
            line = self.owner_transfer_line(result.stdout)
            self.assertIsNotNone(line, result.stdout)
            flags = self.flags(line)
            succ = self.successor_dir(ctx)
            with (succ / "receipt.toml").open("rb") as handle:
                succ_sid = tomllib.load(handle)["bootstrap"]["provider_session_id"]
            expected = {
                "--owner-file": str(ctx["owner_path"]),
                "--expected-owner": self.CURRENT_OWNER_SID,
                "--expected-route": self.CURRENT_ROUTE,
                "--expected-revision": str(ctx["revision"]),
                "--caller": self.CURRENT_OWNER_SID,
                "--new-owner": succ_sid,
                "--new-route": "operator-next",
                "--revision": str(ctx["revision"] + 1),
                "--control-dir": str(ctx["control_dir"]),
                "--handoff": str(ctx["handoff_doc"]),
                "--successor-readiness": str(succ / "successor-ready.toml"),
            }
            self.assertEqual(expected, flags)

    def test_emitted_successor_ready_command_targets_successor_session_and_new_revision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)
            line = self.successor_ready_line(result.stdout)
            self.assertIsNotNone(line, result.stdout)
            flags = self.flags(line)
            succ = self.successor_dir(ctx)
            with (succ / "receipt.toml").open("rb") as handle:
                succ_sid = tomllib.load(handle)["bootstrap"]["provider_session_id"]
            self.assertEqual(str(succ / "successor-ready.toml"), flags["--path"])
            self.assertEqual(succ_sid, flags["--caller"])
            self.assertEqual(succ_sid, flags["--session-id"])
            self.assertEqual(str(ctx["revision"] + 1), flags["--handoff-revision"])

    def test_pre_derived_commands_execute_end_to_end_swap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)

            ready_line = self.successor_ready_line(result.stdout)
            transfer_line = self.owner_transfer_line(result.stdout)

            # Run the successor-ready command exactly as emitted.
            ready = subprocess.run(shlex.split(ready_line), env=ctx["env"], capture_output=True, text=True)
            self.assertEqual(0, ready.returncode, ready.stderr)

            # Then run owner-transfer exactly as emitted.
            transfer = subprocess.run(shlex.split(transfer_line), env=ctx["env"], capture_output=True, text=True)
            self.assertEqual(0, transfer.returncode, transfer.stderr)

            succ = self.successor_dir(ctx)
            with (succ / "receipt.toml").open("rb") as handle:
                succ_sid = tomllib.load(handle)["bootstrap"]["provider_session_id"]
            with ctx["owner_path"].open("rb") as handle:
                owner = tomllib.load(handle)
            self.assertEqual(succ_sid, owner["owner_session_id"])
            self.assertEqual("operator-next", owner["owner_route"])
            self.assertEqual(ctx["revision"] + 1, owner["handoff_revision"])
            self.assertEqual(str(ctx["control_dir"]), owner["control_dir"])

    def test_refuses_when_owner_file_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td, seed_owner=False)
            handoff = Path(td) / "handoffs" / "0004.md"
            handoff.parent.mkdir(parents=True)
            handoff.write_text("# doc\n")
            result = subprocess.run(
                [
                    "bash", str(HANDOFF),
                    "--workspace", "w1", "--cwd", str(ctx["repo"]),
                    "--name", "operator-next", "--handoff", str(handoff),
                ],
                env=ctx["env"], capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(self.successor_dir(ctx).exists())

    def test_refuses_when_handoff_basename_not_next_revision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td, seed_handoff=False)
            # Basename 0009 is not R+1 (0004).
            wrong = ctx["control_dir"] / "handoffs" / "0009.md"
            wrong.write_text("# wrong revision\n")
            result = self.run_launcher(ctx, name="operator-next")
            # Override the handoff path to the wrong-basename file.
            result = subprocess.run(
                [
                    "bash", str(HANDOFF),
                    "--workspace", "w1", "--cwd", str(ctx["repo"]),
                    "--name", "operator-next", "--handoff", str(wrong),
                ],
                env=ctx["env"], capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertFalse(self.successor_dir(ctx).exists())

    def test_refuses_when_handoff_correct_basename_but_wrong_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td, seed_handoff=False)
            # Correct basename 0004.md but in the wrong directory (not
            # control_dir/handoffs).
            wrong_dir = Path(td) / "elsewhere"
            wrong_dir.mkdir()
            doc = wrong_dir / f"{ctx['revision'] + 1:04d}.md"
            doc.write_text("# right name wrong dir\n")
            result = subprocess.run(
                [
                    "bash", str(HANDOFF),
                    "--workspace", "w1", "--cwd", str(ctx["repo"]),
                    "--name", "operator-next", "--handoff", str(doc),
                ],
                env=ctx["env"], capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertFalse(self.successor_dir(ctx).exists())

    def test_dry_run_prints_receipt_and_makes_no_durable_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            owner_before = ctx["owner_path"].read_text()
            result = self.run_launcher(ctx, "--dry-run")
            self.assertEqual(0, result.returncode, result.stderr)
            receipt = tomllib.loads(result.stdout)
            self.assertRegex(receipt["spawn_id"], UUID_RE)
            self.assertEqual("meta-operator", receipt["role"]["name"])
            # No successor dir, no owner change, no spawn.
            self.assertFalse(self.successor_dir(ctx).exists())
            self.assertEqual(owner_before, ctx["owner_path"].read_text())
            fake = Path(ctx["env"]["FAKE_LOG"]).read_text() if Path(ctx["env"]["FAKE_LOG"]).exists() else ""
            self.assertNotIn("tab create", fake)

    def test_never_probes_owner_liveness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)
            probe = ctx["probe_log"]
            self.assertFalse(probe.exists() and probe.read_text().strip(),
                             probe.read_text() if probe.exists() else "")

    def test_prints_exactly_one_owner_transfer_command_no_second_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)
            transfers = [l for l in result.stdout.splitlines() if "octo-control owner-transfer" in l]
            self.assertEqual(1, len(transfers), result.stdout)
            flags = self.flags(transfers[0])
            # Exactly the current owner identity: expected-owner == caller ==
            # current sid; no other/prior sid appears; no authorization flag.
            self.assertEqual(self.CURRENT_OWNER_SID, flags["--expected-owner"])
            self.assertEqual(self.CURRENT_OWNER_SID, flags["--caller"])
            self.assertNotIn("--authorization", flags)
            self.assertNotIn("--authorize", flags)
            self.assertNotIn("--force", flags)
            # No second/prior owner sid embedded anywhere in the transfer line.
            self.assertNotIn("sid-prior", transfers[0])

    def test_output_carries_one_line_boundary_notice(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)
            lowered = result.stdout.lower()
            self.assertIn("live current owner", lowered)
            self.assertIn("manual", lowered)
            self.assertIn("adr-0001", lowered)


if __name__ == "__main__":
    unittest.main()
