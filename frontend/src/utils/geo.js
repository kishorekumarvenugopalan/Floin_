// Small geometry helpers for GeoJSON in EPSG:4326 ([lon, lat] order).
import { lonLatToUtm } from './utm'

/** Model area footprint (the DEM extent), [west, south, east, north]. */
export const MODEL_BBOX = [80.0499, 12.8501, 80.3999, 13.3001]

export function polygonsOf(geometry) {
  if (!geometry) return []
  if (geometry.type === 'Polygon') return [geometry.coordinates]
  if (geometry.type === 'MultiPolygon') return geometry.coordinates
  if (geometry.type === 'GeometryCollection') return geometry.geometries.flatMap(polygonsOf)
  return []
}

export const isAreal = (geometry) => polygonsOf(geometry).length > 0

/** Shape check for GeoJSON coming from the backend or a geocoder. */
export function validateGeometry(geometry) {
  if (!geometry || typeof geometry !== 'object' || !geometry.type) return 'missing geometry'
  const coords = JSON.stringify(geometry.coordinates ?? geometry.geometries ?? []).match(/-?\d+(\.\d+)?/g)
  if (!coords || coords.length < 2) return 'geometry has no coordinates'
  const first = Number(coords[0])
  const second = Number(coords[1])
  if (Math.abs(first) > 180 || Math.abs(second) > 90) return 'coordinates are not longitude/latitude (EPSG:4326)'
  return null
}

export function bboxOf(geometry) {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity
  const visit = (c) => {
    if (typeof c[0] === 'number') {
      w = Math.min(w, c[0]); e = Math.max(e, c[0]); s = Math.min(s, c[1]); n = Math.max(n, c[1])
    } else c.forEach(visit)
  }
  if (geometry.type === 'GeometryCollection') geometry.geometries.forEach((g) => visit(g.coordinates))
  else visit(geometry.coordinates)
  return [w, s, e, n]
}

export const bboxToLeaflet = ([w, s, e, n]) => [[s, w], [n, e]]
export const bboxIntersects = (a, b) => a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]
export const bboxInside = (a, b) => a[0] >= b[0] && a[2] <= b[2] && a[1] >= b[1] && a[3] <= b[3]

export function expandBbox([w, s, e, n], fraction = 0.1) {
  const dx = (e - w) * fraction
  const dy = (n - s) * fraction
  return [w - dx, s - dy, e + dx, n + dy]
}

function inRing(x, y, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/** Point-in-polygon (even-odd, holes respected) for Polygon / MultiPolygon geometries. */
export function pointInGeometry([x, y], geometry, bbox = null) {
  if (bbox && (x < bbox[0] || x > bbox[2] || y < bbox[1] || y > bbox[3])) return false
  return polygonsOf(geometry).some((rings) => inRing(x, y, rings[0]) && !rings.slice(1).some((hole) => inRing(x, y, hole)))
}

function ringAreaUtm(ring) {
  const pts = ring.map(([lon, lat]) => lonLatToUtm(lon, lat, 44))
  let sum = 0
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) sum += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
  return Math.abs(sum) / 2
}

/** Planar area in km² computed in UTM 44N (the model CRS). */
export function areaKm2(geometry) {
  return polygonsOf(geometry).reduce((total, rings) =>
    total + ringAreaUtm(rings[0]) - rings.slice(1).reduce((h, r) => h + ringAreaUtm(r), 0), 0) / 1e6
}

/** True when any vertex of a line/polygon feature falls inside the area. */
export function featureTouchesArea(geometry, area, areaBbox) {
  let hit = false
  const visit = (c) => {
    if (hit) return
    if (typeof c[0] === 'number') hit = pointInGeometry(c, area, areaBbox)
    else c.forEach(visit)
  }
  visit(geometry.coordinates)
  return hit
}

export function centroidOfBbox([w, s, e, n]) {
  return [(w + e) / 2, (s + n) / 2]
}
