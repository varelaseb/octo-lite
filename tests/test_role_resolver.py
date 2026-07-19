from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "workflows" / "lib" / "role_resolver.py"
ROLES = {
    "meta-operator",
    "orchestrator",
    "shaping-reviewer",
    "implementer",
    "code-reviewer",
    "qa-capture",
    "qa-reviewer",
    "reconciler",
}


def load_module():
    spec = importlib.util.spec_from_file_location("role_resolver", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RoleResolverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = load_module()

    def test_roster_and_exact_runtime_pins_match_spec(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        self.assertEqual(set(registry.roles), ROLES)
        expected = {
            "meta-operator": ("anthropic", "claude-fable-5", "xhigh", "auto", "persistent", "default"),
            "orchestrator": ("anthropic", "claude-opus-4-8[1m]", "high", "auto", "persistent", "default"),
            "shaping-reviewer": ("openai", "gpt-5.6-sol", "xhigh", "never", "fresh", "fast"),
            "implementer": ("anthropic", "claude-sonnet-5", "xhigh", "auto", "fresh", "default"),
            "code-reviewer": ("openai", "gpt-5.6-sol", "high", "never", "fresh", "default"),
            "qa-capture": ("anthropic", "claude-sonnet-5", "high", "auto", "fresh", "default"),
            "qa-reviewer": ("openai", "gpt-5.6-sol", "high", "never", "fresh", "fast"),
            "reconciler": ("anthropic", "claude-sonnet-5", "high", "auto", "fresh", "default"),
        }
        actual = {
            name: (
                role.provider,
                role.model,
                role.effort,
                role.mode,
                role.session,
                role.service_tier,
            )
            for name, role in registry.roles.items()
        }
        self.assertEqual(actual, expected)
        self.assertTrue(registry.concise)
        self.assertTrue(registry.forbid_unicode_dashes)

    def test_contracts_are_canonical_concise_and_machine_free(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        forbidden = ("claude-fable", "claude-opus", "claude-sonnet", "gpt-5.6", "xhigh", "service tier")
        for role in registry.roles.values():
            text = (ROOT / role.contract).read_text()
            self.assertNotIn("\u2013", text, role.name)
            self.assertNotIn("\u2014", text, role.name)
            self.assertLessEqual(len(text.splitlines()), 44, role.name)
            for token in forbidden:
                self.assertNotIn(token, text.lower(), f"{role.name}: {token}")

    def test_required_and_matched_conditional_skills_resolve(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        base = self.resolver.resolve_role(registry, "implementer", set())
        ui = self.resolver.resolve_role(registry, "implementer", {"ui", "typescript", "pnpm"})
        self.assertEqual(base.skills, ("tdd", "commit", "octo-lite-github", "push"))
        self.assertEqual(
            ui.skills,
            (
                "tdd",
                "commit",
                "octo-lite-github",
                "push",
                "frontend-design",
                "pnpm",
                "typescript",
            ),
        )

    def test_orchestrator_resolves_shaping_skills_only_in_shaping_mode(self) -> None:
        # There is no separately persistent issue-shaper role or tab: the one issue
        # orchestrator loads the shaping skills conditionally, in its own session.
        registry = self.resolver.load_registry(ROOT)
        base = self.resolver.resolve_role(registry, "orchestrator", set())
        shaping = self.resolver.resolve_role(registry, "orchestrator", {"shaping"})
        delivery = self.resolver.resolve_role(registry, "orchestrator", {"delivery"})
        self.assertEqual(base.skills, ("herdr-comms",))
        self.assertEqual(
            shaping.skills,
            ("herdr-comms", "octo-lite-issue-shaper", "grill-with-docs", "octo-lite-github"),
        )
        self.assertEqual(delivery.skills, ("herdr-comms", "octo-lite-loop"))

    # The following three checks are structural wiring only: they prove the required
    # keyword text is present in the canonical contract a session bootstraps from.
    # They are not, and never substitute for, judged evidence that a model session
    # actually behaves per that text; see the prompt-TDD receipts for that judgment.
    def test_persistent_role_contracts_contain_bootstrap_ack_wiring_text(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        for name in ("meta-operator", "orchestrator"):
            text = (ROOT / registry.roles[name].contract).read_text()
            self.assertIn("BOOTSTRAP_ACK", text, name)
            self.assertIn("before mutation", text, name)

    def test_meta_operator_contract_text_contains_direct_marker_removal_wiring(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        text = (ROOT / registry.roles["meta-operator"].contract).read_text()
        self.assertIn("Own compact Herdr labels", text)
        self.assertIn("Remove `🎤` as soon as an Opus can work autonomously", text)

    def test_orchestrator_contract_text_contains_fresh_probe_wiring(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        text = (ROOT / registry.roles["orchestrator"].contract).read_text()
        self.assertIn("fresh exact-model probe", text)
        self.assertIn("Never infer fleet outage from one session", text)

    def test_generated_adapters_are_exact_and_not_raw_spawn_entrypoints(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        errors = self.resolver.check_adapters(ROOT, registry)
        self.assertEqual(errors, [])
        for name in ROLES:
            claude = (ROOT / "agents" / f"{name}.md").read_text()
            codex_raw = (ROOT / "agents" / f"{name}.toml").read_text()
            codex = tomllib.loads(codex_raw)
            role = registry.roles[name]
            resolved = self.resolver.resolve_role(registry, name)
            self.assertIn("generated: true", claude)
            self.assertIn("raw_spawn: prohibited", claude)
            self.assertIn(f"provider: {role.provider}", claude)
            self.assertIn(f'model: "{role.model}"', claude)
            self.assertIn(f"effort: {role.effort}", claude)
            self.assertIn(f"permissionMode: {role.mode}", claude)
            self.assertIn(f"contractBlob: {resolved.contract_blob}", claude)
            # Codex CLI 0.144.6 only supports the documented top-level custom-agent
            # schema. Unsupported [adapter]/[launch]/[contract] tables make Codex
            # reject the whole file, so only that schema may appear here.
            self.assertIn(
                "# Generated by workflows/lib/role_resolver.py. Resolve before launch. Never edit or spawn raw.",
                codex_raw.splitlines()[0],
            )
            self.assertEqual(set(codex) - {"skills"}, {"name", "description", "model", "model_reasoning_effort", "developer_instructions"})
            self.assertEqual(codex["name"], role.name)
            self.assertEqual(codex["description"], self.resolver._description(resolved.contract_text))
            self.assertEqual(codex["model"], role.model)
            self.assertEqual(codex["model_reasoning_effort"], role.effort)
            self.assertEqual(codex["developer_instructions"], resolved.contract_text)
            skills_config = codex.get("skills", {}).get("config", [])
            self.assertEqual({entry["path"] for entry in skills_config}, {f"skills/{skill}/SKILL.md" for skill in resolved.skills})
            self.assertTrue(all(entry["enabled"] is True for entry in skills_config))
            self.assertTrue(all(set(entry) == {"path", "enabled"} for entry in skills_config))

    def test_codex_adapters_have_no_unsupported_tables(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        for name in ROLES:
            codex = tomllib.loads((ROOT / "agents" / f"{name}.toml").read_text())
            for forbidden in ("adapter", "launch", "contract"):
                self.assertNotIn(forbidden, codex, f"{name}: unsupported table {forbidden!r} present")

    def test_codex_cli_loads_generated_adapters_without_schema_errors(self) -> None:
        codex_bin = shutil.which("codex")
        if not codex_bin:
            self.skipTest("codex CLI not installed")
        registry = self.resolver.load_registry(ROOT)
        # CODEX_HOME must not sit directly under /tmp: codex then refuses to
        # create PATH aliases and prints a warning line before the JSON body.
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
            codex_home = Path(tmp)
            (codex_home / "agents").mkdir()
            (codex_home / "config.toml").write_text('model = "gpt-5.6-sol"\n')
            for name in registry.roles:
                shutil.copy(ROOT / "agents" / f"{name}.toml", codex_home / "agents" / f"{name}.toml")
            result = subprocess.run(
                [codex_bin, "doctor", "--json"],
                env={**os.environ, "CODEX_HOME": str(codex_home)},
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertTrue(result.stdout.strip(), result.stderr)
            report = json.loads(result.stdout)
        details = report["checks"]["config.load"]["details"]
        self.assertEqual(details["config.toml parse"], "ok")
        warning_count = int(details.get("startup warnings", "0"))
        self.assertEqual(warning_count, 0, details.get("startup warning"))

    def test_qa_reviewer_resolves_an_exact_empty_skill_set(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        resolved = self.resolver.resolve_role(registry, "qa-reviewer", set())
        self.assertEqual(resolved.skills, ())
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Test"], check=True)
            (target / "AGENTS.md").write_text("# Target\n")
            subprocess.run(["git", "-C", str(target), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "target"], check=True)
            receipt = self.resolver.build_launch_receipt(
                ROOT,
                resolved,
                spawn_id="qa-dry-run-1",
                parent="issue-orchestrator",
                reply_route="herdr:issue-orchestrator",
                repo=target,
                worktree=target,
                execution_location="remote",
                operator_loopback=False,
                review_delivery="reachable_url_required",
            )
        self.assertEqual(receipt["skills"]["resolved"], [])
        self.assertEqual(receipt["skills"]["paths"], [])
        self.assertEqual(receipt["skills"]["blobs"], [])

    def test_dry_run_receipt_binds_effective_launch_inputs(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Test"], check=True)
            (target / "AGENTS.md").write_text("# Target\n")
            subprocess.run(["git", "-C", str(target), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "target"], check=True)
            resolved = self.resolver.resolve_role(registry, "implementer", {"python"})
            receipt = self.resolver.build_launch_receipt(
                ROOT,
                resolved,
                spawn_id="dry-run-1",
                parent="test-parent",
                reply_route="test-route",
                repo=target,
                worktree=target,
                execution_location="remote",
                operator_loopback=False,
                review_delivery="reachable_url_required",
            )
            acknowledgment = self.resolver.dry_run_child(resolved, receipt)
            parsed = tomllib.loads(self.resolver.render_receipt(receipt))
        self.assertEqual(parsed["role"]["name"], "implementer")
        self.assertEqual(parsed["runtime"]["model"], "claude-sonnet-5")
        self.assertEqual(parsed["runtime"]["effort"], "xhigh")
        self.assertEqual(parsed["runtime"]["mode"], "auto")
        self.assertEqual(parsed["skills"]["resolved"], ["tdd", "commit", "octo-lite-github", "push", "python"])
        self.assertEqual(
            parsed["skills"]["paths"],
            [f"skills/{name}/SKILL.md" for name in parsed["skills"]["resolved"]],
        )
        self.assertEqual(len(parsed["skills"]["blobs"]), len(parsed["skills"]["resolved"]))
        for blob in parsed["skills"]["blobs"]:
            self.assertRegex(blob, r"^[0-9a-f]{40,64}$")
        self.assertRegex(parsed["role"]["contract_blob"], r"^[0-9a-f]{40,64}$")
        self.assertRegex(parsed["role"]["mapping_revision"], r"^[0-9a-f]{40,64}$")
        self.assertRegex(parsed["workspace"]["instructions_blob"], r"^[0-9a-f]{40,64}$")
        self.assertRegex(parsed["workspace"]["starting_head"], r"^[0-9a-f]{40}$")
        self.assertEqual(parsed["access"]["execution_location"], "remote")
        self.assertEqual(parsed["access"]["operator_loopback"], False)
        self.assertEqual(parsed["bootstrap"]["verified"], False)
        self.assertEqual(parsed["bootstrap"]["provider_session_id"], "")
        self.assertEqual(acknowledgment["spawn_id"], "dry-run-1")
        self.assertEqual(acknowledgment["role"], "implementer")
        self.assertEqual(acknowledgment["contract_blob"], parsed["role"]["contract_blob"])
        self.assertEqual(acknowledgment["mapping_revision"], parsed["role"]["mapping_revision"])
        self.assertEqual(acknowledgment["model"], "claude-sonnet-5")
        self.assertEqual(acknowledgment["mode"], "auto")
        self.assertEqual(acknowledgment["skills"], parsed["skills"]["resolved"])
        self.assertEqual(acknowledgment["skill_blobs"], parsed["skills"]["blobs"])
        self.assertEqual(acknowledgment["instructions_blob"], parsed["workspace"]["instructions_blob"])
        self.assertEqual(acknowledgment["starting_head"], parsed["workspace"]["starting_head"])
        self.resolver.verify_bootstrap_ack(receipt, acknowledgment)
        bad_ack = dict(acknowledgment, model="rolling-alias")
        with self.assertRaisesRegex(ValueError, "bootstrap acknowledgment mismatch"):
            self.resolver.verify_bootstrap_ack(receipt, bad_ack)

    def test_registry_rejects_dash_style_and_contract_path_escape(self) -> None:
        registry = self.resolver.load_registry(ROOT)
        bad = (ROOT / "roles" / "implementer.md").read_text().replace("# Implementer", "# Implementer\nBad \u2014 dash", 1)
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            temp_root = Path(tmp)
            (temp_root / "roles").mkdir()
            (temp_root / "roles.toml").write_text((ROOT / "roles.toml").read_text())
            for role in registry.roles.values():
                source = ROOT / role.contract
                target = temp_root / role.contract
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(bad if role.name == "implementer" else source.read_text())
            with self.assertRaisesRegex(ValueError, "unicode dash"):
                self.resolver.load_registry(temp_root)


if __name__ == "__main__":
    unittest.main()
