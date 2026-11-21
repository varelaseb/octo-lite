// The report skill's self-check (SKILL.md, Self-check): node self-check.mjs <report folder>
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const dir = path.resolve(process.argv[2])
const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)])
const bad = [], trust = ['paper', 'preprint', 'primary', 'practitioner', 'vendor', 'unverified']
const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {})
for (const [width, colorScheme] of [[390, 'light'], [390, 'dark'], [1280, 'light']]) {
  const page = await browser.newPage({ viewport: { width, height: 844 }, colorScheme })
  await page.goto(pathToFileURL(path.join(dir, 'summary.html')).href)
  await page.screenshot({ path: path.join(os.tmpdir(), `summary-${width}-${colorScheme}.png`), fullPage: true })
  if (await page.evaluate(() => [document.documentElement, ...document.querySelectorAll('*')].some(e => e.scrollWidth > e.clientWidth + 1 && (e === document.documentElement || /auto|scroll/.test(getComputedStyle(e).overflowX)))))
    bad.push(`summary.html scrolls sideways at ${width}px`)
  await page.close()
}
for (const file of walk(dir)) if (!/^([a-z0-9-]+\/)*[a-z0-9-]+(\.[a-z0-9]+)?$/.test(path.relative(dir, file))) bad.push(`${path.relative(dir, file)}: name not [a-z0-9-]+`)
const page = await browser.newPage()
for (const file of walk(dir).filter(f => f.endsWith('.html'))) {
  await page.goto(pathToFileURL(file).href)
  const p = await page.evaluate(trust => ({
    links: [...document.querySelectorAll('a[href]')].map(a => a.href),
    title: document.title, scripts: document.querySelectorAll('script, form, iframe, frame, object, embed').length,
    dark: [...document.querySelectorAll('style')].some(e => e.textContent.includes('prefers-color-scheme')),
    comment: [...document.querySelectorAll('*')].some(e => [...e.attributes].some(a => a.name.startsWith('data-comment-'))),
    ids: [...document.querySelectorAll('[data-anchor]')].map(e => e.dataset.anchor === e.id ? e.id : `!${e.dataset.anchor}`),
    loose: [...document.querySelectorAll('h1, h2, h3, p, li, figure, table, blockquote')].filter(e => !e.closest('[data-anchor]:is(h1, h2, h3, p, li, figure, table, blockquote, article, header, footer)')).length,
    findings: [...document.querySelectorAll('.finding')].filter(f => !f.querySelector('a[href]') || !f.querySelector('time') || !trust.includes(f.querySelector('.trust')?.textContent.trim())).map(f => f.id),
  }), trust)
  const at = path.relative(dir, file)
  if (!p.title || !p.dark || p.scripts || p.comment) bad.push(`${at}: needs a title and a dark scheme, no script, form, frame, plugin, or data-comment-*`)
  p.ids.filter((id, i) => id.startsWith('!') || p.ids.indexOf(id) !== i).forEach(id => bad.push(`${at}: anchor ${id} not unique or not its id`))
  if (p.loose) bad.push(`${at}: ${p.loose} blocks without data-anchor`)
  p.findings.forEach(id => bad.push(`${at}: finding ${id} lacks a source link, a date read, or a trust label`))
  for (const link of p.links) {
    const [target, hash] = link.split('#')
    if (target.startsWith('file:')) {
      const to = fileURLToPath(target)
      if (!fs.existsSync(to)) bad.push(`${at}: ${link} not found`)
      else if (hash && to.endsWith('.html') && !fs.readFileSync(to, 'utf8').includes(`id="${hash}"`)) bad.push(`${at}: ${link} has no such anchor`)
    } else if (/^https?:/.test(target)) {
      const r = await fetch(target, { signal: AbortSignal.timeout(20000) }).catch(e => ({ status: e.message }))
      if (!(r.status < 400)) bad.push(`${at}: ${link} answers ${r.status}`)
    }
  }
}
await browser.close()
console.log(bad.length ? bad.join('\n') : 'ok')
