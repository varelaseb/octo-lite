"""octo-lite's round video recorder fails a recording that would skip a step or hide a press, naming the step, and
records real use of a prototype. Spec: spec/domains/octo-lite.spec.html #delivery-round-video; criteria
#acceptance-video-unknown-action and #acceptance-video-check. The recorder reads a mockup file in its browser, so these
tests need its pinned driver and browser, as the installer adds them (install.spec.html #install-recorder): run
`npm ci && npx playwright-core install chromium` at the clone root once per clone. The check reads crops of frames the
recorder recorded, kept as fixtures."""

from __future__ import annotations

import functools
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "skills" / "implement-spec" / "assets" / "prototype-video"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "prototype-video"

# Valid HTML a hand-written parser misreads: each item's end tag implied, a named entity in a caption.
MOCKUP = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="mockup-prototype" content="/plan/week">
<title>Week plan - mockup</title>
<ol data-mockup-steps>
<li data-step="week">The week with its open cards
<li data-step="planned" data-illustrates="plan-drop">The card sits on Tuesday &rarr; planned<ul><li data-press=".card"><li data-drag=".card" data-to=".day[data-day=tue]"></ul>
</ol>
"""

# The fixture site's week: its card opens Tuesday, whose link leads back. A trailing button over the card's right removes
# it instead: on a desktop it shows only once the cursor rests on the card, on a phone always. Both presses open another
# page.
ROUND = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="mockup-prototype" content="/week/">
<title>Week - mockup</title>
<ol data-mockup-steps>
<li data-step="week">The week with Tuesday's card
<li data-step="day">Tuesday opens &rarr; its plan<ul><li data-press=".card"></ul>
<li data-step="back">Back to the week<ul><li data-press="a.back"></ul>
</ol>
"""

COVERED = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="mockup-prototype" content="/covered/">
<ol data-mockup-steps>
<li data-step="tile">A tile
<li data-step="open">The tile opens<ul><li data-press=".tile"></ul>
</ol>
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


# Runs the recorder on its arguments and reads the frames its video is made of, as its screencast hands them over:
# whether any frame before the first hover shows the touch at the page's corner, where the page's own first hover at 0, 0
# lands, by the probes on the frame there; and for each tap, whether the touch shows at its point in the last frame
# before the tap, and in the last frame before the next hover, or the video's last, once the finger has lifted.
TAPS = """
import { createRequire } from 'node:module'
const [dir, ...argv] = process.argv.slice(1)
const require = createRequire(`${dir}/recorder.mjs`)
const { chromium } = require('playwright-core')
const { jpegjs } = require('playwright-core/lib/utilsBundle')
const { SHAPES, crop, drawn } = await import(`${dir}/check.mjs`)
const { main } = await import(`${dir}/recorder.mjs`)
const frames = []
const moves = []
const taps = []
const launch = chromium.launch.bind(chromium)
chromium.launch = async options => {
  const browser = await launch(options)
  const newContext = browser.newContext.bind(browser)
  browser.newContext = async options => {
    const context = await newContext(options)
    context.on('page', ({ mouse, touchscreen, screencast }) => {
      const logged = (calls, call) => (x, y, ...rest) => (calls.push({ x, y, at: Date.now() }), call(x, y, ...rest))
      mouse.move = logged(moves, mouse.move.bind(mouse))
      touchscreen.tap = logged(taps, touchscreen.tap.bind(touchscreen))
      const start = screencast.start.bind(screencast)
      screencast.start = ({ onFrame, ...rest }) =>
        start({ ...rest, onFrame: frame => (frames.push(frame), onFrame(frame)) })
    })
    return context
  }
  return browser
}
await main(argv)
const before = at => frames.findLast(frame => frame.timestamp < at)
const touch = (frame, { x, y }, probes = SHAPES.phone.cursor) =>
  drawn(crop(jpegjs.decode(frame.data, { useTArray: true, formatAsRGBA: true }), x, y), probes)
const corner = SHAPES.phone.cursor.filter(([dx, dy]) => dx >= 0 && dy >= 0)
console.log(JSON.stringify({
  corner: frames.filter(frame => frame.timestamp < moves[0].at).some(frame => touch(frame, { x: 0, y: 0 }, corner)),
  taps: taps.map(tap => {
    const next = moves.find(move => move.at > tap.at)
    return { rested: touch(before(tap.at), tap), after: touch(next ? before(next.at) : frames.at(-1), tap) }
  }),
}))
"""


class Site(ThreadingHTTPServer):
    """The fixture prototype, served on a free port."""

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    def __init__(self):
        super().__init__(("127.0.0.1", 0), functools.partial(self.Handler, directory=FIXTURES / "site"))
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def address(self):
        return f"http://127.0.0.1:{self.server_address[1]}/"


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


class LaunchHintTest(unittest.TestCase):
    """With no browser starting, the recorder's fix is the installer's own line with the box's scope, as the installer
    publishes it in its after-pull step (install.spec.html #install-after-pull), so following it keeps that scope."""

    def test_no_browser_names_the_installer_with_the_box_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            env = {**os.environ, "XDG_STATE_HOME": str(state), "CHROME_PATH": str(Path(tmp) / "no-chrome")}
            argv = [str(RECORDER / "prototype-video"), "screen.mockup.html", "http://127.0.0.1:9/"]
            installer, prefix, project = "/clone/scripts/install-octo-lite", "/box", "/work/project"
            for published, fix in (
                    (None, "install-octo-lite"),
                    ([installer, "--after-pull", "--prefix", prefix, "--project", project],
                     f"{installer} --prefix {prefix} --project {project}")):
                with self.subTest(fix=fix):
                    if published:
                        (state / "octo-lite").mkdir(parents=True)
                        quoted = ", ".join(f'"{arg}"' for arg in published)
                        (state / "octo-lite/onboarding.toml").write_text(
                            f'status = "pending"\nafter_pull = [{quoted}]\ncheck = []\ncommit = ""\n')
                    result = subprocess.run(argv, capture_output=True, text=True, cwd=tmp, env=env)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertTrue(result.stderr.rstrip().endswith(f": run {fix}, or set CHROME_PATH"), result.stderr)


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


class RecordingTest(unittest.TestCase):
    """A round recorded from the fixture site at each viewport, from a mockup committed in a repo of its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.site = Site()
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)

    def record(self, mockup, *viewports, program=None):
        """The recorder's run on the mockup, or `program`'s, which runs it (TAPS)."""
        (self.repo / "screen.mockup.html").write_text(mockup)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "screen"]):
            subprocess.run(["git", "-C", str(self.repo), *argv], check=True, env=env)
        recorder = ["node", "--input-type=module", "-e", program, str(RECORDER)] if program else [
            str(RECORDER / "prototype-video")]
        return subprocess.run([*recorder, str(self.repo / "screen.mockup.html"),
                               self.site.address, *(f"--viewport={v}" for v in viewports)],
                              capture_output=True, text=True, cwd=self.repo)

    def test_presses_that_open_pages_record_and_pass_their_check(self):
        """The card's press lands on the card, not the button over its right, on a desktop judged once the cursor
        rests there, where the card's hover shows that button; each press opens a page, through which the cursor, on a
        phone the touch, and its mark still show."""
        result = self.record(ROUND, "desktop", "phone")
        self.assertEqual(result.returncode, 0, result.stderr)
        videos = self.repo / "screen.mockup.html.review" / "videos"
        commit = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                                text=True).stdout.strip()
        self.assertEqual(sorted(p.name for p in videos.iterdir()),
                         [f"{commit}-{v}.{ext}" for v in ("desktop", "phone") for ext in ("vtt", "webm")])
        cues = (videos / f"{commit}-phone.vtt").read_text().split("\n\n")[1:]
        self.assertEqual([cue.splitlines()[2] for cue in cues],
                         ["The week with Tuesday's card", "Tuesday opens \u2192 its plan", "Back to the week"])

    def test_phone_tap_judged_with_the_hover_it_applies(self):
        """On a phone a tap hovers where it lands, so an ungated hover that shows the button over the card's right
        is judged before the tap: the touch presses the card's middle and Tuesday opens."""
        result = self.record(ROUND.replace("/week/", "/ungated/"), "phone")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_phone_touch_rests_from_its_hover_until_its_tap(self):
        """On a phone the recorder hovers a part before it taps it, which shows the part's hover, so the touch rests on
        that point from the hover until the tap: every change has a cause on screen. Before its first hover no finger
        rests, so the page's own hover at 0, 0 draws no touch at the corner. The tap lifts the finger, so once it has
        lifted no touch shows there, on a page the tap opens either: Tuesday, which the card opens only once its press
        mark has run, and the week, which the back link opens while it runs."""
        result = self.record(ROUND.replace("/week/", "/wait/"), "phone", program=TAPS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]),
                         {"corner": False, "taps": [{"rested": True, "after": False}] * 2})

    def test_part_no_press_reaches_fails_naming_its_step(self):
        result = self.record(COVERED, "desktop")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('step "open": a press on ".tile" lands on another part', result.stderr)


if __name__ == "__main__":
    unittest.main()
