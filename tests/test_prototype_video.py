"""octo-lite's round video recorder fails a recording that would skip a step or hide a press, naming the step.
Spec: spec/domains/octo-lite.spec.html #delivery-round-video; criteria #acceptance-video-unknown-action and
#acceptance-video-check. Neither needs the recorder's npm dependencies or a browser: an action the recorder does not
know fails before it starts one, and the check reads crops of frames the recorder recorded, kept as fixtures."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "skills" / "implement-spec" / "assets" / "prototype-video"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "prototype-video"

MOCKUP = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="mockup-prototype" content="/plan/week">
<title>Week plan - mockup</title>
</head>
<body>
<ol data-mockup-steps>
<li data-step="week">The week with its open cards</li>
<li data-step="planned" data-illustrates="plan-drop">The card sits on Tuesday<ul><li data-press=".card"></li><li data-drag=".card" data-to=".day[data-day=tue]"></li></ul></li>
</ol>
</body>
</html>
"""

# Reads crops kept as binary PGM, one byte of luma a pixel, and hands each step's press to the check.
CHECK = """
import { readFileSync } from 'node:fs'
const [check, viewport, ...steps] = process.argv.slice(1)
const { verify } = await import(check)
const crop = file => {
  const data = readFileSync(file)
  const [header, size] = data.toString('latin1').match(/^P5\\s+(\\d+)\\s+\\d+\\s+255\\s/)
  return { size: Number(size), luma: data.subarray(header.length) }
}
for (const step of steps) {
  const [name, file] = step.split('=')
  verify(viewport, name, [{ action: 'press .card', crops: [crop(file)] }])
}
"""


class UnknownActionTest(unittest.TestCase):
    def test_unknown_action_fails_naming_its_step_and_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            mockup = Path(tmp) / "week.mockup.html"
            mockup.write_text(MOCKUP)
            result = subprocess.run([str(RECORDER / "prototype-video"), str(mockup), "http://127.0.0.1:9/"],
                                    capture_output=True, text=True, cwd=tmp)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('step "planned" is reached by the action "drag"', result.stderr)
            self.assertFalse((Path(tmp) / "week.mockup.html.review").exists())


class VideoCheckTest(unittest.TestCase):
    """A real recording's frames at a press: one showing the cursor, on a phone the touch, and its mark, and one from
    a page that hid the drawn cursor as that press landed."""

    def check(self, viewport, *steps):
        return subprocess.run(["node", "--input-type=module", "-e", CHECK, str(RECORDER / "check.mjs"), viewport,
                               *(f"{name}={FIXTURES / f'{viewport}-{shown}.pgm'}" for name, shown in steps)],
                              capture_output=True, text=True)

    def test_second_press_not_shown_fails_naming_step_and_viewport(self):
        for viewport, shape in (("desktop", "cursor"), ("phone", "touch")):
            with self.subTest(viewport=viewport):
                result = self.check(viewport, ("team-open", "shown"), ("export", "hidden"))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'the {viewport} video does not show the {shape} and its press mark at step "export"',
                              result.stderr)

    def test_every_press_shown_passes(self):
        for viewport in ("desktop", "phone"):
            with self.subTest(viewport=viewport):
                result = self.check(viewport, ("team-open", "shown"), ("export", "shown"))
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
