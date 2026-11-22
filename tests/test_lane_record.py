"""Contract checks: octo-lite's published lane record and hand-off formats,
its one acceptance record, and the worker result send, read back by their own
spec keys."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import json
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
# The confirm and resend rule every Claude role's report recipe states
# (spec/domains/herdr-transport.spec.html#transport-native).
REPORT_CONFIRM = (
    "Only a native send Claude reports delivered or timed out, or a `herdr-say` exit 0, confirms the send; "
    "one Claude reports undelivered, or a later delivery notice says held, denied, or expired, goes by `herdr-say`; "
    "on exit 69, which `herdr-say` already re-sent for hours, send it no more; "
    "on any other exit, send it again, 3 sends in all."
)
# The one step from a pane id to its native address, stated where each Claude
# role reports (#transport-native): a pane id is no address.
REPORT_ADDRESS = (
    "Address a native send to `uds:` and the path "
    "`herdr-claude-session <pane> | jq -r '.messagingSocketPath // empty'` prints, looked up just before each send; "
    "none printed means no live Claude session (herdr-transport spec `#transport-native`)."
)


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
        # spec/domains/herdr-transport.spec.html#session-state: lane and operator files
        # live in the caller's Herdr session state directory, located only through
        # octo-lite-state.
        docs = [*ROOT.glob("agents/*.md"), *ROOT.glob("skills/**/SKILL.md"), ROOT / "README.md"]
        for path in docs:
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"octo-lite/(lanes|operator)", path)

    def test_owner_archives_record_log_and_notes_at_close(self) -> None:
        # spec/domains/herdr-transport.spec.html#acceptance-lane-archive, spec
        # #delivery-notes: exploration notes live only in the lane's notes
        # directory; the owner moves record, log, and notes unchanged into archive/
        # after worker teardown, before its close report; the operator touches no
        # record.
        explore = (ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(
            explore,
            r"exploration agent.*write access only\s+to the lane's notes directory, "
            r"`\$\(octo-lite-state\)/lanes/<lane record name>-notes/`",
        )
        owner = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(
            owner,
            r"tear down in order: review rows, the prototype you run, worktrees, workers\. Last, after your last "
            r"hand-off line \(the final worker close, then your own complaint line, if any\) and "
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
        self.assertEqual(kinds, ["note", "prod", "start", "filed", "complaint"])
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

    def assert_receipt_command(self, command: str, fill: dict[str, str], posted: str) -> None:
        # Runs a receipt command as written: it posts nothing when the PR's
        # remote head lacks the accepted commit, else posts the body verbatim.
        for slot, value in {"<branch>": "ann1527", "<pr>": "208", "<commit>": "1a2b3c4", **fill}.items():
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
            git = Path(tmp) / "git"
            git.write_text('#!/bin/sh\necho "$*" >> "$LOG"\n[ "$1" = merge-base ] && exit "$PROOF"\nexit 0\n',
                           encoding="utf-8")
            git.chmod(0o755)
            log = Path(tmp) / "log"
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "BODY": str(body), "LOG": str(log)}
            run = subprocess.run(["sh", "-c", command], env={**env, "PROOF": "1"}, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(body.exists(), "receipt posted without push proof")
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(),
                             ["fetch origin ann1527", "merge-base --is-ancestor 1a2b3c4 origin/ann1527"])
            run = subprocess.run(["sh", "-c", command], env={**env, "PROOF": "0"}, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(body.read_text(encoding="utf-8").strip(), posted)

    def test_chat_spec_receipt_command_keeps_the_humans_words(self) -> None:
        # spec #acceptance-receipt-spec-example, #gates-push-proof,
        # #acceptance-push-proof-receipt: the operator's receipt command, run as
        # written, posts the human's words verbatim, apostrophe included, and
        # posts nothing when the PR's remote head lacks the accepted commit.
        text = OPERATOR.read_text(encoding="utf-8")
        match = re.search(r"in chat is recorded .*?```sh\n(.*?)```", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "chat receipt command is missing")
        self.assert_receipt_command(
            match.group(1),
            {
                "<words>": "your goal is to merge all this stuff. you're preauthorized",
                "<date>": "2026-10-21",
                "<full repository path>": "spec/domains/octo-lite.spec.html",
            },
            'Spec acceptance receipt: human "your goal is to merge all this stuff. '
            "you're preauthorized\" (2026-10-21) accepts spec/domains/octo-lite.spec.html "
            "at 1a2b3c4. Recorded by meta-operator.",
        )

    def test_review_page_receipt_command_needs_push_proof(self) -> None:
        # spec #acceptance-receipt-paths, #gates-push-proof,
        # #acceptance-push-proof-receipt: the owner's Accept spec receipt command,
        # run as written, names each spec by full path then at <commit>, and
        # posts nothing when the PR's remote head lacks the accepted commit.
        text = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        match = re.search(r"Accept spec hand-off from the review page, record it with `([^`]*)`", text)
        self.assertIsNotNone(match, "review page receipt command is missing")
        self.assert_receipt_command(
            match.group(1),
            {
                "<date>": "2026-11-02",
                "<full repository path>": "spec/domains/octo-lite.spec.html",
                "<owner agent name>": "ann1527-prototype-first",
            },
            'Spec acceptance receipt: human "Accept spec" on the review page (2026-11-02) accepts '
            "spec/domains/octo-lite.spec.html at 1a2b3c4. Recorded by ann1527-prototype-first.",
        )

    def test_push_reports_and_receipts_need_ancestor_proof(self) -> None:
        # spec #gates-push-proof, #acceptance-push-proof-report: each surface
        # that reports a push or records a receipt proves the commit is an
        # ancestor of the remote branch head first.
        fetch, prove = "`git fetch origin <branch>`", "`git merge-base --is-ancestor <commit> origin/<branch>`"
        for rel, steps in {
            "agents/orchestrator.md": (fetch, prove),
            "agents/integrator.md": (fetch, prove.replace("<commit>", "<head>")),
            "agents/meta-operator.md": ("git fetch origin <branch> && " + prove.strip("`") + " &&\ngh pr comment",),
            "skills/push/SKILL.md": (fetch, prove),
        }.items():
            text = (ROOT / rel).read_text(encoding="utf-8")
            for step in (*steps, "(spec `#gates-push-proof`)"):
                self.assertIn(step, text, rel)

    def test_standing_spec_acceptance_recorded_on_owner_send(self) -> None:
        # spec #gates-chat-acceptance, #acceptance-standing-acceptance: a standing
        # acceptance is recorded at once when the owner sends the spec head.
        self.assertRegex(
            OPERATOR.read_text(encoding="utf-8"),
            r"standing acceptance .* before the spec head exists is recorded the same way, at once, "
            r"when the owner sends you that spec's review link or head, quoting the human's standing words",
        )

    def test_addendum_receipt_recorded_by_operator_as_spec_example(self) -> None:
        # spec #gates-addendum, #acceptance-receipt-addendum-example: the owner
        # sends the restating commit to the operator, whose receipt body, filled
        # in, is the spec's example.
        text = OPERATOR.read_text(encoding="utf-8")
        self.assertRegex(text, r"adds no behavior, value, or outcome that text does not already state, "
                         r"record an addendum receipt the same way, then tell the human in one line")
        body = re.search(r"\(spec `#gates-addendum`\)\. Its body:\n```text\n(.*?)\n```", text)
        self.assertIsNotNone(body, "addendum receipt body is missing")
        fill = {
            "<full repository path>": "spec/domains/octo-lite.spec.html",
            "<addendum commit>": "5d6e7f8",
            "<anchor>": "gates-merge-check",
            "<accepted commit>": "1a2b3c4",
            "<accepted text>": "the receiving agent checks that the PR head is the accepted commit",
            "<words>": "accept both",
            "<date>": "2026-10-19",
        }
        receipt = body.group(1)
        for slot, value in fill.items():
            receipt = receipt.replace(slot, value)
        example = re.search(r'data-anchor="acceptance-receipt-addendum-example"><code>(.*?)</code>',
                            SPEC.read_text(encoding="utf-8"))
        self.assertEqual(receipt, unescape(example.group(1)))
        owner = " ".join((ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").split())
        self.assertIn("send the operator the commit and the accepted text it restates, quoted with its anchor, "
                      "for an addendum receipt; never record one yourself", owner)

    def test_merge_chain_needs_its_receipt_and_the_accepted_head(self) -> None:
        # spec #gates-merge-check, #acceptance-merge-receipt-fails,
        # #acceptance-merge-pin: the merge runs only after its receipt posts,
        # pinned to the accepted head, deferred merges included.
        skill = (ROOT / "skills/octo-lite-github/SKILL.md").read_text(encoding="utf-8")
        chain = re.search(r"## Merge And Linear Sync.*?```sh\n(.*?)```", skill, flags=re.DOTALL)
        self.assertIsNotNone(chain, "merge chain is missing")
        self.assertIn("after `gh pr checks <pr> --watch --fail-fast &&`, never `--auto`", " ".join(skill.split()))
        self.assertIn("(../skills/octo-lite-github/SKILL.md#merge-and-linear-sync), a merge set to run once checks pass included",
                      OPERATOR.read_text(encoding="utf-8"))
        sha = "9be60f6" + "0" * 33
        command = chain.group(1)
        for slot, value in {"<pr>": "74", "<words>": "merge #74", "<date>": "2026-09-26",
                            "<accepted sha>": sha, "<agent name>": "meta-operator"}.items():
            command = command.replace(slot, value)
        with tempfile.TemporaryDirectory() as tmp:
            log, gh = Path(tmp) / "log", Path(tmp) / "gh"
            gh.write_text('#!/bin/sh\necho "$*" >> "$LOG"\n[ "$2" = comment ] && { cat > /dev/null; exit "$FAIL"; }\nexit 0\n',
                          encoding="utf-8")
            gh.chmod(0o755)
            for fail, calls in (("1", ["pr comment 74 --body-file -"]),
                                ("0", ["pr comment 74 --body-file -", f"pr merge 74 --merge --match-head-commit {sha}"])):
                log.write_text("", encoding="utf-8")
                env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "LOG": str(log), "FAIL": fail}
                run = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True)
                self.assertEqual(run.returncode != 0, fail == "1", run.stderr)
                self.assertEqual(log.read_text(encoding="utf-8").splitlines(), calls)

    def test_merge_at_the_go_never_merges_main_first(self) -> None:
        # spec #gates-merge-check, #delivery-path ("later only on a conflict"),
        # #acceptance-merge-pin: at the go the owner merges the named head at
        # once, a queue taking it as an entry; only a refusal moves the head,
        # and that head needs a fresh go. #delivery-linear: only a PR that
        # reads merged completes the lane, a queue entry watched till then.
        github = " ".join((ROOT / "skills/octo-lite-github/SKILL.md").read_text(encoding="utf-8").split())
        for phrase in ("merge pinned to that commit at once, never merging main first",
                       "a repo with a merge queue takes the merge as a queue entry",
                       "After the go the head changes only when the merge or queue refuses it, for a conflict "
                       "(main goes in) or a failure on the combined build (a fix batch)",
                       "the new head needs a fresh go",
                       "The merge completes the worklane only once `gh pr view <pr> --json state` reads `MERGED`, "
                       "a queue entry watched until it merges or the queue refuses it"):
            self.assertIn(phrase, github)
        skill = " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split())
        callback = skill[skill.index("## Human acceptance callback"):]
        for phrase in ("merge that head at once by its pinned chain", "never merging main first",
                       "a repo with a merge queue takes the merge as a queue entry",
                       "Only when the merge or queue refuses the head, for a conflict (main goes in) or a failure "
                       "on the combined build (a fix batch), does the head change, and that new head goes back "
                       "to the human for a fresh go",
                       "The merge completes the worklane only once the PR reads merged, a queue entry watched "
                       "until it merges or the queue refuses it"):
            self.assertIn(phrase, callback)

    def test_lane_merges_main_once_and_checks_the_candidate_at_once(self) -> None:
        # spec #delivery-path, #roles-load: every ticket integrated, then the
        # lane's one main merge makes the candidate, on which review, the full
        # suite, and any capture start at once; no one-shot run before it.
        skill = " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split())
        finish = skill[skill.index("## Review and finish"):skill.index("## Human acceptance callback")]
        for phrase in ("start each check as soon as the input it checks is ready, never waiting on a step it does not read",
                       "Overlap never skips a gate or lowers a bar: a check whose input an in-flight change would "
                       "alter waits for that change alone",
                       "Once every ticket is integrated, have the integrator merge main into the lane branch, "
                       "the lane's one main merge: the head that leaves is the candidate",
                       "Main goes in earlier only when a conflict with it or a change on it blocks a ticket, "
                       "later only on a conflict with the lane branch",
                       "On the candidate start at once: the full suite under the box lock",
                       "any capture the target requires before a merge ask, and a fresh reviewer",
                       "never runs on a head before a candidate"):
            self.assertIn(phrase, finish)
        self.assertNotIn("Run the target repo's required validation.", finish)
        self.assertIn("The lane runs the full suite only on a candidate head, beside its review, "
                      "and the PR body's validation names the run on the merge ask's head", skill)
        self.assertNotIn("full suite once", skill)

    def test_candidate_head_jobs_take_the_lock_as_merge_path_on_the_head_as_they_start(self) -> None:
        # spec #roles-load-merge (#acceptance-box-lock-merge-first,
        # #acceptance-box-lock-head-moves): the recipe asks merge-path for a
        # candidate head's heavy jobs only, read at start, never restarted.
        skill = " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split())
        validation = skill[skill.index("## Validation"):skill.index("## Review and finish")]
        for phrase in ("A heavy job on a candidate head, its full suite or a capture its merge ask needs, "
                       "adds `--merge`, so it runs ahead of every waiting job that is not; every other heavy "
                       "job takes the lock without it (spec `#roles-load-merge`)",
                       "Such a job reads the lane's head only as it starts, never a commit fixed as it lined up, "
                       "and names the head it ran",
                       "`octo-lite-lock --merge sh -c 'git rev-parse HEAD && SUITE'`",
                       "A fix batch that moves the head while it waits leaves it in line, to run on the new head, "
                       "so never stop it to line up again"):
            self.assertIn(phrase, validation)

    def test_every_finding_on_one_head_goes_in_one_fix_batch(self) -> None:
        # spec #delivery-path, #delivery-review, #health-notes: one batch per
        # head, two rounds over the whole PR, notes in one last batch with no
        # blocker, a batch's delta reviewed as its implementer reports it;
        # #acceptance-path-round-count: a later main merge's resolution is
        # reviewed as a candidate's delta.
        # Step 2 stays the step acting on the verdict: agents/orchestrator.md
        # and annotateanything's operating model link it by number.
        skill = " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split())
        step2 = re.search(r" 2\. (.*?) 3\. ", skill[skill.index("## Review and finish"):]).group(1)
        for phrase in ("Every finding on one head, the verdict's blockers and its notes marked `Fix in this PR`, "
                       "the suite's failures, the capture's code faults, and your own, goes into one fix batch",
                       "the findings, not the history, and its round, one Herdr integrator, one push",
                       "at most 2 fix rounds, counted over the whole PR, so neither a main merge nor the merge ask "
                       "restarts the count",
                       "the second a fresh step-back pass",
                       "With no blocker, the notes marked `Fix in this PR` still go in one last batch, which is no fix round",
                       "A batch's head, or a later main merge's, is a candidate too: a fresh reviewer reviews "
                       "only its fix delta or conflict resolution",
                       "starting on the batch commit as its implementer reports it, beside its integration, "
                       "while the full suite runs again",
                       "A commit that only renames or renumbers",
                       "gets the required checks and no review"):
            self.assertIn(phrase, step2)
        self.assertNotIn("batch of their own", skill)
        self.assertIn("[Review and finish](../skills/implement-spec/SKILL.md#review-and-finish) step 2",
                      (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8"))

    def test_operator_relays_gates_decisions_blockers_lane_closes(self) -> None:
        # spec #roles-operator-writes, #acceptance-operator-quiet,
        # #acceptance-operator-bundle, #acceptance-operator-trade-off,
        # #roles-box-problem, #acceptance-box-problem-human; #roles-eta,
        # #acceptance-eta-relay: a lane's progress line carries its latest ETA.
        text = " ".join(OPERATOR.read_text(encoding="utf-8").split())
        self.assertIn("You are the filter (spec `#roles-operator-writes`): relay to the human only gates, decisions, "
                      "real blockers, lane closes with their complaints (spec `#roles-complaint`), and each problem "
                      "of the box an owner reports (spec "
                      "`#roles-box-problem`) once with the step that fixes it, however many lanes report it, plus the "
                      "one addendum receipt line; progress gets one line or nothing, a lane's line carrying its latest "
                      "ETA (spec `#roles-eta`), its time from now counted as you write.", text)
        self.assertIn("go together as one question asking whether to take your recommendations, one plain line "
                      "per question naming its recommendation", text)
        self.assertIn("A question that weighs real trade-offs goes alone, never in that bundle.", text)
        self.assertNotIn("status only when they ask", text)
        self.assertNotIn("you consume without a message", text)

    def complaint_fields(self, anchor: str) -> set[str]:
        # The fields a complaint row of the spec's hand-off tables declares.
        row = re.search(rf'<tr data-anchor="{anchor}"[^>]*>(.*?)</tr>', SPEC.read_text(encoding="utf-8"))
        self.assertIsNotNone(row, f"{anchor} row is missing")
        return set(re.findall(r"<code>(\w+)</code>", row.group(1).split("</td>", 2)[2]))

    def test_worker_last_report_answers_the_annoyance_question(self) -> None:
        # spec #roles-complaint, #acceptance-complaint-worker, #acceptance-complaint-none:
        # each worker asks itself the one question in its last step and, on yes
        # only, ends its last report with one Annoyed: line; the owner turns that
        # line into one complaint line naming the worker, its session, its sentence.
        for role in ("implementer", "integrator", "code-reviewer", "researcher", "scientist"):
            output = (ROOT / f"agents/{role}.md").read_text(encoding="utf-8").split("## Output", 1)[1]
            self.assertIn(
                "Before your last report, answer one question: did anything about the system annoy you? "
                "On yes, end the report with one line, `Annoyed: <what, in one sentence>`; on no, add nothing "
                "(spec `#roles-complaint`).",
                output,
                role,
            )
            self.assertLess(output.index("Annoyed:"), output.index("Last step"), role)
        owner = " ".join((ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").split())
        self.assertIn("a worker's last report may end with one line `Annoyed: <sentence>`. Consuming it, append one "
                      "complaint line to that file", owner)
        self.assertIn("a report with no such line gets none", owner)
        line = json.loads(re.search(r'`(\{"at": [^`]*"kind": "complaint"[^`]*\})`', owner).group(1))
        self.assertRegex(line["at"], UTC)
        self.assertEqual(set(line) - {"at", "kind"}, {"name", "session", "text"})
        self.assertLessEqual(set(line) - {"at", "kind"}, self.complaint_fields("handoff-kind-complaint"))
        self.assertRegex(line["name"], r"^implementer-")
        # Its session is read as the parked line reads one: Claude's sessionId.
        self.assertIn("`session` read with `herdr-claude-session <its pane> | jq -r .sessionId` before you close it",
                      owner)
        self.assertIn("session: .sessionId", (ROOT / "skills/herdr-comms/assets/herdr-close").read_text(encoding="utf-8"))

    def test_owner_records_its_own_complaint_as_the_lane_closes(self) -> None:
        # spec #roles-complaint, #acceptance-complaint-owner: at close the owner
        # answers the question itself, its line naming no agent and carrying its
        # session, after its final worker close and before the archive move, so the
        # archived log ends with it.
        owner = " ".join((ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").split())
        self.assertIn("At lane close you answer the same question, `Did anything about the system annoy you?`: on "
                      "yes, append your own line, no `name`, `session` yours "
                      "(`herdr-claude-session \"$HERDR_PANE_ID\" | jq -r .sessionId`).", owner)
        self.assertRegex(owner, r"workers\. Last, after your last hand-off line \(the final worker close, then your "
                                r"own complaint line, if any\) and before your close report, move `<name>\.toml`")

    def test_operator_records_its_complaint_before_each_reload(self) -> None:
        # spec #roles-complaint, #handoff-operator-complaint,
        # #acceptance-complaint-operator: the reload's last message asks the
        # question, and the operator's own line names no agent and carries its session.
        text = " ".join(OPERATOR.read_text(encoding="utf-8").split())
        self.assertIn("`Reload for <change>: write $(octo-lite-state)/operator.brief.md, your brief, and answer the "
                      "annoyance question (Write surface), then end your turn.`", text)
        self.assertIn("Its `complaint` lines (spec `#handoff-operator-complaint`): before each reload, as it writes "
                      "its brief, it answers `Did anything about the system annoy you?` (spec `#roles-complaint`), on "
                      "yes appending one with no `name`, `session` its own "
                      "(`herdr-claude-session \"$HERDR_PANE_ID\" | jq -r .sessionId`), on no nothing", text)
        self.assertLessEqual({"name", "session", "issue", "repository"},
                             self.complaint_fields("handoff-operator-complaint"))

    def test_operator_relays_a_closed_lanes_complaints_in_its_close_message(self) -> None:
        # spec #roles-complaint, #roles-operator-writes, #acceptance-complaint-relay:
        # at a lane's close the operator reads its archived log's complaint lines
        # and tells each as one plain line naming the agent and its sentence.
        text = " ".join(OPERATOR.read_text(encoding="utf-8").split())
        self.assertIn("When a lane closes, read the `complaint` lines of its log, `<lane name>.handoffs.jsonl` in "
                      "`$(octo-lite-state)/lanes/archive/`, or in `$(octo-lite-state)/lanes/` when you closed it in "
                      "its owner's place, and in your message telling of that close give each one plain line naming "
                      "its agent (its `name`, else the lane's owner) and its sentence", text)
        # The operator's close in the owner's place touches no record, so that log stays unarchived.
        self.assertIn("when you close it in its owner's place", text)
        self.assertIn("Touch no record: its owner archived it.", text)
        self.assertIn("one naming a problem of the box goes as that problem, once with the step that fixes it", text)

    def test_health_pass_message_carries_its_complaint(self) -> None:
        # spec #roles-complaint, #health-pass: the pass agent runs under the
        # code-reviewer contract, so the repo-health Pass message it sends keeps
        # any Annoyed: line beside the ticket keys, and the operator relays it.
        reviewer = " ".join((ROOT / "agents/code-reviewer.md").read_text(encoding="utf-8").split())
        self.assertIn("the `repo-health` Pass message (ticket keys only, and any `Annoyed:` line)", reviewer)
        skill = " ".join((ROOT / "skills/repo-health/SKILL.md").read_text(encoding="utf-8").split("## Pass", 1)[1].split())
        self.assertIn("each ticket key filed, commented on, or closed, and any `Annoyed:` line. Then stop.", skill)
        self.assertIn("Relay the ticket keys its one message names, nothing else but its complaint (Write surface)",
                      " ".join(OPERATOR.read_text(encoding="utf-8").split()))

    def test_a_complaint_sends_no_message_and_files_nothing(self) -> None:
        # spec #roles-complaint, #acceptance-complaint-quiet: a complaint is no
        # report, note, or ticket.
        owner = " ".join((ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").split())
        self.assertIn("A complaint is no report, note, or ticket: send no one a message for it and file nothing", owner)
        self.assertIn("A complaint never becomes a message to an agent or an issue.",
                      " ".join(OPERATOR.read_text(encoding="utf-8").split()))

    def test_operator_reloads_itself_from_its_brief(self) -> None:
        # spec #roles-contract-change, #roles-operator-brief, #roles-standing-rule,
        # #acceptance-contract-change-operator(-dialogue, -brief),
        # herdr-transport spec #transport-reload: a merged change to its own contract
        # or the operating model reaches the fleet operator by a reload it starts on
        # itself, handing over through its brief.
        text = " ".join(OPERATOR.read_text(encoding="utf-8").split())
        self.assertIn("run `herdr-spawn --reload \"$HERDR_PANE_ID\" '<last message>' '<first message>'` "
                      "as your turn's last step", text)
        self.assertIn("Before each reload (Behavior) it writes `$(octo-lite-state)/operator.brief.md`, its brief", text)
        self.assertIn("reads the brief first, waits again on each owner it names", text)
        self.assertIn("asks the human again none of the questions it names: your reply to an answer "
                      "in your pane names the question it settles, and acts on it", text)
        self.assertIn("It is no rules store: a standing direction", text)
        self.assertIn("It reaches the rest, and you, once that change merges, as a contract change", text)

    def test_owner_challenges_the_asked_frame_once_in_its_first_review_link(self) -> None:
        # spec #delivery-challenge, #acceptance-challenge-said,
        # #acceptance-challenge-silent: at its shaping step the owner names a
        # simpler or sturdier way once, in its first review link's message, and
        # asks nothing when the asked way is the best path.
        shape = [line for line in (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").splitlines()
                 if line.startswith("- Shape with `spec-chat-shape`")]
        self.assertEqual(len(shape), 1, shape)
        self.assertIn("Before non-trivial work, when a simpler or sturdier way exists than the one asked, say so once, "
                      "up front, in the first review link's message, as \"Are you sure you want X? Y is simpler "
                      "because Z\", challenging the frame, not only the details, then go the way the human chooses; "
                      "say nothing when you checked and the asked way is the best path (spec `#delivery-challenge`).",
                      shape[0])

    def test_prototype_worker_sends_its_commit_before_it_records(self) -> None:
        # spec #delivery-path (its shaping-round sentence), #acceptance-path-prototype:
        # the worker sends its commit as a status report before recording and goes
        # on; the owner merges and runs that commit while the worker records, then
        # merges the final commit its last report names.
        worker = " ".join((ROOT / "agents/implementer.md").read_text(encoding="utf-8").split())
        send = ("Then commit, and before you record, send the owner that commit's id as a status report the way "
                "Output sends one, then go on, since it is not your last report: the owner runs it while you record "
                "(spec `#delivery-path`).")
        self.assertIn(send, worker)
        self.assertLess(worker.index(send), worker.index("record from it with `prototype-video`"))
        self.assertNotIn("still serves the prior round's build", worker)
        owner = " ".join((ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").split())
        self.assertIn("Merge into the lane branch the commit it sends before it records, so the prototype runs it while "
                      "the worker records, then the final commit its last report names (spec `#delivery-path`); run "
                      "the prototype from the lane worktree", owner)
        self.assertIn("restarted through that file after each merge", owner)

    def test_reviewer_runs_what_it_judges_from_a_throwaway_clone(self) -> None:
        # spec #delivery-review, #acceptance-review-ran, #acceptance-review-fix-test,
        # #acceptance-review-checkout: the reviewer runs each check itself, never
        # through a review it forks, from a clone of its own in its TMPDIR that
        # adds no worktree or branch, and proves each fix test fails on the last
        # reviewed head and passes on the batch head.
        reviewer = " ".join((ROOT / "agents/code-reviewer.md").read_text(encoding="utf-8").split())
        for phrase in ("run what you check from a throwaway clone of your own at the commit you check, never a "
                       "worktree or branch of the repo (spec `#delivery-review`)",
                       "Run in that clone, yourself, in this session, the changed behavior and the failing case behind "
                       "each finding, leaving the rest to the full suite that runs beside you; never through a review "
                       "you fork, such as `/code-review`",
                       "with the failing case you ran",
                       "name both runs in your verdict"):
            self.assertIn(phrase, reviewer)
        skill = (ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8")
        self.assertNotRegex(skill, r"/code-review\b")
        self.assertIn("take no worktree: each runs its checks from a throwaway clone in its `$TMPDIR`",
                      (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8"))
        clone = re.search(r"`(git clone [^`]*)`", reviewer).group(1)
        swap = re.search(r"`(git checkout <batch head> -- <test file>)`", reviewer).group(1)

        with tempfile.TemporaryDirectory() as tmp:
            repo, lane, scratch = (Path(tmp, name) for name in ("repo", "lane", "scratch"))
            scratch.mkdir()

            def git(cwd: Path, *args: str) -> str:
                return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                      check=True, capture_output=True, text=True).stdout.strip()

            def run(cwd: Path, command: str) -> int:
                return subprocess.run(command, shell=True, cwd=cwd, capture_output=True,
                                      env={**os.environ, "TMPDIR": str(scratch)}).returncode

            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            (repo / "f").write_text("1\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "reviewed head")
            git(repo, "worktree", "add", "-q", "-b", "lane", str(lane))
            reviewed = git(lane, "rev-parse", "HEAD")
            (lane / "f").write_text("2\n", encoding="utf-8")
            (lane / "t.sh").write_text('test "$(cat f)" = 2\n', encoding="utf-8")
            git(lane, "add", "-A")
            git(lane, "commit", "-qm", "fix batch")
            batch = git(lane, "rev-parse", "HEAD")
            before = (git(repo, "worktree", "list", "--porcelain"), git(repo, "branch", "-a"),
                      git(lane, "status", "--porcelain"))
            self.assertEqual(run(repo, clone.replace("<any checkout of the repo>", str(lane))
                                 .replace("<name>", "review").replace("<commit>", reviewed)), 0)
            review = scratch / "review"
            self.assertEqual(git(review, "rev-parse", "HEAD"), reviewed)
            self.assertEqual(run(review, swap.replace("<batch head>", batch).replace("<test file>", "t.sh")), 0)
            self.assertNotEqual(run(review, "sh t.sh"), 0)
            git(review, "checkout", "-q", "--detach", batch)
            self.assertEqual(run(review, "sh t.sh"), 0)
            self.assertEqual((git(repo, "worktree", "list", "--porcelain"), git(repo, "branch", "-a"),
                              git(lane, "status", "--porcelain")), before)

    def test_reviewer_blocks_a_part_its_design_system_shares(self) -> None:
        # spec #roles-design-system, #delivery-review, #acceptance-design-review-hand,
        # #acceptance-design-review-copy, #acceptance-design-review-new-part.
        reviewer = " ".join((ROOT / "agents/code-reviewer.md").read_text(encoding="utf-8").split())
        self.assertIn("Read the design system's one source the target root `AGENTS.md` names (spec "
                      "`#roles-design-system`). A part the diff draws by hand, or as a near copy, where a shared part "
                      "draws it is a blocker naming that shared part; a shared part the diff adds without its entry in "
                      "that source stating its convention, or without its code check, is a blocker naming what is "
                      "missing.", reviewer)

    def test_prototype_worker_imports_shared_parts_and_passes_design_checks(self) -> None:
        # spec #delivery-prototype, #delivery-implement, #acceptance-design-prototype-checks.
        worker = " ".join((ROOT / "agents/implementer.md").read_text(encoding="utf-8").split())
        self.assertIn("imported or copied, never redrawn, a shared part of the design system the target root "
                      "`AGENTS.md` names always imported, never copied", worker)
        checks = ("Before each commit you send the owner, run the code checks that design system names and fix in "
                  "the prototype what they fail (spec `#delivery-prototype`).")
        self.assertIn(checks, worker)
        self.assertLess(worker.index(checks), worker.index("Then commit, and before you record"))
        self.assertIn("Repo tests run in delivery, never during shaping, but for the design system's checks a "
                      "prototype round runs (spec `#delivery-implement`).",
                      " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split()))

    def test_integrator_works_in_the_lane_worktree_holding_its_branch(self) -> None:
        # ANN-2144 item 5: a branch is checked out in one worktree, so the
        # integrator works where the lane worktree holds it, and the owner writes
        # nothing there while it runs.
        skill = " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split())
        self.assertIn("1. Spawn an integrator through `herdr-comms` with `--role integrator` in the lane worktree "
                      "when it holds the integration branch, else in a clean integration worktree. While it runs, "
                      "write nothing in its worktree.", skill)
        self.assertIn("Each writer has a distinct worktree, the integrator the lane worktree when it holds the "
                      "integration branch (step 1)", skill)
        self.assertIn("in the worktree you were spawned in: the lane worktree when it holds the integration branch, "
                      "which you alone write while you run, else a clean integration worktree",
                      " ".join((ROOT / "agents/integrator.md").read_text(encoding="utf-8").split()))

    def test_owner_reports_each_box_problem_to_operator_once(self) -> None:
        # spec #roles-box-problem, #acceptance-box-problem-owner: the owner reports
        # each problem of the box once, apart from the review link that also says it.
        owner = " ".join((ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").split())
        self.assertIn("- Box problems (spec `#roles-box-problem`): a part of the box you or a worker works without "
                      "because it is missing or out of date, such as Stageshow not installed", owner)
        self.assertIn("The first time you meet one, in a worker's report or a step of your own, report it to the "
                      "operator once in its own message, naming the problem and the step that fixes it", owner)
        self.assertIn("besides saying so where this contract says its fallback is said", owner)

    def test_operator_starts_each_lane_under_an_unused_name(self) -> None:
        # spec #lane-record: a lane record's name is never reused, archived included.
        self.assertIn(
            "pick a lane name no open or archived record has (no `<lane name>.toml` in `$(octo-lite-state)/lanes/` "
            "or its `archive/`), so one name is one lane (spec `#lane-record`); `octo-lite-start",
            " ".join(OPERATOR.read_text(encoding="utf-8").split()),
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

    def gate_examples(self) -> dict[str, dict]:
        # The owner's gate lines, read against the spec's gate row and its
        # decision context: every example uses only the gates, verbs, and
        # fields those declare, says why it asks, and gives each answer a line.
        html = unescape(SPEC.read_text(encoding="utf-8"))
        row = re.search(r'<tr data-anchor="handoff-kind-gate">(.*?)</tr>', html)
        self.assertIsNotNone(row, "gate row is missing")
        context = re.search(r'<p data-anchor="handoff-gate-context".*?</p>', html, flags=re.DOTALL)
        self.assertIsNotNone(context, "gate decision context is missing")
        fields = {"at", "kind"} | set(re.findall(r"<code>(\w+)</code>", row.group(1) + context.group(0)))
        gates = re.search(r"<code>gate</code> \((.*?)\)", row.group(1)).group(1)
        gates = {g.split(":")[0].strip() for g in gates.split(", ")}
        verbs = re.search(r"<code>verb</code>, the one action \((.*?)\)", row.group(1)).group(1)
        verbs = set(verbs.split(", "))
        owner = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        block = re.search(r"```jsonl\n(.*?)```", owner, flags=re.DOTALL)
        self.assertIsNotNone(block, "gate line example is missing")
        lines = [json.loads(line) for line in block.group(1).splitlines() if line.strip()]
        for line in lines:
            self.assertRegex(line["at"], UTC)
            self.assertEqual((line["kind"], line["event"]), ("gate", "asked"))
            self.assertIn(line["gate"], gates)
            self.assertIn(line["verb"], verbs)
            self.assertTrue(line["link"])
            self.assertLessEqual(set(line), fields)
            self.assertTrue(line["why"])
            for choice in line.get("answers", []):
                self.assertEqual(set(choice), {"answer", "line"})
                self.assertTrue(choice["answer"] and choice["line"])
        return {line["gate"]: line for line in lines}

    def test_owner_writes_one_gate_line_per_ask(self) -> None:
        # spec #acceptance-lane-gate, #handoff-kind-gate: a review link for a
        # choice to answer goes out with one gate line asked: gate answer,
        # verb Answer, that link.
        self.assertRegex(
            (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8"),
            r"Each ask you make of the human \(.*a choice or pick to answer on a page.*\) is one gate line "
            r"in that file, appended as the ask goes out: `link` where the human answers, `verb` the one action",
        )
        answer = self.gate_examples()["answer"]
        self.assertEqual(answer["verb"], "Answer")
        self.assertNotIn("qa", answer)

    def test_merge_ask_gate_line_carries_pr_and_qa_call(self) -> None:
        # spec #acceptance-lane-gate-merge: a merge ask with QA skipped goes out
        # with one gate line asked: gate merge, verb Accept and merge, the PR
        # as its link, its QA call in words.
        merge = self.gate_examples()["merge"]
        self.assertEqual(merge["verb"], "Accept and merge")
        self.assertRegex(merge["link"], r"^https://github\.com/[^/]+/[^/]+/pull/")
        self.assertRegex(merge["qa"], r"^QA skipped: \w")
        self.assertRegex(
            (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8"),
            r"on a merge `qa`, the QA call the merge ask states, in words",
        )
        skill = " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split())
        self.assertIn(
            "one merge ask that carries the review result, the PR body's Changelog line, that evidence, and its QA call, "
            "and goes out with its gate line (`agents/orchestrator.md`",
            skill,
        )

    def test_merge_ask_carries_see_it_lines(self) -> None:
        # spec #delivery-see-it, #acceptance-see-it-ask, -open, -pr, -unnamed,
        # -relay, -no-gate: the implementer names each changed screen and
        # state, the owner writes one See it line each after the PR link, the
        # operator relays them, and no reviewer judges them.
        def read(path: str) -> str:
            return " ".join((ROOT / path).read_text(encoding="utf-8").split())

        orchestrator = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        self.assertRegex(orchestrator, r"pull/<pr>\n  See it: <screen and state, in plain words> -> <link>\n  ```")
        orchestrator = read("agents/orchestrator.md")
        for phrase in (
            "the PR body and merge ask carry one `See it: <label> -> <link>` line per screen or state it changes",
            "in what the target root `AGENTS.md` says a See it link opens",
            "When it names none, say in plain words where the change can be seen, in place of the link.",
            "A See it line never gates",
        ):
            self.assertIn(phrase, orchestrator)
        self.assertIn("for a ticket that changes a screen, each screen and state it changes, in plain words",
                      read("agents/implementer.md"))
        self.assertIn("A merge ask you relay keeps every See it line the owner sent, without the human asking",
                      read("agents/meta-operator.md"))
        self.assertIn("then the PR link, then the PR body's See it lines", read("skills/implement-spec/SKILL.md"))
        self.assertNotIn("See it", read("agents/code-reviewer.md"))

    def test_question_gate_line_carries_why_evidence_and_each_answer(self) -> None:
        # spec #acceptance-lane-gate-answers, #handoff-gate-context: a question
        # with two answers goes out with one gate line asked carrying why it
        # asks, its evidence, and both answers, each with its own line.
        self.assertRegex(
            (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8"),
            r"`why` with every ask, `evidence` when something backs it, and `answers`, one to four, when the human "
            r"answers by choosing, each with its `line` \(spec `#handoff-gate-context`\)",
        )
        answer = self.gate_examples()["answer"]
        self.assertTrue(answer["evidence"])
        self.assertEqual(len(answer["answers"]), 2)

    def test_merge_ask_gate_line_offers_accept_and_merge(self) -> None:
        # spec #acceptance-lane-gate-merge-answer: a merge ask's gate line
        # carries why it asks, its evidence, and the answer Accept and merge
        # with its own line.
        merge = self.gate_examples()["merge"]
        self.assertTrue(merge["evidence"])
        self.assertEqual([choice["answer"] for choice in merge["answers"]], ["Accept and merge"])

    def test_spec_review_gate_line_offers_accept_spec(self) -> None:
        # spec #acceptance-lane-gate-spec-answer: a spec review link goes out
        # with one gate line asked carrying why it asks and the answer Accept
        # spec with its own line.
        spec = self.gate_examples()["spec review"]
        self.assertEqual(spec["verb"], "Review")
        self.assertEqual([choice["answer"] for choice in spec["answers"]], ["Accept spec"])

    def test_close_links_each_report_kept_outside_main_before_rows_go(self) -> None:
        # spec #acceptance-close-report-link, #roles-teardown: before review
        # rows go, the PR body gains a permalink to each report kept outside
        # main, at the last commit holding it.
        owner = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        close = re.search(
            r"add to the PR body a permalink to each report the lane kept outside main, "
            r"`https://github\.com/<owner>/<repo>/blob/<commit>/<path>` at the last commit holding it, "
            r"`(git log [^`]*)` on the branch that removed it.*tear down in order: review rows, the prototype you run, worktrees, workers\.",
            owner,
        )
        self.assertIsNotNone(close, "report permalink step is missing or after review rows")
        skill = " ".join((ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8").split())
        self.assertRegex(skill, r"add to the PR body a permalink to each report the lane kept outside main, "
                         r"tear down .*\(report permalinks before review rows")

        with tempfile.TemporaryDirectory() as tmp:
            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", "-C", tmp, *args], check=True, capture_output=True, text=True
                ).stdout.strip()

            def commit(message: str) -> str:
                git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
                return git("rev-parse", "HEAD")

            git("init", "-q", "-b", "lane")
            report = Path(tmp) / "reports/qa.report.html"
            report.parent.mkdir()
            for text in ("draft", "final"):
                report.write_text(text, encoding="utf-8")
                git("add", "-A")
                commit(text)
            (Path(tmp) / "code.py").write_text("x = 1\n", encoding="utf-8")
            git("add", "-A")
            holding = commit("code")
            git("rm", "-q", str(report))
            commit("drop report before merge")
            (Path(tmp) / "code.py").write_text("x = 2\n", encoding="utf-8")
            git("add", "-A")
            commit("more code")
            command = close.group(1).replace("<branch>", "lane").replace("<path>", "reports/qa.report.html")
            found = subprocess.run(command, shell=True, cwd=tmp, check=True, capture_output=True, text=True)
            self.assertEqual(found.stdout.strip(), holding)
            self.assertEqual(git("show", f"{holding}:reports/qa.report.html"), "final")

    def test_owner_logs_closed_line_on_closing_a_consumed_worker(self) -> None:
        # spec #acceptance-lane-log-close,
        # spec/domains/herdr-transport.spec.html#transport-close-line: the owner
        # appends what herdr-close prints, its closed line, to the lane's log.
        deliver = (ROOT / "skills/implement-spec/SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(
            deliver,
            r"Close each consumed worker with\s+`herdr-close TAB >> "
            r"\$\(octo-lite-state\)/lanes/<lane record name>\.handoffs\.jsonl`",
        )

    def test_worker_result_send_is_bounded_then_goes_to_operator(self) -> None:
        # spec/domains/herdr-transport.spec.html#roles-goal,
        # #acceptance-worker-owner-gone(-stops): 3 sends to the owner, then one to
        # the operator pane, then stop; the operator forwards to that pane's lane by
        # name and relaunches only a gone, unparked owner.
        # #acceptance-worker-owner-rate-limited: exit 69 already re-sent, so it
        # goes to the operator at once, never re-sent.
        # #transport-native, #acceptance-native-*: natively to a live Claude
        # session; a timed-out native send counts as sent (#acceptance-native-timeout);
        # herdr-say only when undelivered, or a later notice says held, denied, expired.
        for role in ("implementer", "integrator", "code-reviewer", "researcher", "scientist"):
            output = (ROOT / f"agents/{role}.md").read_text(encoding="utf-8").split("## Output", 1)[1]
            self.assertIn(
                "to the owner pane your brief names as a [report](../skills/herdr-comms/SKILL.md#send-a-report), "
                "natively when you run on Claude and that pane has a live Claude session, else with `herdr-say`. "
                + REPORT_ADDRESS + " " + REPORT_CONFIRM + " If none is confirmed, send it once, "
                "naming the owner pane, as a report to the operator pane (`pane` in `$(octo-lite-state)/operator.toml`). "
                "Then stop, whatever the last result.",
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

    def test_owner_and_operator_report_natively_first(self) -> None:
        # spec/domains/herdr-transport.spec.html#transport-native,
        # #acceptance-native-owner-report: the lane owner and the fleet operator
        # report as workers do, natively first, herdr-say only as its fallback
        # under the same confirm and resend rule, never as a choice of the two.
        output = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8").split("\n## Output\n", 1)[1]
        self.assertIn(
            "sent to its recipient as a [report](../skills/herdr-comms/SKILL.md#send-a-report), natively when you run on "
            "Claude and the recipient's pane has a live Claude session, else with `herdr-say`. " + REPORT_ADDRESS + " "
            + REPORT_CONFIRM,
            output)
        self.assertIn(
            "Send an owner your own reports the same way, natively when you run on Claude and that owner's pane has a "
            "live Claude session, else with `herdr-say`. " + REPORT_ADDRESS + " " + REPORT_CONFIRM,
            OPERATOR.read_text(encoding="utf-8"))
        for path in ROOT.glob("agents/*.md"):
            self.assertNotIn("natively or by", path.read_text(encoding="utf-8"), path.name)

    def test_owner_status_carries_its_eta_and_resends_it_when_it_slips(self) -> None:
        # spec #roles-eta, #acceptance-eta-report, #acceptance-eta-slip: every
        # status the owner sends names its next ask of the human as a UTC time
        # with the time from now, how sure, and what could slip it; a later time
        # goes out at once with what moved it.
        output = " ".join((ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
                          .split("\n## Output\n", 1)[1].split())
        self.assertIn("Concise status with exact gate, health, material change, blocker, next action, and ETA (spec "
                      "`#roles-eta`): the time you expect your next ask of the human (review link, answer, or merge "
                      "ask) as a UTC time with the time from now, such as `19:40 UTC, in about 2 h`, how sure you "
                      "are, and what could slip it, most likely first.", output)
        self.assertIn("When that time moves later than the one you last sent, send a report with the new time and "
                      "what moved it.", output)

    def test_claude_roles_report_natively_to_the_pane_session(self) -> None:
        # spec/domains/herdr-transport.spec.html#transport-native: every Claude role
        # contract allows the native send, and the one recipe addresses the target
        # pane's Claude session (#transport-claude-session), never a box-wide name,
        # falling back to herdr-say; every report line points at that recipe.
        # #acceptance-native-timeout: a timed-out send counts as sent, never sent
        # again; its backstop (#roles-goal) is the sender's pane, read when the wait ends.
        # Each states, where it reports, the one step from the target's pane id to that address.
        for path in ROOT.glob("agents/*.md"):
            tools = re.search(r"^tools: (\[.*\])$", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
            self.assertIn("SendMessage", json.loads(tools.group(1)), path.name)
            self.assertIn(REPORT_ADDRESS, path.read_text(encoding="utf-8"), path.name)
        recipe = (ROOT / "skills/herdr-comms/SKILL.md").read_text(encoding="utf-8")
        recipe = recipe.split("\n## Send a report\n", 1)[1].split("\n## ", 1)[0]
        for token in ("herdr-claude-session PANE | jq -r '.messagingSocketPath // empty'", "`uds:<that path>`", "`herdr-say PANE REPORT`",
                      "It counts as sent once Claude reports it delivered to the receiver's inbox or reports it timed out",
                      "a lost result is read from the sender's pane when the owner's wait on it ends"):
            self.assertIn(token, " ".join(recipe.split()))
        for doc in ("agents/orchestrator.md", "agents/meta-operator.md", "skills/implement-spec/SKILL.md", "skills/repo-health/SKILL.md"):
            self.assertIn("herdr-comms/SKILL.md#send-a-report)", (ROOT / doc).read_text(encoding="utf-8"), doc)

    def test_waiter_keeps_one_herdr_wait_on_each_agent_it_sets_to_work(self) -> None:
        # spec/domains/herdr-transport.spec.html#roles-goal, #transport-await,
        # #acceptance-worker-ended,
        # #acceptance-codex-owner-worker-ended, #acceptance-pi-owner-worker-ended,
        # #acceptance-worker-api-error(-resumed), #acceptance-owner-api-error-resumed,
        # #acceptance-worker-moved-unseen: the owner (orchestrator, implement-spec)
        # and the fleet operator send work with herdr-await and link the one wait
        # recipe herdr-comms states (#roles-goal, last sentence): read the screen
        # by name, resume an API-error turn, re-wait --since on one still at its
        # task; no role runs herdr agent wait or a get-based check-in poll.
        recipe = (ROOT / "skills/herdr-comms/SKILL.md").read_text(encoding="utf-8")
        recipe = recipe.split("\n## Wait on an agent\n", 1)[1].split("\n## ", 1)[0]
        for token in ("`herdr agent read <name>`", "`herdr-await <name> continue`", "`stop=send-failed`", "--since <seq>",
                      "on Claude in the background"):
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
        # #acceptance-await-notice, #acceptance-await-human-typing: an owner on
        # Claude waits by its own task, asking for nothing: its pane decides.
        for path in ("orchestrator", "implement-spec"):
            self.assertIn("on Claude run in the background", " ".join(callers[path].split()), path)
        for path, text in {**callers, "herdr-comms": recipe}.items():
            self.assertNotIn("--notice", text, path)

    def test_steward_owns_a_self_improvement_lane_and_directs_no_research(self) -> None:
        # spec #self-improvement-steward, -team, -messages (steward and operator
        # rows), -spend, -cap, -stop, -finish, #acceptance-self-improvement-(owner,
        # no-direction, no-gain, human-stop, status, ask-spend, merge-ask,
        # spec-change, no-keep): the lane owner's steward rule.
        raw = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        owner = " ".join(raw.split())
        steward = " ".join(raw.split("\n- Steward (spec `#self-improvement-steward`", 1)[1].split("\n- ", 1)[0].split())
        for phrase in (
            "shape no spec, file no ticket graph, run no experiment, and never name a hypothesis or an experiment "
            "to a scientist",
            "spawn three scientists, `--role scientist`",
            "`scientist1-<issue key>` to `scientist3-<issue key>` lowercase",
            "each in its own worktree and branch off the lane branch",
            # herdr-transport spec #acceptance-pane-for-life-rule: a live pane is recovered in place.
            "one whose pane is still open you recover in that pane, never a new one",
            "`git merge --ff-only <commit>`",
            "worklane-provider.spec.html#spend)",
            "`GET <the box's evidence address>/lanes`",
            "name the spend so far in every report and every ask you send",
            "No budget caps it",
            "a round ending with no keep",
            "the human's stop the operator relays",
            "`Stop: record the running experiment and start none.`",
            "[Review and finish](../skills/implement-spec/SKILL.md#review-and-finish)",
            "the main number at the baseline and at the champion on the dev and held-out splits, each keep with its "
            "gain and what made it win, and the spend",
            "before the merge ask",
            "close the PR unmerged",
            "naming no PR to merge",
        ):
            self.assertIn(phrase, steward)
        # The stop line it appends carries the spec's stop fields and nothing else.
        line = json.loads(re.search(r'`(\{"at": [^`]*"kind": "stop"[^`]*\})`', steward).group(1))
        row = re.search(r'<tr data-anchor="self-improvement-log-stop">.*?</td><td>.*?</td><td>(.*?)</td></tr>',
                        SPEC.read_text(encoding="utf-8")).group(1)
        self.assertEqual(set(line) - {"at", "by", "kind"}, set(re.findall(r"<code>(\w+)</code>", row)))
        self.assertIn(line["reason"], {"no gain", "human"})
        # Before the finish the scientists make every change; the steward writes only keeps.
        self.assertIn("On a self-improvement lane (Steward) the scientists make every change until the finish", owner)

    def test_steward_writes_the_lane_report_and_links_it(self) -> None:
        # spec #self-improvement-report, -finish, -stop, -log-kinds,
        # #acceptance-self-improvement-(report, no-keep, merge-ask): the steward
        # writes the lane's report with the report skill, from the log, and the
        # merge ask, PR body, and close report link it, a PR by its Proof path only.
        raw = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        owner = " ".join(raw.split())
        steward = raw.split("\n- Steward (spec `#self-improvement-steward`", 1)[1].split("\n- ", 1)[0]
        bullet = lambda name: " ".join(steward.split(f"\n  - {name} (spec ", 1)[1].split("\n  - ", 1)[0].split())
        report = bullet("Report")
        # The skill's lane folder and address, its question the fixed one of the lane's report.
        skill = " ".join((ROOT / "skills/report/SKILL.md").read_text(encoding="utf-8").split())
        address = "`<Proof's address>/reports/<lane record name>/<question>/`"
        self.assertIn(address, skill)
        self.assertIn(address.replace("<question>", "self-improvement"), report)
        self.assertIn("`reports/self-improvement/`", report)
        # Written as the owner-side rule says, never restated: one scope-row recipe in the contract.
        self.assertIn("as Research says for a report you write yourself", report)
        self.assertEqual(owner.count("review-host register"), 1)
        for phrase in ("once the log holds its `eval` line", "at every keep", "before the stop report",
                       "before the merge ask", "`experiments.jsonl`", "leads with the gain",
                       "`data-answers=\"Let it run, Stop\"`", "is the human's stop",
                       "every report and ask you send links its address",
                       "only its Proof path, `/reports/<lane record name>/self-improvement/`, never the evidence address"):
            self.assertIn(phrase, report)
        # Every log kind and field it reads from is one the spec's log table names.
        html = SPEC.read_text(encoding="utf-8")
        rows = dict(re.findall(r'<tr data-anchor="self-improvement-log-\w+"><td><code>(\w+)</code></td><td>.*?</td>'
                               r'<td>(.*?)</td></tr>', html))
        fields = {f for row in rows.values() for f in re.findall(r"<code>(\w+)</code>", row)}
        for kind in ("eval", "hypothesis", "proposal", "result"):
            self.assertIn(kind, rows)
            self.assertIn(f"`{kind}`", report)
        for field in ("noise", "taught", "unreached"):
            self.assertIn(field, fields)
            self.assertIn(f"`{field}`", report)
        # The human's stop may come on the report; the PR body and close report link it.
        self.assertIn("or a hand-off on the lane's report gives", bullet("Stop"))
        finish = bullet("Finish")
        self.assertIn("and the spend, and links the lane's report", finish)
        self.assertIn("your close report linking the lane's report and naming no PR to merge", finish)

    def test_scientist_works_the_goal_from_the_log(self) -> None:
        # spec #self-improvement-team, -messages (scientist rows), -log,
        # -log-kinds, -goal, -goal-where, -eval, -hypotheses, -critique,
        # -experiment, -stop, #roles-load, #acceptance-self-improvement-(critique,
        # dead-end, shared, retire, reach, headroom, question, noise, one-line,
        # declared-check, goal-added, live-goal, tests-floor): the scientist contract.
        raw = (ROOT / "agents/scientist.md").read_text(encoding="utf-8")
        text = " ".join(raw.split())
        front = raw.split("---", 2)[1]
        for name in json.loads(re.search(r"^skills: (\[.*\])$", front, flags=re.MULTILINE).group(1)):
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file()
                            or (ROOT / "agents/skills" / name / "SKILL.md").is_file(), name)
        # Every example log line carries only the fields the spec's log table
        # names for its kind, and together they write every field of each kind.
        html = SPEC.read_text(encoding="utf-8")
        rows = dict(re.findall(r'<tr data-anchor="self-improvement-log-\w+"><td><code>(\w+)</code></td><td>.*?</td>'
                               r'<td>(.*?)</td></tr>', html))
        block = re.search(r"```jsonl\n(.*?)\n *```", raw, flags=re.DOTALL).group(1)
        lines = [json.loads(line) for line in block.splitlines()]
        written: dict[str, set[str]] = {}
        for line in lines:
            self.assertRegex(line["at"], UTC)
            self.assertRegex(line["by"], r"^scientist\d-[a-z]+-\d+$")
            fields = set(line) - {"at", "by", "kind"}
            self.assertLessEqual(fields, set(re.findall(r"<code>(\w+)</code>", rows[line["kind"]])), line)
            written.setdefault(line["kind"], set()).update(fields)
        for kind in ("eval", "hypothesis", "proposal", "critique", "result"):
            self.assertEqual(written[kind], set(re.findall(r"<code>(\w+)</code>", rows[kind])), kind)
        self.assertNotIn("stop", written)  # the steward's line
        for line in lines:
            self.assertIn(line.get("event", "opened"), {"opened", "retired"})
            self.assertIn(line.get("verdict", "go"), {"go", "no"})
            self.assertIn(line.get("outcome", "keep"), {"keep", "discard", "crash"})
        # A teammate's pane is found by its spawn name, by the lookup herdr-say makes.
        say = (ROOT / "skills/herdr-comms/assets/herdr-say").read_text(encoding="utf-8")
        self.assertIn("jq -r '.result.agent.pane_id // empty'", say)
        self.assertIn("`herdr agent get <name> | jq -r '.result.agent.pane_id // empty'`", text)
        # The stop it obeys is the one the steward sends.
        stop = re.search(r"(`Stop: [^`]*`)", (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")).group(1)
        self.assertIn(f"on the steward's {stop}", text)
        for phrase in (
            # -goal, -goal-where, #acceptance-self-improvement-(declared-check, goal-added)
            "the one the goal's repository `AGENTS.md` declares for the goal under `Goals:`",
            "in the same commit, add its line under `Goals:`",
            # -eval, #acceptance-self-improvement-live-goal
            "Never try anything on live traffic",
            "such as a replay of recorded traffic",
            "first on a small sample",
            # -eval, #acceptance-self-improvement-(reach, headroom, question)
            "Until reach and room both hold, propose no change to the code under improvement",
            "count each item the code cannot reach, with the input it lacks",
            "an input only the human can give",
            "no experiment changes it",
            "the held-out split only as you set the eval",
            # -hypotheses, #acceptance-self-improvement-(retire, no-direction)
            "what result would refute it",
            "nobody assigns one",
            "a direction nobody has tried, a follow-up of what made the latest keep win, "
            "the open hypothesis fewest scientists work",
            "Never propose under a retired hypothesis",
            "five results in a row under a hypothesis gain nothing",
            # -critique, #acceptance-self-improvement-(critique, dead-end)
            "one scientist whose latest proposal names another hypothesis, else any other",
            "run it only on that critic's go",
            "repeats a dead end without saying what differs",
            "duplicates a running experiment",
            "changes nothing the eval reaches",
            "On a no, run nothing and record no result",
            # -experiment, #roles-load, #acceptance-self-improvement-(one-line, noise, tests-floor)
            "one `result` line, however many settings it sweeps",
            "`octo-lite-lock CMD`",
            "beats the champion's by more than the noise",
            "every floor holds",
            "the tests of the code it touched",
            "its `why` naming that test",
            "kept only when both beat the champion",
            "send its commit to the steward",
            "merge it into your branch and score it again",
            # -messages, #acceptance-self-improvement-shared
            "to every other scientist and the steward",
            # -team: a respawned scientist goes on from the log
            "go on from the log",
            # herdr-transport #acceptance-pane-for-life-rule, disk #acceptance-disk-own-only-rule
            "Spawn, respawn, or close a teammate: the steward does",
            "never a teammate's or another lane's",
        ):
            self.assertIn(phrase, text)

    def test_operator_launches_a_self_improvement_lane_only_on_a_named_goal(self) -> None:
        # spec #self-improvement-what, -goal, -goal-where, -why, -messages (operator
        # row), #acceptance-self-improvement-(launch, no-goal, workbench-goal,
        # human-stop): the human names the goal; the operator launches the lane as
        # any lane, in the goal's repository, asks which goal when none is named,
        # and relays the human's stop to the steward.
        raw = OPERATOR.read_text(encoding="utf-8")
        operator = " ".join(raw.split())
        launch = " ".join(raw.split("\nSelf-improvement lane (spec `#self-improvement-what`", 1)[1].split("\n\n", 1)[0].split())
        for phrase in (
            "only when the human asks you to launch a self improvement lane on a goal it names",
            "never on your own, never on a goal you choose, and never again when one ends, so none is a standing loop",
            "by Lane start in the goal's repository",
            "its brief naming it a self-improvement lane, its goal, and the goal's repository",
            "one question to the human, before any lane starts, asking which goal",
            "the goals that repository's `AGENTS.md` declares under `Goals:`",
            "your pick marked",
            "The human's stop goes to its steward by `herdr-say <lane name> <stop>`",
        ):
            self.assertIn(phrase, launch)
        # Lane start is the one launch: no second recipe for this lane kind.
        self.assertEqual(operator.count("octo-lite-start --cwd"), 1)
        # The goals list it offers is the one the spec places in AGENTS.md.
        self.assertIn("under <code>Goals:</code>", SPEC.read_text(encoding="utf-8"))
        # The steward works that goal in that repository, its scientists there too.
        raw = (ROOT / "agents/orchestrator.md").read_text(encoding="utf-8")
        steward = raw.split("\n- Steward (spec `#self-improvement-steward`", 1)[1].split("\n- ", 1)[0]
        head = " ".join(steward.split("\n  - ", 1)[0].split())
        self.assertIn("on a lane your brief names a self-improvement lane, its goal, and the goal's repository", head)
        self.assertIn("work that goal in that repository and never another (spec `#self-improvement-goal`)", head)
        team = " ".join(steward.split("\n  - Team (spec ", 1)[1].split("\n  - ", 1)[0].split())
        self.assertIn("each in its own worktree and branch off the lane branch in the goal's repository", team)
        self.assertIn("each briefed with your brief's goal and its repository", team)

    def test_researcher_hands_the_x_token_to_curl_on_stdin_only(self) -> None:
        # spec #roles-research-x, #acceptance-research-x, #acceptance-research-x-missing:
        # the researcher reads the token from the X credential file at each search
        # and no command line holds it; with no file, or one whose line holds no
        # value, no search runs. It takes the line's value as the installer's
        # check does, one pair of matching quotes around it dropped, never
        # running the file (spec/domains/install.spec.html#acceptance-x-token-quoted,
        # #install-x-token).
        text = (ROOT / "agents/researcher.md").read_text(encoding="utf-8")
        block = next(b for _, b in re.findall(r"\n( *)```sh\n(.*?)\n\1```", text, flags=re.DOTALL) if "x.env" in b)
        with tempfile.TemporaryDirectory() as tmp:
            home, out, bin_ = Path(tmp, "home"), Path(tmp, "out"), Path(tmp, "bin")
            for d in (home / ".config/workbench", out, bin_):
                d.mkdir(parents=True)
            (bin_ / "curl").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$OUT/argv"\ncat > "$OUT/stdin"\n')
            (bin_ / "curl").chmod(0o755)
            env = {**os.environ, "HOME": str(home), "OUT": str(out), "PATH": f"{bin_}:{os.environ['PATH']}"}
            run = lambda: subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True)
            run()
            self.assertFalse((out / "argv").exists(), "searched with no X credential file")
            for held in ("", "X_BEARER_TOKEN=\n", "TOKEN=kept\n"):
                (home / ".config/workbench/x.env").write_text(held)
                run()
                self.assertFalse((out / "argv").exists(), f"searched with no X token: {held!r}")
            # One pair of matching quotes around the value is dropped, as a shell
            # assignment holds it; sourcing would run the planted command.
            for n, quote in enumerate(("'", '"', "")):
                with self.subTest(quote=quote):
                    for f in ("argv", "stdin"):
                        (out / f).unlink(missing_ok=True)
                    token = f"AAAA%3D{n}$(touch {out}/ran)secret"
                    (home / ".config/workbench/x.env").write_text(f"X_BEARER_TOKEN={quote}{token}{quote}\n")
                    run()
                    argv = (out / "argv").read_text()
                    self.assertEqual((out / "stdin").read_text(), f"Authorization: Bearer {token}\n")
                    self.assertFalse((out / "ran").exists(), "ran the X credential file")
                    self.assertNotIn("secret", argv)
                    self.assertIn("https://api.x.com/2/tweets/search/recent", argv)
        self.assertNotRegex(block, r"\s(-v|--verbose|--trace\S*)\s")  # each prints the header

    def test_report_skill_states_the_folder_other_lanes_read(self) -> None:
        # spec #roles-report, #boundary-report, #delivery-notes, #store-research:
        # one folder per question, in the lane's notes or a research folder, its
        # latest pair on top and earlier rounds under round-<n>; the owner and
        # the fleet operator load the skill and spawn the researcher; Proof
        # serves it at /reports/<lane>/<question>/ or /research/<name>/.
        skill = " ".join((ROOT / "skills/report/SKILL.md").read_text(encoding="utf-8").split())
        for token in ("`$(octo-lite-state)/lanes/<lane record name>-notes/reports/<question>/`",
                      "`$(octo-lite-state)/research/<name>/`", "`summary.html`", "`findings.html`",
                      "`round-<n>/summary.html`", 'data-anchor="<id>"', 'data-answers="A, B, C"',
                      "`findings.html#<id>`", "no `data-comment-*` attribute", "slug `operator`",
                      "`<Proof's address>/reports/<lane record name>/<question>/`",
                      "`<Proof's address>/research/<name>/`", "prefers-color-scheme", "no dotfiles"):
            self.assertIn(token, skill)
        researcher = (ROOT / "agents/researcher.md").read_text(encoding="utf-8")
        skills = json.loads(re.search(r"^skills: (\[.*\])$", researcher, flags=re.MULTILINE).group(1))
        self.assertIn("report", skills)
        for name in skills:
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file(), name)
        tools = json.loads(re.search(r"^tools: (\[.*\])$", researcher, flags=re.MULTILINE).group(1))
        self.assertLessEqual({"WebSearch", "WebFetch"}, set(tools))
        for role in ("orchestrator", "meta-operator"):
            text = (ROOT / f"agents/{role}.md").read_text(encoding="utf-8")
            self.assertIn('"report"', text.split("---", 2)[1], role)
            self.assertIn("researcher", text, role)
        self.assertIn("--role researcher --cwd <target main checkout>", OPERATOR.read_text(encoding="utf-8"))

    def test_operator_launch_example_writes_started_at(self) -> None:
        text = OPERATOR.read_text(encoding="utf-8")
        match = re.search(r"```toml\n(.*?)```", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "operator launch example is missing")
        record = tomllib.loads(match.group(1))
        self.assertRegex(record["started_at"], UTC)
        self.assertIn("operator.toml", text)


if __name__ == "__main__":
    unittest.main()
