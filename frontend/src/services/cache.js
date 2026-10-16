// Session cache for large, immutable backend resources (terrain grid, a run's outputs).
// Successful results are kept; failures are not cached so a retry can succeed.
import { request } from './api'
import { getTerrainGrid, getTerrainOverlay } from './floinApi'

const store = new Map()

function cached(key, load) {
  if (!store.has(key)) {
    const p = load().catch((err) => {
      store.delete(key)
      throw err
    })
    store.set(key, p)
  }
  return store.get(key)
}

// Callers may abort their own wait; the shared download itself is not cancelled.
function withSignal(promise, signal) {
  if (!signal) return promise
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('aborted', 'AbortError'))
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    promise.then(resolve, reject)
  })
}

export const terrainGrid = (signal) => withSignal(cached('terrain:640', () => getTerrainGrid(640)), signal)
export const depthOverlay = (sid, signal) => withSignal(cached(`overlay:${sid}:640`, () => getTerrainOverlay(sid, 640)), signal)
/** All flood polygons of a run (GeoJSON, EPSG:4326). Large: about 15 MB for a 300 mm run. */
export const floodPolygons = (sid, signal) =>
  withSignal(cached(`flood:${sid}`, () => request(`/simulations/${encodeURIComponent(sid)}/flood`, { params: { simplify_m: 20 }, timeoutMs: 180000 })), signal)
