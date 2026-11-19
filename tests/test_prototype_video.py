"""octo-lite's round video recorder fails a recording that would skip a step or hide a press, naming the step, and
records real use of a prototype, each step action as a person does it. Spec: spec/domains/octo-lite.spec.html
#delivery-round-video, #delivery-round-video-actions; criteria #acceptance-video-unknown-action, -check, -drag, -hold,
-hold-slide, -menu, -hover, -select, -busy, and -length. The recorder reads a mockup file in its browser, so these
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

def mockup(route, *steps):
    """A prototype mockup file of the route whose walkthrough is the steps, each its name, caption, and actions."""
    items = "\n".join(f'<li data-step="{name}">{caption}' + (f"<ul>{actions}</ul>" if actions else "")
                      for name, caption, actions in steps)
    return (f'<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n<meta name="mockup-prototype" content="{route}">\n'
            f"<ol data-mockup-steps>\n{items}\n</ol>\n")


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


# Runs the recorder on its arguments, logging each input it sends and every frame its video is made of, as its
# screencast hands them over, for the test's own lines after it to read: `inputs`, each mouse move, down, and up with
# its button, each touch, with its point and time; `frames`; and helpers that read a frame at a point.
HARNESS = """
import { readdirSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
const [dir, ...argv] = process.argv.slice(1)
const require = createRequire(`${dir}/recorder.mjs`)
const { chromium } = require('playwright-core')
const { jpegjs } = require('playwright-core/lib/utilsBundle')
const { SHAPES, crop, drawn } = await import(`${dir}/check.mjs`)
const { main } = await import(`${dir}/recorder.mjs`)
const frames = []
const inputs = []
const log = (type, { x, y }, more) => inputs.push({ type, x, y, at: Date.now(), ...more })
const launch = chromium.launch.bind(chromium)
chromium.launch = async options => {
  const browser = await launch(options)
  const newContext = browser.newContext.bind(browser)
  browser.newContext = async options => {
    const context = await newContext(options)
    const newCDPSession = context.newCDPSession.bind(context)
    context.newCDPSession = async page => {
      const session = await newCDPSession(page)
      const send = session.send.bind(session)
      session.send = (method, params) => {
        if (method === 'Input.dispatchTouchEvent') {
          log(params.type, params.touchPoints[0] ?? inputs.findLast(input => input.type.startsWith('touch')))
        }
        return send(method, params)
      }
      return session
    }
    context.on('page', page => {
      const { mouse, screencast } = page
      let at = { x: 0, y: 0 }
      const [move, down, up] = [mouse.move, mouse.down, mouse.up].map(call => call.bind(mouse))
      mouse.move = (x, y, ...rest) => (at = { x, y }, log('move', at), move(x, y, ...rest))
      mouse.down = options => (log('down', at, { button: options?.button ?? 'left' }), down(options))
      mouse.up = options => (log('up', at, { button: options?.button ?? 'left' }), up(options))
      const start = screencast.start.bind(screencast)
      screencast.start = ({ onFrame, ...rest }) =>
        start({ ...rest, onFrame: frame => (frames.push(frame), onFrame(frame)) })
    })
    return context
  }
  return browser
}
await main(argv)
const videos = `${argv[0]}.review/videos`
const of = type => inputs.filter(input => input.type === type)
const before = at => frames.findLast(frame => frame.timestamp < at)
const after = at => frames.find(frame => frame.timestamp > at)
const decode = frame => jpegjs.decode(frame.data, { useTArray: true, formatAsRGBA: true })
const shape = (frame, { x, y }, probes) => drawn(crop(decode(frame), x, y), probes)
const color = (frame, { x, y }) => {
  const { width, data } = decode(frame)
  const k = 4 * (Math.round(y) * width + Math.round(x))
  return [...data.subarray(k, k + 3)]
}
const like = (rgb, hex) => rgb.every((value, n) => Math.abs(value - parseInt(hex.slice(1 + 2 * n, 3 + 2 * n), 16)) < 48)
// What `read`, run with `arg` on a page holding a video and a canvas, reads of the spool's video `webm` at /video.webm.
const play = async (webm, read, arg) => {
  const browser = await launch()
  try {
    const page = await browser.newPage()
    await page.route('http://video.test/**', route => route.request().url().endsWith('.webm')
      ? route.fulfill({ path: `${videos}/${webm}`, contentType: 'video/webm' })
      : route.fulfill({ contentType: 'text/html', body: '<video muted></video><canvas></canvas>' }))
    await page.goto('http://video.test/')
    return await page.evaluate(read, arg)
  } finally {
    await browser.close()
  }
}
"""

# Whether any frame before the first hover shows the touch at the page's corner, where the page's own first hover at
# 0, 0 lands, by the probes on the frame there; and for each tap, whether the touch shows at its point in the last
# frame before the tap, and in the last frame before the next hover, or the video's last, once the finger has lifted.
TAPS = HARNESS + """
const corner = SHAPES.phone.cursor.filter(([dx, dy]) => dx >= 0 && dy >= 0)
const moves = of('move')
console.log(JSON.stringify({
  corner: frames.filter(frame => frame.timestamp < moves[0].at).some(frame => shape(frame, { x: 0, y: 0 }, corner)),
  taps: of('touchStart').map(tap => {
    const next = moves.find(move => move.at > tap.at)
    return {
      rested: shape(before(tap.at), tap, SHAPES.phone.cursor),
      after: shape(next ? before(next.at) : frames.at(-1), tap, SHAPES.phone.cursor),
    }
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
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", "screen"]):
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

    def probe(self, mockup, viewport, program):
        """The harness's run of the recorder (HARNESS), passing, and what `program` read of it."""
        result = self.record(mockup, viewport, program=HARNESS + program)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def test_drag_lifts_the_card_under_the_cursor_and_drops_it_on_the_day(self):
        """#acceptance-video-drag: the browser draws the card a native drag lifts outside the page, so the recorder
        draws it, lifted under the cursor as it travels through the gap between the tray and the week, where the page
        shows no card; then the card sits on Tuesday where the cursor let go."""
        seen = self.probe(mockup("/calendar/", ("week", "The week with its pitch deck", ""),
                                 ("planned", "The deck sits on Tuesday",
                                  '<li data-hold=".tray .card" data-to=".day[data-day=tue]">')), "desktop", """
const [down] = of('down')
const [up] = of('up')
const gap = Array.from({ length: 23 * 8 }, (_, n) => ({ x: 400 + 20 * (n % 23), y: 40 + 20 * Math.floor(n / 23) }))
const carried = frames.filter(frame => frame.timestamp > down.at && frame.timestamp < up.at)
const blue = frame => {
  const { width, data } = decode(frame)
  return gap.filter(({ x, y }) => like([...data.subarray(4 * (y * width + x), 4 * (y * width + x) + 3)], '#2563eb')).length
}
console.log(JSON.stringify({
  lifted: carried.some(frame => blue(frame) >= 3),
  dropped: like(color(frames.at(-1), { x: up.x - 30, y: up.y - 30 }), '#2563eb'),
}))
""")
        self.assertEqual(seen, {"lifted": True, "dropped": True})

    def test_drag_to_a_day_far_below_scrolls_it_into_view_and_rests_there(self):
        """#delivery-round-video: the card held, the page first scrolls Tuesday, 1600 px below, into view, and the
        cursor rests on it before it lets go there, which drops the card on Tuesday."""
        seen = self.probe(mockup("/far/", ("week", "The week with its pitch deck", ""),
                                 ("planned", "The deck sits on Tuesday, far below",
                                  '<li data-hold=".tray .card" data-to=".day[data-day=tue]">')), "desktop", """
const [up] = of('up')
const last = of('move').findLast(move => move.at < up.at)
console.log(JSON.stringify({
  rested: up.at - last.at >= 400,
  dropped: like(color(frames.at(-1), { x: up.x - 30, y: up.y + 20 }), '#2563eb'),
}))
""")
        self.assertEqual(seen, {"rested": True, "dropped": True})

    def test_phone_carry_to_a_day_far_below_scrolls_it_into_view(self):
        """#delivery-round-video on a phone: the touch holds the card, the page first scrolls Tuesday, 1600 px below,
        into view, and the touch slides there still down and rests on it before it lifts: the recording passes only
        once that rest lands on Tuesday."""
        seen = self.probe(mockup("/far/", ("week", "The week with its pitch deck", ""),
                                 ("planned", "The deck carried to Tuesday, far below",
                                  '<li data-hold=".tray .card" data-to=".day[data-day=tue]">')), "phone", """
const starts = of('touchStart')
const [end] = of('touchEnd')
const slides = of('touchMove')
console.log(JSON.stringify({
  stillDown: starts.length === 1 && slides.length > 0 && slides.every(slide => slide.at < end.at),
  rested: end.at - slides.at(-1).at >= 400,
}))
""")
        self.assertEqual(seen, {"stillDown": True, "rested": True})

    def test_hold_shows_the_touch_down_while_the_full_text_shows_then_lifts(self):
        """#acceptance-video-hold: the touch holds the title, its mark full, through the step whose full text shows
        only while it is down, and lifts as the next step starts, which shows the full text gone and no touch."""
        seen = self.probe(mockup("/title/", ("list", "The reel's title, cut short", ""),
                                 ("peek", "Held &rarr; the full title", '<li data-hold=".title">'),
                                 ("let-go", "Let go &rarr; cut short again", "")), "phone", """
const [start] = of('touchStart')
const [end] = of('touchEnd')
const held = before(end.at)
const last = frames.at(-1)
const full = { x: 180, y: 230 }
console.log(JSON.stringify({
  held: shape(held, start, SHAPES.phone.cursor) && shape(held, start, SHAPES.phone.mark) && like(color(held, full), '#f59e0b'),
  after: shape(last, start, SHAPES.phone.cursor) || like(color(last, full), '#f59e0b'),
  down: end.at - start.at >= 1400,
}))
""")
        self.assertEqual(seen, {"held": True, "after": False, "down": True})

    def test_hold_slides_still_down_to_the_item_its_menu_opened_and_picks_it(self):
        """#acceptance-video-hold-slide: the touch holds Save until its menu shows, however the page hides it until
        then, slides still down to Trips, and lifts there, which saves to Trips."""
        for hide in ("opacity", "visibility", "display"):
            with self.subTest(hide=hide):
                seen = self.probe(mockup(f"/save/?hide={hide}", ("reel", "The reel with Save", ""),
                                         ("saved", "Held &rarr; its collections; slid to Trips &rarr; saved there",
                                          '<li data-hold=".save" data-to=".menu [data-collection=trips]">')), "phone", """
const starts = of('touchStart')
const [end] = of('touchEnd')
const slides = of('touchMove')
console.log(JSON.stringify({
  heldUntilOpen: slides.length > 0 && slides[0].at - starts[0].at >= 500,
  stillDown: starts.length === 1 && slides.every(slide => slide.at < end.at),
  picked: like(color(frames.at(-1), { x: 180, y: 450 }), '#16a34a'),
}))
""")
                self.assertEqual(seen, {"heldUntilOpen": True, "stillDown": True, "picked": True})

    def test_menu_right_clicks_the_card_which_opens_its_menu(self):
        """#acceptance-video-menu: on a desktop the card's menu opens by a right-click, its mark checked by the
        recorder; the next step rests on the menu's item, which shows only once the menu opened."""
        seen = self.probe(mockup("/cards/", ("cards", "A saved card", ""),
                                 ("menu", "Right-clicked &rarr; its menu", '<li data-menu=".card">'),
                                 ("move", "Move to a collection", '<li data-hover=".menu .move">')), "desktop", """
console.log(JSON.stringify(of('down').map(down => down.button)))
""")
        self.assertEqual(seen, ["right"])

    def test_hover_rests_with_no_press_mark_while_the_tip_shows(self):
        """#acceptance-video-hover: the cursor rests on Export, pressing nothing, and no frame from then shows a
        press mark there, while its tip shows."""
        seen = self.probe(mockup("/tip/", ("toolbar", "The toolbar", ""),
                                 ("tip", "Resting on Export &rarr; its tip", '<li data-hover=".export">')), "desktop", """
const rest = of('move').at(-1)
const since = frames.filter(frame => frame.timestamp > rest.at)
console.log(JSON.stringify({
  presses: of('down').length,
  cursor: shape(frames.at(-1), rest, SHAPES.desktop.cursor),
  mark: since.some(frame => shape(frame, rest, SHAPES.desktop.mark)),
  tip: like(color(frames.at(-1), { x: 190, y: 330 }), '#7c3aed'),
}))
""")
        self.assertEqual(seen, {"presses": 0, "cursor": True, "mark": False, "tip": True})

    def test_select_picks_its_option_with_a_mark_and_no_list_opened(self):
        """#acceptance-video-select: the cursor presses the select, its mark checked by the recorder, with no press
        sent that opens the list the browser draws apart from the page; the next step rests on the reels in the order
        picked, which shows only once the option is."""
        seen = self.probe(mockup("/sort/", ("reels", "Reels, oldest first", ""),
                                 ("sorted", "Newest first",
                                  """<li data-type="select[aria-label='Sort reels']" data-text="Newest first">"""),
                                 ("newest", "The newest reel on top", '<li data-hover=".reels[data-sort=newest] li">')),
                          "desktop", """
console.log(JSON.stringify(of('down').length))
""")
        self.assertEqual(seen, 0)

    def test_press_on_a_page_busy_after_it_shows_its_mark(self):
        """#acceptance-video-busy: the page is too busy to draw for 1.5 s from the press, yet the recording passes,
        its check finding the cursor, on a phone the touch, and its mark at the press, which still opens Tuesday."""
        result = self.record(mockup("/busy/", ("card", "Tuesday's card", ""),
                                    ("open", "Pressed &rarr; Tuesday done", '<li data-press=".card">'),
                                    ("done", "Tuesday done", '<li data-hover=".card.done">')), "desktop", "phone")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_video_lasts_as_long_as_its_captions_to_the_last_step_result(self):
        """#acceptance-video-length: the last step scrolls to Send far below and presses it, then nothing moves; the
        video, read back as a browser plays it, lasts as long as its captions, and its last frame shows Send sent."""
        seen = self.probe(mockup("/long/", ("chat", "The chat", ""),
                                 ("sent", "Send, far below &rarr; sent", '<li data-press=".send">')), "desktop", """
const webm = readdirSync(videos).find(name => name.endsWith('-desktop.webm'))
const vtt = readFileSync(`${videos}/${webm.replace(/webm$/, 'vtt')}`, 'utf8')
const [h, m, sec] = vtt.match(/--> (\\S+)\\n[^\\n]*\\n?$/)[1].split(':').map(Number)
const press = of('down').at(-1)
const played = await play(webm, async ({ x, y }) => {
  const video = document.querySelector('video')
  video.src = '/video.webm'
  await new Promise(done => video.addEventListener('loadedmetadata', done, { once: true }))
  video.playbackRate = 8 // played through: a seek may show the frame it decodes from, not the last
  await video.play()
  await new Promise(done => video.addEventListener('ended', done, { once: true }))
  const canvas = document.querySelector('canvas')
  Object.assign(canvas, { width: video.videoWidth, height: video.videoHeight })
  const context = canvas.getContext('2d')
  context.drawImage(video, 0, 0)
  return { duration: video.duration, rgb: [...context.getImageData(x, y, 1, 1).data.slice(0, 3)] }
}, { x: press.x - 200, y: press.y })
console.log(JSON.stringify({ drift: Math.abs(played.duration - (h * 3600 + m * 60 + sec)) < 0.05, sent: like(played.rgb, '#16a34a') }))
""")
        self.assertEqual(seen, {"drift": True, "sent": True})

    def test_press_again_on_a_part_taller_than_the_screen_waits_on_no_scroll(self):
        """#delivery-round-video: a part taller than the screen never fits in view, so the page scrolls it no further
        once the pointer can rest on it there: its second press follows its first by the step's hold, with no wait on a
        scroll that cannot start."""
        seen = self.probe(mockup("/tall/", ("poster", "The poster", ""),
                                 ("once", "Pressed once", '<li data-press=".poster">'),
                                 ("twice", "Pressed twice", '<li data-press=".poster">')), "desktop", """
const [up] = of('up')
const next = of('move').find(move => move.at > up.at)
console.log(JSON.stringify(next.at - up.at))
""")
        self.assertLess(seen, 1400 + 2000)

    def test_part_that_shows_long_after_its_press_is_waited_for(self):
        """#delivery-round-video: a loaded box can take a page seconds to draw what a press shows, so a working step
        never fails on it: the result that shows 8 s after its search is still reached and pressed."""
        result = self.record(mockup("/late/", ("search", "The search", ""),
                                    ("searched", "Searched", '<li data-press=".search">'),
                                    ("opened", "Its result, shown late &rarr; opened", '<li data-press=".result">')),
                             "desktop")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_press_on_a_part_the_page_still_moves_lands_where_it_ends(self):
        """#delivery-round-video: the week's days arrive in pieces for 6 s after Load, each pushing Tuesday down while
        the pointer travels and rests on it, as a loaded box commits a render late; the pointer goes again to where
        Tuesday is until it rests on it, so its press opens Tuesday."""
        for viewport in ("desktop", "phone"):
            with self.subTest(viewport=viewport):
                seen = self.probe(mockup("/arriving/", ("week", "The week, not loaded", ""),
                                         ("loading", "Loading its days", '<li data-press=".load">'),
                                         ("opened", "Tuesday, once its days arrived &rarr; opened",
                                          '<li data-press=".tuesday">')), viewport, """
const press = [...of('down'), ...of('touchStart')].at(-1)
console.log(JSON.stringify(like(color(frames.at(-1), { x: press.x - 150, y: press.y }), '#16a34a')))
""")
                self.assertTrue(seen)

    def test_part_no_press_reaches_fails_naming_its_step(self):
        result = self.record(COVERED, "desktop")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('step "open": a press on ".tile" never lands on it: it does not show there or lets presses through,'
                      ' or another part lies over it'
                      ' or acts inside it', result.stderr)


if __name__ == "__main__":
    unittest.main()
