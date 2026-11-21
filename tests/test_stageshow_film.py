"""Stageshow films a still on a box without Chrome, with no browser path set, in
the Chromium its pinned browser driver installs. Spec:
spec/domains/install.spec.html #install-stageshow-browser; criterion
#acceptance-stageshow-no-chrome. It films with the Stageshow this clone's
installer fetched, so it skips in a clone without one. A Node preload makes
every Chrome launch fail, since a box, CI's image too, may ship Chrome at the
fixed path Playwright looks in."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGESHOW = ROOT / "agents" / "skills" / "stageshow"

# Loaded before Stageshow's script, from its folder: the driver it imports
# refuses Chrome as a box without Chrome does.
NO_CHROME = """import { createRequire } from 'node:module'
const { chromium } = createRequire(process.cwd() + '/')('playwright-core')
const launch = chromium.launch.bind(chromium)
chromium.launch = (options = {}) =>
  options.channel?.startsWith('chrome') ? Promise.reject(new Error('Chrome is missing')) : launch(options)
"""

STILL = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Still</title>
<div class="ss-stage" style="width:320px;height:180px">A still</div>
"""


@unittest.skipUnless((STAGESHOW / "node_modules").is_dir(), "Stageshow not installed in this clone")
class NoChromeTest(unittest.TestCase):
    def test_films_a_still_in_its_drivers_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "no-chrome.mjs").write_text(NO_CHROME)
            (tmp / "still.html").write_text(STILL)
            env = {k: v for k, v in os.environ.items() if k != "CHROME_PATH"}
            env["NODE_OPTIONS"] = f"--import={(tmp / 'no-chrome.mjs').as_uri()}"
            r = subprocess.run(["node", "scripts/film.mjs", (tmp / "still.html").as_uri(), "--still",
                                "--out", str(tmp / "still.png")],
                               cwd=STAGESHOW, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((tmp / "still.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
