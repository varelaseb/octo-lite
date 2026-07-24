"""gh#28 leg2/leg3 operator-visibility publication helper (delivery-lifecycle
qa-publication-single-writer, qa-publication-surface-target,
qa-publication-surface-required, qa-served, qa-publication-readback,
edge-evidence-missing).

ONE deterministic publication helper, the SOLE writer of an issue's
operator-visibility surface. It:

  a. reads the operator-visibility surface DECLARATION (served root, verdict
     index location, rendered-card verify command) from the TARGET repo
     AGENTS.md -- octo-lite stays target-neutral, no hard-coded path;
  b. creates and verifies the served-evidence symlink for the exact issue at the
     served root;
  c. writes the verdict card into the verdict-index (operator-read) location
     sourced from the ONE durable evidence home (qa-artifacts/qa-verdicts),
     asserting exactly one durable store;
  d. runs the rendered-card verify command and checks the exact fields
     issue / PR / HEAD / verdict / story IDs / criterion coverage;
  e. FAILS LOUD on any missing link, missing/incomplete surface declaration, or
     unreadable/mismatched rendered card -- never a silent skip.

octo-lite owns only mechanism + readback; the concrete surface is target-owned.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

from octo_lite.runtime import GateError


# Target AGENTS.md surface-declaration signal keys (delivery-lifecycle
# qa-publication-surface-target). A target that has not fully declared all three
# fails the publish loud (qa-publication-surface-required); none is hard-coded.
SURFACE_SERVED_ROOT_SIGNAL = "Operator-visibility served root:"
SURFACE_VERDICT_INDEX_SIGNAL = "Operator-visibility verdict index:"
SURFACE_RENDERED_VERIFY_SIGNAL = "Operator-visibility rendered-card verify:"

# The exact rendered-card fields readiness requires (qa-served,
# qa-publication-readback): the readback proves the RENDERED operator card, not
# only the written artifact, carries each of these for the exact issue.
REQUIRED_CARD_FIELDS = ("issue", "pr", "head", "verdict", "story_ids", "criterion_coverage")


def _signal_value(text: str, signal: str) -> str | None:
    # Single-line AGENTS.md signal, mirroring operator-sweep's convention: the
    # last non-empty declaration wins; an absent, blank, or unfilled-placeholder
    # signal returns None so the caller fails loud on an incomplete declaration.
    found: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if stripped.startswith(signal):
            value = stripped[len(signal):].strip()
            # adv3: the target-init template ships each signal with a `TODO: ...`
            # placeholder. An unfilled placeholder is NOT a real declaration; it
            # must fail loud at the surface-declaration gate, not slip through and
            # break later at the filesystem/render step.
            if value and not value.startswith("TODO:"):
                found = value
    return found


def read_surface_declaration(agents_text: str) -> dict:
    """Parse the target AGENTS.md operator-visibility surface declaration. Fails
    loud (qa-publication-surface-required) if any of the three fields is absent or
    blank, so a missing declaration can never become a silent no-publish path."""
    served_root = _signal_value(agents_text, SURFACE_SERVED_ROOT_SIGNAL)
    verdict_index = _signal_value(agents_text, SURFACE_VERDICT_INDEX_SIGNAL)
    rendered_verify = _signal_value(agents_text, SURFACE_RENDERED_VERIFY_SIGNAL)
    missing = [
        name
        for name, value in (
            ("served root", served_root),
            ("verdict index", verdict_index),
            ("rendered-card verify command", rendered_verify),
        )
        if not value
    ]
    if missing:
        raise GateError(
            "target AGENTS.md operator-visibility surface incompletely declared; missing: "
            + ", ".join(missing)
        )
    return {
        "served_root": served_root,
        "verdict_index": verdict_index,
        "rendered_verify": rendered_verify,
    }


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path)


def publish_evidence(
    *,
    issue: str,
    agents_path: Path,
    durable_home: Path,
    target_root: Path,
    expected: Mapping[str, object],
    run_verify=None,
) -> dict:
    """Publish the exact issue's operator-visibility surface atomically-or-loud.

    - `agents_path`: target repo AGENTS.md declaring the surface.
    - `durable_home`: the ONE durable evidence home root; the verdict card is
      sourced from `<durable_home>/qa-verdicts/<issue>.json`.
    - `target_root`: base for resolving relative declared paths.
    - `expected`: the exact rendered-card fields readiness requires
      (issue/pr/head/verdict/story_ids/criterion_coverage).
    - `run_verify`: injectable rendered-card verify runner (default: subprocess);
      returns the rendered card as a dict. Tests inject a deterministic runner.
    """
    if not issue or not issue.strip():
        raise GateError("publish requires an issue identifier")
    if not agents_path.is_file():
        raise GateError("target AGENTS.md missing; operator-visibility surface undeclared")
    declaration = read_surface_declaration(agents_path.read_text(encoding="utf-8"))

    # One durable store assertion (qa-publication-single-writer): the verdict card
    # is sourced ONLY from the single durable home; no second durable store.
    verdict_source = durable_home / "qa-verdicts" / f"{issue}.json"
    if not verdict_source.is_file():
        raise GateError(f"durable verdict card missing for {issue}: {verdict_source}")
    try:
        card = json.loads(verdict_source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"durable verdict card unreadable for {issue}") from error

    # adv1 (octo-lite data integrity): the rendered-card readback below validates
    # the target render command's output against the CALLER-supplied `expected`.
    # A target render command that merely echoes the caller args reduces that
    # check to caller-vs-caller, so a durable card that says verdict=blocking can
    # be published as ready when the caller passes --verdict clear. Cross-check
    # the caller-supplied verified fields against the DURABLE source card here, at
    # the octo-lite data-integrity boundary (NOT target render logic): any field
    # the durable card carries must match what the caller asserts. A mismatch
    # (e.g. caller verdict does not match durable card) fails LOUD, no ready.
    _assert_caller_matches_durable(card, expected, issue=issue)

    # Leg 2 (qa-publication-single-writer): create + verify the served-evidence
    # symlink for the EXACT issue at the target-declared served root. A missing or
    # dangling link fails readiness loud (edge-evidence-missing).
    served_root = _resolve(target_root, declaration["served_root"])
    served_root.mkdir(parents=True, exist_ok=True)
    link = served_root / issue
    link_target = durable_home / issue
    if not link_target.exists():
        raise GateError(f"served-evidence source for {issue} missing: {link_target}")
    if link.is_symlink() or link.exists():
        # The helper is the sole writer: replace a stale link with the exact one.
        if link.is_symlink() or link.is_file():
            link.unlink()
    os.symlink(link_target, link)
    if not link.is_symlink() or not link.resolve().exists():
        raise GateError(f"served-evidence link for {issue} did not resolve")

    # Leg 3 (qa-publication-single-writer): write the verdict card into the
    # target-declared verdict-index (operator-read) location, sourced from the ONE
    # durable home. The helper is the sole writer of that location.
    verdict_index = _resolve(target_root, declaration["verdict_index"])
    verdict_index.mkdir(parents=True, exist_ok=True)
    index_card = verdict_index / f"{issue}.json"
    _atomic_write_json(index_card, card)
    if not index_card.is_file():
        raise GateError(f"verdict index card for {issue} not written")

    # Rendered-card readback (qa-served, qa-publication-readback,
    # edge-evidence-missing): run the target-declared rendered-card verify command
    # and require the RENDERED operator card carry each exact field. An unreadable
    # or mismatched rendered card is NOT ready.
    rendered = _run_rendered_verify(
        declaration["rendered_verify"], issue=issue, target_root=target_root, run_verify=run_verify,
    )
    _assert_rendered_matches(rendered, expected, issue=issue)

    # adv1: the operator-read INDEX card the helper WROTE must still equal the
    # DURABLE source it was sourced from. Re-read the index at readback time and
    # assert it has not diverged from the durable card (split-brain), failing loud
    # rather than reporting ready on a stale/tampered operator-read index.
    _assert_index_matches_durable(index_card, card, issue=issue)

    return {
        "issue": issue,
        "served_link": str(link),
        "served_link_resolved": str(link.resolve()),
        "verdict_index_card": str(index_card),
        "durable_source": str(verdict_source),
        "rendered": rendered,
        "ready": True,
    }


# The caller-supplied verified fields cross-checked against the durable card
# (adv1). Only fields the durable card actually carries are checked, so a minimal
# durable card is not spuriously rejected; a field present in BOTH must agree.
_DURABLE_CROSSCHECK_FIELDS = ("issue", "pr", "head", "verdict", "story_ids", "criterion_coverage")


def _assert_caller_matches_durable(card: Mapping[str, object], expected: Mapping[str, object], *, issue: str) -> None:
    mismatched = [
        field
        for field in _DURABLE_CROSSCHECK_FIELDS
        if field in card and field in expected and card.get(field) != expected.get(field)
    ]
    if mismatched:
        detail = ", ".join(
            f"{field} (caller {expected.get(field)!r} vs durable {card.get(field)!r})"
            for field in mismatched
        )
        raise GateError(
            f"caller-supplied fields do not match the durable verdict card for {issue}: {detail}"
        )


def _assert_index_matches_durable(index_card: Path, durable_card: Mapping[str, object], *, issue: str) -> None:
    try:
        written = json.loads(index_card.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"operator-read index card unreadable for {issue}") from error
    if written != durable_card:
        raise GateError(
            f"operator-read index card for {issue} diverged from the durable source card"
        )


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _run_rendered_verify(command: str, *, issue: str, target_root: Path, run_verify) -> dict:
    if run_verify is not None:
        rendered = run_verify(command=command, issue=issue, target_root=target_root)
        if not isinstance(rendered, dict):
            raise GateError("rendered-card verify returned an unreadable card")
        return rendered
    # Default runner: the declared command is run with the issue as ISSUE in the
    # environment and must emit the rendered card as JSON on stdout. A nonzero
    # exit, empty, or non-JSON stdout means the rendered card is unreadable ->
    # not ready (edge-evidence-missing).
    env = dict(os.environ, ISSUE=issue, OCTO_PUBLISH_ISSUE=issue)
    try:
        result = subprocess.run(
            command, shell=True, cwd=str(target_root), env=env,
            capture_output=True, text=True,
        )
    except OSError as error:
        raise GateError(f"rendered-card verify command failed to run for {issue}") from error
    if result.returncode != 0:
        raise GateError(
            f"rendered operator card not readable for {issue}: verify exited {result.returncode}"
        )
    try:
        rendered = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GateError(f"rendered operator card for {issue} is not readable JSON") from error
    if not isinstance(rendered, dict):
        raise GateError(f"rendered operator card for {issue} is not a card object")
    return rendered


def _assert_rendered_matches(rendered: Mapping[str, object], expected: Mapping[str, object], *, issue: str) -> None:
    missing = [field for field in REQUIRED_CARD_FIELDS if field not in rendered]
    if missing:
        raise GateError(
            f"rendered operator card for {issue} missing fields: {', '.join(missing)}"
        )
    mismatched = [
        field
        for field in REQUIRED_CARD_FIELDS
        if field in expected and rendered.get(field) != expected.get(field)
    ]
    if mismatched:
        raise GateError(
            f"rendered operator card for {issue} field mismatch: {', '.join(mismatched)}"
        )
