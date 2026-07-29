from __future__ import annotations

import json
import unittest
from pathlib import Path

from octo_lite.launch import LaneProvision
from octo_lite.runtime import GateError
from octo_lite import stream_envelope


HEAD = "f00b13357cb1be87b5c5e6d7bd98fd9572915154"
ISSUE = "TUR-447"
PR = 6
WORKTREE = "/root/octo-lite"


class DeliveryEntryBuilderTests(unittest.TestCase):
    def test_delivery_entry_is_exactly_the_three_declared_facts(self) -> None:
        entry = stream_envelope.build_delivery_entry(issue=ISSUE, pr=PR, head=HEAD)
        self.assertEqual({"issue": ISSUE, "pr": PR, "head": HEAD}, entry)

    def test_missing_declared_fact_fails_closed(self) -> None:
        with self.assertRaises(GateError):
            stream_envelope.build_delivery_entry(issue="", pr=PR, head=HEAD)
        with self.assertRaises(GateError):
            stream_envelope.build_delivery_entry(issue=ISSUE, pr=PR, head="")


class DeliveryEntryProductionInvocationTests(unittest.TestCase):
    def _provision(self) -> LaneProvision:
        return LaneProvision(
            record={
                "schema_version": 1,
                "source": "host-provisioned-worktree",
                "lane": "gh34-loop-debloat",
                "control_repo": WORKTREE,
                "worktree": WORKTREE,
                "worktree_root": "/root",
                "repo_slug": "varelaseb/octo-lite",
                "branch": "octo-lite/issue34-loop-debloat",
                "starting_head": HEAD,
                "resolver_root": WORKTREE,
                "install_check": "clean",
                "provisioned_at": "2026-07-29T00:00:00+00:00",
            },
            record_path=Path("/tmp/gh34-loop-debloat.json"),
            install_check_owner_route=None,
        )

    def test_stream_name_reaches_runner_as_parsed_declared_entry_never_raw_flag(self) -> None:
        calls = []

        def runner(cwd, args):
            calls.append((cwd, args))
            return {"ok": True}

        stream_name = "gh34-loop-debloat"
        result = stream_envelope.launch_stream_lane(
            stream_name,
            provision=self._provision(),
            issue=ISSUE,
            pr=PR,
            head=HEAD,
            runner=runner,
        )

        self.assertEqual({"ok": True}, result)
        self.assertEqual([(Path(WORKTREE), {"issue": ISSUE, "pr": PR, "head": HEAD})], calls)
        raw_flag = f"--stream {stream_name}"
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw_flag)
        self.assertNotEqual(raw_flag, json.dumps(calls[0][1]))

    def test_empty_stream_name_fails_closed(self) -> None:
        with self.assertRaises(GateError):
            stream_envelope.launch_stream_lane(
                "",
                provision=self._provision(),
                issue=ISSUE,
                pr=PR,
                head=HEAD,
                runner=lambda cwd, args: None,
            )


if __name__ == "__main__":
    unittest.main()
