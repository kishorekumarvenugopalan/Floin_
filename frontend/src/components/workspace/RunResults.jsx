import { useEffect, useState } from 'react'
import { CheckCircle2, Circle, Loader2 } from 'lucide-react'
import { useApi, usePolling } from '../../hooks/useApi'
import { getSimulation, getSimulationResults, getSimulationWards } from '../../services/floinApi'
import { depthOverlay, terrainGrid } from '../../services/cache'
import { useAreaRunSummary } from '../../hooks/useAreaData'
import { ErrorState, LoadingState, StatusBadge } from '../common/ui'
import { lonLatToUtm } from '../../utils/utm'
import { fmt, fmtDate, fmtDuration, fmtInt } from '../../utils/format'
import {
  areaText, classLabels, depthText, depthWords, GROUND_SHORT, lengthText, shareText, stormName, volumeText,
} from '../../utils/plain'

// Stage names written by the backend simulation service, with plain descriptions.
const STAGES = [
  ['resolve_datasets', 'Loading the map data'],
  ['rainfall', 'Adding the rain'],
  ['curve_number', 'Checking land and soil'],
  ['runoff', 'Working out how much rain runs off'],
  ['routing', 'Following the water downhill'],
  ['flood_depth', 'Finding where the water collects'],
  ['flood_extent', 'Mapping the flooded areas'],
  ['exposure', 'Counting affected buildings and roads'],
  ['store_outputs', 'Saving the results'],
]
const STATUS_LABELS = { completed: 'Finished', running: 'Running', queued: 'Waiting', failed: 'Failed' }

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
  const current = STAGES.findIndex(([s]) => s === run.current_stage)
  return (
    <div>
      <ol className="space-y-1">
        {STAGES.map(([s, label], i) => {
          const isDone = current > i
          const active = current === i
          return (
            <li key={s} className={`flex items-center gap-2 text-xs ${active ? 'text-mangrove' : isDone ? 'text-ink' : 'text-faint'}`}>
              {isDone ? <CheckCircle2 size={13} className="text-teal-ink" /> : active ? <Loader2 size={13} className="animate-spin" /> : <Circle size={13} />}
              {label}
            </li>
          )
        })}
      </ol>
      <p className="mt-2 text-[11px] text-faint">
        {run.status === 'queued' ? 'Waiting to start…' : 'This usually takes 2–5 minutes. Counting the affected buildings and roads is the slowest step. You can keep exploring the map meanwhile.'}
      </p>
    </div>
  )
}

/** Stored results of one completed run, in plain language. Only values from the backend are shown. */
export function RunSummary({ run, r, full = false }) {
  const h = r.hydrology
  const f = r.flood
  const e = r.exposure
  const p = run.parameters || {}
  const minDepth = f.min_flood_depth_m
  const classes = classLabels(f.class_names, f.class_breaks_m, minDepth)
  const roads = Object.entries(e.roads?.by_highway_km || {}).sort((a, b) => b[1] - a[1])
  const railKm = (e.railways?.affected_rail_km || 0) + (e.railways?.affected_metro_km || 0)
  return (
    <div className="space-y-3">
      <div className="rounded-md bg-paper-2 px-3 py-2 text-xs leading-relaxed text-ink">
        <div className="mb-0.5 font-semibold">In short</div>
        {f.flooded_area_km2 > 0
          ? <>Water at least {depthText(minDepth)} deep covers <b>{areaText(f.flooded_area_km2)}</b> of Chennai.</>
          : <>No part of Chennai gets water {depthText(minDepth)} deep or more.</>}{' '}
        It touches <b>{e.buildings?.affected ? `${fmtInt(e.buildings.affected)} building${e.buildings.affected === 1 ? '' : 's'}` : 'no buildings'}</b> and{' '}
        <b>{e.roads?.affected_km ? `${lengthText(e.roads.affected_km)} of road` : 'no roads'}</b>.
        {f.max_depth_m > 0 && <> The deepest water is {depthText(f.max_depth_m)} ({depthWords(f.max_depth_m)}).</>}
      </div>

      <Section title="What you entered">
        <Row k="Rain" v={run.rainfall_source === 'uniform'
          ? `${fmt(run.rainfall_mm)} mm, the same everywhere`
          : `${stormName(run.rainfall_dataset)}: ${fmt(h.rainfall_mm?.min, { digits: 0 })}–${fmt(h.rainfall_mm?.max, { digits: 0 })} mm depending on the area`} />
        <Row k="How long it rained" v={`${fmt(run.duration_hours)} hour${run.duration_hours === 1 ? '' : 's'}`} />
        <Row k="Ground before the rain" v={GROUND_SHORT[p.antecedent_moisture] || p.antecedent_moisture} />
      </Section>

      <Section title="Where the rain went">
        <Row k="Rain that fell on Chennai" v={volumeText(h.rainfall_volume_m3)} />
        <Row k="Rain that ran off" v={`${volumeText(h.runoff_volume_m3)}`}
             sub={`${shareText(h.runoff_coefficient)} of the rain. The rest soaked into the ground or was held back by plants and small dips.`} />
      </Section>

      <Section title="Flooding across Chennai">
        <Row k="Area under water" v={areaText(f.flooded_area_km2)} sub={`Water at least ${depthText(minDepth)} deep. Lakes, tanks and canals are not counted.`} />
        <Row k="Typical water depth" v={depthText(f.mean_depth_m)} sub={depthWords(f.mean_depth_m)} />
        <Row k="Deepest water" v={depthText(f.max_depth_m)} sub={depthWords(f.max_depth_m)} />
        {classes.length > 0 && (
          <div className="grid grid-cols-[8.5rem_1fr] gap-2 text-xs">
            <dt className="text-muted">How deep the flooded area is</dt>
            <dd className="space-y-0.5">
              {classes.map(({ name, label }) => (
                <div key={name} className="flex justify-between gap-2">
                  <span className="text-muted">{label}</span>
                  <span className="text-ink">{areaText(f.by_class?.[name]?.area_km2)}</span>
                </div>
              ))}
            </dd>
          </div>
        )}
      </Section>

      <Section title="What the water touches">
        <Row k="Buildings" v={fmtInt(e.buildings?.affected)} sub={`out of ${fmtInt(e.buildings?.total_in_layer)} buildings on the map. The building map is incomplete, so the real number may be higher.`} />
        <Row k="Roads under water" v={lengthText(e.roads?.affected_km)} sub="Bridges, flyovers and tunnels are not counted." />
        <Row k="Railway and metro track" v={lengthText(railKm)} />
      </Section>

      {full && (
        <Section title="Technical details">
          <Row k="Model" v={f.model_type} />
          <Row k="Ia ratio · min. depth" v={`${p.ia_ratio} · ${p.min_flood_depth_m} m`} />
          <Row k="Depth class breaks" v={(p.depth_class_breaks_m || []).join(', ') + ' m'} />
          <Row k="Direct runoff depth" v={`${fmt(h.runoff_mm?.mean, { digits: 2 })} mm mean`} sub={`range ${fmt(h.runoff_mm?.min)}–${fmt(h.runoff_mm?.max)} mm`} />
          <Row k="Runoff coefficient" v={fmt(h.runoff_coefficient, { digits: 3 })} />
          <Row k="Curve number (derived)" v={`${fmt(h.curve_number?.mean)} mean`} sub={`range ${fmt(h.curve_number?.min)}–${fmt(h.curve_number?.max)}`} />
          <Row k="Flood water volume" v={volumeText(f.flood_volume_m3)} />
          <Row k="Flood polygons" v={fmtInt(f.polygon_count)} />
          {roads.length > 0 && <Row k="Roads by class" v={roads.slice(0, 8).map(([k, v]) => `${k} ${lengthText(v)}`).join(' · ')} />}
          <Row k="Population" v={e.population} />
          <Row k="Critical infrastructure" v={e.critical_infrastructure} />
        </Section>
      )}

      <p className="text-[10px] text-faint">
        Simulation {run.id} · created {fmtDate(run.created_at)} · took {fmtDuration(run.runtime_seconds)}
      </p>
    </div>
  )
}

/** The run at the selected place: exact ward figures, an area estimate, or the clicked spot. */
export function LocationRunSummary({ area, runId }) {
  const isPoint = area?.kind === 'map-point'
  const wards = useApi((signal) => getSimulationWards(runId, { signal }), [runId], { enabled: !!runId && !!area?.wardIds?.length })
  const summary = useAreaRunSummary(area, runId, wards.data)
  const overlay = useApi((signal) => depthOverlay(runId, signal), [runId], { enabled: !!runId && isPoint })
  const grid = useApi((signal) => terrainGrid(signal), [], { enabled: !!runId && isPoint })
  if (!area) return <p className="text-xs text-muted">Choose a place (search above or click the map) to see what happens there.</p>

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
  const line = (k, v, sub) => (
    <div className="grid grid-cols-[8.5rem_1fr] gap-2 text-xs">
      <dt className="text-muted">{k}</dt>
      <dd className="text-ink">{v}{sub && <div className="text-[10.5px] text-faint">{sub}</div>}</dd>
    </div>
  )
  return (
    <div className="space-y-2.5">
      {isPoint && (
        <div>
          <div className="mb-0.5 text-[11px] font-medium text-muted">At this spot (the {block?.size ?? 90} m square around it)</div>
          {(overlay.loading || grid.loading) && <LoadingState rows={1} label="Reading the results…" />}
          {overlay.error && <ErrorState error={overlay.error} />}
          {block && (
            block.share == null
              ? <p className="text-xs text-muted">No result here: this spot is in the sea or outside the area the model covers.</p>
              : block.share === 0 && !(block.max > 0)
                ? <p className="text-xs text-ink">No water collects at this spot.</p>
                : <dl className="space-y-0.5">
                    {line('Under water', `${shareText(block.share)} of the square`)}
                    {line('Average water depth', depthText(block.mean), depthWords(block.mean))}
                    {line('Deepest water', depthText(block.max), depthWords(block.max))}
                  </dl>
          )}
        </div>
      )}
      {w && (
        <div>
          <div className="mb-0.5 text-[11px] font-medium text-muted">
            {isPoint ? `In Ward ${area.containingWard?.code ?? ''} (the ward this spot is in)` : `In the selected ward${w.wards > 1 ? 's' : ''} (${w.wards})`}
          </div>
          <dl className="space-y-0.5">
            {line('Area under water', areaText(w.flooded_area_km2), `${shareText(w.flooded_area_km2 / w.area_km2)} of the ward area`)}
            {line('Buildings touched', fmtInt(w.buildings_affected))}
            {line('Roads under water', lengthText(w.road_km))}
          </dl>
        </div>
      )}
      {wards.error && <ErrorState error={wards.error} />}
      {!isPoint && area.geometry && (
        <div>
          <div className="mb-0.5 text-[11px] font-medium text-muted">Inside {area.label} (estimate)</div>
          {summary.error && <ErrorState error={summary.error} />}
          {b ? (
            <dl className="space-y-0.5">
              {line('Area under water', areaText(b.flooded_km2), 'Also counts water standing in lakes and canals.')}
              {line('Deepest water', depthText(b.max_depth_m), depthWords(b.max_depth_m))}
            </dl>
          ) : !summary.error && <LoadingState rows={1} label="Working it out…" />}
        </div>
      )}
      {isPoint && !area.containingWard && <p className="text-[11px] text-faint">This spot is outside the Greater Chennai Corporation wards, so there are no ward figures for it.</p>}
    </div>
  )
}

export function RunHeader({ run }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-ink">{run.scenario}</div>
        <div className="text-[10px] text-faint">{fmtDate(run.created_at)}</div>
      </div>
      <StatusBadge status={run.status} label={STATUS_LABELS[run.status]} />
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
        <span>{v}</span>
        {sub && <div className="text-[10.5px] text-faint">{sub}</div>}
      </dd>
    </div>
  )
}
