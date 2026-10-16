// Plain-language wording for non-specialists. Comparisons use fixed reference sizes only:
//  - IMD (India Meteorological Department) 24-hour rainfall categories
//  - Olympic swimming pool: 50 m × 25 m × 2 m = 2,500 m³
//  - football pitch: 105 m × 68 m = 7,140 m² (FIFA recommended size)
import { isNum } from './format'

const POOL_M3 = 2500
const PITCH_M2 = 7140

const n = (v, max = 0) => v.toLocaleString('en-IN', { maximumFractionDigits: max })

/** IMD category for a 24-hour rainfall total (mm). */
export function imdCategory(mm) {
  if (!isNum(mm) || mm <= 0) return null
  if (mm < 2.5) return 'very light rain'
  if (mm < 15.6) return 'light rain'
  if (mm < 64.5) return 'moderate rain'
  if (mm < 115.6) return 'heavy rain'
  if (mm < 204.5) return 'very heavy rain'
  return 'extremely heavy rain'
}

/** Water depth as cm below 1 m, otherwise metres. */
export function depthText(m) {
  if (!isNum(m)) return '—'
  if (m < 1) return `${n(m * 100)} cm`
  return `${n(m, 1)} m`
}

/** Rough body-height comparison for an adult standing in the water. */
export function depthWords(m) {
  if (!isNum(m) || m <= 0) return null
  if (m < 0.15) return 'about ankle-deep'
  if (m < 0.5) return 'up to about the knee'
  if (m < 1.0) return 'up to about the waist'
  if (m < 1.5) return 'up to about the chest'
  if (m < 1.8) return 'about head-high'
  return 'deeper than a person is tall'
}

/** Area in km² (large) or m² (small), with a football-pitch comparison for small areas. */
export function areaText(km2) {
  if (!isNum(km2)) return '—'
  if (km2 === 0) return 'none'
  const m2 = km2 * 1e6
  if (km2 >= 1) return `${n(km2, 1)} km²`
  const pitches = m2 / PITCH_M2
  const cmp = pitches < 0.5 ? 'less than half a football pitch' : `about ${n(pitches, pitches < 10 ? 1 : 0)} football pitch${pitches >= 1.5 ? 'es' : ''}`
  if (km2 >= 0.01) return `${n(km2, 2)} km² (${cmp})`
  return `${n(m2)} m² (${cmp})`
}

/** Volume in m³ with an Olympic-pool comparison. */
export function volumeText(m3) {
  if (!isNum(m3)) return '—'
  const pools = m3 / POOL_M3
  const amount = m3 >= 1e6 ? `${n(m3 / 1e6, 2)} million m³` : `${n(m3)} m³`
  if (pools < 1) return `${amount} (less than one Olympic pool)`
  return `${amount} (about ${n(pools, pools < 10 ? 1 : 0)} Olympic swimming pools)`
}

/** Road / track length in km or m. */
export function lengthText(km) {
  if (!isNum(km)) return '—'
  if (km === 0) return 'none'
  if (km < 1) return `${n(km * 1000)} m`
  return `${n(km, 1)} km`
}

/** Percentage with sensible precision for small shares. */
export function shareText(fraction) {
  if (!isNum(fraction)) return '—'
  const pct = fraction * 100
  if (pct === 0) return '0%'
  if (pct < 1) return `${n(pct, 2)}%`
  return `${n(pct)}%`
}

export const GROUND_LABELS = {
  I: 'Dry (little or no rain in the last 5 days)',
  II: 'Normal',
  III: 'Wet (heavy rain in the last 5 days, ground already soaked)',
}
export const GROUND_SHORT = { I: 'Dry', II: 'Normal', III: 'Wet / soaked' }

/** Friendly names for the rainfall maps registered in the backend catalog. */
export const STORM_NAMES = {
  rainfall_chirps_2015_event_30m: 'December 2015 Chennai floods (30 Nov – 2 Dec 2015)',
}
export const stormName = (dataset) => STORM_NAMES[dataset?.name ?? dataset] || dataset?.title || dataset

/** Depth class labels such as "Low (10–30 cm)" from the run's own thresholds. */
export function classLabels(names, breaks, minDepth) {
  const edges = [minDepth, ...(breaks || [])]
  return (names || []).map((name, i) => {
    const lo = edges[i]
    const hi = edges[i + 1]
    const range = hi != null ? `${depthText(lo)}–${depthText(hi)}` : `over ${depthText(lo)}`
    return { name, label: `${name[0].toUpperCase()}${name.slice(1)} (${range})` }
  })
}
