import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { listSimulations } from '../services/floinApi'
import { usePolling } from '../hooks/useApi'

// Shares the list of simulation runs and the run shown in the workspace (sidebar results and
// map overlays). The choice is remembered per browser.
const SimulationContext = createContext(null)
const STORAGE_KEY = 'floin.selectedSimulation'

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function SimulationProvider({ children }) {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedIdState] = useState(readStored)

  const refresh = useCallback(async (signal) => {
    try {
      const data = await listSimulations(200, { signal })
      setRuns(data)
      setError(null)
    } catch (err) {
      if (!signal?.aborted) setError(err)
    }
  }, [])

  const anyActive = (runs || []).some((r) => r.status === 'queued' || r.status === 'running')
  usePolling(refresh, anyActive ? 5000 : 30000, true)

  const completed = useMemo(() => (runs || []).filter((r) => r.status === 'completed'), [runs])

  // Fall back to the newest completed run when nothing (valid) is selected.
  useEffect(() => {
    if (!runs) return
    if (!selectedId || !runs.some((r) => r.id === selectedId)) {
      setSelectedIdState(completed[0]?.id || null)
    }
  }, [runs, completed, selectedId])

  const setSelectedId = useCallback((id) => {
    setSelectedIdState(id)
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch {
      /* storage unavailable: selection lasts for this page load only */
    }
  }, [])

  /** Select a run that may not be in the list yet (just submitted): refresh first. */
  const trackRun = useCallback(async (id) => {
    await refresh()
    setSelectedId(id)
  }, [refresh, setSelectedId])

  const selected = (runs || []).find((r) => r.id === selectedId) || null
  const value = { runs, completed, error, refresh, selectedId, selected, setSelectedId, trackRun }
  return <SimulationContext.Provider value={value}>{children}</SimulationContext.Provider>
}

export function useSimulations() {
  const ctx = useContext(SimulationContext)
  if (!ctx) throw new Error('useSimulations must be used inside SimulationProvider')
  return ctx
}
