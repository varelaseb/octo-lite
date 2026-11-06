// A prototype mockup file's route and walkthrough, read as Spec Chat reads them (mockups #prototype-file,
// #prototype-steps, #markup-steps): the route in <meta name="mockup-prototype">, and each <li data-step> of
// <ol data-mockup-steps> with its caption, its text outside the nested list, and the actions that reach it from the
// step before, the items of that list: data-press with a selector, data-type with a selector and data-text.
// An action the recorder does not know fails here, naming its step and the action, before any browser starts
// (octo-lite #delivery-round-video), so no video skips one.

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'])
const RAW = new Set(['script', 'style'])
const NAMED = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: '\u00a0', lsquo: '\u2018', rsquo: '\u2019', ldquo: '\u201c', rdquo: '\u201d', hellip: '\u2026', middot: '\u00b7', times: '\u00d7' }

function decode(text) {
  return text.replace(/&(?:#(x[0-9a-f]+|\d+)|([a-z]+));/gi, (whole, code, name) => !code ? NAMED[name] ?? whole
    : String.fromCodePoint(code[0] === 'x' || code[0] === 'X' ? parseInt(code.slice(1), 16) : Number(code)))
}

function attributes(source) {
  const found = {}
  for (const [, name, double, single, bare] of source.matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
    found[name.toLowerCase()] = decode(double ?? single ?? bare ?? '')
  }
  return found
}

// The page as a tree of elements and text, enough for the markup a mockup file holds.
function parse(html) {
  const root = { tag: '#root', attrs: {}, children: [] }
  const open = [root]
  const tags = /<!--[\s\S]*?-->|<!\w[^>]*>|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^'">])*)>/g
  let at = 0
  for (let m; (m = tags.exec(html));) {
    if (m.index > at) open.at(-1).children.push(decode(html.slice(at, m.index)))
    at = tags.lastIndex
    const [, closing, tag, rest] = m
    if (closing) {
      const i = open.findLastIndex(el => el.tag === closing.toLowerCase())
      if (i > 0) open.length = i
    } else if (tag) {
      const el = { tag: tag.toLowerCase(), attrs: attributes(rest), children: [] }
      open.at(-1).children.push(el)
      if (RAW.has(el.tag)) {
        const end = html.toLowerCase().indexOf(`</${el.tag}`, at)
        at = tags.lastIndex = end < 0 ? html.length : end
      } else if (!VOID.has(el.tag) && !rest.trim().endsWith('/')) open.push(el)
    }
  }
  return root
}

const elements = el => el.children.filter(child => typeof child !== 'string')

function* within(el) {
  for (const child of elements(el)) {
    yield child
    yield* within(child)
  }
}

function text(el, skip = new Set()) {
  return el.children.map(c => typeof c === 'string' ? c : skip.has(c.tag) ? ' ' : text(c, skip)).join('')
}

// Each action an item names: one Spec Chat plays, else the name of the one it does not know.
function action(step, item) {
  if ('data-press' in item.attrs) return { press: item.attrs['data-press'] }
  if ('data-type' in item.attrs) return { type: item.attrs['data-type'], text: item.attrs['data-text'] ?? '' }
  const named = Object.keys(item.attrs).find(name => name.startsWith('data-'))
  const what = named ? named.slice(5) : text(item).trim() || `<${item.tag}>`
  throw new Error(`step "${step}" is reached by the action "${what}", which the recorder does not know`)
}

export function walkthrough(html) {
  const page = parse(html)
  const meta = [...within(page)].find(el => el.tag === 'meta' && el.attrs.name === 'mockup-prototype')
  const route = meta?.attrs.content?.trim()
  if (!route) throw new Error('the mockup file names no route in <meta name="mockup-prototype">')
  const list = [...within(page)].find(el => 'data-mockup-steps' in el.attrs)
  const steps = list ? [...within(list)].filter(el => 'data-step' in el.attrs && el.attrs['data-step'].trim()).map(item => {
    const name = item.attrs['data-step'].trim()
    const actions = elements(item).filter(el => ['ul', 'ol'].includes(el.tag)).flatMap(list => elements(list).filter(el => el.tag === 'li'))
    return {
      name,
      caption: text(item, new Set(['ul', 'ol'])).replace(/\s+/g, ' ').trim(),
      actions: actions.map(el => action(name, el)).filter(a => (a.press ?? a.type).trim()),
    }
  }) : []
  if (!steps.length) throw new Error('the mockup file holds no walkthrough steps in <ol data-mockup-steps>')
  return { route, steps }
}
