---
name: report
description: Answer a human a question in writing as a report, an executive summary and its research findings, two self-contained pages per question that Proof publishes for comments. Any agent loads it to write one, a researcher, a lane owner, or the fleet operator.
---

# Report

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Spec: octo-lite [`spec/domains/octo-lite.spec.html#roles-report`](https://github.com/varelaseb/octo-lite/blob/main/spec/domains/octo-lite.spec.html#roles-report), its [summary](https://github.com/varelaseb/octo-lite/blob/main/spec/domains/octo-lite.spec.html#roles-report-summary) and [findings](https://github.com/varelaseb/octo-lite/blob/main/spec/domains/octo-lite.spec.html#roles-report-findings).
A report is an output, never a spec: it is never on a branch.

## Folder

One folder per question, named `<question>` or `<name>`, lowercase `[a-z0-9-]+`, never reused:

- In a lane: `$(octo-lite-state)/lanes/<lane record name>-notes/reports/<question>/`. It moves into the archive with the lane's notes at lane close.
- Outside any lane: `$(octo-lite-state)/research/<name>/`.

Files:

- `summary.html`, the executive summary, and `findings.html`, the research findings: the latest round.
- `round-<n>/summary.html` and `round-<n>/findings.html`, each earlier round, `n` from 1.
- Everything a page shows sits in the folder, linked relatively.
- Every folder and file name in it is `[a-z0-9-]+`, plus `.html` or an asset's extension; no dotfiles.

Each page is self-contained HTML that needs no script: `<!doctype html>`, `<meta name="viewport" content="width=device-width, initial-scale=1">`, its `<title>` the report title, its styles in one `<style>`. Proof's page policy allows only the comment layer it injects, so a page has no `<script>`, form, frame, or plugin: a chart is SVG, an image, or markup.

## Blocks

- Every block, such as a heading, paragraph, finding, chart, question, or list item, is an element with `data-anchor="<id>"` and the same `id`, unique on its page, so a link's `#<id>` lands on it. Keep a block's id across rounds while the block lives; a new block gets a new id.
- A question block also carries `data-answers="A, B, C"`, your pick first, no comma inside an answer, and shows the pick's reason in one line.
- A claim links the finding behind it: `findings.html#<id>`.
- Load no comment layer and write no `data-comment-*` attribute: Proof injects the layer and sets every comment attribute itself, labelling a block by its own heading, else its text, and offering a question's `data-answers` as starters. A block's thread follows its id across rounds.

## Summary

A reader who is not an engineer takes it in within minutes, on a phone or a desktop. It carries only what bears on the question.

- Headline: the answer, in one plain sentence. Under it one plain line and at most three numbers that carry it, each beside what it compares to, such as `62% of teams, against 30% a year ago`.
- Each section's heading states its finding as a sentence, never a topic label, and shows it in the one form that makes it plain: a number, a chart (inline SVG or CSS), a comparison, a ladder, or a few real examples. The findings decide the sections and their forms; there is no fixed template.
- Each decision it needs is one question block naming its answers, your pick first with its one-line reason, where the reader meets the findings it rests on. The comment control offers the answers as starters.
- Every claim links its finding.
- Closing line: how the research was done, what it read and whether it changed anything (`read production without changing it`), what it cost, whose names it shows, and when. A later round links the round before here (Rounds).
- No customer's name or personal data, anywhere.
- Nothing scrolls sideways at a phone's width: stack what a wide table would show.

## Findings

Every finding the research made, whether or not the summary uses it. In this order:

1. The plan: each answer the question could have and the evidence that would settle it.
2. The findings: one `<article class="finding">` block each, giving the finding in one sentence, its source linked at the exact place (a page's anchor, a post, a file's line at a commit, or a query with what it read, as a file in the folder), the date read as `<time>`, and its trust label as `<span class="trust">`:
   - `paper`: a peer-reviewed study.
   - `preprint`: a study not yet peer reviewed.
   - `primary`: from the source's own owner, such as a platform's own help page.
   - `practitioner`: a named person's or team's own account of what they do or found, such as an engineering post or a post on X.
   - `vendor`: a seller's claim about itself.
   - `unverified`: from memory, when the source could not be fetched.

   A study's finding names its authors, year, venue, link by DOI or preprint id, what it measured and on how many, and the number the summary uses. A practice's finding names who follows it, when they said so, and any practice it replaced. A post's finding names its author, date, and link. A finding links its source and never restates another finding.
3. Dead ends: each direction tried that came to nothing, such as a search that found nothing, a source that did not hold up, or an answer the evidence ruled out, with what was tried and why it failed.
4. Gaps: each source sought and not read, why, and what that leaves unknown.

## Look

Draw both light and dark, through `@media (prefers-color-scheme: dark)`. Draw in the target product's own design system when its root `AGENTS.md` or `CLAUDE.md` declares one, such as a `DESIGN.md`: its type, colors, and shared parts, their tokens and styles copied into the page's `<style>` and any font file into the folder, so the report reads as the product's own document. With none declared, follow `frontend-design` and `clean-copy`.

## Rounds

A hand-off on either page starts the next round. Before rewriting, move the top-level pair and what only it shows into `round-<n>/`, `n` the round it was, and add `../` to each of its relative links that leaves that pair. Then read the round before's findings, its dead ends first, retry none of them, and rewrite both pages for what the round settles: the summary answers each comment's point and its closing line links `round-<n>/summary.html`, the round before.

## Self-check

Before any link to the report goes out, render the summary at a phone's width and a desktop's, and check every link in every page of the folder (headless Chromium from the octo-lite clone's `playwright-core`; `CHROME_PATH` overrides):

```sh
root="$(dirname "$(dirname "$(readlink -f ~/.claude/skills/report)")")"
node - "$root" <report folder> <<'EOF'
const [root, dir] = process.argv.slice(2), fs = require('fs'), path = require('path'), { pathToFileURL, fileURLToPath } = require('url')
const { chromium } = require(path.join(root, 'node_modules/playwright-core'))
const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)])
const bad = [], trust = ['paper', 'preprint', 'primary', 'practitioner', 'vendor', 'unverified']
;(async () => {
  const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {})
  for (const [width, colorScheme] of [[390, 'light'], [390, 'dark'], [1280, 'light']]) {
    const page = await browser.newPage({ viewport: { width, height: 844 }, colorScheme })
    await page.goto(pathToFileURL(path.join(dir, 'summary.html')).href)
    await page.screenshot({ path: path.join(process.env.TMPDIR, `summary-${width}-${colorScheme}.png`), fullPage: true })
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
})()
EOF
```

Then:

1. Read each screenshot in `$TMPDIR`, phone light and dark and desktop, as the reader would, knowing only the question, and fix what reads unclear.
2. Fix each line it prints; a site that refuses a script but opens in WebFetch is fine. The script checks an outside link's page, not its `#`: open each outside link with one and see it lands where it names.
3. Read the summary once more: every claim links a finding, and every finding links its source.

## Publishing

Proof serves the folder, each page as a host of Spec Chat's comment layer, at the report's address, under Proof's address, the evidence address the box's operating model names:

- A lane report: `<Proof's address>/reports/<lane record name>/<question>/`. Proof reads it from the lane's notes, else from their archive, so the address outlives the lane.
- Outside any lane: `<Proof's address>/research/<name>/`.

The folder's address shows `summary.html`; `findings.html`, `round-<n>/`, whose index is its `summary.html`, and each asset sit at their paths under it. Only once the self-check passes does the address go to anyone.

- A lane report's comments land in the lane's review scope, its slug the lane record's `issue` lowercased with the hyphen removed (`ANN-336` is `ann336`), and its hand-off wakes the lane owner. The owner registers that scope row when the lane has none, `review-host register --slug <slug> --owner "${HERDR_SESSION:-default}/$HERDR_PANE_ID"`, and removes it at teardown with the lane's other review rows.
- A report outside any lane: its comments land in the fleet operator's scope row, slug `operator`, which the fleet operator registers once the same way, and wake it.
- On a box without Proof the report is still written; its owner reports Proof missing once as a problem of the box, naming the folder.
