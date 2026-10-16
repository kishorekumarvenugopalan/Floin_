import { useEffect, useState } from 'react'
import { CheckCircle2, Circle, Loader2 } from 'lucide-react'
import { useApi, usePolling } from '../../hooks/useApi'
import { getSimulation, getSimulationResults, getSimulationWards } from '../../services/floinApi'
import { depthOverlay, terrainGrid } from '../../services/cache'
import { useAreaRunSummary } from '../../hooks/useAreaData'
import { ErrorState, LoadingState, StatusBadge } from '../common/ui'
import { lonLatToUtm } from '../../utils/utm'
import { fmt, fmtDate, fmtDuration, fmtInt, fmtPct, fmtVolume, titleCase } from '../../utils/format'

// Stage names written by the backend simulation service.
const STAGES = ['resolve_datasets', 'rainfall', 'curve_number', 'runoff', 'routing', 'flood_depth', 'flood_extent', 'exposure', 'store_outputs']

/** A run (polled every 4 s until it finishes) and, once completed, its stored results. */
export function useRun(runId) {
  const [run, setRun] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { setRun(null); setError(null) }, [runId])
  const finished = run && run.id === runId && (run.status === 'completed' || run.status === 'failed')
  usePolling(async (signal) => {
    try {
      const r = await getSimulation(runId, { signal })
      setRun(r)
      setError(null)
    } catch (err) {
      if (!signal.aborted) setError(err)
    }
  }, 4000, !!runId && !finished)
  const done = run?.id === runId && run?.status === 'completed'
  const results = useApi((signal) => getSimulationResults(runId, { signal }), [runId], { enabled: done })
  return { run: run?.id === runId ? run : null, error, results, done }
}

export function RunProgress({ run }) {
  const current = STAGES.indexOf(run.current_stage)
  return (
    <div>
      <ol className="space-y-1">
        {STAGES.map((s, i) => {
          const isDone = current > i
          const active = current === i
          return (
            <li key={s} className={`flex items-center gap-2 text-xs ${active ? 'text-mangrove' : isDone ? 'text-ink' : 'text-faint'}`}>
              {isDone ? <CheckCircle2 size={13} className="text-teal-ink" /> : active ? <Loader2 size={13} className="animate-spin" /> : <Circle size={13} />}
              {titleCase(s)}
            </li>
          )
        })}
      </ol>
      <p className="mt-2 text-[11px] text-faint">{run.status === 'queued' ? 'Queued, waiting to start…' : 'Runs take a few minutes; exposure (PostGIS overlays) is usually the longest stage. You can keep exploring the map.'}</p>
    </div>
  )
}

/** Stored results of one completed run. Only values present in the backend response are shown. */
export function RunSummary({ run, r, full = false }) {
  const h = r.hydrology
  const f = r.flood
  const e = r.exposure
  const p = run.parameters || {}
  const roads = Object.entries(e.roads?.by_highway_km || {}).sort((a, b) => b[1] - a[1])
  return (
    <div className="space-y-3">
      <Section title="Inputs used">
        <Row k="Rainfall" v={run.rainfall_source === 'uniform' ? `${fmt(run.rainfall_mm)} mm, uniform` : `${run.rainfall_dataset} (mean ${fmt(h.rainfall_mm?.mean)} mm)`} />
        <Row k="Duration" v={`${fmt(run.duration_hours)} h · mean intensity ${fmt(h.mean_intensity_mm_per_hour, { digits: 2 })} mm/h`} />
        <Row k="Antecedent moisture" v={p.antecedent_moisture} />
        <Row k="Ia ratio · min depth" v={`${p.ia_ratio} · ${p.min_flood_depth_m} m`} />
        {full && <Row k="Depth class breaks" v={(p.depth_class_breaks_m || []).join(', ') + ' m'} />}
      </Section>

      <Section title="Runoff estimate (SCS-CN)">
        <Row k="Direct runoff depth" v={`${fmt(h.runoff_mm?.mean)} mm mean`} sub={`range ${fmt(h.runoff_mm?.min)}–${fmt(h.runoff_mm?.max)} mm`} />
        <Row k="Runoff volume" v={fmtVolume(h.runoff_volume_m3)} sub={`of ${fmtVolume(h.rainfall_volume_m3)} rainfall`} />
        <Row k="Runoff coefficient" v={fmt(h.runoff_coefficient, { digits: 2 })} />
        <Row k="Curve number (derived)" v={`${fmt(h.curve_number?.mean)} mean`} sub={`range ${fmt(h.curve_number?.min)}–${fmt(h.curve_number?.max)}`} />
      </Section>

      <Section title="Flood screening (whole model area)">
        <Row k="Flooded area" v={`${fmt(f.flooded_area_km2)} km²`} sub={`depth ≥ ${f.min_flood_depth_m} m, lakes and channels excluded`} />
        <Row k="Depth" v={`mean ${fmt(f.mean_depth_m, { digits: 2 })} m · max ${fmt(f.max_depth_m, { digits: 2 })} m`} sub={`95th percentile ${fmt(f.p95_depth_m, { digits: 2 })} m`} />
        {f.flood_volume_m3 != null && <Row k="Flood water volume" v={fmtVolume(f.flood_volume_m3)} />}
        {(f.class_names || []).length > 0 && (
          <Row k="Area by depth class" v={(f.class_names || []).map((c) => `${c}: ${fmt(f.by_class?.[c]?.area_km2, { digits: 2 })}`).join(' · ') + ' km²'} />
        )}
        {full && <Row k="Flood polygons" v={fmtInt(f.polygon_count)} />}
      </Section>

      <Section title="Exposure (OpenStreetMap assets)">
        <Row k="Buildings reached" v={fmtInt(e.buildings?.affected)} sub={`of ${fmtInt(e.buildings?.total_in_layer)} mapped · lower bound, OSM is incomplete`} />
        <Row k="At-grade roads in flood" v={`${fmt(e.roads?.affected_km)} km`} sub={`bridges/tunnels excluded (${fmt(e.roads?.excluded_bridge_or_tunnel_km)} km)`} />
        <Row k="Rail · metro at grade" v={`${fmt(e.railways?.affected_rail_km, { digits: 2 })} km · ${fmt(e.railways?.affected_metro_km, { digits: 2 })} km`} />
        {full && roads.length > 0 && <Row k="Roads by class" v={roads.slice(0, 8).map(([k, v]) => `${k} ${fmt(v)} km`).join(' · ')} />}
        {full && <Row k="Population" v={e.population} />}
        {full && <Row k="Critical infrastructure" v={e.critical_infrastructure} />}
      </Section>

      <p className="font-mono text-[10px] text-faint">
        {run.id} · {run.model_version} · created {fmtDate(run.created_at)} · runtime {fmtDuration(run.runtime_seconds)}
      </p>
    </div>
  )
}

/** The run at the selected location: exact ward figures, block estimate, or the clicked block. */
export function LocationRunSummary({ area, runId }) {
  const isPoint = area?.kind === 'map-point'
  const wards = useApi((signal) => getSimulationWards(runId, { signal }), [runId], { enabled: !!runId && !!area?.wardIds?.length })
  const summary = useAreaRunSummary(area, runId, wards.data)
  const overlay = useApi((signal) => depthOverlay(runId, signal), [runId], { enabled: !!runId && isPoint })
  const grid = useApi((signal) => terrainGrid(signal), [], { enabled: !!runId && isPoint })
  if (!area) return <p className="text-xs text-muted">Select a location (search or click the map) to see this run there.</p>

  let block = null
  if (isPoint && overlay.data && grid.data && overlay.data.depth_mean.length === grid.data.height) {
    const [left, , , top] = grid.data.bounds_projected
    const [e, n] = lonLatToUtm(area.point[0], area.point[1], 44)
    const c = Math.floor((e - left) / grid.data.cell_size_m)
    const rr = Math.floor((top - n) / grid.data.cell_size_m)
    block = {
      size: grid.data.cell_size_m,
      share: overlay.data.flooded_share[rr]?.[c],
      mean: overlay.data.depth_mean[rr]?.[c],
      max: overlay.data.depth_max[rr]?.[c],
    }
  }
  const w = summary.wardTotals
  const b = summary.blocks
  return (
    <div className="space-y-2">
      {isPoint && (
        <div>
          <div className="text-[11px] font-medium text-muted">At the clicked {block?.size ?? 90} m block</div>
          {(overlay.loading || grid.loading) && <LoadingState rows={1} label="Reading the depth grid…" />}
          {overlay.error && <ErrorState error={overlay.error} />}
          {block && (
            block.share == null
              ? <p className="text-xs text-muted">No modelled value here (open sea or outside the model area).</p>
              : <dl className="grid grid-cols-2 gap-y-0.5 text-xs">
                  <dt className="text-muted">Flooded share</dt><dd className="text-right font-mono">{fmtPct(block.share)}</dd>
                  <dt className="text-muted">Depth, block mean</dt><dd className="text-right font-mono">{fmt(block.mean, { digits: 2 })} m</dd>
                  <dt className="text-muted">Depth, deepest cell</dt><dd className="text-right font-mono">{fmt(block.max, { digits: 2 })} m</dd>
                </dl>
          )}
        </div>
      )}
      {w && (
        <div>
          <div className="text-[11px] font-medium text-muted">
            {isPoint ? `GCC ward ${area.containingWard?.code ?? ''} containing the point` : `${w.wards} GCC ward${w.wards > 1 ? 's' : ''}`} · exact, from the stored ward summary
          </div>
          <dl className="grid grid-cols-2 gap-y-0.5 text-xs">
            <dt className="text-muted">Flooded area</dt><dd className="text-right font-mono">{fmt(w.flooded_area_km2, { digits: 2 })} km² ({fmtPct(w.flooded_area_km2 / w.area_km2)})</dd>
            <dt className="text-muted">Buildings reached</dt><dd className="text-right font-mono">{fmtInt(w.buildings_affected)}</dd>
            <dt className="text-muted">At-grade roads</dt><dd className="text-right font-mono">{fmt(w.road_km)} km</dd>
          </dl>
        </div>
      )}
      {wards.error && <ErrorState error={wards.error} />}
      {!isPoint && area.geometry && (
        <div>
          <div className="text-[11px] font-medium text-muted">Inside the boundary · estimate from {b?.cell_size_m ?? 90} m blocks</div>
          {summary.error && <ErrorState error={summary.error} />}
          {b ? (
            <dl className="grid grid-cols-2 gap-y-0.5 text-xs">
              <dt className="text-muted">Wet area</dt><dd className="text-right font-mono">{fmt(b.flooded_km2, { digits: 2 })} km²</dd>
              <dt className="text-muted">Deepest cell</dt><dd className="text-right font-mono">{fmt(b.max_depth_m, { digits: 2 })} m</dd>
            </dl>
          ) : !summary.error && <LoadingState rows={1} label="Summarising…" />}
          <p className="mt-0.5 text-[10px] text-faint">Includes water standing in lakes and channels, unlike the official flooded area.</p>
        </div>
      )}
      {isPoint && !area.containingWard && <p className="text-[11px] text-faint">The point is outside the GCC wards, so no ward figures exist for it.</p>}
    </div>
  )
}

export function RunHeader({ run }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-ink">{run.scenario}</div>
        <div className="font-mono text-[10px] text-faint">{run.id} · {fmtDate(run.created_at)}</div>
      </div>
      <StatusBadge status={run.status} />
    </div>
  )
}

export function Section({ title, children }) {
  return (
    <section>
      <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</h4>
      <dl className="space-y-1">{children}</dl>
    </section>
  )
}

export function Row({ k, v, sub }) {
  if (v === undefined || v === null || v === '') return null
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-2 text-xs">
      <dt className="text-muted">{k}</dt>
      <dd className="min-w-0 text-ink">
        <span className="font-mono text-[11.5px]">{v}</span>
        {sub && <div className="text-[10.5px] text-faint">{sub}</div>}
      </dd>
    </div>
  )
}
