from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "scripts/octo-control"
SLUG = "org/repo"
PUBLISHER = "octo-lite-bot"


# TUR-447 cycle1 pass4 F5 (gpt-5.6-sol review, F5 NOT RESOLVED + high finding).
# Three anti-forgery closures on Shaped-transition authority (scripts/octo-control):
#   1. --repo dual-meaning is split: --repo is the LOCAL PATH for git -C, the
#      canonical owner/repo gh identity is the separate --repo-slug, so git -C
#      and gh api both work and the cross-surface binding compares ONE canonical
#      slug identity (delivery-lifecycle shaping-operator-approval-binding).
#   2. The operator-intent record is unforgeable: verification fetches the exact
#      bound live PR comment id and requires its AUTHOR login to equal the
#      trusted command publisher, so a fabricated TOML plus a comment self-posted
#      under any other identity is rejected (operator-control
#      supervision-operator-gate-no-hashes; role-runtime launch-shaping-authority).
#   3. The shaping-verdict journal is not self-attesting: its provenance codex
#      session id must resolve to an ACTUAL codex rollout record under
#      CODEX_HOME/sessions proving provider=openai + the declared model/effort +
#      that the verdict payload/sha256 came from that rollout, reusing the
#      launch.py rollout reader / verify_relay_verbatim discipline; an arbitrary
#      session id or hash with no resolvable record fails closed (role-runtime
#      launch-shaping-authority, role-openai-fail-closed).


def _load_module():
    loader = importlib.machinery.SourceFileLoader("octo_control_f5", str(CONTROL))
    spec = importlib.util.spec_from_file_location("octo_control_f5", CONTROL, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
    (repo / "seed.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


# A stateful gh fake that persists issue comments in $GH_COMMENTS and stamps
# each posted comment's author login from $GH_PUBLISHER, so a comment posted by
# a NON-trusted author can be simulated and the author-identity check exercised.
_GH_FAKE = r"""#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
store = os.environ["GH_COMMENTS"]
def load():
    return json.load(open(store)) if os.path.exists(store) and open(store).read().strip() else []
def save(items):
    json.dump(items, open(store, "w"))
def field(f):
    return next((v.split("=", 1)[1] for v in argv if v.startswith(f + "=")), None)
if argv[:2] == ["pr", "view"]:
    print(json.dumps({"headRefOid": os.environ.get("GH_HEAD", "")})); sys.exit(0)
method = argv[argv.index("--method") + 1] if "--method" in argv else None
endpoint = next(t for i, t in enumerate(argv) if i > 0 and argv[i-1] not in ("--method", "-f") and t not in ("--paginate", "--method", "-f", "api"))
if endpoint.endswith("/comments") and method in (None, "GET"):
    print(json.dumps(load())); sys.exit(0)
if endpoint.endswith("/comments") and method == "POST":
    items = load()
    new = {"id": len(items) + 1, "body": field("body"),
           "user": {"login": os.environ.get("GH_PUBLISHER", "octo-lite-bot")},
           "html_url": "u/%d" % (len(items) + 1)}
    items.append(new); save(items); print(json.dumps(new)); sys.exit(0)
if "/comments/" in endpoint and method == "PATCH":
    cid = int(endpoint.split("/")[-1]); items = load()
    for it in items:
        if it["id"] == cid:
            it["body"] = field("body"); save(items); print(json.dumps(it)); sys.exit(0)
    sys.exit(3)
if "/comments/" in endpoint and method is None:
    cid = int(endpoint.split("/")[-1])
    for it in load():
        if it["id"] == cid:
            print(json.dumps(it)); sys.exit(0)
    sys.exit(4)
sys.exit(9)
"""


def _install_gh(fake_bin: Path) -> None:
    fake_bin.mkdir(parents=True, exist_ok=True)
    gh = fake_bin / "gh"
    gh.write_text(_GH_FAKE)
    gh.chmod(0o755)


def _write_rollout(
    codex_home: Path, session_id: str, *, model: str, effort: str,
    final_message: str, provider: str = "openai",
) -> None:
    sessions = codex_home / "sessions" / "2026" / "07" / "21"
    sessions.mkdir(parents=True, exist_ok=True)
    rollout = sessions / f"rollout-2026-07-21T00-00-00-{session_id}.jsonl"
    rollout.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"session_id": session_id, "model_provider": provider}}),
        json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort}}),
        json.dumps({
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": final_message}]},
        }),
    ]) + "\n")


class IntentRecordAuthorForgeryTests(unittest.TestCase):
    # Finding 2 (blocking): a fabricated valid-head intent TOML plus a matching
    # comment posted under a NON-trusted author must be REJECTED. Body match
    # alone never suffices; the comment's own author identity is checked.

    def _env(self, base: Path, head: str, store: Path, publisher: str) -> dict:
        fake_bin = base / "bin"
        _install_gh(fake_bin)
        return dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
            GH_HEAD=head, GH_COMMENTS=str(store), GH_PUBLISHER=publisher,
        )

    def test_fabricated_record_with_matching_comment_under_untrusted_author_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = _init_repo(repo)
            stream = base / "stream"
            store = base / "comments.json"
            module = _load_module()
            recorded_at = "2026-07-21T00:00:00+00:00"
            body = module._intent_surface_body(
                repo=SLUG, pr=7, head=head, intent_ref="ruling-15", recorded_at=recorded_at,
            )
            digest = module._surface_digest(body)
            # An attacker self-posts the EXACT matching surface body, but under a
            # non-trusted author login (not the trusted command publisher).
            attacker_env = self._env(base, head, store, publisher="attacker")
            posted = subprocess.run(
                ["gh", "api", "--method", "POST",
                 f"repos/{SLUG}/issues/7/comments", "-f", f"body={body}"],
                capture_output=True, text=True, env=attacker_env,
            )
            self.assertEqual(0, posted.returncode, posted.stderr)
            comment_id = json.loads(posted.stdout)["id"]
            # A fabricated local record binds that real comment id and a correct
            # self-digest, and names the trusted publisher, but the LIVE comment
            # author is the attacker.
            stream.mkdir()
            (stream / "intent-record.toml").write_text(
                'schema_version = 1\nintent_ref = "ruling-15"\n'
                f'head = "{head}"\nrecorded_at = "{recorded_at}"\n'
                f'repo = {json.dumps(SLUG)}\npr = 7\n'
                f'surface_sha256 = "{digest}"\n'
                f'comment_id = {comment_id}\npublisher = {json.dumps(PUBLISHER)}\n'
            )
            result = subprocess.run(
                [str(CONTROL), "intent-record", "--verify",
                 "--stream-dir", str(stream), "--repo", str(repo),
                 "--repo-slug", SLUG, "--trusted-publisher", PUBLISHER],
                capture_output=True, text=True,
                env=self._env(base, head, store, publisher=PUBLISHER),
            )
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("trusted command identity", result.stderr)

    def test_command_produced_record_under_trusted_author_is_accepted(self) -> None:
        # Positive counterpart: the genuine command publishes under the trusted
        # author, so its own record verifies.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = _init_repo(repo)
            stream = base / "stream"
            store = base / "comments.json"
            env = self._env(base, head, store, publisher=PUBLISHER)
            produced = subprocess.run(
                [str(CONTROL), "intent-record", "--stream-dir", str(stream),
                 "--intent-ref", "ruling-15", "--repo", str(repo),
                 "--repo-slug", SLUG, "--pr", "7"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, produced.returncode, produced.stderr)
            result = subprocess.run(
                [str(CONTROL), "intent-record", "--verify",
                 "--stream-dir", str(stream), "--repo", str(repo),
                 "--repo-slug", SLUG, "--trusted-publisher", PUBLISHER],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(PUBLISHER, payload["publisher"])
            self.assertEqual(head, payload["head"])


class RepoSplitTests(unittest.TestCase):
    # Finding 1: the single --repo dual-meaning is impossible. git -C uses the
    # LOCAL PATH (--repo) and gh api uses the canonical owner/repo slug
    # (--repo-slug); both must work under the split. A full remote URL passed as
    # the slug normalizes to the same canonical identity the record binds.

    def _env(self, base: Path, head: str, store: Path) -> dict:
        fake_bin = base / "bin"
        _install_gh(fake_bin)
        return dict(
            os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
            GH_HEAD=head, GH_COMMENTS=str(store), GH_PUBLISHER=PUBLISHER,
        )

    def test_git_and_gh_both_work_under_the_split_and_binding_is_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"          # local filesystem path for git -C
            head = _init_repo(repo)
            stream = base / "stream"
            store = base / "comments.json"
            env = self._env(base, head, store)
            # Producer: git -C reads head from the LOCAL PATH, gh publishes under
            # the canonical slug.
            produced = subprocess.run(
                [str(CONTROL), "intent-record", "--stream-dir", str(stream),
                 "--intent-ref", "ruling-15", "--repo", str(repo),
                 "--repo-slug", SLUG, "--pr", "7"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, produced.returncode, produced.stderr)
            with (stream / "intent-record.toml").open("rb") as handle:
                import tomllib
                record = tomllib.load(handle)
            self.assertEqual(SLUG, record["repo"])  # canonical slug, not a path
            # Verify with the slug expressed as a full remote URL: it normalizes
            # to the same canonical identity, so the binding is consistent.
            result = subprocess.run(
                [str(CONTROL), "intent-record", "--verify",
                 "--stream-dir", str(stream), "--repo", str(repo),
                 "--repo-slug", f"https://github.com/{SLUG}.git",
                 "--trusted-publisher", PUBLISHER],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)

    def test_a_local_path_is_not_a_valid_repo_slug(self) -> None:
        # The dual-meaning is impossible: a filesystem path can never be the gh
        # slug, so passing one as --repo-slug is rejected as non-canonical.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            head = _init_repo(repo)
            stream = base / "stream"
            result = subprocess.run(
                [str(CONTROL), "intent-record", "--stream-dir", str(stream),
                 "--intent-ref", "ruling-15", "--repo", str(repo),
                 "--repo-slug", str(repo), "--pr", "7"],
                capture_output=True, text=True, env=self._env(base, head, base / "c.json"),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("canonical owner/repo identity", result.stderr)


class ShapingVerdictRolloutReadbackTests(unittest.TestCase):
    # Finding 3 (high): the shaping-verdict journal must not self-attest. Its
    # provenance codex session id must resolve to an actual rollout record under
    # CODEX_HOME/sessions proving provider=openai + declared model/effort + that
    # the verdict payload/sha256 came from that rollout.

    def _read(self, module, path: Path, issue: str, codex_home: Path):
        saved = dict(os.environ)
        os.environ["CODEX_HOME"] = str(codex_home)
        try:
            return module._read_shaping_verdict_journal(path, issue)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def _write_verdict(
        self, path: Path, *, head: str, session_id: str = "codex-session-1",
        model: str = "gpt-5.6-sol", effort: str = "high",
        payload: str | None = None,
    ) -> str:
        payload = payload if payload is not None else "VERDICT clear at " + head
        entry = {
            "schema_version": 1, "review_type": "shaping", "verdict": "clear",
            "issue": "TUR-1", "repo": SLUG, "pr": 7, "head": head,
            "codex_session_id": session_id, "verdict_payload": payload,
            "verdict_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "codex_model": model, "codex_effort": effort,
            "provenance": "relay-verbatim-rollout",
        }
        path.write_text(json.dumps(entry))
        return payload

    def test_verdict_with_no_resolvable_rollout_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            module = _load_module()
            head = "a" * 40
            verdict = base / "verdict.json"
            self._write_verdict(verdict, head=head, session_id="ghost-session")
            codex_home = base / "codex-home"  # no rollout file written
            codex_home.mkdir()
            with self.assertRaises(module.GateError) as ctx:
                self._read(module, verdict, "TUR-1", codex_home)
            self.assertIn("rollout readback failed", str(ctx.exception))

    def test_verdict_with_non_openai_provider_rollout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            module = _load_module()
            head = "b" * 40
            verdict = base / "verdict.json"
            payload = self._write_verdict(verdict, head=head)
            codex_home = base / "codex-home"
            _write_rollout(
                codex_home, "codex-session-1", model="gpt-5.6-sol", effort="high",
                final_message=payload, provider="anthropic",
            )
            with self.assertRaises(module.GateError) as ctx:
                self._read(module, verdict, "TUR-1", codex_home)
            self.assertIn("rollout readback failed", str(ctx.exception))

    def test_verdict_with_wrong_model_or_effort_rollout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            module = _load_module()
            head = "c" * 40
            for label, model, effort in (
                ("model", "gpt-4.1", "high"),
                ("effort", "gpt-5.6-sol", "low"),
            ):
                with self.subTest(case=label):
                    verdict = base / f"verdict-{label}.json"
                    payload = self._write_verdict(
                        verdict, head=head, model="gpt-5.6-sol", effort="high",
                    )
                    codex_home = base / f"codex-{label}"
                    _write_rollout(
                        codex_home, "codex-session-1", model=model, effort=effort,
                        final_message=payload,
                    )
                    with self.assertRaises(module.GateError) as ctx:
                        self._read(module, verdict, "TUR-1", codex_home)
                    self.assertIn("rollout readback failed", str(ctx.exception))

    def test_verdict_whose_payload_sha_does_not_match_rollout_message_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            module = _load_module()
            head = "d" * 40
            verdict = base / "verdict.json"
            self._write_verdict(verdict, head=head, payload="CLAIMED VERDICT")
            codex_home = base / "codex-home"
            # The rollout's own final message differs from the claimed payload.
            _write_rollout(
                codex_home, "codex-session-1", model="gpt-5.6-sol", effort="high",
                final_message="DIFFERENT ACTUAL MESSAGE",
            )
            with self.assertRaises(module.GateError) as ctx:
                self._read(module, verdict, "TUR-1", codex_home)
            self.assertIn("rollout readback failed", str(ctx.exception))

    def test_rollout_backed_verdict_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            module = _load_module()
            head = "e" * 40
            verdict = base / "verdict.json"
            payload = self._write_verdict(verdict, head=head)
            codex_home = base / "codex-home"
            _write_rollout(
                codex_home, "codex-session-1", model="gpt-5.6-sol", effort="high",
                final_message=payload,
            )
            entry = self._read(module, verdict, "TUR-1", codex_home)
            self.assertEqual("clear", entry["verdict"])
            self.assertEqual(head, entry["head"])

    def test_arbitrary_session_and_hash_without_provenance_fields_is_rejected(self) -> None:
        # An interim ack-echo verdict, or one lacking the rollout provenance
        # fields, carries no authority even before the readback.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            module = _load_module()
            verdict = base / "verdict.json"
            verdict.write_text(json.dumps({
                "schema_version": 1, "review_type": "shaping", "verdict": "clear",
                "issue": "TUR-1", "repo": SLUG, "pr": 7, "head": "f" * 40,
                "codex_session_id": "s", "verdict_sha256": "a" * 64,
                "provenance": "relay-verbatim-rollout",
            }))
            with self.assertRaises(module.GateError) as ctx:
                self._read(module, verdict, "TUR-1", base / "codex-home")
            self.assertIn("provenance", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
