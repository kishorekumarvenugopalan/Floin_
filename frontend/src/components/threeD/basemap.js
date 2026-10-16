// Street basemap draped on the 3D terrain: OpenStreetMap standard raster tiles, stitched into one
// canvas texture for the visible crop (the tile server sends CORS headers). OSM tile usage policy:
// attribution is shown on the map and each view loads a bounded number of tiles (no bulk fetching).
import * as THREE from 'three'

const TILE = 256
export const BASEMAP_ATTRIBUTION = '© OpenStreetMap contributors'
const tileUrl = (z, x, y) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`

const lonToX = (lon, z) => ((lon + 180) / 360) * 2 ** z * TILE
const latToY = (lat, z) => {
  const s = Math.sin((lat * Math.PI) / 180)
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * 2 ** z * TILE
}

function loadImage(url, signal) {
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    signal?.addEventListener('abort', () => { img.src = ''; resolve(null) })
    img.src = url
  })
}

/** Loads the tiles covering `bbox` at the highest zoom with at most `maxTiles` tiles. */
export async function loadBasemap([w, s, e, n], { maxTiles = 36, signal } = {}) {
  let z = 16
  let x0, x1, y0, y1
  for (; z >= 8; z--) {
    x0 = Math.floor(lonToX(w, z) / TILE); x1 = Math.floor(lonToX(e, z) / TILE)
    y0 = Math.floor(latToY(n, z) / TILE); y1 = Math.floor(latToY(s, z) / TILE)
    if ((x1 - x0 + 1) * (y1 - y0 + 1) <= maxTiles) break
  }
  const width = (x1 - x0 + 1) * TILE
  const height = (y1 - y0 + 1) * TILE
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#dfe3e8'
  ctx.fillRect(0, 0, width, height)
  const jobs = []
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      jobs.push(loadImage(tileUrl(z, x, y), signal).then((img) => {
        if (img) ctx.drawImage(img, (x - x0) * TILE, (y - y0) * TILE)
        return !!img
      }))
    }
  }
  const ok = await Promise.all(jobs)
  if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
  const loaded = ok.filter(Boolean).length
  if (loaded === 0) throw new Error('Basemap tiles could not be loaded (offline or blocked).')
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 4
  const uvOf = (lon, lat) => [(lonToX(lon, z) - x0 * TILE) / width, 1 - (latToY(lat, z) - y0 * TILE) / height]
  return { texture, uvOf, zoom: z, loaded, total: ok.length }
}
