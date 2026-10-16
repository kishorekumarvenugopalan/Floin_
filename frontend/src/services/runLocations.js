// The backend's simulation API has no location field, so the location a run was started from
// is remembered in this browser only (localStorage). It is labelled as such wherever shown.
const KEY = 'floin.runLocations'
const MAX = 100

function readAll() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}')
  } catch {
    return {}
  }
}

export function saveRunLocation(runId, selection) {
  if (!selection) return
  try {
    const all = readAll()
    all[runId] = { ...selection, savedAt: new Date().toISOString() }
    const ids = Object.keys(all).sort((a, b) => (all[b].savedAt || '').localeCompare(all[a].savedAt || ''))
    ids.slice(MAX).forEach((id) => delete all[id])
    localStorage.setItem(KEY, JSON.stringify(all))
  } catch {
    /* storage full or unavailable: the run itself is still stored by the backend */
  }
}

export const getRunLocation = (runId) => readAll()[runId] || null
export const getRunLocations = () => readAll()
