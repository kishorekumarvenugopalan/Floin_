// Locality search.
//  1. GCC zones and wards: real boundary polygons from the FLOIN backend (layer wards_gcc).
//  2. OpenStreetMap places via the public Nominatim service, bounded to the FLOIN model area.
//     Nominatim usage policy: max 1 request/second, attribution required, no bulk use.
//     Only the typed search text is sent. Results are boundaries only when OSM has one.
import { MODEL_BBOX } from '../utils/geo'

const NOMINATIM = 'https://nominatim.openstreetmap.org/search'
const AREA_CATEGORIES = new Set(['place', 'boundary', 'landuse', 'natural', 'leisure'])
let lastRequest = 0

export function searchGcc(query, wards) {
  const q = query.trim().toLowerCase()
  if (!q || !wards) return []
  const zones = new Map()
  wards.features.forEach((f) => {
    const zone = f.properties.zone
    if (!zone) return
    if (!zones.has(zone)) zones.set(zone, [])
    zones.get(zone).push(f)
  })
  const out = []
  for (const [zone, features] of zones) {
    if (zone.toLowerCase().includes(q)) {
      out.push({ kind: 'zone', id: `zone:${zone}`, label: `${titleZone(zone)} zone`, sublabel: `GCC zone · ${features.length} wards`, wardIds: features.map((f) => f.id) })
    }
  }
  const wardMatch = q.match(/^(?:ward\s*)?(\d{1,3})$/)
  wards.features.forEach((f) => {
    const code = String(f.properties.code ?? '')
    if ((wardMatch && code === wardMatch[1]) || (q.length >= 3 && `ward ${code}`.includes(q))) {
      out.push({ kind: 'ward', id: `ward:${f.id}`, label: `Ward ${code}`, sublabel: `GCC ward · ${titleZone(f.properties.zone)} zone`, wardIds: [f.id] })
    }
  })
  return out.slice(0, 8)
}

export const titleZone = (z) => (z ? z.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : '')

export async function searchOsm(query, signal) {
  const wait = Math.max(0, lastRequest + 1100 - Date.now())
  if (wait) await new Promise((resolve, reject) => {
    const t = setTimeout(resolve, wait)
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('aborted', 'AbortError')) })
  })
  lastRequest = Date.now()
  const [w, s, e, n] = MODEL_BBOX
  const params = new URLSearchParams({
    q: query, format: 'jsonv2', polygon_geojson: '1', limit: '8', 'accept-language': 'en',
    viewbox: `${w},${n},${e},${s}`, bounded: '1', countrycodes: 'in',
  })
  const res = await fetch(`${NOMINATIM}?${params}`, { signal, headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`OpenStreetMap search failed (HTTP ${res.status})`)
  const data = await res.json()
  if (!Array.isArray(data)) throw new Error('OpenStreetMap search returned an unexpected response')
  return data.map((r) => {
    // A polygon is used as the area boundary only for area-type OSM objects. Polygons of
    // individual features (a bus-stop platform, a building) are not localities, so those
    // results are handled like points (containing GCC ward).
    const areal = AREA_CATEGORIES.has(r.category) && r.geojson && (r.geojson.type === 'Polygon' || r.geojson.type === 'MultiPolygon')
    return {
      kind: 'osm',
      id: `osm:${r.osm_type}/${r.osm_id}`,
      label: r.name || r.display_name.split(',')[0],
      sublabel: `${r.display_name.split(',').slice(1, 4).join(',').trim()} · OSM ${r.category}/${r.type}`,
      osmType: `${r.category}/${r.type}`,
      geometry: areal ? r.geojson : null,
      point: [Number(r.lon), Number(r.lat)],
      hasBoundary: areal,
    }
  })
}
