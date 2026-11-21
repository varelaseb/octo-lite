"""Stageshow films a still on a box without Chrome, with no browser path set, in
the Chromium its pinned browser driver installs, and with neither names that
Chromium's error and how to install it. Spec: spec/domains/install.spec.html
#install-stageshow-browser; criterion #acceptance-stageshow-no-chrome. It films
with the Stageshow this clone's installer fetched, as CI's does, so it skips in
a clone without one. A Node preload makes browser launches fail, since a box,
CI's image too, may ship Chrome at the fixed path Playwright looks in."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGESHOW = ROOT / "agents" / "skills" / "stageshow"

# Loaded before Stageshow's script, from its folder: the driver it imports
# refuses each browser REFUSED matches, as a box without it does.
REFUSE = """import { createRequire } from 'node:module'
const { chromium } = createRequire(process.cwd() + '/')('playwright-core')
const launch = chromium.launch.bind(chromium)
chromium.launch = (options = {}) => REFUSED
  ? Promise.reject(new Error(`${options.channel ?? 'chromium'} is missing\\nits log`)) : launch(options)
"""
NO_CHROME = REFUSE.replace("REFUSED", "options.channel?.startsWith('chrome')")
NO_BROWSER = REFUSE.replace("REFUSED", "true")

STILL = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Still</title>
<div class="ss-stage" style="width:320px;height:180px">A still</div>
"""


@unittest.skipUnless((STAGESHOW / "node_modules").is_dir(), "Stageshow not installed in this clone")
class NoChromeTest(unittest.TestCase):
    def film(self, preload):
        """Films a still with no browser path set, PRELOAD refusing launches:
        the run, and the still's first bytes or None."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "refuse.mjs").write_text(preload)
            (tmp / "still.html").write_text(STILL)
            env = {k: v for k, v in os.environ.items() if k != "CHROME_PATH"}
            env["NODE_OPTIONS"] = f"--import={(tmp / 'refuse.mjs').as_uri()}"
            r = subprocess.run(["node", "scripts/film.mjs", (tmp / "still.html").as_uri(), "--still",
                                "--out", str(tmp / "still.png")],
                               cwd=STAGESHOW, env=env, capture_output=True, text=True, timeout=120)
            still = tmp / "still.png"
            return r, still.read_bytes()[:8] if still.exists() else None

    def test_films_a_still_in_its_drivers_chromium(self):
        r, still = self.film(NO_CHROME)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(still, b"\x89PNG\r\n\x1a\n")

    def test_names_its_chromiums_error_and_fix_when_no_browser_starts(self):
        r, still = self.film(NO_BROWSER)
        self.assertEqual((r.returncode, still), (2, None), r.stderr)
        self.assertIn("(chromium is missing)", r.stderr)
        self.assertIn("run install-octo-lite to install its Chromium", r.stderr)


if __name__ == "__main__":
    unittest.main()
