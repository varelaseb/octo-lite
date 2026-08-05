from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Canonical code-reviewer / qa-reviewer relay runtime the provenance readback
# verifies like-with-like against roles.toml (both openai gpt-5.6-sol high).
REVIEWER_MODEL = "gpt-5.6-sol"
REVIEWER_EFFORT = "high"

SLUG = "turbohq/octo-lite"
PR = 65
HEAD = "d" * 40
SESSION = "sess-code-reviewer-0001"


def _load_octo_control():
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader(
        "octo_control_cli_prov", str(ROOT / "scripts/octo-control")
    )
    spec = importlib.util.spec_from_loader("octo_control_cli_prov", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


MODULE = _load_octo_control()
GateError = MODULE.GateError


def _write_codex_rollout(
    codex_home: Path, session_id: str, *, model: str, effort: str,
    final_message: str, provider: str = "openai",
) -> None:
    # Mirror the codex rollout record shape (octo_lite.launch._read_codex_rollout_record).
    sessions_dir = codex_home / "sessions" / "2026" / "08" / "05"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rollout = sessions_dir / f"rollout-2026-08-05T00-00-00-{session_id}.jsonl"
    lines = [
        json.dumps({"type": "session_meta", "payload": {"session_id": session_id, "model_provider": provider}}),
        json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort}}),
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": final_message}],
            },
        }),
    ]
    rollout.write_text("\n".join(lines) + "\n")


def _reviewer_message(pr: int = PR, head: str = HEAD) -> str:
    # A code-reviewer prose verdict message that binds this exact PR and reviewed head.
    return (
        f"Code review of PR {pr} at head {head}.\n"
        f"verdict: clear -- the committed red and green hold at this exact head.\n"
    )


def _verdict_args(**overrides) -> argparse.Namespace:
    base = dict(
        repo="/tmp/repo", repo_slug=SLUG, pr=PR, review_type="code",
        verdict="clear", head=HEAD, receipt="session:reviewer",
        bound_input=[], finding=[], conversation_log_reference=[],
        conversation_cutoff="", reviewer_session_id=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _extract_body(argv: list[str]) -> str:
    for token in argv:
        if isinstance(token, str) and token.startswith("body="):
            return token[len("body="):]
    return ""


class FakeGh:
    # Minimal gh substitute for run_json: reports the PR head as the declared head
    # and echoes any posted comment body back on readback, so a publish with no
    # gate rejection SUCCEEDS. This lets a provenance rejection be observed crisply
    # as the ONLY reason a valid-head publish fails.
    def __init__(self, head: str = HEAD):
        self.head = head
        self.posted_body = ""

    def __call__(self, argv: list[str]) -> dict:
        if "view" in argv:
            return {"headRefOid": self.head}
        if "--paginate" in argv:
            return []
        if "POST" in argv or "PATCH" in argv:
            self.posted_body = _extract_body(argv)
            return {"id": 7}
        return {"body": self.posted_body, "html_url": "https://github.com/x/comment/7"}


class VerdictProvenanceParserTest(unittest.TestCase):
    def _parse(self, tokens: list[str]) -> str | None:
        parser = MODULE.parser()
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                parser.parse_args(tokens)
        except SystemExit:
            return err.getvalue()
        return None

    def test_review_type_choices_include_qa(self) -> None:
        # GH-65 item 3b: verdict-publish --review-type must accept qa.
        rejection = self._parse([
            "verdict-publish", "--repo", "/tmp/r", "--repo-slug", SLUG,
            "--pr", str(PR), "--review-type", "qa", "--verdict", "clear",
            "--head", HEAD, "--receipt", "r", "--reviewer-session-id", SESSION,
        ])
        self.assertIsNone(rejection, msg=f"qa review-type rejected: {rejection}")

    def test_reviewer_session_id_flag_exists(self) -> None:
        # GH-65 item 3b: verdict-publish accepts a reviewer rollout provenance flag.
        rejection = self._parse([
            "verdict-publish", "--repo", "/tmp/r", "--repo-slug", SLUG,
            "--pr", str(PR), "--review-type", "code", "--verdict", "clear",
            "--head", HEAD, "--receipt", "r", "--reviewer-session-id", SESSION,
        ])
        self.assertIsNone(rejection, msg=f"--reviewer-session-id rejected: {rejection}")


class VerdictProvenanceGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_run_json = MODULE.run_json
        self._saved_codex_home = os.environ.get("CODEX_HOME")

    def tearDown(self) -> None:
        MODULE.run_json = self._saved_run_json
        if self._saved_codex_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self._saved_codex_home

    def _use_codex_home(self, tmp: Path) -> Path:
        home = tmp / "codex-home"
        (home / "sessions").mkdir(parents=True, exist_ok=True)
        os.environ["CODEX_HOME"] = str(home)
        return home

    def test_code_verdict_requires_a_reviewer_rollout_session(self) -> None:
        # GH-65 item 3b: a code verdict-publish with no reviewer rollout reference
        # fails closed (this kills the self-published verdict). The guard precedes
        # any gh call, so run_json must never be reached.
        def boom(argv):
            raise AssertionError("gh must not be called before the provenance guard")

        MODULE.run_json = boom
        with self.assertRaisesRegex(GateError, "reviewer"):
            MODULE.command_verdict(_verdict_args(review_type="code", reviewer_session_id=None))

    def test_qa_verdict_requires_a_reviewer_rollout_session(self) -> None:
        def boom(argv):
            raise AssertionError("gh must not be called before the provenance guard")

        MODULE.run_json = boom
        with self.assertRaisesRegex(GateError, "reviewer"):
            MODULE.command_verdict(_verdict_args(review_type="qa", reviewer_session_id=""))

    def test_code_verdict_fails_closed_without_a_resolvable_rollout_at_head(self) -> None:
        # A reviewer session id that resolves to NO rollout record fails closed,
        # even though the PR head matches: a self-authored verdict with a fabricated
        # session id can never publish (path-C near-miss).
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            self._use_codex_home(Path(raw))
            MODULE.run_json = FakeGh(head=HEAD)
            with self.assertRaises(GateError):
                MODULE.command_verdict(
                    _verdict_args(review_type="code", reviewer_session_id="no-such-session")
                )

    def test_code_verdict_publishes_with_a_genuine_reviewer_rollout(self) -> None:
        # A genuine code-reviewer relay rollout binding this exact PR and head at the
        # canonical reviewer identity satisfies the provenance gate and publishes.
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT,
                final_message=_reviewer_message(),
            )
            MODULE.run_json = FakeGh(head=HEAD)
            out = MODULE.command_verdict(
                _verdict_args(review_type="code", reviewer_session_id=SESSION)
            )
            self.assertEqual(out["head"], HEAD)
            self.assertEqual(out["verdict"], "clear")

    def test_code_verdict_rejects_a_rollout_not_naming_the_reviewed_head(self) -> None:
        # A real reviewer rollout that reviewed a DIFFERENT head cannot back a
        # verdict at THIS head: the rollout message must name the reviewed head.
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT,
                final_message=_reviewer_message(head="e" * 40),
            )
            MODULE.run_json = FakeGh(head=HEAD)
            with self.assertRaises(GateError):
                MODULE.command_verdict(
                    _verdict_args(review_type="code", reviewer_session_id=SESSION)
                )

    def test_code_verdict_rejects_wrong_identity_rollout(self) -> None:
        # A rollout under a non-canonical (weaker) model cannot self-attest: the
        # readback verifies like-with-like against the canonical reviewer runtime.
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model="gpt-4.1-mini", effort=REVIEWER_EFFORT,
                final_message=_reviewer_message(),
            )
            MODULE.run_json = FakeGh(head=HEAD)
            with self.assertRaises(GateError):
                MODULE.command_verdict(
                    _verdict_args(review_type="code", reviewer_session_id=SESSION)
                )

    def test_shaping_verdict_publish_needs_no_reviewer_session(self) -> None:
        # Shaping verdict provenance is the separate journal path; a shaping
        # verdict-publish still publishes without a reviewer rollout session, so the
        # new code/qa gate does not regress shaping.
        MODULE.run_json = FakeGh(head=HEAD)
        out = MODULE.command_verdict(_verdict_args(
            review_type="shaping", verdict="clear",
            conversation_log_reference=["session.jsonl:1-10"],
            conversation_cutoff="session.jsonl:10",
            reviewer_session_id=None,
        ))
        self.assertEqual(out["verdict"], "clear")


if __name__ == "__main__":
    unittest.main()
