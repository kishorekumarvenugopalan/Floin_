import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { History, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useSimulations } from '../context/SimulationContext'
import { useArea } from '../context/AreaContext'
import { getSimulation } from '../services/floinApi'
import { getRunLocation, saveRunLocation } from '../services/runLocations'
import { bboxAround } from '../components/threeD/sceneData'
import LocationPanel from '../components/workspace/LocationPanel'
import SimulationForm, { DEFAULT_FORM, formFromParameters } from '../components/workspace/SimulationForm'
import { LocationRunSummary, RunHeader, RunProgress, RunSummary, useRun } from '../components/workspace/RunResults'
import TerrainMap from '../components/workspace/TerrainMap'
import { ErrorState, LoadingState } from '../components/common/ui'

export default function SimulationWorkspace() {
  const { runs, selectedId, setSelectedId, trackRun } = useSimulations()
  const { area, selection, pickPoint, restore } = useArea()
  const [params, setParams] = useSearchParams()
  const [focus, setFocus] = useState(null)
  const [restored, setRestored] = useState(null)
  const [restoreError, setRestoreError] = useState(null)
  const [sidebar, setSidebar] = useState(true)
  const resultsRef = useRef(null)
  const current = useRun(selectedId)
  const running = current.run && (current.run.status === 'queued' || current.run.status === 'running')

  // A searched area moves the map there; a clicked point does not (the user is exploring).
  const lastAreaId = useRef(area?.id)
  useEffect(() => {
    if (area?.id === lastAreaId.current) return
    lastAreaId.current = area?.id
    if (area && area.kind !== 'map-point' && area.bbox) setFocus(area.bbox)
  }, [area])

  // Opening a run from Simulation History: show it and restore its inputs. Never re-runs it.
  const openRun = params.get('run')
  useEffect(() => {
    if (!openRun) return undefined
    const ctrl = new AbortController()
    setRestoreError(null)
    getSimulation(openRun, { signal: ctrl.signal })
      .then((run) => {
        setSelectedId(run.id)
        setRestored({ runId: run.id, form: formFromParameters(run.parameters), label: run.scenario })
        const loc = getRunLocation(run.id)
        if (loc) {
          const { savedAt: _savedAt, ...sel } = loc
          restore(sel)
        }
        setParams({}, { replace: true })
        setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 200)
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          setRestoreError(err)
          setParams({}, { replace: true })
        }
      })
    return () => ctrl.abort()
  }, [openRun, setSelectedId, restore, setParams])

  const zoomTo = (a) => {
    if (a.bbox) setFocus(a.bbox)
    else if (a.point) setFocus(bboxAround(a.point, 6))
  }

  async function onSubmitted(id) {
    saveRunLocation(id, selection)
    await trackRun(id)
    setRestored(null)
    setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
  }

  const pin = area?.point && (area.kind === 'map-point' || area.kind === 'osm-point') ? area.point : null

  return (
    <div className="relative flex h-full overflow-hidden">
      <aside className={`${sidebar ? 'flex' : 'hidden'} absolute inset-y-0 left-0 z-30 w-full max-w-[400px] flex-col border-r border-line bg-paper shadow-2xl lg:static lg:w-[380px] lg:shadow-none`}
             aria-label="Simulation panel">
        <div className="flex items-center justify-between border-b border-line px-4 py-2 lg:hidden">
          <span className="text-xs font-semibold text-muted">Simulation panel</span>
          <button type="button" onClick={() => setSidebar(false)} className="flex items-center gap-1 text-xs text-mangrove"><PanelLeftClose size={15} /> Show map</button>
        </div>
        <div className="scroll-thin flex-1 overflow-y-auto">
          <SidebarSection n="1" title="Choose a place">
            <LocationPanel onZoom={(a) => { zoomTo(a); if (window.matchMedia?.('(max-width: 1023px)').matches) setSidebar(false) }} />
          </SidebarSection>

          <SidebarSection n="2" title="Set up the rain">
            {restoreError && <div className="mb-2"><ErrorState error={restoreError} title="Could not open that simulation" /></div>}
            <SimulationForm key={restored?.runId || 'new'} initial={restored?.form || DEFAULT_FORM} restoredFrom={restored?.label}
                            onSubmitted={onSubmitted} busy={running} />
            <p className="mt-2 text-[11px] leading-relaxed text-faint">
              The simulation always covers all of Chennai, because water flows from one area into the next.
              The results below then show what happens at the place you chose.
            </p>
          </SidebarSection>

          <div ref={resultsRef}>
            <SidebarSection n="3" title="Results" action={<Link to="/history" className="flex items-center gap-1 text-[11px] text-mangrove hover:underline"><History size={12} /> History</Link>}>
              <CurrentRun current={current} hasRuns={!!runs?.length} area={area} />
            </SidebarSection>
          </div>
        </div>
      </aside>

      <main className="relative min-w-0 flex-1">
        <TerrainMap focusBbox={focus} area={area} pin={pin} run={current.run} runRunning={running}
                    onPick={(lonlat) => { pickPoint(lonlat); if (window.matchMedia?.('(max-width: 1023px)').matches) setSidebar(true) }}
                    onHome={() => setFocus(null)} />
        {!sidebar && (
          <button type="button" onClick={() => setSidebar(true)}
                  className="absolute bottom-12 left-3 z-20 flex items-center gap-1.5 rounded-md bg-mangrove px-3 py-2 text-sm font-semibold text-ivory shadow-lg lg:bottom-auto lg:top-14">
            <PanelLeftOpen size={16} /> Panel
          </button>
        )}
        {sidebar && (
          <button type="button" onClick={() => setSidebar(false)} title="Hide panel" aria-label="Hide panel"
                  className="absolute left-3 top-14 z-20 hidden rounded-md border border-line-strong bg-paper/95 p-2 text-ink shadow-lg hover:bg-paper-2 lg:block">
            <PanelLeftClose size={16} />
          </button>
        )}
      </main>
    </div>
  )
}

function CurrentRun({ current, hasRuns, area }) {
  const { run, error, results, done } = current
  if (!hasRuns && !run) {
    return <p className="text-xs leading-relaxed text-muted">No simulation yet. Set up the rain above and press <b className="text-ink">Run simulation</b>. The results will appear here and on the map.</p>
  }
  if (error && !run) return <ErrorState error={error} title="Could not load the simulation" />
  if (!run) return <LoadingState rows={2} label="Loading simulation…" />
  return (
    <div className="space-y-3">
      <RunHeader run={run} />
      {(run.status === 'queued' || run.status === 'running') && <RunProgress run={run} />}
      {run.status === 'failed' && <ErrorState title="This simulation could not finish" error={{ message: run.error || 'No error message recorded.' }} />}
      {done && !results.data && !results.error && <LoadingState rows={3} label="Loading results…" />}
      {done && results.error && <ErrorState error={results.error} onRetry={results.reload} />}
      {done && results.data && (
        <>
          <div className="rounded-md border border-mangrove/30 bg-mangrove/5 p-2.5">
            <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-mangrove">At the place you chose</h4>
            <LocationRunSummary area={area} runId={run.id} />
          </div>
          <RunSummary run={run} r={results.data} />
        </>
      )}
    </div>
  )
}

function SidebarSection({ n, title, action, children }) {
  return (
    <section className="border-b border-line px-4 py-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-mangrove/15 font-mono text-[10px] text-mangrove">{n}</span>
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  )
}
