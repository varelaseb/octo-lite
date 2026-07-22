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
# Extract the absolute receipt path from the prose prompt. The path may contain
# spaces (e.g. an XDG_STATE_HOME with a space), so anchor on the known
# receipt.toml suffix and the trailing comma delimiter rather than stopping at
# the first space.
receipt_path="$(printf '%s' "$prompt" | python3 -c 'import re,sys; m=re.search(r"(/.*?receipt\.toml)", sys.stdin.read()); print(m.group(1) if m else "")')"
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
elif [[ "$1 $2" == "agent start" ]]; then
  # Real 0.7.5 grammar: agent start <NAME> --kind <KIND> --pane <ID>
  # [--timeout MS] [-- AGENT_ARG...]; NO --tab/--no-focus (unknown options).
  shift 2
  kind=""
  pane=""
  while (($#)); do
    case "$1" in
      --tab|--no-focus)
        echo "error: unexpected argument '$1' found" >&2
        exit 2
        ;;
      --kind) kind="${2:-}"; shift 2 ;;
      --pane) pane="${2:-}"; shift 2 ;;
      --timeout) shift 2 ;;
      --) shift; break ;;
      *) shift ;;
    esac
  done
  if [[ -z "$kind" || -z "$pane" ]]; then
    echo "error: the following required arguments were not provided: --kind --pane" >&2
    exit 2
  fi
elif [[ "$1 $2" == "agent get" ]]; then
  echo '{"result":{"agent":{"pane_id":"w1:p1"}}}'
elif [[ "$1 $2" == "pane read" ]]; then
  printf 'ready\n'
fi
"""

# Timer-install interceptors. The initial launcher installs a periodic sweep by
# invoking scripts/operator-timer (which internally shells out to systemd-run);
# see launch-meta-operator.sh. The LIVE handoff launcher must install NO timer at
# all. Detecting that reliably requires shadowing BOTH boundaries a timer install
# would cross: the operator-timer entrypoint (by name on PATH, ahead of the real
# scripts/operator-timer) and systemd-run. Each shadow APPENDS an unmistakable
# marker line to a dedicated marker file (TIMER_MARKER), so the never-installs
# assertion can require that file absent/empty rather than grepping a shared log
# for a string the fake might never emit.
FAKE_OPERATOR_TIMER = "#!/usr/bin/env bash\nprintf 'TIMER-INSTALL-INVOKED operator-timer %s\\n' \"$*\" >>\"$TIMER_MARKER\"\nexit 0\n"
FAKE_SYSTEMD_RUN = "#!/usr/bin/env bash\nprintf 'TIMER-INSTALL-INVOKED systemd-run %s\\n' \"$*\" >>\"$TIMER_MARKER\"\nexit 0\n"

# Any liveness probe of the current owner (ps/kill/pane-read of the owner)
# is forbidden. These fakes record a marker if the launcher ever calls them so
# the never-probes test can assert their absence.
FAKE_PS = "#!/usr/bin/env bash\nprintf 'PROBE ps %s\\n' \"$*\" >>\"$PROBE_LOG\"\nexit 0\n"
FAKE_KILL = "#!/usr/bin/env bash\nprintf 'PROBE kill %s\\n' \"$*\" >>\"$PROBE_LOG\"\nexit 0\n"


class HandoffMetaOperatorTests(unittest.TestCase):
    CURRENT_OWNER_SID = "sid-current-owner-0001"
    CURRENT_ROUTE = "operator-current"

    def environment(self, td, *, revision=3, seed_owner=True, seed_handoff=True, state_subdir="state"):
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
        timer_marker = base / "timer-install.marker"
        for name, body in (
            ("claude", FAKE_BOOTSTRAP_CLAUDE),
            ("herdr", FAKE_HERDR),
            ("operator-timer", FAKE_OPERATOR_TIMER),
            ("systemd-run", FAKE_SYSTEMD_RUN),
            ("ps", FAKE_PS),
            ("kill", FAKE_KILL),
        ):
            (fake_bin / name).write_text(body)
            (fake_bin / name).chmod(0o755)

        state_home = base / state_subdir
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
            TIMER_MARKER=str(timer_marker),
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
            "timer_marker": timer_marker,
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

            # No timer install. Both timer boundaries are shadowed by fakes that
            # append a TIMER-INSTALL-INVOKED marker if the launcher ever crosses
            # them: the operator-timer entrypoint (the exact invocation the initial
            # launch-meta-operator.sh uses) and systemd-run. The live handoff
            # launcher installs no timer, so the dedicated marker file must be
            # absent (or empty). A grep of the shared call log is NOT sufficient
            # here: a real install would go through operator-timer/systemd-run and
            # need never write the literal strings the old assertion looked for.
            marker = ctx["timer_marker"]
            marker_text = marker.read_text() if marker.exists() else ""
            self.assertEqual("", marker_text.strip(), marker_text)
            self.assertNotIn("TIMER-INSTALL-INVOKED", marker_text)

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

    def test_emitted_commands_survive_paths_with_spaces(self) -> None:
        # An XDG_STATE_HOME whose path contains a space makes the owner file,
        # successor dir, and successor-readiness paths all contain a space. The
        # emitted owner-transfer line must be a single runnable command whose
        # space-containing values survive shell word-splitting verbatim.
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td, state_subdir="state dir with spaces")
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)
            line = self.owner_transfer_line(result.stdout)
            self.assertIsNotNone(line, result.stdout)

            tokens = shlex.split(line)
            transfers = [
                i for i in range(len(tokens) - 1)
                if tokens[i].endswith("octo-control") and tokens[i + 1] == "owner-transfer"
            ]
            self.assertEqual(1, len(transfers), line)
            # 2 leading tokens (octo-control owner-transfer) + 11 flags + 11 values.
            self.assertEqual(2 + 22, len(tokens), tokens)

            flags = self.flags(line)
            succ = self.successor_dir(ctx)
            self.assertIn(" ", str(ctx["owner_path"]))
            self.assertEqual(str(ctx["owner_path"]), flags["--owner-file"])
            self.assertEqual(str(ctx["handoff_doc"]), flags["--handoff"])
            self.assertEqual(str(succ / "successor-ready.toml"), flags["--successor-readiness"])

            # The successor-ready line is a SEPARATE emitted command whose --path
            # value is a space-containing successor-ready path. Parsing only the
            # owner-transfer line above would miss dropped quoting on this line, so
            # capture it too, shlex.split it, and assert its --path is the intact
            # space-containing path as a SINGLE token (word-split would shatter an
            # unquoted value into extra tokens and change --path's parsed value).
            ready_line = self.successor_ready_line(result.stdout)
            self.assertIsNotNone(ready_line, result.stdout)
            ready_tokens = shlex.split(ready_line)
            ready_flags = self.flags(ready_line)
            successor_ready_path = str(succ / "successor-ready.toml")
            self.assertIn(" ", successor_ready_path)
            self.assertEqual(successor_ready_path, ready_flags["--path"])
            # The intact path is exactly one token in the split command line.
            self.assertIn(successor_ready_path, ready_tokens)

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
            self.assertEqual(65, result.returncode, result.stderr)
            self.assertIn("no owner record", result.stderr)
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
            self.assertEqual(65, result.returncode, result.stdout)
            self.assertIn("basename must be", result.stderr)
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
            self.assertEqual(65, result.returncode, result.stdout)
            self.assertIn("must live under", result.stderr)
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
            # A dry-run must also install NO timer. The prior assertions only cover
            # the successor dir, owner file, and herdr tab create; a dry-run timer
            # install (operator-timer / systemd-run) would leave all three clean yet
            # still be a durable mutation. Reuse the TIMER_MARKER wiring: both timer
            # boundaries are shadowed by fakes that append a marker if crossed, so
            # the marker file must be absent/empty under --dry-run.
            marker = ctx["timer_marker"]
            marker_text = marker.read_text() if marker.exists() else ""
            self.assertEqual("", marker_text.strip(), marker_text)
            self.assertNotIn("TIMER-INSTALL-INVOKED", marker_text)

    @staticmethod
    def _strip_shell_comments(source: str) -> str:
        # Return the script body with whole-line comments removed so the static
        # source scan matches only meaningful command usage. Every forbidden-word
        # occurrence in the real launcher lives in a whole-line comment (e.g. the
        # header "installs NO timer, and never probes owner liveness."), so we drop
        # any line whose first non-whitespace character is '#' (this also drops the
        # shebang). We deliberately do NOT strip inline "code # trailing" comments:
        # the launcher has none carrying forbidden words, and a naive inline strip
        # would corrupt in-string '#' characters. If a future edit adds a forbidden
        # word only inside an inline comment, this scan errs on the safe side by
        # flagging it, which is the correct fail-closed direction.
        kept = []
        for line in source.splitlines():
            if line.lstrip().startswith("#"):
                continue
            kept.append(line)
        return "\n".join(kept)

    def test_script_source_has_no_liveness_probe_or_timer_install(self) -> None:
        # CATEGORICAL closure (primary): read the ACTUAL bytes of the launcher and
        # prove it contains NO liveness-probe and NO timer-install command usage at
        # all. This is independent of PATH-fake interception limits: a 'kill' Bash
        # builtin bypasses a PATH-fake 'kill', and a timer install can route through
        # boundaries a runtime fake never sees. A source scan closes the entire
        # class regardless of how the probe/install would be dispatched at runtime.
        source = HANDOFF.read_text()
        body = self._strip_shell_comments(source)

        # (pattern, human description). Word-boundary regex so we match the command
        # token, not an unrelated identifier substring (e.g. 'skill_dir' must not
        # trip the 'kill' rule, 'spawn' must not trip anything). \b anchors on token
        # edges; where a literal contains non-word chars we anchor explicitly.
        forbidden = [
            (r"\bkill\b", "kill invocation (builtin or external liveness probe)"),
            (r"kill\s+-0\b", "kill -0 liveness probe"),
            (r"\bps\b", "ps process probe"),
            (r"/proc/", "/proc/ liveness inspection"),
            (r"\bpgrep\b", "pgrep process probe"),
            (r"\bsystemd-run\b", "systemd-run timer install"),
            (r"\boperator-timer\b", "operator-timer install entrypoint"),
            (r"herdr\b[^\n]*\bpane\s+read\b", "herdr pane read owner discovery"),
            (r"herdr\b[^\n]*\bpane\s+list\b", "herdr pane list owner discovery"),
            (r"\btimer\s+install\b", "timer install command"),
        ]
        offenders = []
        for pattern, desc in forbidden:
            for m in re.finditer(pattern, body):
                offenders.append(f"{desc}: matched {m.group(0)!r} at offset {m.start()}")
        self.assertEqual(
            [], offenders,
            "launcher source must contain no liveness-probe or timer-install "
            "command usage; offenders:\n" + "\n".join(offenders),
        )

    def test_never_probes_owner_liveness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = self.environment(td)
            result = self.run_launcher(ctx)
            self.assertEqual(0, result.returncode, result.stderr)
            probe = ctx["probe_log"]
            self.assertFalse(probe.exists() and probe.read_text().strip(),
                             probe.read_text() if probe.exists() else "")

            # A ps/kill probe is not the only way to probe the owner: a herdr
            # pane-read (or any herdr call targeting the owner session id / route)
            # would also probe owner liveness and must never happen. The launcher
            # only READS the owner TOML file; it must never message or probe the
            # owner over herdr. The owner file is seeded with a KNOWN owner session
            # id and route, and FAKE_HERDR logs every herdr invocation to FAKE_LOG.
            # Assert no logged herdr invocation references either owner identity.
            # herdr-spawn legitimately targets the SUCCESSOR name/pane, so only
            # owner-targeted herdr calls are banned, not herdr use in general.
            fake_log = Path(ctx["env"]["FAKE_LOG"])
            log_lines = fake_log.read_text().splitlines() if fake_log.exists() else []
            # FAKE_LOG is shared with the bootstrap claude fake (its lines start
            # with "claude "); herdr invocations are every other logged line.
            herdr_lines = [ln for ln in log_lines if not ln.startswith("claude ")]
            self.assertTrue(herdr_lines, log_lines)  # herdr WAS used (on the successor).

            def normalize(line):
                # Normalize a herdr command line into a flat token list where an
                # attached-value flag ("--flag=value") is split into TWO tokens
                # ("--flag", "value"), so owner-routing hidden as "--target=OWNER"
                # is caught exactly like the "--target OWNER" spaced form. Without
                # this split, shlex keeps "--target=OWNER" as one token and the
                # owner-routing bans below silently miss the attached form.
                out = []
                for tok in shlex.split(line):
                    if tok.startswith("--") and "=" in tok:
                        flag, _, value = tok.partition("=")
                        out.append(flag)
                        out.append(value)
                    else:
                        out.append(tok)
                return out

            route_flags = ("--name", "--route", "--session", "--session-id", "--target")
            for ln in herdr_lines:
                tokens = normalize(ln)
                # A herdr pane list/read that references the OWNER identity is an
                # owner-discovery probe and is banned. herdr-spawn (the REAL wrapper,
                # only the herdr CLI is faked) legitimately pane-reads the SUCCESSOR
                # pane for readiness, so a blanket pane-read ban is wrong; the ban is
                # scoped to pane ops that name the owner session id or route. The
                # owner-identity assertions below already cover the general case,
                # but this makes the pane-discovery form explicit and fail-closed.
                is_pane_op = any(
                    tok == "pane" and i + 1 < len(tokens) and tokens[i + 1] in ("list", "read")
                    for i, tok in enumerate(tokens)
                )
                if is_pane_op:
                    self.assertNotIn(self.CURRENT_OWNER_SID, tokens,
                                     f"herdr pane op references the owner session: {ln}")
                    self.assertNotIn(self.CURRENT_ROUTE, tokens,
                                     f"herdr pane op references the owner route: {ln}")
                # The owner's immutable session id must never appear in ANY herdr
                # invocation: it is never a legitimate path segment or successor
                # target, so any occurrence means the launcher probed/messaged the
                # owner over herdr.
                self.assertNotIn(self.CURRENT_OWNER_SID, tokens, ln)
                # The owner route legitimately appears only as a directory segment
                # inside the invariant control-dir path embedded in the spawn
                # prompt (the launcher reads the owner TOML / handoff doc). It must
                # never be a herdr ROUTING TARGET: a bare route token, or a
                # session/route/pane target argument naming the owner, in EITHER the
                # spaced ("--target OWNER") or attached ("--target=OWNER") form
                # (both are normalized above). Any herdr token that IS the owner
                # route (not merely containing it inside a filesystem path) is an
                # owner-targeted call and is banned.
                for i, tok in enumerate(tokens):
                    self.assertNotEqual(
                        self.CURRENT_ROUTE, tok,
                        f"owner route used as a bare herdr target token: {ln}",
                    )
                    if tok in route_flags:
                        value = tokens[i + 1] if i + 1 < len(tokens) else ""
                        self.assertNotEqual(
                            self.CURRENT_ROUTE, value,
                            f"herdr {tok} targets the owner route: {ln}",
                        )
                        self.assertNotEqual(
                            self.CURRENT_OWNER_SID, value,
                            f"herdr {tok} targets the owner session: {ln}",
                        )

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
