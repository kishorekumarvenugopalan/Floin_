// Pure helpers for the 3D explorer: cropping the backend block grids to the selected area
// and converting GeoJSON (EPSG:4326) into scene coordinates draped on the terrain.
import { lonLatToUtm, utmToLonLat } from '../../utils/utm'

export const KM = 1000

/**
 * Row/column window of a block grid that covers `bbox` (lon/lat), padded so that small
 * areas keep some surrounding terrain. Without a bbox the whole grid is used.
 */
export function cropWindow(grid, bbox, { minCells = 48, pad = 0.35 } = {}) {
  const full = { r0: 0, r1: grid.height - 1, c0: 0, c1: grid.width - 1 }
  if (!bbox) return full
  const [left, , , top] = grid.bounds_projected
  const cell = grid.cell_size_m
  const [w, s, e, n] = bbox
  const corners = [[w, s], [w, n], [e, s], [e, n]].map(([lon, lat]) => lonLatToUtm(lon, lat, 44))
  const minE = Math.min(...corners.map((p) => p[0])), maxE = Math.max(...corners.map((p) => p[0]))
  const minN = Math.min(...corners.map((p) => p[1])), maxN = Math.max(...corners.map((p) => p[1]))
  let c0 = Math.floor((minE - left) / cell), c1 = Math.ceil((maxE - left) / cell)
  let r0 = Math.floor((top - maxN) / cell), r1 = Math.ceil((top - minN) / cell)
  const grow = (a, b, size) => {
    const span = b - a
    const want = Math.max(minCells, Math.round(span * (1 + 2 * pad)))
    const mid = (a + b) / 2
    let lo = Math.round(mid - want / 2)
    let hi = lo + want
    if (lo < 0) { hi -= lo; lo = 0 }
    if (hi > size - 1) { lo -= hi - (size - 1); hi = size - 1 }
    return [Math.max(0, lo), hi]
  }
  ;[c0, c1] = grow(c0, c1, grid.width)
  ;[r0, r1] = grow(r0, r1, grid.height)
  if (c1 <= c0 || r1 <= r0) return null // area entirely outside the model grid
  return { r0, r1, c0, c1 }
}

const sliceRows = (rows, win) => rows.slice(win.r0, win.r1 + 1).map((row) => row.slice(win.c0, win.c1 + 1))

/** A block grid restricted to the window, with its own projected bounds. */
export function cropGrid(grid, win) {
  const [left, , , top] = grid.bounds_projected
  const cell = grid.cell_size_m
  const values = sliceRows(grid.values, win)
  const height = values.length
  const width = values[0].length
  const bounds = [left + win.c0 * cell, top - (win.r1 + 1) * cell, left + (win.c1 + 1) * cell, top - win.r0 * cell]
  return { cell_size_m: cell, width, height, bounds_projected: bounds, values }
}

export function cropOverlay(overlay, win) {
  return {
    ...overlay,
    depth_mean: sliceRows(overlay.depth_mean, win),
    depth_max: sliceRows(overlay.depth_max, win),
    flooded_share: sliceRows(overlay.flooded_share, win),
  }
}

/** lon/lat bbox of a projected rectangle (used for bbox layer requests). */
export function lonLatBbox([left, bottom, right, top]) {
  const pts = [[left, bottom], [left, top], [right, bottom], [right, top]].map(([e, n]) => utmToLonLat(e, n, 44))
  return [Math.min(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[1]))]
}

/**
 * Scene frame: x = easting, z = -northing (km from the crop centre), y = elevation (km) ×
 * exaggeration. `ground(e, n)` interpolates the block grid bilinearly between block centres,
 * which is what the rendered surface does too, so draped features sit on it.
 */
export function makeFrame(grid) {
  const [left, bottom, right, top] = grid.bounds_projected
  const cx = (left + right) / 2
  const cy = (bottom + top) / 2
  const cell = grid.cell_size_m
  const valid = grid.values.flat().filter((v) => v !== null).sort((a, b) => a - b)
  const lo = valid[Math.floor(valid.length * 0.01)] ?? 0
  const hi = valid[Math.floor(valid.length * 0.99)] ?? 1
  const at = (r, c) => {
    const rr = Math.min(grid.height - 1, Math.max(0, r))
    const cc = Math.min(grid.width - 1, Math.max(0, c))
    return grid.values[rr][cc] ?? 0
  }
  const ground = (e, n) => {
    const fc = (e - left) / cell - 0.5
    const fr = (top - n) / cell - 0.5
    const c = Math.floor(fc), r = Math.floor(fr)
    const tx = fc - c, ty = fr - r
    return (at(r, c) * (1 - tx) + at(r, c + 1) * tx) * (1 - ty) + (at(r + 1, c) * (1 - tx) + at(r + 1, c + 1) * tx) * ty
  }
  const cellAt = (e, n) => [Math.floor((top - n) / cell), Math.floor((e - left) / cell)]
  return {
    left, top, cx, cy, cell, lo, hi, ground, cellAt,
    inside: (e, n) => e >= left && e <= right && n >= bottom && n <= top,
    spanKm: (Math.max(grid.width, grid.height) * cell) / KM,
    toX: (c) => (left + (c + 0.5) * cell - cx) / KM,
    toZ: (r) => -((top - (r + 0.5) * cell) - cy) / KM,
    project: (lon, lat) => lonLatToUtm(lon, lat, 44),
  }
}

/** Nice contour interval giving roughly 6–14 lines over the elevation range. */
export function contourInterval(lo, hi) {
  const range = Math.max(1, hi - lo)
  for (const step of [1, 2, 5, 10, 20, 50]) if (range / step <= 14) return step
  return 100
}

export const lineParts = (g) => {
  if (!g) return []
  switch (g.type) {
    case 'LineString': return [g.coordinates]
    case 'MultiLineString': return g.coordinates
    case 'Polygon': return g.coordinates
    case 'MultiPolygon': return g.coordinates.flat()
    default: return []
  }
}

export const polygonParts = (g) => (g?.type === 'Polygon' ? [g.coordinates] : g?.type === 'MultiPolygon' ? g.coordinates : [])

/**
 * lon/lat of each block centre, interpolated bilinearly from the four corner centres.
 * UTM 44N is very close to affine over the model area, so this stays within a few metres,
 * far below the 90 m block size; it is used only to place basemap imagery.
 */
export function blockLonLat(grid) {
  const [left, , , top] = grid.bounds_projected
  const cell = grid.cell_size_m
  const W = grid.width - 1 || 1
  const H = grid.height - 1 || 1
  const at = (r, c) => utmToLonLat(left + (c + 0.5) * cell, top - (r + 0.5) * cell, 44)
  const nw = at(0, 0), ne = at(0, W), sw = at(H, 0), se = at(H, W)
  return (r, c) => {
    const u = c / W, v = r / H
    return [0, 1].map((k) => (nw[k] * (1 - u) + ne[k] * u) * (1 - v) + (sw[k] * (1 - u) + se[k] * u) * v)
  }
}

/** lon/lat bbox (about `km` across) centred on a point. */
export function bboxAround([lon, lat], km = 8) {
  const dLat = km / 2 / 110.6
  const dLon = km / 2 / (111.3 * Math.cos((lat * Math.PI) / 180))
  return [lon - dLon, lat - dLat, lon + dLon, lat + dLat]
}
