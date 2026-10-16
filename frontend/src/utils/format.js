// Formatting helpers. Missing values are shown as "—", never as 0.

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v)

export function fmt(value, { digits = 1, unit = '' } = {}) {
  if (!isNum(value)) return '—'
  const abs = Math.abs(value)
  const d = abs >= 1000 ? 0 : digits
  const s = value.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: d })
  return unit ? `${s} ${unit}` : s
}

export const fmtInt = (v) => (isNum(v) ? Math.round(v).toLocaleString('en-IN') : '—')
export const fmtPct = (v, digits = 1) => (isNum(v) ? `${(v * 100).toFixed(digits)} %` : '—')

/** Cubic metres as million m³ when large. */
export function fmtVolume(m3) {
  if (!isNum(m3)) return '—'
  if (Math.abs(m3) >= 1e6) return `${(m3 / 1e6).toLocaleString('en-IN', { maximumFractionDigits: 2 })} million m³`
  return `${Math.round(m3).toLocaleString('en-IN')} m³`
}

export function fmtDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

export function fmtDuration(seconds) {
  if (!isNum(seconds)) return '—'
  if (seconds < 90) return `${Math.round(seconds)} s`
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`
}

export const titleCase = (s) => (s ? String(s).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : '')
