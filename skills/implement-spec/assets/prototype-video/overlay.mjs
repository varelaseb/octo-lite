// The cursor, the touch, and the press mark the recorder draws over the page it records (octo-lite
// #delivery-round-video): a browser's recording shows none of them, so the recorder adds them to its own page, never to
// product code. Each is dark with a white edge, so it reads on any screen, and the check reads it back out of the
// video's frames by the same shapes (check.mjs).

// The arrow, its hotspot at 0,0, and the white edge drawn outside its dark body, in px.
export const ARROW = [[0, 0], [0, 17], [4, 13.4], [6.9, 19.8], [9.8, 18.6], [7, 12.3], [12.2, 12.3]]
export const EDGE = 2
// A ring: a dark band inside its radius and a white halo outside it. A touch rests on the point while the finger is
// down; the press mark lands on the point, full size within `full[0]` ms and holding until `full[1]`, then spreads and
// fades, as Stageshow's ripple does.
export const TOUCH = { radius: 13, band: 3, halo: 2.5 }
export const MARK = { radius: 21, band: 4, halo: 3, ms: 650, full: [70, 330] }

// Runs in each document the recording page loads, before the page's own scripts. A phone draws the touch on each
// touchstart; a desktop draws the arrow wherever the mouse is and the mark on each mousedown. The overlay sits in the top
// layer and goes back on top whenever the page opens a dialog or popover there, so nothing the page shows covers it.
export function overlay({ ARROW, EDGE, TOUCH, MARK, touch }) {
  const host = document.createElement('octo-lite-cursor')
  host.setAttribute('popover', 'manual')
  host.style.cssText = 'all: initial; position: fixed; inset: 0; width: 100vw; height: 100vh; margin: 0; padding: 0; '
    + 'border: 0; background: transparent; overflow: visible; pointer-events: none; z-index: 2147483647'
  const root = host.attachShadow({ mode: 'closed' })
  const ring = ({ radius, band, halo }) => `width: ${2 * radius}px; height: ${2 * radius}px; margin: ${-radius}px 0 0 ${-radius}px; `
    + `box-sizing: border-box; border-radius: 50%; border: ${band}px solid #111; box-shadow: 0 0 0 ${halo}px #fff`
  root.innerHTML = `<style>
    .at { position: absolute; left: 0; top: 0 }
    svg { display: block; overflow: visible; filter: drop-shadow(0 1px 1.5px rgba(0, 0, 0, 0.25)) }
    path { fill: #111; stroke: #fff; stroke-width: ${2 * EDGE}px; stroke-linejoin: round; paint-order: stroke }
    .touch { ${ring(TOUCH)}; background: rgba(255, 255, 255, 0.3); opacity: 0; transition: opacity 0.3s ease }
    .touch[data-down] { opacity: 1; transition-duration: 0.06s }
    .mark { position: absolute; ${ring(MARK)} }
  </style>`
  const cursor = document.createElement('div')
  cursor.className = 'at'
  cursor.style.display = 'none'
  cursor.innerHTML = touch ? '<div class="touch"></div>'
    : `<svg width="1" height="1"><path d="M${ARROW.map(p => p.join(' ')).join(' L')} Z"/></svg>`
  root.append(cursor)
  const mount = () => {
    if (host.isConnected || !document.documentElement) return
    document.documentElement.append(host)
    host.showPopover()
  }
  const place = (x, y) => {
    mount()
    cursor.style.display = ''
    cursor.style.transform = `translate(${x}px, ${y}px)`
  }
  const mark = (x, y) => {
    const el = document.createElement('div')
    el.className = 'mark'
    el.style.left = `${x}px`
    el.style.top = `${y}px`
    root.insertBefore(el, cursor) // under the cursor, which presses through it
    const [grown, held] = MARK.full.map(ms => ms / MARK.ms)
    const animation = el.animate([
      { transform: 'scale(0.7)', opacity: 1, easing: 'ease-out' },
      { transform: 'scale(1)', opacity: 1, offset: grown },
      { transform: 'scale(1)', opacity: 1, offset: held, easing: 'cubic-bezier(0.25, 0.8, 0.25, 1)' },
      { transform: 'scale(1.25)', opacity: 0 },
    ], MARK.ms)
    animation.id = 'octo-lite-recorder' // the recorder's own motion, which a step never waits on
    animation.finished.then(() => el.remove())
  }
  const options = { capture: true, passive: true }
  if (touch) {
    let lift
    addEventListener('touchstart', e => {
      const { clientX: x, clientY: y } = e.touches[0]
      place(x, y)
      clearTimeout(lift)
      cursor.firstChild.setAttribute('data-down', '')
      mark(x, y)
    }, options)
    // The finger lifts away slowly enough for its press to read.
    addEventListener('touchend', () => { lift = setTimeout(() => cursor.firstChild.removeAttribute('data-down'), 350) }, options)
  } else {
    addEventListener('mousemove', e => place(e.clientX, e.clientY), options)
    addEventListener('mousedown', e => mark(e.clientX, e.clientY), options)
  }
  addEventListener('toggle', e => {
    if (e.target !== host && e.newState === 'open' && host.isConnected) {
      host.hidePopover()
      host.showPopover()
    }
  }, true)
  addEventListener('DOMContentLoaded', mount)
}
