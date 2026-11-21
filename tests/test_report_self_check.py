"""The report skill's self-check passes a report folder that keeps the folder and
page rules and names each fault of one that does not. Spec:
spec/domains/octo-lite.spec.html#roles-report-folder; criterion
#acceptance-report-folder. It runs the skill's own self-check.mjs by the command
its SKILL.md gives, through the installed skill link, in a browser: run
`npm ci && npx playwright-core install chromium` at the clone root once per
clone. No fixture links outside the folder, so no test fetches."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/report/SKILL.md"
COMMAND = "node ~/.claude/skills/report/self-check.mjs <report folder>"
STYLE = "body{font:16px system-ui;margin:1rem}@media (prefers-color-scheme: dark){body{background:#111;color:#eee}}"
SUMMARY = """<header data-anchor="top" id="top"><h1>Teams ship weekly</h1><p>62% of teams, against 30% a year ago.</p></header>
<section data-anchor="pick" id="pick" data-answers="Weekly, Monthly">
<h2 data-anchor="pick-q" id="pick-q">Ship weekly?</h2>
<p data-anchor="pick-why" id="pick-why">Weekly: <a href="findings.html#f1">most teams do</a>.</p>
</section>
<footer data-anchor="how" id="how"><p>Read public posts without changing anything.</p></footer>"""
FINDING = """<article class="finding" data-anchor="{id}" id="{id}"><p>Most teams ship weekly.</p>
<a href="query-a.txt">query</a> <time datetime="2026-11-20">2026-11-20</time> <span class="trust">{trust}</span></article>"""
FINDINGS = '<h1 data-anchor="title" id="title">Findings</h1>\n' + FINDING.format(id="f1", trust="primary")


def page(body: str, title: str = "Teams ship weekly") -> str:
    return ('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{title}</title>\n<style>{STYLE}</style>\n<body>\n{body}\n</body>\n</html>\n")


def write(folder: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    return folder


class ReportSelfCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        text = SKILL.read_text(encoding="utf-8").split("\n## Self-check\n", 1)[1]
        self.assertIn(f"```sh\n{COMMAND}\n```", text)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        # The command runs the file through the installed skill link.
        home = self.tmp / "home"
        (home / ".claude/skills").mkdir(parents=True)
        (home / ".claude/skills/report").symlink_to(ROOT / "skills/report")
        (self.tmp / "scratch").mkdir()
        chrome = os.environ.get("CHROME_PATH") or subprocess.run(
            ["node", "-e", "console.log(require('playwright-core').chromium.executablePath())"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        self.env = {**os.environ, "HOME": str(home), "TMPDIR": str(self.tmp / "scratch"), "CHROME_PATH": chrome}

    def self_check(self, folder: Path) -> list[str]:
        r = subprocess.run(["bash", "-c", COMMAND.replace("<report folder>", '"$1"'), "bash", str(folder)],
                           env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def test_a_folder_keeping_the_rules_is_ok(self) -> None:
        folder = write(self.tmp / "good", {"summary.html": page(SUMMARY), "findings.html": page(FINDINGS),
                                           "query-a.txt": "query=ship weekly\n"})
        self.assertEqual(self.self_check(folder), ["ok"])
        for shot in ("summary-390-light.png", "summary-390-dark.png", "summary-1280-light.png"):
            self.assertTrue((self.tmp / "scratch" / shot).is_file(), shot)

    def test_each_fault_planted_in_a_folder_is_named(self) -> None:
        folder = self.tmp / "bad"
        write(folder, {
            "summary.html": page(SUMMARY + '\n<div data-anchor="wide" id="wide" style="width:1000px">wide</div>'
                                 '\n<p data-anchor="more" id="more"><a href="gone.html">gone</a>'
                                 ' <a href="findings.html#nowhere">nowhere</a></p>'),
            "findings.html": page(FINDINGS + "\n<script></script>\n" + FINDING.format(id="f1", trust="primary")
                                  + "\n<p>loose</p>\n" + FINDING.format(id="f2", trust="blog")),
            "round-1/summary.html": page('<p data-anchor="r" id="s" data-comment-thread="1">old</p>', title=""),
            "query-a.txt": "query=ship weekly\n",
            "Notes.txt": "mine\n",
        })
        rules = "needs a title and a dark scheme, no script, form, frame, plugin, or data-comment-*"
        self.assertEqual(set(self.self_check(folder)), {
            "summary.html scrolls sideways at 390px",
            "Notes.txt: name not [a-z0-9-]+",
            f"summary.html: {(folder / 'gone.html').as_uri()} not found",
            f"summary.html: {(folder / 'findings.html').as_uri()}#nowhere has no such anchor",
            f"findings.html: {rules}",
            "findings.html: anchor f1 not unique or not its id",
            "findings.html: 1 blocks without data-anchor",
            "findings.html: finding f2 lacks a source link, a date read, or a trust label",
            f"round-1/summary.html: {rules}",
            "round-1/summary.html: anchor !r not unique or not its id",
        })


if __name__ == "__main__":
    unittest.main()
