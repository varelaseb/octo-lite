// octo-lite's one round video recorder (octo-lite #delivery-round-video), which every prototype worker runs and none
// writes for its lane. It reads the screen's mockup file, loads its route on the worker's running prototype, and
// reaches each walkthrough step by its actions as Spec Chat does (mockups #prototype-steps), as a person would, at the
// pace of Stageshow's motion rules: the cursor, on a phone a touch, travels to each part an action names, the page
// first scrolling it into view, rests on it so its hover shows, and does that action there, judged with the hover it
// will have, on what Spec Chat acts on (#delivery-round-video-actions): it presses, holds, carries, right-clicks,
// picks an option, or only rests, with a mark wherever it pressed, and types one key at a time. Each change plays at
// the product's own speed and each step's result holds before the next. It checks the video as it records it, each
// action against the frames the video shows at it (check.mjs), and keeps every viewport's, with captions timed to its
// own frames, where Spec Chat reads them (mockups #round-video-store), only once all pass.

import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { crop, shows, verify } from './check.mjs'
import { walkthrough } from './mockup.mjs'
import { ARROW, EDGE, MARK, TOUCH, overlay } from './overlay.mjs'

const USAGE = 'usage: prototype-video <mockup.html> <prototype-address> [--viewport desktop|phone]... [--spool <mockup>.review]'
// The sizes Spec Chat frames a prototype at (mockups #frame-viewports).
const VIEWPORTS = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } }
// Stageshow motion.md, Pace and easing: travel's curve, and a person's timing in ms.
const TRAVEL = [0.45, 0, 0.1, 1]
const PACE = { open: 1200, reach: 500, rest: 400, press: 90, key: 90, hold: 1400, last: 2200 }
// How long, in ms, a part may take to show, and the video to show an action, however loaded the box.
const WAIT = { part: 5000, video: 10000 }
// What acts of its own when pressed, as Spec Chat tells a press through a prototype from a click on nothing that acts
// (its runtime's PROTOTYPE_ACTS).
const ACTS = 'a[href],button,input,select,textarea,label,summary,[role=button],[role=link],[role=tab],[role=menuitem],'
  + '[role=checkbox],[role=radio],[role=switch],[contenteditable]'

const sleep = ms => new Promise(done => setTimeout(done, ms))

export async function main(argv) {
  let args
  try {
    args = parseArgs({ args: argv, allowPositionals: true, options: { viewport: { type: 'string', multiple: true }, spool: { type: 'string' } } })
  } catch (e) {
    return fail(`${e.message}\n${USAGE}`, 2)
  }
  const [mockup, address, ...extra] = args.positionals
  const viewports = args.values.viewport ?? ['desktop']
  const unknown = viewports.find(viewport => !VIEWPORTS[viewport])
  if (!mockup || !address || extra.length || unknown) return fail(unknown ? `no viewport "${unknown}"\n${USAGE}` : USAGE, 2)
  let browser
  let files = []
  try {
    browser = await launch()
    const { route, steps } = await walkthrough(browser, readFileSync(mockup, 'utf8'))
    const commit = execFileSync('git', ['-C', dirname(resolve(mockup)), 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
    const url = new URL(route.replace(/^\/+/, ''), address.replace(/\/*$/, '/')).href
    const videos = join(args.values.spool ?? `${realpathSync(mockup)}.review`, 'videos')
    files = viewports.map(viewport => ({ viewport, part: join(videos, `.${commit}-${viewport}.part.webm`), name: join(videos, `${commit}-${viewport}`) }))
    mkdirSync(videos, { recursive: true })
    for (const file of files) file.captions = await record(browser, url, steps, file.viewport, file.part)
    for (const { part, name, captions } of files) {
      writeFileSync(`${name}.vtt`, captions)
      renameSync(part, `${name}.webm`)
      console.log(`${name}.webm`)
    }
  } catch (e) {
    for (const { part } of files) rmSync(part, { force: true })
    fail(e.message, 1)
  } finally {
    await browser?.close()
  }
}

function fail(message, code) {
  console.error(`prototype-video: ${message}`)
  process.exitCode = code
}

// playwright-core's own Chromium, as install-octo-lite installs it (install.spec.html #install-recorder), or CHROME_PATH.
async function launch() {
  let chromium
  try {
    ({ chromium } = createRequire(import.meta.url)('playwright-core'))
  } catch {
    throw new Error(`playwright-core is not installed: run ${installer()}`)
  }
  try {
    return await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {})
  } catch (e) {
    throw new Error(`no browser starts (${e.message.split('\n')[0]}): run ${installer()}, or set CHROME_PATH`)
  }
}

// The installer's own fix line, with the prefix and project it last ran with, read from the after-pull step it
// publishes in the box's onboarding file (install.spec.html #install-after-pull); with none, the installer alone.
function installer() {
  const onboarding = join(process.env.XDG_STATE_HOME || join(homedir(), '.local/state'), 'octo-lite/onboarding.toml')
  try {
    const step = JSON.parse(readFileSync(onboarding, 'utf8').match(/^after_pull = (.*)$/m)[1])
    return step.filter(arg => arg !== '--after-pull').join(' ')
  } catch {
    return 'install-octo-lite'
  }
}

// One viewport's video into `file`, each action checked as it plays; returns its captions.
async function record(browser, url, steps, viewport, file) {
  const size = VIEWPORTS[viewport]
  const touch = viewport === 'phone'
  const { jpegjs } = createRequire(import.meta.url)('playwright-core/lib/utilsBundle')
  const context = await browser.newContext({ viewport: size, ...(touch && { isMobile: true, hasTouch: true }) })
  try {
    // The pointer the overlay draws (overlay.mjs): where it is, whether a phone's finger is on the screen, since when a
    // press is down, and where and when the last let go. The video opens on the first step's finished screen, the
    // cursor resting below the middle of it; a phone's finger is on the screen from when it reaches a part until it
    // lets go of it, or reaches the next.
    const pointer = { x: Math.round(size.width * 0.62), y: Math.round(size.height * 0.68), finger: false, down: null, lifted: null }
    const now = () => ({
      ...pointer,
      down: pointer.down === null ? null : Date.now() - pointer.down,
      lifted: pointer.lifted && { x: pointer.lifted.x, y: pointer.lifted.y, since: Date.now() - pointer.lifted.at },
    })
    await context.exposeBinding('octoLiteRecorder', now)
    await context.addInitScript(overlay, { ARROW, EDGE, MARK, TOUCH, touch })
    const page = await context.newPage()
    // A document the action opens asks for the pointer as it starts, so one this misses still draws it.
    const show = () => page.evaluate(state => dispatchEvent(new CustomEvent('octo-lite-recorder', { detail: state })), now())
      .catch(() => {})
    // A phone's touches are the browser's own touch events, as Playwright's tap sends them, so one can stay down.
    const cdp = touch && await context.newCDPSession(page)
    const finger = (type, { x, y } = pointer) =>
      cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] })
    let frames = []
    let latest = 0
    let held = null // the hold still down, let go before the next action

    // Waits for a frame of the video, from now, that shows the pointer at its point, with `mark` its press mark too; a
    // step whose video shows none fails, naming the step and its viewport.
    const seen = async (step, action, mark) => {
      const { x, y } = pointer
      const since = Date.now()
      const crops = []
      await until(() => {
        for (const frame of frames.splice(0)) {
          if (frame.timestamp >= since) crops.push(crop(jpegjs.decode(frame.data, { useTArray: true, formatAsRGBA: true }), x, y))
        }
        return crops.some(frame => shows(viewport, frame, mark))
      }, WAIT.video)
      verify(viewport, step.name, [{ action, crops, mark }])
    }

    // The pointer goes to the part, the page first scrolling it into view, and rests on it: inside it but off its words
    // (Stageshow motion.md, The cursor), else its middle, at the first point where a press would act on what Spec Chat
    // acts on, judged once it rests there, as its hover may show a part over that point; else it goes on to the next.
    // A phone's tap hovers the point before it presses there, so the mouse hovers it, the finger resting there as the
    // cause of that hover.
    const reach = async (step, action) => {
      const target = page.locator(action.selector).first()
      let box = await shown(step, target, action.selector)
      const { width, height } = page.viewportSize()
      if (box.x < 0 || box.y < 0 || box.x + box.width > width || box.y + box.height > height) {
        await target.evaluate(el => new Promise(done => {
          addEventListener('scrollend', done, { capture: true, once: true })
          setTimeout(done, 3000) // a page that cannot scroll it ends no scroll
          el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' })
        }))
        box = await shown(step, target, action.selector)
      }
      for (const point of points(box)) {
        if (!await lands(target, point)) continue
        if (touch) {
          if (pointer.finger) {
            pointer.finger = false // the finger leaves the part it rested on
            await show()
          }
          await sleep(PACE.reach)
          Object.assign(pointer, point, { finger: true })
          await show()
          await page.mouse.move(point.x, point.y)
        } else {
          await travel(pointer, point, (x, y) => page.mouse.move(x, y))
        }
        await sleep(PACE.rest)
        if (await lands(target, point)) return target
      }
      throw new Error(`step "${step.name}": ${action.kind === 'hover' ? 'the pointer' : 'a press'} on "${action.selector}" `
        + 'lands on another part, over it or acting inside it')
    }

    // The press goes down where the pointer is, its mark drawn first, so the video shows both before the page answers
    // it, however long the page then takes to draw; with no button, the mark alone. It comes up as `up` lets go. A
    // tap's touch ends without waiting on a page busy with its start, as Playwright's tap does.
    const press = async (step, label, button) => {
      pointer.down = Date.now()
      await show()
      await seen(step, label, true)
      const down = button && (touch ? finger('touchStart') : await page.mouse.down({ button }))
      return async () => {
        if (button && touch) await Promise.all([down, finger('touchEnd')])
        else if (button) await page.mouse.up({ button })
        await sleep(pointer.down + MARK.grow + MARK.full - Date.now())
        pointer.down = null
        pointer.lifted = { x: pointer.x, y: pointer.y, at: Date.now() }
        pointer.finger = false
        await show()
      }
    }

    // A hold lets go before the next action, and as the next step starts, which opens on what letting go does.
    const letGo = async () => {
      if (!held) return
      await held.up()
      held = null
      await settle(page)
    }

    // One action, as a person does it (#delivery-round-video-actions); then the motion it starts ends, as Spec Chat waits
    // (mockups #prototype-steps).
    const act = async (step, action) => {
      await letGo()
      const target = await reach(step, action)
      const label = {
        press: `press ${action.selector}`, type: `type into ${action.selector}`, menu: `open the menu of ${action.selector}`,
        hover: `hover ${action.selector}`, hold: `hold ${action.selector}${action.to ? ` to ${action.to}` : ''}`,
      }[action.kind]
      if (action.kind === 'hover') return seen(step, label, false)
      // A select picks its option with no list open: the list a browser draws apart from the page shows in no recording.
      const select = action.kind === 'type' && await target.evaluate(el => el.localName === 'select')
      const up = await press(step, label, select ? null : action.kind === 'menu' && !touch ? 'right' : 'left')
      if (select) {
        await target.selectOption({ label: action.text })
      } else if (action.kind === 'hold' || (action.kind === 'menu' && touch)) {
        if (!action.to) {
          held = { step, label, up }
          return settle(page)
        }
        // Held until the part `data-to` names shows, then carried there still down and let go on it.
        const to = page.locator(action.to).first()
        const box = await shown(step, to, action.to)
        let point
        for (const at of points(box)) if (!point && await lands(to, at)) point = at
        if (!point) throw new Error(`step "${step.name}": letting go on "${action.to}" lands on another part, over it or acting inside it`)
        await travel(pointer, point, touch ? (x, y) => finger('touchMove', { x, y }) : (x, y) => page.mouse.move(x, y))
        await show()
        await seen(step, label, true)
      } else {
        await sleep(PACE.press)
      }
      await up()
      if (action.kind === 'type' && !select) {
        await sleep(PACE.rest)
        if (await target.inputValue().catch(() => '')) await page.keyboard.press('ControlOrMeta+A')
        await page.keyboard.type(action.text, { delay: PACE.key })
      }
      await settle(page)
    }

    await page.goto(url)
    await settle(page)
    if (!touch) await page.mouse.move(pointer.x, pointer.y)
    const cues = []
    await page.screencast.start({ path: file, size, onFrame: frame => {
      frames.push(frame)
      latest = frame.timestamp
    } })
    for (const [n, step] of steps.entries()) {
      cues.push({ step, at: Date.now() })
      if (!n) await sleep(PACE.open)
      await letGo()
      for (const action of step.actions) await act(step, action)
      await settle(page) // a step the screen reaches on its own plays with the cursor at rest
      await sleep(n === steps.length - 1 ? PACE.last : PACE.hold)
      if (held) await seen(held.step, held.label, true) // a hold shows down for as long as it is down
      frames = []
    }
    // Every frame to the end of the last step reaches the video before it stops, so it holds that step's result.
    const end = Date.now()
    await until(() => latest >= end, WAIT.video)
    await page.screencast.stop()
    return captions(cues, timeline(file))
  } finally {
    await context.close()
  }
}

// Inside the part but off its words, else its middle.
function points(box) {
  return [[box.width > 40 ? 0.85 : 0.5, 0.6], [0.5, 0.5]]
    .map(([across, down]) => ({ x: Math.round(box.x + box.width * across), y: Math.round(box.y + box.height * down) }))
}

function lands(target, point) {
  return target.evaluate(pressesPart, { ...point, acts: ACTS })
}

// Whether a press at x, y presses the part as Spec Chat's click on it does: what lies there is the part or inside it,
// with nothing between that acts of its own.
function pressesPart(part, { x, y, acts }) {
  const hit = document.elementFromPoint(x, y)
  const own = hit?.closest(acts)
  return Boolean(hit && part.contains(hit) && (!own || own === part || !part.contains(own)))
}

// The part's box once it shows; it has none while the page has it hidden or is drawing it anew.
async function shown(step, target, selector) {
  let box = null
  await until(async () => (box = await target.boundingBox({ timeout: WAIT.part }).catch(() => null)), WAIT.part)
  if (!box) throw new Error(`step "${step.name}": nothing visible on the route matches "${selector}"`)
  return box
}

async function until(done, ms) {
  for (const by = Date.now() + ms; !await done() && Date.now() < by;) await sleep(20)
}

// The pointer travels on a slight arc, departing and arriving softly, in more time the further it goes.
async function travel(from, to, move) {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const ms = Math.min(1100, 420 + Math.hypot(dx, dy) * 0.45)
  const begun = Date.now()
  for (let t = 0; t < 1;) {
    await sleep(12)
    t = Math.min(1, (Date.now() - begun) / ms)
    const along = ease(t)
    const bow = Math.sin(Math.PI * along) * 0.06
    await move(...(t < 1 ? [from.x + dx * along - dy * bow, from.y + dy * along + dx * bow] : [to.x, to.y]))
  }
  Object.assign(from, to)
}

function ease(t) {
  const [x1, y1, x2, y2] = TRAVEL
  const curve = (a, b, u) => 3 * a * u * (1 - u) ** 2 + 3 * b * u * u * (1 - u) + u ** 3
  let [lo, hi] = [0, 1]
  for (let i = 0; i < 30; i++) {
    const mid = (lo + hi) / 2
    if (curve(x1, x2, mid) < t) lo = mid
    else hi = mid
  }
  return curve(y1, y2, (lo + hi) / 2)
}

// As Spec Chat's frames settle: a page an action opens loads, fonts arrive, and each finite motion the page started ends.
async function settle(page) {
  await sleep(50)
  for (let tries = 0; ; tries++) {
    try {
      await page.waitForLoadState()
      return await page.evaluate(async () => {
        await document.fonts.ready
        await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))
        const moving = document.getAnimations()
          .filter(a => a.id !== 'octo-lite-recorder' && Number.isFinite(a.effect?.getComputedTiming().endTime))
        await Promise.race([Promise.all(moving.map(a => a.finished.catch(() => {}))), new Promise(done => setTimeout(done, 5000))])
      })
    } catch (e) {
      if (tries) throw e // the page the action opened replaced the one asked; asked once more
    }
  }
}

// The video's own timeline, as Playwright's encoder writes it in the Segment Info of its Matroska file: the wall time
// its first frame stands for (DateUTC, the encoder's start, from which it times each frame), and its length (Duration).
function timeline(file) {
  const data = readFileSync(file)
  const vint = at => {
    let n = 1
    while (n < 8 && !(data[at] & (0x80 >> (n - 1)))) n++
    let value = data[at] & (0xff >> n)
    for (let i = 1; i < n; i++) value = value * 256 + data[at + i]
    return { n, value }
  }
  const info = { scale: 1e6 }
  for (let at = 0; at < data.length && (info.date === undefined || info.length === undefined);) {
    const id = vint(at)
    const size = vint(at + id.n)
    const body = at + id.n + size.n
    const element = data.readUIntBE(at, id.n)
    if (element === 0x18538067 || element === 0x1549a966) { // Segment and Info, read inside
      at = body
      continue
    }
    if (element === 0x2ad7b1) info.scale = data.readUIntBE(body, size.value)
    if (element === 0x4489) info.length = size.value === 4 ? data.readFloatBE(body) : data.readDoubleBE(body)
    if (element === 0x4461) info.date = Number(data.readBigInt64BE(body) / 1000000n) + Date.UTC(2001, 0, 1)
    at = body + size.value
  }
  return { origin: info.date, length: info.length * info.scale / 1e6 }
}

// mockups #round-video-store: the step captions, each timed on the video's own timeline from its step's start to the
// next's, the last to the video's end.
function captions(cues, { origin, length }) {
  const time = ms => new Date(ms).toISOString().slice(11, 23)
  const text = caption => caption.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return ['WEBVTT', ...cues.map(({ step, at }, n) =>
    `${step.name}\n${time(n && at - origin)} --> ${time(n + 1 < cues.length ? cues[n + 1].at - origin : length)}\n${text(step.caption)}`)]
    .join('\n\n') + '\n'
}
