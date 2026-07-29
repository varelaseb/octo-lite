"""gh#28 leg2/leg3 operator-visibility publication helper (delivery-lifecycle
qa-publication-single-writer, qa-publication-surface-target,
qa-publication-surface-required, qa-served, qa-publication-readback,
edge-evidence-missing).

ONE deterministic publication helper, the SOLE writer of an issue's
operator-visibility surface. It:

  a. reads the operator-visibility surface DECLARATION (served root, verdict
     index location) from the TARGET repo AGENTS.md -- octo-lite stays
     target-neutral, no hard-coded path;
  b. creates and verifies the served-evidence symlink for the exact issue at the
     served root;
  c. writes the verdict card into the verdict-index (operator-read) location
     sourced from the ONE durable evidence home (qa-artifacts/qa-verdicts),
     asserting exactly one durable store;
  d. reads back the WRITTEN operator-read index card and confirms it is readable
     JSON carrying the exact fields issue / PR / HEAD / verdict / story IDs /
     criterion coverage for the exact issue;
  e. FAILS LOUD on any missing link, missing/incomplete surface declaration, or
     unreadable/incomplete written card -- never a silent skip.

octo-lite owns only mechanism + readback; the concrete surface is target-owned.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


from octo_lite.runtime import GateError


# Target AGENTS.md surface-declaration signal keys (delivery-lifecycle
# qa-publication-surface-target). A target that has not declared BOTH signals
# fails the publish loud (qa-publication-surface-required); none is hard-coded.
SURFACE_SERVED_ROOT_SIGNAL = "Operator-visibility served root:"
SURFACE_VERDICT_INDEX_SIGNAL = "Operator-visibility verdict index:"

# The exact card fields readiness requires (qa-served, qa-publication-readback):
# the readback proves the WRITTEN operator-read index card carries each of these
# for the exact issue.
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
            # break later at the filesystem step.
            if value and not value.startswith("TODO:"):
                found = value
    return found


def read_surface_declaration(agents_text: str) -> dict:
    """Parse the target AGENTS.md operator-visibility surface declaration. Fails
    loud (qa-publication-surface-required) if EITHER field is absent or blank, so
    a missing declaration can never become a silent no-publish path."""
    served_root = _signal_value(agents_text, SURFACE_SERVED_ROOT_SIGNAL)
    verdict_index = _signal_value(agents_text, SURFACE_VERDICT_INDEX_SIGNAL)
    missing = [
        name
        for name, value in (
            ("served root", served_root),
            ("verdict index", verdict_index),
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
) -> dict:
    """Publish the exact issue's operator-visibility surface atomically-or-loud.

    - `agents_path`: target repo AGENTS.md declaring the surface.
    - `durable_home`: the ONE durable evidence home root; the verdict card is
      sourced from `<durable_home>/qa-verdicts/<issue>.json`.
    - `target_root`: base for resolving relative declared paths.
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

    # Written-card readback (qa-served, qa-publication-readback,
    # edge-evidence-missing): RE-READ the written operator-read index card and
    # require it be readable JSON carrying each exact field for the exact issue.
    # The card content is the durable card (single source), so this both proves
    # single-writer landing AND that the operator-read card is readable-for-those-
    # fields. An unreadable or incomplete written card is NOT ready.
    readback = _readback_written_card(index_card, issue=issue)

    return {
        "issue": issue,
        "served_link": str(link),
        "served_link_resolved": str(link.resolve()),
        "verdict_index_card": str(index_card),
        "durable_source": str(verdict_source),
        "readback": readback,
        "ready": True,
    }


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _readback_written_card(index_card: Path, *, issue: str) -> dict:
    try:
        card = json.loads(index_card.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(
            f"written operator card for {issue} is not readable JSON"
        ) from error
    if not isinstance(card, dict):
        raise GateError(f"written operator card for {issue} is not a card object")
    missing = [field for field in REQUIRED_CARD_FIELDS if field not in card]
    if missing:
        raise GateError(
            f"written operator card for {issue} missing fields: {', '.join(missing)}"
        )
    if card.get("issue") != issue:
        raise GateError(
            f"written operator card issue mismatch for {issue}: {card.get('issue')!r}"
        )
    return card
