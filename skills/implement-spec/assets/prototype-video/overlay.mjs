// The cursor, the touch, the press mark, and the item a browser lifts in a drag, which the recorder draws over the page
// it records (octo-lite #delivery-round-video): a browser's recording shows none of them, so the recorder adds them to
// its own page, never to product code. Each is dark with a white edge, so it reads on any screen, and the check reads
// the cursor, the touch, and the mark back out of the video's frames by the same shapes (check.mjs).

// The arrow, its hotspot at 0,0, and the white edge drawn outside its dark body, in px.
export const ARROW = [[0, 0], [0, 17], [4, 13.4], [6.9, 19.8], [9.8, 18.6], [7, 12.3], [12.2, 12.3]]
export const EDGE = 2
// A ring: a dark band inside its radius and a white halo outside it. A touch rests on the point while the finger is
// on the screen. The press mark grows onto the point in `grow` ms as a press goes down and stays full while it is
// down, travelling with a held press, then spreads and fades in `fade` ms once let go, as Stageshow's ripple does; a
// press the recorder lets go at once stays down `full` ms once grown, so it reads.
export const TOUCH = { radius: 13, band: 3, halo: 2.5 }
export const MARK = { radius: 21, band: 4, halo: 3, grow: 70, full: 260, fade: 320 }

// Runs in each document the recording page loads, before the page's own scripts. It draws what the recorder's pointer
// is (recorder.mjs), asked of the recorder as the document starts and handed over on each change: where it is,
// whether a phone's finger is on the screen, since when a press is down, and the last press let go. Between changes it
// follows the events the pointer sends: a desktop's mouse moves, a phone's finger slides, and a drag's moves. An item
// the browser lifts in a drag it draws as the page drew it, lifted under the pointer, until it drops.
// A part of it always moves, so the page keeps drawing frames however still the screen or busy the page, and each
// frame the video shows what the pointer is then. The overlay sits in the top layer and goes back on top whenever the
// page opens a dialog or popover there, so nothing the page shows covers it.
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
    .beat { position: absolute; left: 0; top: 0; width: 1px; height: 1px; background: #000; opacity: 0.01 }
  </style><div class="beat"></div>`
  const own = (el, keyframes, options) => {
    const animation = el.animate(keyframes, options)
    animation.id = 'octo-lite-recorder' // the recorder's own motion, which a step never waits on
    return animation
  }
  own(root.lastChild, [{ transform: 'translateX(0)' }, { transform: 'translateX(1px)' }],
    { duration: 1000, iterations: Infinity, direction: 'alternate' })
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

  let state = null
  let mark = null // the mark of the press down now
  let item = null // the item a drag lifts, and where under the pointer it was taken up
  const ringAt = (x, y) => {
    const el = document.createElement('div')
    el.className = 'mark'
    el.style.transform = `translate(${x}px, ${y}px)`
    root.insertBefore(el, cursor) // under the cursor, which presses through it
    return el
  }
  // A press let go `since` ms ago at x, y, as one let go in the document before goes on in this one.
  const fade = (x, y, since) => {
    const el = ringAt(x, y)
    const at = `translate(${x}px, ${y}px)`
    const animation = own(el, [{ transform: `${at} scale(1)`, opacity: 1 }, { transform: `${at} scale(1.25)`, opacity: 0 }],
      { duration: MARK.fade, easing: 'cubic-bezier(0.25, 0.8, 0.25, 1)', fill: 'forwards' })
    animation.currentTime = since
    animation.finished.then(() => el.remove())
  }
  const move = (x, y) => {
    mount()
    state.x = x
    state.y = y
    cursor.style.display = ''
    cursor.style.transform = `translate(${x}px, ${y}px)`
    if (mark) mark.style.transform = `translate(${x}px, ${y}px)`
    if (item) item.el.style.transform = `translate(${x - item.dx}px, ${y - item.dy}px) scale(1.03)`
  }
  const draw = next => {
    const first = !state
    state = next
    move(state.x, state.y)
    if (touch) cursor.firstChild.toggleAttribute('data-down', state.finger)
    if (state.down !== null && !mark) {
      // The mark travels with the point by its wrapper and grows by its own ring, so moving it keeps its growth.
      const at = document.createElement('div')
      at.className = 'at'
      root.insertBefore(at, cursor)
      at.append(ringAt(0, 0))
      at.style.transform = `translate(${state.x}px, ${state.y}px)`
      mark = at
      own(at.firstChild, [{ transform: 'scale(0.7)' }, { transform: 'scale(1)' }],
        { duration: MARK.grow, easing: 'ease-out', fill: 'forwards' }).currentTime = state.down
    } else if (state.down === null && mark) {
      mark.remove()
      mark = null
      fade(state.lifted.x, state.lifted.y, state.lifted.since)
    } else if (first && state.lifted && state.lifted.since < MARK.fade) {
      fade(state.lifted.x, state.lifted.y, state.lifted.since)
    }
  }
  const options = { capture: true, passive: true }
  const follow = e => state && move(e.clientX, e.clientY)
  if (touch) addEventListener('touchmove', e => follow(e.touches[0]), options)
  else addEventListener('mousemove', follow, options)
  addEventListener('dragover', follow, options)
  // The item as the page draws it as the drag starts, each part with the styles the page gives it, lifted. Each takes
  // the overlay's pointer-events, none, so no drag or drop finds it.
  addEventListener('dragstart', ({ target }) => {
    if (!state || !(target instanceof Element)) return
    const box = target.getBoundingClientRect()
    const el = target.cloneNode(true)
    const parts = [el, ...el.querySelectorAll('*')];
    [target, ...target.querySelectorAll('*')].forEach((part, n) => {
      const style = getComputedStyle(part)
      for (const name of style) if (name !== 'pointer-events') parts[n].style.setProperty(name, style.getPropertyValue(name))
    })
    Object.assign(el.style, { position: 'absolute', inset: 'auto', left: '0', top: '0', margin: '0', transition: 'none',
      animation: 'none', opacity: '0.92', boxShadow: '0 14px 30px rgba(0, 0, 0, 0.28)' })
    root.insertBefore(el, root.querySelector('.beat').nextSibling) // under the mark and the cursor
    item = { el, dx: state.x - box.left, dy: state.y - box.top }
    move(state.x, state.y)
  }, options)
  addEventListener('dragend', () => {
    item?.el.remove()
    item = null
  }, options)
  addEventListener('octo-lite-recorder', e => draw(e.detail), options)
  addEventListener('toggle', e => {
    if (e.target !== host && e.newState === 'open' && host.isConnected) {
      host.hidePopover()
      host.showPopover()
    }
  }, true)
  addEventListener('DOMContentLoaded', mount)
  // The recorder's pointer is the top document's; a frame inside it draws only the cursor its own events move.
  if (window === top) octoLiteRecorder().then(next => state || draw(next))
  else if (!touch) state = { finger: false, down: null, lifted: null }
}
