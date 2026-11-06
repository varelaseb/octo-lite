"""install-octo-lite registers the command-time hook in each agent CLI's hook
settings beside other tools' hooks, verifies it, and undoes only its own.
Spec: spec/domains/install.spec.html#install-hooks; criteria
#acceptance-hooks-register, -codex-trust, -check, -undo. The other tool's
entries are shaped as this box's moshi-hook entries are."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-octo-lite"
# skillfile stubbed unreachable: installer runs never fetch.
OFFLINE = f"{ROOT / 'tests' / 'offline-bin'}:{os.environ['PATH']}"


def problems(run):
    """The problems a run names, but Stageshow's: offline, it is never fetched."""
    return [line for line in run.stderr.splitlines()
            if "; fix: " in line and not line.startswith("Stageshow not installed")]

MOSHI = "'/opt/moshi/bin/moshi-hook' {}-hook"
CLAUDE_SETTINGS = {
    "model": "opus",
    "permissions": {"allow": ["Bash(git status)"]},
    "hooks": {
        "Notification": [{"matcher": "permission_prompt", "hooks": [
            {"type": "command", "command": MOSHI.format("claude"), "async": True}]}],
        "PostToolUse": [{"matcher": "AskUserQuestion", "hooks": [
            {"type": "command", "command": MOSHI.format("claude"), "async": True}]}],
        "PreToolUse": [{"matcher": "ExitPlanMode", "hooks": [
            {"type": "command", "command": MOSHI.format("claude"), "async": True}]}],
    },
}
CODEX_HOOKS = {"hooks": {
    event: [{"hooks": [{"command": MOSHI.format("codex"), "type": "command"}]}]
    for event in ("PermissionRequest", "SessionStart", "Stop", "UserPromptSubmit")
}}
CODEX_CONFIG = """[features]
hooks = true

[hooks.state."/home/op/.codex/hooks.json:stop:0:0"]
trusted_hash = "sha256:0a9e"
"""
EVENTS = {".claude/settings.json": ["PostToolUse", "PostToolUseFailure"],
          ".codex/hooks.json": ["PreToolUse", "PostToolUse"]}


class InstallHooksTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.prefix = Path(tmp.name).resolve() / "prefix"
        self.claude = self.prefix / ".claude/settings.json"
        self.codex = self.prefix / ".codex/hooks.json"
        self.config = self.prefix / ".codex/config.toml"
        self.claude.parent.mkdir(parents=True)
        self.codex.parent.mkdir(parents=True)
        self.claude.write_text(json.dumps(CLAUDE_SETTINGS, indent=2))
        self.codex.write_text(json.dumps(CODEX_HOOKS, indent=2))
        self.config.write_text(CODEX_CONFIG)
        self.hook = str(self.prefix / ".local/bin/octo-lite-command-time")

    def install(self, *extra: str, ok: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run([str(INSTALLER), "--prefix", str(self.prefix), *extra],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                env={**os.environ, "PATH": OFFLINE})
        if ok:
            self.assertEqual([], problems(result), result.stderr)
        return result

    def without_ours(self, path: Path) -> dict:
        data = json.loads(path.read_text())
        for event in list(data["hooks"]):
            data["hooks"][event] = [g for g in data["hooks"][event]
                                    if g["hooks"] != [{"type": "command", "command": self.hook}]]
            if not data["hooks"][event]:
                del data["hooks"][event]
        return data

    def test_register_beside_other_tools_hooks(self) -> None:
        self.install()
        for path, original in ((self.claude, CLAUDE_SETTINGS), (self.codex, CODEX_HOOKS)):
            with self.subTest(settings=path.name):
                data = json.loads(path.read_text())
                for event in EVENTS[str(path.relative_to(self.prefix))]:
                    self.assertIn({"matcher": "Bash", "hooks": [{"type": "command", "command": self.hook}]},
                                  data["hooks"][event])
                self.assertEqual(original, self.without_ours(path), "other entries unchanged")
        self.assertEqual(Path(self.hook).resolve(), (ROOT / "scripts/octo-lite-command-time").resolve())
        before = (self.claude.read_text(), self.codex.read_text())
        self.install()
        self.assertEqual(before, (self.claude.read_text(), self.codex.read_text()), "registered once")

    def test_report_names_codex_trust_and_no_trust_is_recorded(self) -> None:
        result = self.install()
        self.assertIn("Codex runs octo-lite's command-time hook only once you trust it in Codex",
                      result.stdout)
        self.assertEqual(CODEX_CONFIG, self.config.read_text())
        self.config.unlink()
        self.install()
        self.assertFalse(self.config.exists(), "no trust written for the operator")

    def test_check_fails_naming_settings_that_lack_the_hook(self) -> None:
        self.install()
        self.assertEqual([], problems(self.install("--check")))
        self.claude.write_text(json.dumps(CLAUDE_SETTINGS, indent=2))
        result = self.install("--check", ok=False)
        self.assertEqual([f"missing command-time hook (PostToolUse, PostToolUseFailure): {self.claude};"
                          f" fix: run {INSTALLER} --prefix {self.prefix}"], problems(result))

    def test_check_names_every_settings_file_that_lacks_the_hook(self) -> None:
        self.install()
        self.claude.write_text(json.dumps(CLAUDE_SETTINGS, indent=2))
        self.codex.write_text(json.dumps(CODEX_HOOKS, indent=2))
        result = self.install("--check", ok=False)
        self.assertEqual([[str(self.claude)], [str(self.codex)]],
                         [[p for p in (str(self.claude), str(self.codex)) if p in line]
                          for line in problems(result)])

    def test_undo_removes_only_octo_lites_hook(self) -> None:
        self.install()
        self.install("--undo")
        self.assertEqual(CLAUDE_SETTINGS, json.loads(self.claude.read_text()))
        self.assertEqual(CODEX_HOOKS, json.loads(self.codex.read_text()))

    def test_unreadable_settings_are_left_untouched_and_reported(self) -> None:
        self.claude.write_text("{not json")
        result = self.install()
        self.assertEqual("{not json", self.claude.read_text())
        self.assertIn(str(self.claude), result.stderr)
        self.assertIn(self.hook, self.codex.read_text())
        self.claude.chmod(0o000)
        self.addCleanup(self.claude.chmod, 0o644)
        self.codex.write_text(json.dumps(CODEX_HOOKS, indent=2))
        result = self.install()
        self.assertIn(str(self.claude), result.stderr)
        self.assertIn(self.hook, self.codex.read_text())

    def test_settings_the_installer_cannot_write_are_left_untouched_and_reported(self) -> None:
        locked = self.prefix / "dotfiles"
        locked.mkdir()
        (locked / "settings.json").write_text(self.claude.read_text())
        self.claude.unlink()
        self.claude.symlink_to(locked / "settings.json")
        locked.chmod(0o555)
        self.addCleanup(locked.chmod, 0o755)
        result = self.install()
        self.assertEqual(CLAUDE_SETTINGS, json.loads(self.claude.read_text()))
        self.assertIn(str(self.claude), result.stderr)
        self.assertIn(self.hook, self.codex.read_text())
        self.assertTrue((self.prefix / ".local/state/octo-lite/onboarding.toml").exists())

    def test_settings_keep_their_link_and_mode(self) -> None:
        real = self.prefix / "dotfiles/settings.json"
        real.parent.mkdir()
        self.claude.rename(real)
        self.claude.symlink_to(real)
        real.chmod(0o600)
        self.install()
        self.assertTrue(self.claude.is_symlink())
        self.assertIn(self.hook, real.read_text())
        self.assertEqual(0o600, real.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
