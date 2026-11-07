// A prototype mockup file's route and walkthrough, read as Spec Chat reads them (mockups #prototype-file,
// #prototype-steps, #markup-steps): the browser parses the file and its DOM is read as Spec Chat's walkthroughOf reads
// it, for the route in <meta name="mockup-prototype"> and each [data-step] of [data-mockup-steps] with its caption,
// its text outside its lists, and the actions that reach it from the step before, the items of a list in it:
// data-press with a selector, data-type with a selector and data-text.
// An action the recorder does not know fails here, naming its step and the action, before any recording starts
// (octo-lite #delivery-round-video), so no video skips one.

export async function walkthrough(browser, html) {
  const page = await browser.newPage()
  let read
  try {
    read = await page.evaluate(readSteps, html)
  } finally {
    await page.close()
  }
  const { route, steps } = read
  if (!route) throw new Error('the mockup file names no route in <meta name="mockup-prototype">')
  if (!steps.length) throw new Error('the mockup file holds no walkthrough steps in [data-mockup-steps]')
  for (const step of steps) {
    const unknown = step.actions.find(action => action.unknown)
    if (unknown) throw new Error(`step "${step.name}" is reached by the action "${unknown.unknown}", which the recorder does not know`)
  }
  return { route, steps }
}

// Runs in the browser, which parses the file as Spec Chat's page does.
function readSteps(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const text = (node, skip) => {
    const parts = []
    const walk = parent => {
      for (const child of parent.childNodes) {
        if (child.nodeType === 3) parts.push(child.nodeValue)
        else if (child.nodeType === 1 && !child.matches(skip)) walk(child)
      }
    }
    walk(node)
    return parts.join('').split(/\s+/).filter(Boolean).join(' ')
  }
  const action = el => el.hasAttribute('data-press') ? { press: el.getAttribute('data-press') }
    : el.hasAttribute('data-type') ? { type: el.getAttribute('data-type'), text: el.getAttribute('data-text') || '' }
    : { unknown: el.getAttributeNames().find(name => name.startsWith('data-'))?.slice(5) || text(el, 'script,style') || `<${el.localName}>` }
  const list = doc.querySelector('[data-mockup-steps]')
  return {
    route: doc.querySelector('meta[name="mockup-prototype"]')?.content.trim(),
    steps: list ? [...list.querySelectorAll('[data-step]')].map(item => ({
      name: item.getAttribute('data-step').trim(),
      caption: text(item, 'script,style,ul,ol'),
      actions: [...item.querySelectorAll(':is(ul, ol) > li, [data-press], [data-type]')].map(action)
        .filter(a => a.unknown || (a.press ?? a.type).trim()),
    })).filter(step => step.name) : [],
  }
}
