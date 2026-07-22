from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "scripts/octo-control"

# Canonical shaping-reviewer runtime the producer/consumer derive from roles.toml.
CANONICAL_MODEL = "gpt-5.6-sol"
CANONICAL_EFFORT = "xhigh"

ISSUE = "TUR-447"
SLUG = "turbohq/octo-lite"
PR = 6
HEAD = "a" * 40
SESSION = "sess-shaping-0001"


def _write_codex_rollout(
    codex_home: Path, session_id: str, *, model: str, effort: str,
    final_message: str, provider: str = "openai",
) -> None:
    # Mirror the codex rollout record shape (octo_lite.launch._read_codex_rollout_record).
    sessions_dir = codex_home / "sessions" / "2026" / "07" / "21"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rollout = sessions_dir / f"rollout-2026-07-21T00-00-00-{session_id}.jsonl"
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


def _clear_verdict_payload(issue: str = ISSUE, pr: int = PR, head: str = HEAD) -> str:
    # A genuine clear shaping-reviewer prose verdict binding this exact
    # issue/PR/head, matching _verify_rollout_message_binds_verdict.
    return (
        f"Shaping review of {issue} on PR {pr} at head {head}.\n"
        f"verdict: clear -- specs, stories, and TDD contract agree at this exact head.\n"
    )


def _run(argv: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CONTROL), *argv],
        env=env, capture_output=True, text=True,
    )


class ShapingVerdictJournalProducerTest(unittest.TestCase):
    def _env(self, codex_home: Path) -> dict:
        env = dict(os.environ)
        env["CODEX_HOME"] = str(codex_home)
        return env

    def test_red_producer_subcommand_exists(self) -> None:
        # RED (proving the producer was missing before): the octo-control CLI
        # must expose the shaping-verdict-journal-write producer subcommand. On
        # the pre-D4 tree this subcommand does not exist and argparse rejects it.
        result = _run(["shaping-verdict-journal-write", "--help"], dict(os.environ))
        self.assertEqual(
            result.returncode, 0,
            msg=f"producer subcommand missing: stderr={result.stderr}",
        )

    def test_round_trip_producer_then_consumer(self) -> None:
        # CONSUMER CONSISTENCY: a journal this producer writes must pass the
        # consumer Unit J uses. Here we write via the producer and prove the
        # producer's own consumer round-trip (it reads back through
        # _read_shaping_verdict_journal) succeeds with the exact required shape.
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            codex_home = base / "codex-home"
            payload = _clear_verdict_payload()
            _write_codex_rollout(
                codex_home, SESSION,
                model=CANONICAL_MODEL, effort=CANONICAL_EFFORT, final_message=payload,
            )
            journal = base / "shaping-verdict.json"
            result = _run(
                [
                    "shaping-verdict-journal-write",
                    "--journal", str(journal),
                    "--issue", ISSUE,
                    "--repo-slug", SLUG,
                    "--pr", str(PR),
                    "--head", HEAD,
                    "--codex-session-id", SESSION,
                ],
                self._env(codex_home),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            out = json.loads(result.stdout)
            self.assertEqual(out["provenance"], "relay-verbatim-rollout")
            self.assertEqual(out["codex_model"], CANONICAL_MODEL)
            self.assertEqual(out["codex_effort"], CANONICAL_EFFORT)
            self.assertEqual(out["issue"], ISSUE)
            self.assertEqual(out["pr"], PR)
            self.assertEqual(out["head"], HEAD)
            self.assertEqual(out["verdict_sha256"], hashlib.sha256(payload.encode()).hexdigest())

            # The persisted journal on disk carries exactly the consumer-required
            # fields, verbatim from the rollout record (not caller self-report).
            entry = json.loads(journal.read_text())
            self.assertEqual(entry["schema_version"], 1)
            self.assertEqual(entry["review_type"], "shaping")
            self.assertEqual(entry["verdict"], "clear")
            self.assertEqual(entry["verdict_payload"], payload)
            self.assertEqual(entry["provenance"], "relay-verbatim-rollout")
            self.assertTrue(set(entry).issuperset({
                "codex_session_id", "verdict_sha256", "codex_model",
                "codex_effort", "verdict_payload", "repo", "pr", "head", "issue",
            }))

    def test_producer_rejects_missing_rollout_fail_closed(self) -> None:
        # No rollout record for the claimed session id: the producer must fail
        # closed and never persist a journal (caller self-report is not a source).
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            codex_home = base / "codex-home"
            (codex_home / "sessions").mkdir(parents=True, exist_ok=True)
            journal = base / "shaping-verdict.json"
            result = _run(
                [
                    "shaping-verdict-journal-write",
                    "--journal", str(journal),
                    "--issue", ISSUE,
                    "--repo-slug", SLUG,
                    "--pr", str(PR),
                    "--head", HEAD,
                    "--codex-session-id", "no-such-session",
                ],
                self._env(codex_home),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(journal.exists())

    def test_producer_rejects_wrong_identity_rollout(self) -> None:
        # A rollout under a non-canonical model must be rejected fail-closed: the
        # producer verifies like-with-like against the canonical roles.toml
        # shaping-reviewer runtime, so a weaker-model rollout cannot self-attest.
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            codex_home = base / "codex-home"
            payload = _clear_verdict_payload()
            _write_codex_rollout(
                codex_home, SESSION,
                model="gpt-weak", effort=CANONICAL_EFFORT, final_message=payload,
            )
            journal = base / "shaping-verdict.json"
            result = _run(
                [
                    "shaping-verdict-journal-write",
                    "--journal", str(journal),
                    "--issue", ISSUE,
                    "--repo-slug", SLUG,
                    "--pr", str(PR),
                    "--head", HEAD,
                    "--codex-session-id", SESSION,
                ],
                self._env(codex_home),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(journal.exists())

    def test_producer_rejects_non_binding_rollout(self) -> None:
        # A real, canonical-identity rollout that clears a DIFFERENT issue must
        # not back a clear journal for THIS issue: the producer applies the same
        # rollout-message binding Unit J requires before persisting.
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            codex_home = base / "codex-home"
            payload = _clear_verdict_payload(issue="TUR-999")
            _write_codex_rollout(
                codex_home, SESSION,
                model=CANONICAL_MODEL, effort=CANONICAL_EFFORT, final_message=payload,
            )
            journal = base / "shaping-verdict.json"
            result = _run(
                [
                    "shaping-verdict-journal-write",
                    "--journal", str(journal),
                    "--issue", ISSUE,
                    "--repo-slug", SLUG,
                    "--pr", str(PR),
                    "--head", HEAD,
                    "--codex-session-id", SESSION,
                ],
                self._env(codex_home),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(journal.exists())


if __name__ == "__main__":
    unittest.main()
