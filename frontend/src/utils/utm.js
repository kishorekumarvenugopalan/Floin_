// WGS84 lon/lat -> UTM (northern hemisphere) using the standard Transverse Mercator series
// (Snyder 1987, USGS Professional Paper 1395, eqs. 8-9 to 8-13). Accurate to well under a
// metre within the zone, which is far finer than the 3D terrain cells.
const a = 6378137
const f = 1 / 298.257223563
const e2 = f * (2 - f)
const ep2 = e2 / (1 - e2)
const k0 = 0.9996

export function lonLatToUtm(lon, lat, zone = 44) {
  const lon0 = ((zone - 1) * 6 - 180 + 3) * (Math.PI / 180)
  const phi = lat * (Math.PI / 180)
  const lam = lon * (Math.PI / 180)
  const sin = Math.sin(phi)
  const cos = Math.cos(phi)
  const tan = Math.tan(phi)
  const N = a / Math.sqrt(1 - e2 * sin * sin)
  const T = tan * tan
  const C = ep2 * cos * cos
  const A = cos * (lam - lon0)
  const e4 = e2 * e2
  const e6 = e4 * e2
  const M = a * ((1 - e2 / 4 - (3 * e4) / 64 - (5 * e6) / 256) * phi
    - ((3 * e2) / 8 + (3 * e4) / 32 + (45 * e6) / 1024) * Math.sin(2 * phi)
    + ((15 * e4) / 256 + (45 * e6) / 1024) * Math.sin(4 * phi)
    - ((35 * e6) / 3072) * Math.sin(6 * phi))
  const easting = k0 * N * (A + ((1 - T + C) * A ** 3) / 6 + ((5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5) / 120) + 500000
  const northing = k0 * (M + N * tan * ((A * A) / 2 + ((5 - T + 9 * C + 4 * C * C) * A ** 4) / 24
    + ((61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6) / 720))
  return [easting, northing]
}

/** Inverse of lonLatToUtm by Newton iteration on the forward series (sub-metre after 4 steps). */
export function utmToLonLat(e, n, zone = 44) {
  let lon = (zone - 1) * 6 - 180 + 3 + (e - 500000) / 108000
  let lat = n / 110600
  for (let i = 0; i < 4; i++) {
    const [fe, fn] = lonLatToUtm(lon, lat, zone)
    const [fe2] = lonLatToUtm(lon + 1e-4, lat, zone)
    const [, fn2] = lonLatToUtm(lon, lat + 1e-4, zone)
    lon += ((e - fe) / (fe2 - fe)) * 1e-4
    lat += ((n - fn) / (fn2 - fn)) * 1e-4
  }
  return [lon, lat]
}
