"""Contract checks: octo-lite's published lane record and hand-off formats,
its one acceptance record, and the worker result send, read back by their own
spec keys."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import os
import re
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec/domains/octo-lite.spec.html"
OPERATOR = ROOT / "agents/meta-operator.md"
UTC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


class LaneRecordTests(unittest.TestCase):
    def test_spec_example_is_valid_toml_with_declared_types(self) -> None:
        html = SPEC.read_text(encoding="utf-8")
        match = re.search(
            r'<pre data-anchor="octo-lane-record-example"><code>(.*?)</code></pre>',
            html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, "lane record example is missing")
        record = tomllib.loads(unescape(match.group(1)))

        self.assertRegex(record["owner"], r"^w\d+:p")
        self.assertIsInstance(record["repository"], str)
        self.assertIsInstance(record["issue"], str)
        self.assertIsInstance(record["pr"], int)
        self.assertIsInstance(record["last_handoff_at"], str)
        self.assertRegex(record["started_at"], UTC)
        self.assertIn(
            record["waiting_on"],
            {"", "blocked", "operator"},
        )
        self.assertNotIn("workers", record)
        self.assertNotIn("tickets", record)

    def test_lane_record_holds_no_tickets(self) -> None:
        # spec #acceptance-lane-no-tickets: no contract writes ticket entries.
        contracts = [*ROOT.glob("agents/*.md"), *ROOT.glob("skills/**/SKILL.md")]
        for path in contracts:
            self.assertNotIn("[[tickets]]", path.read_text(encoding="utf-8"), path)

    def test_contracts_locate_session_state_through_octo_lite_state(self) -> None:
        # spec #session-state: lane and operator files live in the caller's
        # Herdr session state directory, located only through octo-lite-state.
        docs = [*ROOT.glob("agents/*.md"), *ROOT.glob("skills/**/SKILL.md"), ROOT / "README.md"]
        for path in docs:
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"octo-lite/(lanes|operator)", path)

    def test_owner_archives_record_log_and_notes_at_close(self) -> None:
        # spec #acceptance-lane-archive, #delivery-notes: exploration notes live
        # only in the lane's notes directory; the owner moves record, log, and
        # notes unchanged into archive/ after worker teardown, before its close
        # report; the operator touches no record.
        explore = (ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(
            explore,
            r"exploration agent.*write access only\s+to the lane's notes directory, "
            r"`\$\(octo-lite-state\)/lanes/<lane record name>-notes/`",
        )
        owner = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(
            owner,
            r"tear down in order: review rows, worktrees, workers\. Last, after your last "
            r"hand-off line \(the final worker close\) and "
            r"before your close report, move `<name>\.toml`, "
            r"`<name>\.handoffs\.jsonl`, and `<name>-notes/` when present, "
            r"unchanged into `archive/` in the lanes directory",
        )
        self.assertNotIn("archive state", owner)
        self.assertNotRegex(OPERATOR.read_text(encoding="utf-8"), r"delete the record")

    def test_acceptance_has_one_record_the_pr_receipt(self) -> None:
        contracts = [*ROOT.glob("agents/*.md"), *ROOT.glob("skills/**/SKILL.md")]
        for path in contracts:
            self.assertNotIn("octo-lite/acceptance/", path.read_text(encoding="utf-8"), path)
        html = SPEC.read_text(encoding="utf-8")
        table = re.search(r'id="handoff-operator".*?<tbody>(.*?)</tbody>', html, flags=re.DOTALL)
        self.assertIsNotNone(table, "operator log table is missing")
        kinds = re.findall(r"<tr[^>]*><td><code>(\w+)</code>", table.group(1))
        self.assertEqual(kinds, ["note", "prod", "start", "filed"])
        self.assertNotRegex(OPERATOR.read_text(encoding="utf-8"), r"gate relay|merge executed")

    def test_operator_logs_start_and_filed_lines(self) -> None:
        # spec #acceptance-operator-log-start, #acceptance-operator-log-filed:
        # starting a lane or filing an issue for an action event appends one
        # operator log line naming the event's id.
        self.assertRegex(
            OPERATOR.read_text(encoding="utf-8"),
            r"sole writer of `operator\.handoffs\.jsonl`:\s+on each prod .*, note to the human .*, "
            r"lane you start that an action\s+event asks for \(`start`\), and issue you file that one "
            r"asks for \(`filed`\), each naming the event's id, append one JSON line per octo-lite spec "
            r"`#handoff-operator`",
        )

    def test_owner_posts_spec_receipt_on_accept_spec_handoff(self) -> None:
        # spec #acceptance-receipt-paths: each spec by full path then at <commit>.
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"Accept spec hand-off.*gh pr comment.*Spec acceptance receipt: human.*"
            r"accepts <full repository path> at <exact commit>\.",
        )

    def test_owner_leaves_relayed_spec_acceptance_to_operator(self) -> None:
        # spec #gates-chat-acceptance, #acceptance-chat-acceptance: a spec
        # acceptance the operator relays is the operator's receipt; the owner
        # posts a receipt only for a review-page Accept spec hand-off.
        lines = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").splitlines()
        relayed = [line for line in lines if "#gates-chat-acceptance" in line]
        self.assertEqual(len(relayed), 1, relayed)
        self.assertRegex(relayed[0], r"operator relays is the operator's to record.*never post")
        posts = [line for line in lines if "gh pr comment" in line]
        self.assertTrue(posts)
        for line in posts:
            self.assertIn("Accept spec hand-off from the review page", line)

    def test_chat_spec_acceptance_records_only_the_pr_receipt(self) -> None:
        # spec #acceptance-chat-one-record, #gates-chat-acceptance: the operator
        # records a chat spec acceptance only as the PR receipt; review-host
        # reviewed moves the row base and records no acceptance.
        contracts = [*ROOT.glob("agents/*.md"), *ROOT.glob("skills/**/SKILL.md")]
        for path in contracts:
            self.assertNotIn("--accepted", path.read_text(encoding="utf-8"), path)
        self.assertRegex(
            OPERATOR.read_text(encoding="utf-8"),
            r"`review-host\.py reviewed --id <resource id>` per accepted spec: "
            r"it moves the row's base to the accepted commit and records no acceptance\.",
        )

    def test_chat_spec_receipt_command_keeps_the_humans_words(self) -> None:
        # spec #acceptance-receipt-spec-example: the operator's receipt command,
        # run as written, posts the human's words verbatim, apostrophe included.
        text = OPERATOR.read_text(encoding="utf-8")
        match = re.search(r"in chat is recorded .*?```sh\n(.*?)```", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "chat receipt command is missing")
        fill = {
            "<pr>": "208",
            "<words>": "your goal is to merge all this stuff. you're preauthorized",
            "<date>": "2026-10-21",
            "<full repository path>": "spec/domains/octo-lite.spec.html",
            "<commit>": "1a2b3c4",
        }
        command = match.group(1)
        for slot, value in fill.items():
            command = command.replace(slot, value)
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "body"
            gh = Path(tmp) / "gh"
            gh.write_text(
                "#!/bin/sh\n"
                "while [ $# -gt 0 ]; do\n"
                '  case $1 in --body) printf %s "$2" > "$BODY";; --body-file) cat "$2" > "$BODY";; esac\n'
                "  shift\n"
                "done\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "BODY": str(body)}
            run = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(
                body.read_text(encoding="utf-8").strip(),
                'Spec acceptance receipt: human "your goal is to merge all this stuff. '
                "you're preauthorized\" (2026-10-21) accepts spec/domains/octo-lite.spec.html "
                "at 1a2b3c4. Recorded by meta-operator.",
            )

    def test_standing_spec_acceptance_recorded_on_owner_send(self) -> None:
        # spec #gates-chat-acceptance, #acceptance-standing-acceptance: a standing
        # acceptance is recorded at once when the owner sends the spec head.
        self.assertRegex(
            OPERATOR.read_text(encoding="utf-8"),
            r"standing acceptance .* before the spec head exists is recorded the same way, at once, "
            r"when the owner sends you that spec's review link or head, quoting the human's standing words",
        )

    def test_owner_logs_attempt_line_on_consuming_worker_result(self) -> None:
        # spec #acceptance-lane-log: consuming a worker's result appends one
        # attempt line naming the worker's role, ticket, pane, and commit.
        html = SPEC.read_text(encoding="utf-8")
        row = re.search(
            r'<tr data-anchor="handoff-kind-attempt"><td><code>attempt</code></td>'
            r"<td>(.*?)</td><td>(.*?)</td></tr>",
            html,
        )
        self.assertIsNotNone(row, "attempt row is missing")
        self.assertEqual(unescape(row.group(1)), "A worker's result is consumed.")
        for field in ("<code>role</code>", "<code>ticket</code>", "<code>worker</code> (pane)", "<code>commit</code>"):
            self.assertIn(field, row.group(2))
        owner = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(
            owner,
            r"At each hand-off moment, append one line to `<lane record name>\.handoffs\.jsonl`"
            r"\s+beside it, per spec `#handoff-fields`",
        )

    def test_worker_result_send_is_bounded_then_goes_to_operator(self) -> None:
        # spec #roles-goal, #acceptance-worker-owner-gone(-stops): 3 sends to
        # the owner, then one to the operator pane, then stop; the operator
        # forwards to that pane's lane by name and relaunches only a gone,
        # unparked owner.
        # #acceptance-worker-owner-rate-limited: exit 69 already re-sent, so it
        # goes to the operator at once, never re-sent.
        for role in ("implementer", "integrator", "code-reviewer"):
            output = (ROOT / f"agents/{role}.md").read_text(encoding="utf-8").split("## Output", 1)[1]
            self.assertIn(
                "to the owner pane your brief names with `herdr-say`. Only exit 0 confirms the send; "
                "on exit 69, which `herdr-say` already re-sent for hours, send it no more; "
                "on any other exit, send it again, 3 sends in all. If none exits 0, send it once, "
                "naming the owner pane, to the operator pane (`pane` in `$(octo-lite-state)/operator.toml`). "
                "Then stop, whatever the last exit.",
                output,
                role,
            )
        self.assertRegex(
            OPERATOR.read_text(encoding="utf-8"),
            r"A worker result sent to you names its unreachable owner pane.*"
            r"forward it with `herdr-say <lane name> <result>`, the lane whose record's `owner` is that pane.*; "
            r"only when no live or parked owner has that name, relaunch fresh.*"
            r"`#roles-park`\), then forward\.",
        )

    def test_waiter_keeps_one_herdr_wait_on_each_agent_it_sets_to_work(self) -> None:
        # spec #roles-goal, #transport-await, #acceptance-worker-ended,
        # #acceptance-codex-owner-worker-ended, #acceptance-pi-owner-worker-ended,
        # #acceptance-worker-api-error(-resumed), #acceptance-owner-api-error-resumed,
        # #acceptance-worker-moved-unseen: the owner (orchestrator, implement-spec)
        # and the fleet operator send work with herdr-await and link the one wait
        # recipe herdr-comms states (#roles-goal, last sentence): read the screen
        # by name, resume an API-error turn, re-wait --since on one still at its
        # task; no role runs herdr agent wait or a get-based check-in poll.
        recipe = (ROOT / "skills/herdr-comms/SKILL.md").read_text(encoding="utf-8")
        recipe = recipe.split("\n## Wait on an agent\n", 1)[1].split("\n## ", 1)[0]
        for token in ("`herdr agent read <name>`", "`herdr-await <name> continue`", "`stop=send-failed`", "--since <seq>"):
            self.assertIn(token, recipe)
        callers = {
            "orchestrator": (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8"),
            "implement-spec": (ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8"),
            "meta-operator": OPERATOR.read_text(encoding="utf-8"),
        }
        for path, text in callers.items():
            self.assertIn("herdr-comms/SKILL.md#wait-on-an-agent)", text, path)
            self.assertIn("`herdr-await <", text, path)
            self.assertNotIn("herdr agent get", text, path)
            self.assertNotRegex(text, r"check-in,? reads?", path)
            self.assertNotRegex(text, r"herdr agent wait <", path)
        self.assertIn("never a standing wait on every owner", callers["meta-operator"])

    def test_operator_launch_example_writes_started_at(self) -> None:
        text = OPERATOR.read_text(encoding="utf-8")
        match = re.search(r"```toml\n(.*?)```", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "operator launch example is missing")
        record = tomllib.loads(match.group(1))
        self.assertRegex(record["started_at"], UTC)
        self.assertIn("operator.toml", text)


if __name__ == "__main__":
    unittest.main()
