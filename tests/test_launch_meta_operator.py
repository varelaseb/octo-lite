from __future__ import annotations

import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "skills/launch-meta-operator/scripts/launch-meta-operator.sh"
OPERATOR_SAY = ROOT / "skills/herdr-comms/assets/operator-say"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Fakes only the two boundaries launch-meta-operator.sh crosses through herdr-spawn:
# the read-only bootstrap provider call and the herdr CLI. No live Herdr or systemd.
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


class LaunchMetaOperatorIdentityTests(unittest.TestCase):
    def environment(self, td):
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
        (fake_bin / "claude").write_text(FAKE_BOOTSTRAP_CLAUDE)
        (fake_bin / "claude").chmod(0o755)
        (fake_bin / "herdr").write_text(FAKE_HERDR)
        (fake_bin / "herdr").chmod(0o755)
        (fake_bin / "systemd-run").write_text(FAKE_SYSTEMD_RUN)
        (fake_bin / "systemd-run").chmod(0o755)

        state_home = base / "state"
        env = dict(
            os.environ,
            PATH=f"{fake_bin}:{ROOT / 'scripts'}:{os.environ['PATH']}",
            XDG_STATE_HOME=str(state_home),
            FAKE_LOG=str(log),
            CALL_LOG=str(log),
            HERDR_SPAWN_BOOTSTRAP_RETRIES="2",
        )
        return repo, state_home, env

    def test_named_launch_writes_routable_name_and_verified_session_id_to_owner_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, state_home, env = self.environment(td)
            result = subprocess.run(
                [
                    "bash", str(LAUNCH),
                    "--workspace", "w1", "--cwd", str(repo), "--name", "operator-test-1",
                    "--objective", "inventory", "--handoff", "none",
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)

            owner_path = state_home / "octo-lite/operator-owner.toml"
            with owner_path.open("rb") as handle:
                owner = tomllib.load(handle)
            self.assertEqual("operator-test-1", owner["owner_route"])

            receipt_path = state_home / "octo-lite/operators/operator-test-1/receipt.toml"
            with receipt_path.open("rb") as handle:
                receipt = tomllib.load(handle)
            self.assertRegex(receipt["spawn_id"], UUID_RE)
            self.assertTrue(receipt["bootstrap"]["verified"])
            # The owner identity is the immutable bootstrap-verified provider session,
            # never the routable Herdr name; the two fields must stay distinct.
            self.assertEqual(receipt["bootstrap"]["provider_session_id"], owner["owner_session_id"])
            self.assertNotEqual(owner["owner_session_id"], owner["owner_route"])

            say_bin = Path(td) / "say-bin"
            say_bin.mkdir()
            say_log = Path(td) / "say.log"
            (say_bin / "herdr").write_text(FAKE_HERDR)
            (say_bin / "herdr").chmod(0o755)
            say_env = dict(
                os.environ,
                PATH=f"{say_bin}:{os.environ['PATH']}",
                FAKE_LOG=str(say_log),
                XDG_STATE_HOME=str(state_home),
                OCTO_OPERATOR_OWNER=str(owner_path),
            )
            subprocess.run(
                ["bash", str(OPERATOR_SAY), "--kind", "info", "hello operator"],
                env=say_env, check=True,
            )
            calls = say_log.read_text().splitlines()
            resolve_call = next(call for call in calls if call.startswith("agent get"))
            self.assertIn("operator-test-1", resolve_call.split())
            self.assertNotIn(receipt["spawn_id"], resolve_call)

    def test_dry_run_uses_a_valid_uuid_receipt_spawn_id_without_mutating_durable_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, state_home, env = self.environment(td)
            result = subprocess.run(
                [
                    "bash", str(LAUNCH),
                    "--workspace", "w1", "--cwd", str(repo), "--name", "operator-test-2",
                    "--objective", "inventory", "--handoff", "none", "--dry-run",
                ],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            receipt = tomllib.loads(result.stdout)
            self.assertRegex(receipt["spawn_id"], UUID_RE)
            self.assertNotEqual("operator-test-2", receipt["spawn_id"])
            self.assertFalse((state_home / "octo-lite/operator-owner.toml").exists())
            self.assertFalse((state_home / "octo-lite/operators").exists())


if __name__ == "__main__":
    unittest.main()
