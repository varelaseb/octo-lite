// The recorder's check of each video it records (octo-lite #delivery-round-video): every press shows the cursor, on a
// phone the touch, and the press mark, in a frame the video shows while the mark is full, and on a desktop each step's
// result shows the cursor at rest; a step that does not fails, naming the step and its viewport. It reads the frames
// for the shapes overlay.mjs draws.

import { ARROW, EDGE, MARK, TOUCH } from './overlay.mjs'

const DARK = 100 // luma under which a pixel reads as a shape's dark body
const LIGHT = 160 // luma over which a pixel reads as its white edge
const SHOWN = 0.8 // the share of a shape's probes that must read as drawn
export const HALF = MARK.radius + MARK.halo + 1 // a crop reaches from the press point past the mark's halo

// A frame's luma (2 * HALF + 1) px square around the press point at x, y, with what lies off the frame mid grey.
export function crop({ width, height, data }, x, y) {
  const size = 2 * HALF + 1
  const luma = new Uint8Array(size * size).fill(128)
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      const fx = x - HALF + i
      const fy = y - HALF + j
      if (fx < 0 || fy < 0 || fx >= width || fy >= height) continue
      const k = 4 * (fy * width + fx)
      luma[j * size + i] = Math.round(0.299 * data[k] + 0.587 * data[k + 1] + 0.114 * data[k + 2])
    }
  }
  return { size, luma }
}

function inside([x, y], poly) {
  let odd = false
  for (let a = 0, b = poly.length - 1; a < poly.length; b = a++) {
    const [ax, ay] = poly[a]
    const [bx, by] = poly[b]
    if ((ay > y) !== (by > y) && x < ax + (y - ay) * (bx - ax) / (by - ay)) odd = !odd
  }
  return odd
}

function distance([x, y], poly) {
  return Math.min(...poly.map(([ax, ay], a) => {
    const [bx, by] = poly[(a + 1) % poly.length]
    const t = Math.max(0, Math.min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
    return Math.hypot(x - ax - t * (bx - ax), y - ay - t * (by - ay))
  }))
}

// Probes as [dx, dy, light], the pixel offsets from the press point and whether the drawn shape is white there.
// The arrow's: its body well inside its outline, and its white edge just outside it.
const ARROW_PROBES = []
for (let dy = -EDGE; dy < 24; dy++) {
  for (let dx = -EDGE; dx < 16; dx++) {
    const at = [dx + 0.5, dy + 0.5]
    const from = distance(at, ARROW)
    if (inside(at, ARROW) && from >= 1.5) ARROW_PROBES.push([dx, dy, false])
    else if (!inside(at, ARROW) && from >= 0.6 && from <= EDGE - 0.6) ARROW_PROBES.push([dx, dy, true])
  }
}

// A ring's: its dark band and its white halo, every 15 degrees, leaving out each angle the arrow and its shadow cover.
function ringProbes({ radius, band, halo }, clear = () => true) {
  return Array.from({ length: 24 }, (_, k) => k * Math.PI / 12).flatMap(angle => {
    const pair = [[radius - band / 2, false], [radius + halo / 2, true]]
      .map(([r, light]) => [Math.floor(r * Math.cos(angle)), Math.floor(r * Math.sin(angle)), light])
    return pair.every(clear) ? pair : []
  })
}
const clearOfArrow = ([dx, dy]) => !inside([dx + 0.5, dy + 0.5], ARROW) && distance([dx + 0.5, dy + 0.5], ARROW) > EDGE + 4
const SHAPES = {
  desktop: { cursor: ARROW_PROBES, mark: ringProbes(MARK, clearOfArrow) },
  phone: { cursor: ringProbes(TOUCH), mark: ringProbes(MARK) },
}

function drawn({ size, luma }, probes) {
  const read = probes.filter(([dx, dy, light]) => {
    const value = luma[(HALF + dy) * size + HALF + dx]
    return light ? value > LIGHT : value < DARK
  })
  return read.length >= SHOWN * probes.length
}

// One step's presses, each with its crops of the frames the video shows while its mark is full, and on a desktop the
// crop of the step's last frame where the cursor rests.
export function verify(viewport, step, presses, rest) {
  const { cursor, mark } = SHAPES[viewport]
  const missing = (what, why = '') => new Error(`the ${viewport} video does not show the ${what} at step "${step}"${why}; `
    + 'fix the prototype and record again')
  for (const press of presses) {
    if (!press.crops.some(frame => drawn(frame, cursor) && drawn(frame, mark))) {
      throw missing(`${viewport === 'phone' ? 'touch' : 'cursor'} and its press mark`, ` (${press.action})`)
    }
  }
  if (rest && !drawn(rest, cursor)) throw missing('cursor at rest')
}
