from __future__ import annotations

import argparse
import contextlib
import hashlib
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


def _reviewer_block(
    verdict: str = "clear", head: str = HEAD, findings: list[str] | None = None,
    review_type: str = "code",
) -> str:
    # The reviewer's OWN structured verdict, the same canonical octo-lite-verdict
    # marker/TOML octo_lite.runtime.verdict_body emits, carried verbatim in the
    # reviewer relay's final rollout message. verdict-publish parses THIS
    # authoritative block, so the published comment IS the reviewer's own verdict
    # (its verdict, head, and findings), never a caller re-authoring.
    return MODULE.verdict_body(review_type, verdict, head, [], findings or [], "reviewer-own-receipt")


def _reviewer_message(
    pr: int = PR, head: str = HEAD, verdict: str = "clear", findings: list[str] | None = None,
) -> str:
    # A code-reviewer verdict message that names this PR and reviewed head in prose
    # AND carries the reviewer's authoritative octo-lite-verdict block that
    # verdict-publish binds the published verdict semantics to.
    return (
        f"Code review of PR {pr} at head {head}.\n"
        f"verdict: {verdict} -- the committed red and green hold at this exact head.\n"
        + _reviewer_block(verdict=verdict, head=head, findings=findings)
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

    def test_blocking_reviewer_rollout_cannot_authorize_a_clear_publish(self) -> None:
        # GH-65 codex finding 1 (hole 1): a BLOCKING reviewer rollout can never back
        # a --verdict clear publish. The published verdict binds to the reviewer's
        # OWN asserted verdict in its authoritative octo-lite-verdict block, so
        # blocking-as-clear is rejected fail-closed even though the head matches.
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT,
                final_message=_reviewer_message(verdict="blocking"),
            )
            gh = FakeGh(head=HEAD)
            MODULE.run_json = gh
            with self.assertRaises(GateError):
                MODULE.command_verdict(
                    _verdict_args(review_type="code", verdict="clear", reviewer_session_id=SESSION)
                )
            self.assertEqual(gh.posted_body, "", "no verdict comment may be published on a mismatch")

    def test_cross_target_mention_rollout_is_rejected(self) -> None:
        # GH-65 codex finding 1 (hole 2): a rollout that REVIEWED a DIFFERENT head
        # but merely MENTIONS the requested PR/head as prior context is rejected. The
        # authoritative reviewed head is the reviewer's own verdict block head, not a
        # prose mention, so a different-target verdict cannot advance this head.
        import tempfile

        other = "e" * 40
        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            message = (
                f"Prior context: this follows the earlier review of PR {PR} at head {HEAD}.\n"
                + _reviewer_message(head=other)
            )
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT,
                final_message=message,
            )
            gh = FakeGh(head=HEAD)
            MODULE.run_json = gh
            with self.assertRaises(GateError):
                MODULE.command_verdict(
                    _verdict_args(review_type="code", head=HEAD, reviewer_session_id=SESSION)
                )
            self.assertEqual(gh.posted_body, "", "a cross-target mention may not publish")

    def test_published_verdict_carries_verified_session_and_digest_not_caller_receipt(self) -> None:
        # GH-65 codex finding 2 (hole 3): the durable published verdict body carries
        # the VERIFIED reviewer session id and rollout digest as its receipt, never a
        # caller-supplied --receipt. Readback proves the persisted provenance is the
        # verified rollout, not caller-authored.
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            payload = _reviewer_message()
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT, final_message=payload,
            )
            gh = FakeGh(head=HEAD)
            MODULE.run_json = gh
            MODULE.command_verdict(
                _verdict_args(
                    review_type="code", reviewer_session_id=SESSION,
                    receipt="caller-authored-receipt",
                )
            )
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            self.assertIn(SESSION, gh.posted_body, "published body must carry the verified session id")
            self.assertIn(digest, gh.posted_body, "published body must carry the verified rollout digest")
            self.assertNotIn(
                "caller-authored-receipt", gh.posted_body,
                "the caller --receipt must never reach the durable verdict body",
            )

    def test_published_findings_are_the_reviewers_not_caller_authored(self) -> None:
        # GH-65 codex finding 1: the published findings are the reviewer's OWN, parsed
        # from its authoritative verdict block, never the caller's --finding values.
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            payload = _reviewer_message(findings=["reviewer-observed-nit"])
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT, final_message=payload,
            )
            gh = FakeGh(head=HEAD)
            MODULE.run_json = gh
            MODULE.command_verdict(
                _verdict_args(
                    review_type="code", reviewer_session_id=SESSION,
                    finding=["caller-fabricated-finding"],
                )
            )
            self.assertIn("reviewer-observed-nit", gh.posted_body)
            self.assertNotIn("caller-fabricated-finding", gh.posted_body)

    def test_reviewer_verdict_return_carries_the_reviewers_findings(self) -> None:
        # GH-65 RE-review finding A: verdict-publish RETURNS the verified verdict,
        # head, AND findings it DERIVED from the reviewer's own rollout block, so the
        # host loop binds the whole advancement decision (verdict + head + fix
        # findings) to ONE verified source, never the separate LLM binder. A blocking
        # reviewer rollout returns its own findings for the fix route.
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT,
                final_message=_reviewer_message(verdict="blocking", findings=["reviewer-observed-defect"]),
            )
            MODULE.run_json = FakeGh(head=HEAD)
            out = MODULE.command_verdict(
                _verdict_args(review_type="code", verdict="blocking", reviewer_session_id=SESSION)
            )
            self.assertEqual(out["verdict"], "blocking")
            self.assertEqual(out["head"], HEAD)
            self.assertEqual(out["findings"], ["reviewer-observed-defect"])

    def test_earlier_example_block_cannot_publish_clear_over_a_final_blocking_block(self) -> None:
        # GH-65 finding A2: a legitimate BLOCKING review that quotes an earlier CLEAR
        # block as an EXAMPLE and ends with the authoritative BLOCKING block must never
        # publish CLEAR. The parser splits on the FIRST marker and takes the FIRST
        # toml fence, so today the earlier clear example wins and the final blocking
        # verdict is silently discarded. The authoritative verdict is the SINGLE final
        # block; a message carrying more than one octo-lite-verdict block fails CLOSED.
        import tempfile

        clear_example = MODULE.verdict_body("code", "clear", HEAD, [], [], "example-receipt")
        final_blocking = MODULE.verdict_body(
            "code", "blocking", HEAD, [], ["reviewer-observed-defect"], "reviewer-own-receipt",
        )
        message = (
            f"Code review of PR {PR} at head {HEAD}.\n"
            "For reference a clear verdict block looks like this example:\n"
            + clear_example
            + "\nThe AUTHORITATIVE verdict for THIS review at that head is:\n"
            + final_blocking
        )
        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT, final_message=message,
            )
            gh = FakeGh(head=HEAD)
            MODULE.run_json = gh
            with self.assertRaises(GateError):
                # verdict=None mirrors the host loop, which omits --verdict and binds
                # the published verdict to the reviewer's OWN authoritative block.
                MODULE.command_verdict(
                    _verdict_args(review_type="code", verdict=None, reviewer_session_id=SESSION)
                )
            self.assertEqual(gh.posted_body, "", "an earlier example block may never publish a clear verdict")

    def test_trailing_content_after_the_verdict_block_fails_closed(self) -> None:
        # GH-65 finding A2: the authoritative octo-lite-verdict block must be the FINAL
        # non-whitespace content of the reviewer message. A single block followed by
        # any trailing prose fails CLOSED rather than being accepted as authoritative.
        import tempfile

        message = _reviewer_message(verdict="blocking", findings=["reviewer-observed-defect"]) + (
            "\n\nPS: please disregard the formatting note above."
        )
        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT, final_message=message,
            )
            gh = FakeGh(head=HEAD)
            MODULE.run_json = gh
            with self.assertRaises(GateError):
                MODULE.command_verdict(
                    _verdict_args(review_type="code", verdict=None, reviewer_session_id=SESSION)
                )
            self.assertEqual(gh.posted_body, "", "a non-final verdict block may never publish")

    def test_qa_verdict_with_satisfied_vocab_fails_closed_deferred_to_76(self) -> None:
        # GH-65 RE-review finding C: QA verdict publication is deferred to issue #76.
        # The qa reviewer grades with a satisfied/blocking vocabulary, but the
        # reviewer-rollout block parser (like verdict_body) accepts ONLY
        # clear/blocking, so a latent standalone qa verdict-publish over a satisfied
        # block fails CLOSED and posts nothing. No qa verdict publishes in-loop, so no
        # spec claim asserts one does; the vocabulary reconciliation lands with #76.
        import tempfile

        satisfied_block = (
            "<!-- octo-lite-verdict:qa -->\n"
            "```toml\n"
            'review_type = "qa"\n'
            'verdict = "satisfied"\n'
            f'head = "{HEAD}"\n'
            "findings = []\n"
            "```"
        )
        message = f"QA review of PR {PR} at head {HEAD}.\n" + satisfied_block
        with tempfile.TemporaryDirectory() as raw:
            home = self._use_codex_home(Path(raw))
            _write_codex_rollout(
                home, SESSION, model=REVIEWER_MODEL, effort=REVIEWER_EFFORT, final_message=message,
            )
            gh = FakeGh(head=HEAD)
            MODULE.run_json = gh
            with self.assertRaises(GateError):
                MODULE.command_verdict(
                    _verdict_args(review_type="qa", verdict="satisfied", reviewer_session_id=SESSION)
                )
            self.assertEqual(gh.posted_body, "", "a satisfied-vocab qa verdict may never publish")

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
