import { Crosshair, Loader2, MapPin, X } from 'lucide-react'
import { useApi } from '../../hooks/useApi'
import { useArea } from '../../context/AreaContext'
import { useAreaStats } from '../../hooks/useAreaData'
import { featuresNear, NEAR_RADIUS_M } from '../../services/pointFeatures'
import { terrainGrid } from '../../services/cache'
import LocalitySearch from '../search/LocalitySearch'
import { ErrorState } from '../common/ui'
import { lonLatToUtm } from '../../utils/utm'
import { fmt, fmtInt } from '../../utils/format'

const HYDRO_LABELS = {
  gcc_basin_rivers: 'Rivers & streams',
  gcc_buckingham_canal: 'Buckingham Canal',
  gcc_basin_macro_drains: 'Macro drains',
  gcc_basin_micro_drains: 'Micro drains',
  gcc_storm_water_drains_2023: 'Storm-water drains',
}

export default function LocationPanel({ onZoom }) {
  const { area, clear } = useArea()
  return (
    <div className="space-y-3">
      <LocalitySearch />
      {!area && <p className="text-xs leading-relaxed text-muted">Search a locality, GCC zone or ward, or click anywhere on the map to inspect that point.</p>}
      {area && (
        <div className="rounded-md border border-line bg-ivory/60 p-2.5">
          <div className="flex items-start gap-2">
            <MapPin size={15} className="mt-0.5 shrink-0 text-mangrove" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-ink">{area.label}</div>
              {area.sublabel && <div className="truncate text-[11px] text-muted">{area.sublabel}</div>}
            </div>
            <button type="button" onClick={() => onZoom(area)} title="Zoom the map here" aria-label="Zoom the map here"
                    className="rounded p-1 text-muted hover:bg-paper-2 hover:text-mangrove"><Crosshair size={15} /></button>
            <button type="button" onClick={clear} title="Clear the selection" aria-label="Clear the selection"
                    className="rounded p-1 text-muted hover:bg-paper-2 hover:text-ink"><X size={15} /></button>
          </div>
          <div className="mt-2 border-t border-line pt-2">
            {area.kind === 'map-point' ? <PointDetails area={area} /> : <AreaDetails area={area} />}
          </div>
        </div>
      )}
    </div>
  )
}

function PointDetails({ area }) {
  const [lon, lat] = area.point
  const grid = useApi((signal) => terrainGrid(signal), [])
  const near = useApi((signal) => featuresNear(area.point, signal), [area.id])
  const [e, n] = lonLatToUtm(lon, lat, 44)
  let elevation
  if (grid.data) {
    const [left, , , top] = grid.data.bounds_projected
    const c = Math.floor((e - left) / grid.data.cell_size_m)
    const r = Math.floor((top - n) / grid.data.cell_size_m)
    elevation = grid.data.values[r]?.[c]
  }
  return (
    <div className="space-y-2.5">
      <dl className="space-y-0.5 text-xs">
        <KV k="Latitude, longitude" v={`${lat.toFixed(5)}°, ${lon.toFixed(5)}°`} />
        <KV k="UTM 44N (m)" v={`${Math.round(e)} E, ${Math.round(n)} N`} />
        <KV k={`Ground elevation`} v={grid.data ? (elevation == null ? 'open sea / outside model' : `${fmt(elevation)} m`) : '…'}
            sub={grid.data && `${grid.data.cell_size_m} m block mean of the Copernicus GLO-30 surface model`} />
        <KV k="GCC ward · zone" v={area.containingWard ? `Ward ${area.containingWard.code} · ${area.containingWard.zone}` : 'outside GCC wards'} />
      </dl>
      <div>
        <div className="mb-1 text-[11px] font-medium text-muted">Mapped features within {NEAR_RADIUS_M} m</div>
        {near.loading && <p className="flex items-center gap-1.5 text-xs text-muted"><Loader2 size={12} className="animate-spin" /> Querying the FLOIN database…</p>}
        {near.error && <ErrorState error={near.error} />}
        {near.data && near.data.features.length === 0 && <p className="text-xs text-muted">No road, railway, waterway, drain, water body or building is mapped this close.</p>}
        {near.data && near.data.features.length > 0 && (
          <ul className="scroll-thin max-h-56 space-y-1.5 overflow-y-auto pr-1">
            {near.data.features.slice(0, 12).map((f) => <FeatureItem key={f.key} f={f} />)}
          </ul>
        )}
        {near.data?.failed.length > 0 && <p className="mt-1 text-[11px] text-terracotta-ink">Not loaded: {near.data.failed.join(', ')}</p>}
      </div>
    </div>
  )
}

// Descriptive attributes worth showing, with readable labels. Identifiers (id, source_id) are left out.
const ATTRIBUTE_LABELS = {
  highway: 'Road type',
  building_type: 'Building type',
  railway: 'Railway type',
  waterway_type: 'Waterway type',
  drain_class: 'Drain type',
  water_type: 'Water body type',
}
const readable = (v) => String(v).replace(/_/g, ' ')

function FeatureItem({ f }) {
  const p = f.properties
  const attrs = Object.entries(ATTRIBUTE_LABELS)
    .filter(([k]) => p[k] !== null && p[k] !== undefined && p[k] !== '')
    // OSM building=yes means the type was not recorded.
    .map(([k, label]) => [label, k === 'building_type' && p[k] === 'yes' ? 'not specified in OSM' : readable(p[k])])
  if (p.is_metro) attrs.push(['Metro', 'yes'])
  return (
    <li className="rounded border border-line px-2 py-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-xs font-semibold text-ink">{p.name || <span className="font-normal italic text-muted">No name in the database</span>}</span>
        <span className="shrink-0 font-mono text-[10px] text-faint">{f.distance_m === 0 ? 'here' : `${Math.round(f.distance_m)} m`}</span>
      </div>
      <div className="text-[11px] text-muted">{f.label}</div>
      {attrs.length > 0 && (
        <dl className="mt-0.5 space-y-0.5 text-[11px]">
          {attrs.map(([label, v]) => (
            <div key={label} className="flex gap-1.5"><dt className="text-faint">{label}:</dt><dd className="text-ink">{v}</dd></div>
          ))}
        </dl>
      )}
    </li>
  )
}

function AreaDetails({ area }) {
  const s = useAreaStats(area)
  if (!area.geometry) {
    return <p className="text-xs text-muted">{area.boundarySource === 'loading' ? 'Loading ward boundaries…' : area.note}</p>
  }
  const count = (c, state) => (state.error ? 'error' : c ? `${fmtInt(c.n)}${c.truncated ? '+' : ''}` : '…')
  return (
    <dl className="space-y-0.5 text-xs">
      <KV k="Boundary" v={area.boundarySource} />
      {area.note && <p className="text-[11px] text-lime-ink">{area.note}</p>}
      <KV k="Area" v={`${fmt(s.areaKm2, { digits: 2 })} km²`} />
      {area.zones?.length > 0 && <KV k="GCC zone" v={area.zones.join(', ')} />}
      {area.wardCodes?.length > 0 && <KV k="GCC wards" v={area.wardCodes.length > 12 ? `${area.wardCodes.length} wards` : area.wardCodes.join(', ')} />}
      {s.insideModel === false && <p className="text-[11px] text-terracotta-ink">Part of this area lies outside the FLOIN model area.</p>}
      <KV k="Elevation range" v={s.elevation ? `${fmt(s.elevation.min)} – ${fmt(s.elevation.max)} m` : s.elevationState.error ? 'error' : '…'}
          sub={s.elevation && `median ${fmt(s.elevation.median)} m · ${s.elevation.n} blocks of ${s.elevation.cellSize} m`} />
      {Object.entries(HYDRO_LABELS).map(([k, label]) => (
        <KV key={k} k={label} v={s.hydro ? count(s.hydro[k], s.hydroState) : s.hydroState.error ? 'error' : '…'} />
      ))}
      <KV k="Road features (OSM)" v={count(s.roads, s.roadsState)} />
      <KV k="Buildings (OSM)" v={count(s.buildings, s.buildingsState)} sub="lower bound: OSM building coverage is incomplete" />
      <p className="pt-1 text-[10px] text-faint">Counts are database features touching the boundary. “+” means the request limit was reached.</p>
    </dl>
  )
}

function KV({ k, v, sub }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-2">
      <dt className="text-muted">{k}</dt>
      <dd className="min-w-0 break-words text-ink">{v}{sub && <div className="text-[10px] text-faint">{sub}</div>}</dd>
    </div>
  )
}
