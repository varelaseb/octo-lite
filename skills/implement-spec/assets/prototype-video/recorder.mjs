// octo-lite's one round video recorder (octo-lite #delivery-round-video), which every prototype worker runs and none
// writes for its lane. It reads the screen's mockup file, loads its route on the worker's running prototype, and
// reaches each walkthrough step by its actions as Spec Chat does (mockups #prototype-steps), as a person would, at the
// pace of Stageshow's motion rules: the cursor, on a phone a touch, travels to each part an action names, the page
// first scrolling it into view, rests on it so its hover shows, and presses it with a mark where, judged with the hover
// the press will have, the press lands on what Spec Chat presses; typed text goes in one key at a time; each change
// plays at the product's own speed and each step's result holds before the next. It checks each video (check.mjs) and
// keeps every viewport's, with its captions, where Spec Chat reads them (mockups #round-video-store), only once all pass.

import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { crop, verify } from './check.mjs'
import { walkthrough } from './mockup.mjs'
import { ARROW, EDGE, MARK, TOUCH, overlay } from './overlay.mjs'

const USAGE = 'usage: prototype-video <mockup.html> <prototype-address> [--viewport desktop|phone]... [--spool <mockup>.review]'
// The sizes Spec Chat frames a prototype at (mockups #frame-viewports).
const VIEWPORTS = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } }
// Stageshow motion.md, Pace and easing: travel's curve, and a person's timing in ms.
const TRAVEL = [0.45, 0, 0.1, 1]
const PACE = { open: 1200, reach: 500, rest: 400, press: 90, key: 90, hold: 1400, last: 2200 }
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

// One viewport's video into `file`, each step checked once its result has held; returns its captions.
async function record(browser, url, steps, viewport, file) {
  const size = VIEWPORTS[viewport]
  const touch = viewport === 'phone'
  const { jpegjs } = createRequire(import.meta.url)('playwright-core/lib/utilsBundle')
  const context = await browser.newContext({ viewport: size, ...(touch && { isMobile: true, hasTouch: true }) })
  try {
    // The video opens on the first step's finished screen, the cursor resting below the middle of it.
    const pointer = { x: Math.round(size.width * 0.62), y: Math.round(size.height * 0.68) }
    const presses = []
    // What each document the page opens draws first (overlay.mjs): the cursor at rest, a phone's touch resting
    // nowhere, and the last press, so one that opened the document still shows.
    await context.exposeBinding('octoLiteRecorder', () => {
      const last = presses.at(-1)
      return { rest: !touch && pointer, last: last && { x: last.x, y: last.y, since: Date.now() - last.at } }
    })
    await context.addInitScript(overlay, { ARROW, EDGE, MARK, TOUCH, touch })
    const page = await context.newPage()
    await page.goto(url)
    await settle(page)
    if (!touch) await page.mouse.move(pointer.x, pointer.y)
    const frames = []
    const cues = []
    const decode = frame => jpegjs.decode(frame.data, { useTArray: true, formatAsRGBA: true })
    const start = Date.now()
    await page.screencast.start({ path: file, size, onFrame: ({ data, timestamp }) => { frames.push({ data, timestamp }) } })
    for (const [n, step] of steps.entries()) {
      cues.push({ step, at: n && Date.now() - start })
      if (!n) await sleep(PACE.open)
      for (const action of step.actions) await act(page, step, action, touch, pointer, presses)
      await settle(page) // a step the screen reaches on its own plays with the cursor at rest
      await sleep(n === steps.length - 1 ? PACE.last : PACE.hold)
      verify(viewport, step.name, presses.splice(0).map(({ action, x, y, at }) => {
        const [from, to] = MARK.full.map(ms => at + ms)
        const seen = [frames.findLast(f => f.timestamp <= from), ...frames.filter(f => f.timestamp > from && f.timestamp <= to)]
        return { action, crops: seen.filter(Boolean).map(f => crop(decode(f), x, y)) }
      }))
      frames.splice(0, frames.length - 1)
    }
    const end = Date.now() - start
    await page.screencast.stop()
    return captions(cues, end)
  } finally {
    await context.close()
  }
}

// One action, as a person does it; then the motion it starts ends, as Spec Chat waits (mockups #prototype-steps).
async function act(page, step, action, touch, pointer, presses) {
  const selector = action.press ?? action.type
  const target = page.locator(selector).first()
  try {
    await target.waitFor({ state: 'visible', timeout: 5000 })
  } catch {
    throw new Error(`step "${step.name}": nothing visible on the route matches "${selector}"`)
  }
  let box = await target.boundingBox()
  const { width, height } = page.viewportSize()
  if (box.x < 0 || box.y < 0 || box.x + box.width > width || box.y + box.height > height) {
    await target.evaluate(el => el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' }))
    box = await scrolled(target)
  }
  // Inside the part but off its words (Stageshow motion.md, The cursor), else its middle. The cursor goes to the first
  // where a press would press what Spec Chat presses, and presses once it has rested there if a press still would,
  // judged then, as its hover may show a part over that point; else it goes on to the next. A phone's tap hovers the
  // point before it presses there, so the mouse, which a phone's overlay never draws, hovers it first.
  const lands = point => target.evaluate(pressesPart, { ...point, acts: ACTS })
  let to
  for (const [across, down] of [[box.width > 40 ? 0.85 : 0.5, 0.6], [0.5, 0.5]]) {
    const point = { x: Math.round(box.x + box.width * across), y: Math.round(box.y + box.height * down) }
    if (!await lands(point)) continue
    if (touch) {
      await sleep(PACE.reach)
      await page.mouse.move(point.x, point.y)
    } else {
      await travel(page, pointer, point)
    }
    await sleep(PACE.rest)
    if (await lands(point)) {
      to = point
      break
    }
  }
  if (!to) throw new Error(`step "${step.name}": a press on "${selector}" lands on another part, over it or acting inside it`)
  presses.push({ action: `${action.press ? 'press' : 'type into'} ${selector}`, ...to, at: Date.now() })
  if (touch) {
    await page.touchscreen.tap(to.x, to.y)
  } else {
    await page.mouse.down()
    await sleep(PACE.press)
    await page.mouse.up()
  }
  if (action.type !== undefined) {
    await sleep(PACE.rest)
    if (await target.inputValue().catch(() => '')) await page.keyboard.press('ControlOrMeta+A')
    await page.keyboard.type(action.text, { delay: PACE.key })
  }
  await settle(page)
}

// Whether a press at x, y presses the part as Spec Chat's click on it does: what lies there is the part or inside it,
// with nothing between that acts of its own.
function pressesPart(part, { x, y, acts }) {
  const hit = document.elementFromPoint(x, y)
  const own = hit?.closest(acts)
  return Boolean(hit && part.contains(hit) && (!own || own === part || !part.contains(own)))
}

// Where the part comes to rest once the page has scrolled it into view.
async function scrolled(target) {
  let last = await target.boundingBox()
  for (let n = 0; n < 60; n++) {
    await sleep(50)
    const box = await target.boundingBox()
    if (box.x === last.x && box.y === last.y) return box
    last = box
  }
  return last
}

// The cursor travels on a slight arc, departing and arriving softly, in more time the further it goes.
async function travel(page, from, to) {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const ms = Math.min(1100, 420 + Math.hypot(dx, dy) * 0.45)
  const begun = Date.now()
  for (let t = 0; t < 1;) {
    await sleep(12)
    t = Math.min(1, (Date.now() - begun) / ms)
    const along = ease(t)
    const bow = Math.sin(Math.PI * along) * 0.06
    await page.mouse.move(...(t < 1 ? [from.x + dx * along - dy * bow, from.y + dy * along + dx * bow] : [to.x, to.y]))
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

// mockups #round-video-store: the step captions, each timed from its step's start to the next's.
function captions(cues, end) {
  const time = ms => new Date(ms).toISOString().slice(11, 23)
  const text = caption => caption.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return ['WEBVTT', ...cues.map(({ step, at }, n) => `${step.name}\n${time(at)} --> ${time(cues[n + 1]?.at ?? end)}\n${text(step.caption)}`)]
    .join('\n\n') + '\n'
}
