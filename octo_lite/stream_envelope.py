"""Delivery-entry invocation for ADR 0004.

The invocation layer passes exactly issue, PR, and head. The loop derives every
other binding from canonical state at fire.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from octo_lite.launch import LaneProvision
from octo_lite.runtime import GateError


def _required(value: Any, label: str) -> Any:
    if value is None or value == "":
        raise GateError(f"delivery entry requires the declared {label}")
    return value


def build_delivery_entry(*, issue: str, pr: Any, head: str) -> dict[str, Any]:
    """Return exactly the three declared delivery-entry facts."""
    return {
        "issue": _required(issue, "issue"),
        "pr": _required(pr, "PR"),
        "head": _required(head, "head"),
    }


def launch_stream_lane(
    stream_name: str,
    *,
    provision: LaneProvision,
    issue: str,
    pr: Any,
    head: str,
    runner: Callable[[Path, Mapping[str, Any]], Any],
) -> Any:
    """Start a lane with parsed three-fact arguments, never a raw stream flag."""
    if not isinstance(stream_name, str) or not stream_name.strip():
        raise GateError("stream name required")
    entry = build_delivery_entry(issue=issue, pr=pr, head=head)
    return runner(Path(provision.record["worktree"]), entry)
