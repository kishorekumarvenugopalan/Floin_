// Mapped features near a clicked point, from the FLOIN database through the existing
// bbox layer endpoint. Distances are measured in UTM 44N metres in the browser.
import { getLayerGeojson } from './floinApi'
import { lonLatToUtm } from '../utils/utm'
import { pointInGeometry } from '../utils/geo'
import { lineParts, polygonParts } from '../components/threeD/sceneData'

export const NEAR_RADIUS_M = 40

export const POINT_LAYERS = {
  osm_roads: 'Road (OSM)',
  osm_railways: 'Railway (OSM)',
  gcc_basin_rivers: 'River / stream (GCC)',
  gcc_buckingham_canal: 'Buckingham Canal (GCC)',
  gcc_basin_macro_drains: 'Macro drain (GCC)',
  gcc_basin_micro_drains: 'Micro drain (GCC)',
  gcc_storm_water_drains_2023: 'Storm-water drain (GCC 2023)',
  osm_natural_water: 'Water body (OSM)',
  gcc_waterbodies_2019: 'Water body (GCC 2019)',
  osm_buildings: 'Building footprint (OSM)',
}

function segmentDistance([px, py], [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay
  const len2 = dx * dx + dy * dy
  const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

function distanceTo(point, utmPoint, geometry) {
  if (polygonParts(geometry).length && pointInGeometry(point, geometry)) return 0
  let best = Infinity
  for (const part of lineParts(geometry)) {
    const pts = part.map(([lon, lat]) => lonLatToUtm(lon, lat, 44))
    for (let i = 1; i < pts.length; i++) best = Math.min(best, segmentDistance(utmPoint, pts[i - 1], pts[i]))
    if (pts.length === 1) best = Math.min(best, Math.hypot(utmPoint[0] - pts[0][0], utmPoint[1] - pts[0][1]))
  }
  return best
}

/** Features within NEAR_RADIUS_M of [lon, lat], nearest first, with their stored attributes. */
export async function featuresNear([lon, lat], signal) {
  const dLat = (NEAR_RADIUS_M * 1.2) / 110600
  const dLon = (NEAR_RADIUS_M * 1.2) / (111300 * Math.cos((lat * Math.PI) / 180))
  const bbox = [lon - dLon, lat - dLat, lon + dLon, lat + dLat].map((v) => v.toFixed(6)).join(',')
  const utmPoint = lonLatToUtm(lon, lat, 44)
  const names = Object.keys(POINT_LAYERS)
  const settled = await Promise.all(names.map((name) => getLayerGeojson(name, { bbox, limit: 200 }, { signal })
    .then((fc) => ({ name, fc }))
    .catch((error) => {
      if (signal?.aborted) throw error
      return { name, error }
    })))
  const features = []
  const failed = []
  for (const { name, fc, error } of settled) {
    if (error) { failed.push(POINT_LAYERS[name]); continue }
    for (const f of fc.features) {
      const d = distanceTo([lon, lat], utmPoint, f.geometry)
      if (d <= NEAR_RADIUS_M) features.push({ key: `${name}:${f.id}`, layer: name, label: POINT_LAYERS[name], distance_m: d, properties: f.properties })
    }
  }
  features.sort((a, b) => a.distance_m - b.distance_m)
  return { features, failed }
}
