import { Fragment, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronRight, ExternalLink, History, Loader2, RefreshCw } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { getSimulationResults, listSimulations } from '../services/floinApi'
import { getRunLocations } from '../services/runLocations'
import { RunSummary, useRun } from '../components/workspace/RunResults'
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/common/ui'
import { fmt, fmtDate } from '../utils/format'

const PAGE = 25

export default function SimulationHistory() {
  const list = useApi((signal) => listSimulations(200, { signal }), [])
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState(null)
  const [query, setQuery] = useState('')
  const locations = useMemo(() => getRunLocations(), [])
  const navigate = useNavigate()

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (list.data || []).filter((r) => !q || r.scenario.toLowerCase().includes(q) || r.id.toLowerCase().includes(q)
      || (locations[r.id]?.label || '').toLowerCase().includes(q))
  }, [list.data, query, locations])
  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const visible = rows.slice(page * PAGE, page * PAGE + PAGE)

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-6 md:px-6">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold text-ink"><History size={20} className="text-mangrove" /> Simulation history</h1>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">
              Runs stored by the FLOIN backend (PostgreSQL), newest first. Opening a run shows its stored inputs and results in the
              workspace; it does not run the simulation again.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input value={query} onChange={(e) => { setQuery(e.target.value); setPage(0) }} placeholder="Filter by name, ID or location"
                   aria-label="Filter simulations" className="w-56 rounded-md border border-line-strong bg-paper px-2.5 py-1.5 text-sm text-ink placeholder:text-faint focus:border-mangrove focus:outline-none" />
            <button type="button" onClick={list.reload} title="Refresh" aria-label="Refresh"
                    className="rounded-md border border-line-strong bg-paper p-2 text-muted hover:text-ink"><RefreshCw size={15} /></button>
          </div>
        </div>

        {list.loading && <LoadingState rows={6} label="Loading simulations…" />}
        {list.error && <ErrorState error={list.error} onRetry={list.reload} title="Could not load the simulation history" />}
        {list.data && list.data.length === 0 && (
          <EmptyState title="No simulations yet. Run your first simulation to see it here."
                      action={<Link to="/simulation" className="rounded-md bg-mangrove px-3 py-2 text-sm font-semibold text-ivory">Open the workspace</Link>} />
        )}
        {list.data && list.data.length > 0 && (
          <>
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full min-w-[860px] text-left text-sm">
                <thead className="bg-paper-2 text-[10px] uppercase tracking-wider text-muted">
                  <tr>
                    <th scope="col" className="w-8 px-2 py-2"><span className="sr-only">Expand</span></th>
                    <th scope="col" className="px-3 py-2 font-medium">Simulation</th>
                    <th scope="col" className="px-3 py-2 font-medium">Date</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Rainfall</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Duration</th>
                    <th scope="col" className="px-3 py-2 font-medium">Location</th>
                    <th scope="col" className="px-3 py-2 font-medium">Status</th>
                    <th scope="col" className="px-3 py-2 font-medium">Result summary</th>
                    <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line bg-paper">
                  {visible.map((r) => {
                    const open = expanded === r.id
                    const loc = locations[r.id]
                    return (
                      <Fragment key={r.id}>
                        <tr className={open ? 'bg-paper-2/60' : 'hover:bg-paper-2/40'}>
                          <td className="px-2 py-2">
                            <button type="button" onClick={() => setExpanded(open ? null : r.id)} aria-expanded={open}
                                    aria-label={open ? 'Hide details' : 'View details'} className="rounded p-1 text-muted hover:text-ink">
                              {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                            </button>
                          </td>
                          <td className="px-3 py-2">
                            <div className="font-medium text-ink">{r.scenario}</div>
                            <div className="font-mono text-[10px] text-faint">{r.id}</div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-xs">{fmtDate(r.created_at)}</td>
                          <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-xs">{r.rainfall_source === 'uniform' ? `${fmt(r.rainfall_mm)} mm` : <span title={r.rainfall_dataset}>grid</span>}</td>
                          <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-xs">{fmt(r.duration_hours)} h</td>
                          <td className="max-w-[12rem] px-3 py-2 text-xs">
                            {loc ? <><div className="truncate text-ink" title={loc.label}>{loc.label}</div><div className="text-[10px] text-faint">saved in this browser</div></>
                              : <span className="text-faint" title="The backend does not store a location; every run covers the whole model area.">whole model area</span>}
                          </td>
                          <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                          <td className="px-3 py-2 text-xs"><Summary run={r} /></td>
                          <td className="px-3 py-2 text-right">
                            <button type="button" onClick={() => navigate(`/simulation?run=${encodeURIComponent(r.id)}`)}
                                    className="inline-flex items-center gap-1 rounded-md border border-mangrove/50 px-2.5 py-1 text-xs font-semibold text-mangrove hover:bg-mangrove/10">
                              Open <ExternalLink size={12} />
                            </button>
                          </td>
                        </tr>
                        {open && (
                          <tr className="bg-ivory/60">
                            <td colSpan={9} className="px-4 py-4"><Details runId={r.id} location={loc} /></td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted">
              <span>{rows.length} simulation{rows.length === 1 ? '' : 's'}{list.data.length >= 200 ? ' (latest 200)' : ''}</span>
              {pages > 1 && (
                <div className="flex items-center gap-2">
                  <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="rounded border border-line-strong px-2 py-1 disabled:opacity-40">Previous</button>
                  <span>Page {page + 1} of {pages}</span>
                  <button type="button" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)} className="rounded border border-line-strong px-2 py-1 disabled:opacity-40">Next</button>
                </div>
              )}
            </div>
            <p className="mt-3 text-[11px] text-faint">
              Locations: the backend's simulation API has no location field, so the location you had selected when starting a run is
              remembered in this browser only. Runs started elsewhere show “whole model area”, which is what every run simulates.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

/** One-line summary from the stored results of a completed run. */
function Summary({ run }) {
  const res = useApi((signal) => getSimulationResults(run.id, { signal }), [run.id], { enabled: run.status === 'completed' })
  if (run.status === 'failed') return <span className="text-terracotta-ink" title={run.error || ''}>failed{run.current_stage ? ` at ${run.current_stage}` : ''}</span>
  if (run.status !== 'completed') return <span className="flex items-center gap-1 text-muted"><Loader2 size={12} className="animate-spin" /> {run.current_stage || run.status}</span>
  if (res.loading) return <span className="text-faint">…</span>
  if (res.error) return <span className="text-terracotta-ink">results unavailable</span>
  const r = res.data
  return (
    <span className="font-mono text-[11px] text-ink">
      runoff {fmt(r.hydrology.runoff_mm.mean)} mm · flooded {fmt(r.flood.flooded_area_km2)} km² · max {fmt(r.flood.max_depth_m, { digits: 1 })} m
    </span>
  )
}

function Details({ runId, location }) {
  const { run, error, results, done } = useRun(runId)
  if (error && !run) return <ErrorState error={error} />
  if (!run) return <LoadingState rows={3} />
  if (run.status === 'failed') return <ErrorState title={`Simulation failed${run.current_stage ? ` at "${run.current_stage}"` : ''}`} error={{ message: run.error || 'No error message recorded.' }} />
  if (!done) return <p className="text-xs text-muted">This run is {run.status} ({run.current_stage}). Details appear when it completes.</p>
  if (results.error) return <ErrorState error={results.error} onRetry={results.reload} />
  if (!results.data) return <LoadingState rows={4} label="Loading stored results…" />
  return (
    <div className="grid gap-6 md:grid-cols-[1fr_18rem]">
      <RunSummary run={run} r={results.data} full />
      <div className="space-y-3">
        <div className="rounded-md border border-line p-3">
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Stored inputs & outputs</h4>
          <ul className="space-y-0.5 text-[11px]">
            {(run.inputs || []).map((i) => <li key={i.role} className="truncate text-muted"><span className="text-ink">{i.role}</span>: {i.dataset_name}</li>)}
          </ul>
          <ul className="mt-2 space-y-0.5 text-[11px]">
            {(run.outputs || []).map((o) => <li key={o.name} className="text-muted"><span className="text-ink">{o.name}</span> · {o.format} · {fmt(o.size_bytes / 1e6, { digits: 1 })} MB</li>)}
          </ul>
        </div>
        {location && (
          <div className="rounded-md border border-line p-3 text-xs text-muted">
            Started with <span className="text-ink">{location.label}</span> selected (remembered in this browser). Open the run to see its figures for that location.
          </div>
        )}
      </div>
    </div>
  )
}
