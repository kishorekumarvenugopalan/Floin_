import { useEffect, useMemo, useRef, useState } from 'react'
import { Home, Layers, Loader2, Maximize2, Minimize2, RotateCcw, X } from 'lucide-react'
import { useApi } from '../../hooks/useApi'
import { depthOverlay, floodPolygons, terrainGrid } from '../../services/cache'
import { getLayerGeojson } from '../../services/floinApi'
import { ErrorBoundary, ErrorState, InfoTip } from '../common/ui'
import TerrainScene, {
  AREA_COLOUR, BUILDING_COLOUR, DEPTH_MAX_M, DEPTH_STOPS, ELEVATION_STOPS, EXTENT_COLOUR, PLAIN_COLOUR,
} from '../threeD/TerrainScene'
import { BASEMAP_ATTRIBUTION, loadBasemap } from '../threeD/basemap'
import { contourInterval, cropGrid, cropOverlay, cropWindow, lonLatBbox, makeFrame } from '../threeD/sceneData'
import { bboxIntersects, bboxOf } from '../../utils/geo'
import { utmToLonLat } from '../../utils/utm'
import { fmt, fmtInt } from '../../utils/format'

function webglAvailable() {
  try {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

// Database layers that can be draped on the terrain. detail: only for a zoomed-in view.
export const MAP_LAYERS = {
  wards_gcc: { label: 'GCC ward boundaries', colour: '#94A3B8', lift: 3, simplify: 15 },
  gcc_basin_rivers: { label: 'Rivers & streams', colour: '#0284C7', lift: 2 },
  gcc_buckingham_canal: { label: 'Buckingham Canal', colour: '#0EA5E9', lift: 2 },
  gcc_basin_macro_drains: { label: 'Macro drains', colour: '#0891B2', lift: 2 },
  gcc_basin_micro_drains: { label: 'Micro drains', colour: '#06B6D4', lift: 2, detail: true },
  gcc_storm_water_drains_2023: { label: 'Storm-water drains', colour: '#22D3EE', lift: 2, detail: true, simplify: 5 },
  osm_railways: { label: 'Rail & metro', colour: '#A855F7', lift: 3 },
  osm_roads: { label: 'Roads', colour: '#475569', lift: 1.5, detail: true },
  osm_buildings: { label: 'Building footprints', colour: BUILDING_COLOUR, detail: true, polygons: true },
}
const DEFAULT_LAYERS = ['gcc_basin_rivers', 'gcc_buckingham_canal']
const MAX_DETAIL_KM2 = 400

const layerCache = new Map()
function fetchLayer(name, bbox, signal) {
  const key = `${name}|${bbox}`
  if (!layerCache.has(key)) {
    const p = getLayerGeojson(name, { bbox, simplify_m: MAP_LAYERS[name].simplify ?? 3, limit: 20000 }).catch((err) => {
      layerCache.delete(key)
      throw err
    })
    layerCache.set(key, p)
  }
  return new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    layerCache.get(key).then(resolve, reject)
  })
}

export default function TerrainMap({ focusBbox, area, pin, run, runRunning, onPick, onHome }) {
  const [hasWebgl] = useState(webglAvailable)
  const [colourMode, setColourMode] = useState('map')
  const [contours, setContours] = useState(false)
  const [exaggeration, setExaggeration] = useState(8)
  const [showDepth, setShowDepth] = useState(true)
  const [showExtent, setShowExtent] = useState(true)
  const [layers, setLayers] = useState(DEFAULT_LAYERS)
  const [panel, setPanel] = useState(false)
  const [legend, setLegend] = useState(() => typeof window !== 'undefined' && window.matchMedia?.('(min-width: 1024px)').matches)
  const [fullscreen, setFullscreen] = useState(false)
  const scene = useRef()
  const wrapper = useRef()
  const runId = run?.status === 'completed' ? run.id : null

  // A newly shown run (e.g. opened from History) always starts with its flood output visible.
  useEffect(() => {
    setShowDepth(true)
    setShowExtent(true)
  }, [runId])
  const hideFloodOutput = () => {
    setShowDepth(false)
    setShowExtent(false)
  }

  const grid = useApi((signal) => terrainGrid(signal), [], { enabled: hasWebgl })
  const overlay = useApi((signal) => depthOverlay(runId, signal), [runId], { enabled: hasWebgl && !!runId })

  const win = useMemo(() => (grid.data ? cropWindow(grid.data, focusBbox) : null), [grid.data, focusBbox])
  const crop = useMemo(() => (grid.data && win ? cropGrid(grid.data, win) : null), [grid.data, win])
  const frame = useMemo(() => (crop ? makeFrame(crop) : null), [crop])
  const overlayFits = overlay.data && grid.data && overlay.data.depth_mean.length === grid.data.height && overlay.data.depth_mean[0]?.length === grid.data.width
  const overlayCrop = useMemo(() => (overlayFits && win ? cropOverlay(overlay.data, win) : null), [overlayFits, overlay.data, win])
  const cropBbox = useMemo(() => (crop ? lonLatBbox(crop.bounds_projected) : null), [crop])
  const bboxParam = cropBbox ? cropBbox.map((v) => v.toFixed(5)).join(',') : null
  const cropKm2 = crop ? (crop.width * crop.height * crop.cell_size_m ** 2) / 1e6 : null
  const detailAllowed = !!focusBbox && cropKm2 != null && cropKm2 <= MAX_DETAIL_KM2
  const interval = frame ? contourInterval(frame.lo, frame.hi) : 5

  const basemap = useApi((signal) => loadBasemap(cropBbox, { signal }), [bboxParam], { enabled: hasWebgl && !!cropBbox && colourMode === 'map' })
  useEffect(() => () => basemap.data?.texture.dispose(), [basemap.data])

  const wantExtent = showExtent && !!runId && detailAllowed
  const extent = useApi((signal) => floodPolygons(runId, signal), [runId], { enabled: hasWebgl && wantExtent })
  const extentFeatures = useMemo(() => {
    if (!wantExtent || !extent.data || !cropBbox) return null
    return extent.data.features.filter((f) => bboxIntersects(bboxOf(f.geometry), cropBbox))
  }, [wantExtent, extent.data, cropBbox])

  const activeLayers = layers.filter((n) => !MAP_LAYERS[n].detail || detailAllowed)
  const vectors = useApi(async (signal) => {
    const settled = await Promise.all(activeLayers.map((name) => fetchLayer(name, bboxParam, signal)
      .then((fc) => ({ name, fc }))
      .catch((error) => {
        if (signal.aborted) throw error
        return { name, error }
      })))
    return Object.fromEntries(settled.map((x) => [x.name, x]))
  }, [activeLayers.join(','), bboxParam], { enabled: hasWebgl && !!bboxParam && activeLayers.length > 0 })
  const lineLayers = useMemo(() => activeLayers
    .filter((n) => !MAP_LAYERS[n].polygons && vectors.data?.[n]?.fc)
    .map((n) => ({ name: n, features: vectors.data[n].fc.features, ...MAP_LAYERS[n] })), [activeLayers, vectors.data])
  const buildingFeatures = activeLayers.includes('osm_buildings') ? vectors.data?.osm_buildings?.fc?.features || null : null

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === wrapper.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])
  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen?.()
    else wrapper.current?.requestFullscreen?.().catch(() => {})
  }

  const pick = (p) => onPick?.(utmToLonLat(p.easting, p.northing, 44))

  if (!hasWebgl) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted">
        WebGL is not available in this browser, so the 3D map cannot be drawn. Location search, simulation and history still work from the panel.
      </div>
    )
  }

  const layerStatus = (n) => {
    if (!layers.includes(n)) return null
    if (MAP_LAYERS[n].detail && !detailAllowed) return 'zoom in'
    const x = vectors.data?.[n]
    if (vectors.loading || !x) return '…'
    if (x.error) return 'error'
    return `${fmtInt(x.fc.features.length)}${x.fc.properties?.truncated ? '+' : ''}`
  }

  return (
    <div ref={wrapper} className="relative h-full w-full bg-[#0B1220]">
      {grid.loading && <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 text-sm text-muted"><Loader2 size={16} className="animate-spin" /> Loading the Chennai elevation grid…</div>}
      {grid.error && <div className="absolute inset-x-4 top-16 z-10"><ErrorState error={grid.error} onRetry={grid.reload} title="Terrain unavailable from the backend" /></div>}
      {grid.data && !win && <div className="absolute inset-x-4 top-16 z-10 rounded-md bg-paper p-3 text-sm text-muted">The selected location lies outside the FLOIN terrain grid.</div>}
      {crop && frame && (
        <ErrorBoundary title="3D rendering failed">
          <TerrainScene ref={scene} grid={crop} frame={frame} overlay={overlayCrop} area={area} pin={pin}
                        basemap={colourMode === 'map' ? basemap.data : null}
                        exaggeration={exaggeration} colourMode={colourMode === 'map' && !basemap.data ? 'relief' : colourMode}
                        contours={contours} interval={interval} showDepth={showDepth && !!runId}
                        extentFeatures={extentFeatures} lineLayers={lineLayers} buildingFeatures={buildingFeatures} onPick={pick} />
        </ErrorBoundary>
      )}

      {/* controls */}
      <div className="absolute right-3 top-3 z-20 flex flex-col gap-1.5">
        <IconButton label="Layers and display" active={panel} onClick={() => setPanel((v) => !v)}><Layers size={16} /></IconButton>
        <IconButton label="Reset camera" onClick={() => scene.current?.reset()}><RotateCcw size={16} /></IconButton>
        <IconButton label="Show all of Chennai" onClick={onHome}><Home size={16} /></IconButton>
        <IconButton label={fullscreen ? 'Exit full screen' : 'Full screen'} onClick={toggleFullscreen}>{fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</IconButton>
      </div>

      {panel && (
        <div className="scroll-thin absolute right-14 top-3 z-20 max-h-[calc(100%-1.5rem)] w-64 overflow-y-auto rounded-lg border border-line-strong bg-paper/97 p-3 text-xs shadow-xl" role="dialog" aria-label="Layers and display">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold text-ink">Map layers</span>
            <button type="button" onClick={() => setPanel(false)} aria-label="Close" className="text-muted hover:text-ink"><X size={14} /></button>
          </div>
          <Group title="Terrain surface">
            <div className="grid grid-cols-3 gap-1" role="radiogroup" aria-label="Terrain colouring">
              {[['map', 'Streets'], ['elevation', 'Elevation'], ['relief', 'Relief']].map(([k, label]) => (
                <button key={k} type="button" role="radio" aria-checked={colourMode === k} onClick={() => setColourMode(k)}
                        className={`rounded px-1.5 py-1 ${colourMode === k ? 'bg-mangrove text-ivory' : 'bg-paper-2 text-ink hover:bg-line'}`}>{label}</button>
              ))}
            </div>
            <Toggle checked={contours} onChange={setContours} label={`Contours (${interval} m)`} />
            <label className="block text-muted">
              <span className="flex items-center gap-1">Height exaggeration ×{exaggeration}
                <InfoTip text="Chennai is very flat, so heights are multiplied for visibility. Horizontal distances are true scale." /></span>
              <input type="range" min="1" max="40" value={exaggeration} onChange={(e) => setExaggeration(+e.target.value)} className="w-full accent-[#1A73E8]" />
            </label>
          </Group>
          <Group title={`Simulation output${run ? ` · ${run.scenario}` : ''}`}>
            {!runId && <p className="text-faint">{runRunning ? 'Shown when the running simulation completes.' : 'No completed simulation selected.'}</p>}
            <Toggle checked={showDepth} onChange={setShowDepth} disabled={!runId} label="Flood depth (90 m blocks)" />
            <Toggle checked={showExtent} onChange={setShowExtent} disabled={!runId || !detailAllowed}
                    label={`Flood extent polygons${runId && !detailAllowed ? ' (zoom in)' : ''}`}
                    status={wantExtent ? (extent.loading ? 'loading…' : extent.error ? 'error' : extentFeatures ? fmtInt(extentFeatures.length) : null) : null} />
          </Group>
          <Group title="Database layers">
            {Object.entries(MAP_LAYERS).map(([name, cfg]) => (
              <Toggle key={name} checked={layers.includes(name)} label={cfg.label} swatch={cfg.colour} status={layerStatus(name)}
                      onChange={(on) => setLayers((l) => (on ? [...l, name] : l.filter((x) => x !== name)))} />
            ))}
            {!detailAllowed && <p className="pt-1 text-faint">Roads, buildings and minor drains load after you zoom to a location (search, or the crosshair on a clicked point).</p>}
          </Group>
        </div>
      )}

      {/* status line */}
      <div className="pointer-events-none absolute left-3 top-3 z-20 flex max-w-[calc(100%-5rem)] flex-wrap gap-1.5">
        <Chip>{focusBbox ? (area?.label || 'Zoomed view') : 'Chennai model area'}{crop ? ` · ${fmt(cropKm2, { digits: 0 })} km²` : ''}</Chip>
        {runId && (showDepth || (showExtent && detailAllowed)) && (
          <span className="group pointer-events-auto relative inline-flex items-center gap-1 rounded-full border border-violet/40 bg-paper/90 py-1 pl-2.5 pr-1 text-[11px] text-violet-ink shadow">
            Flood output: {run.scenario}
            <button type="button" onClick={hideFloodOutput} title="Hide the flood output and show the plain map"
                    aria-label={`Hide flood output of ${run.scenario}`}
                    className="ml-0.5 rounded-full p-0.5 text-violet-ink/70 transition-colors hover:bg-violet/20 hover:text-ink focus-visible:bg-violet/20">
              <X size={12} />
            </button>
            <span role="tooltip" className="pointer-events-none absolute left-0 top-full mt-1 hidden whitespace-nowrap rounded bg-paper-2 px-2 py-1 text-[10px] text-ink shadow group-hover:block">
              Click × to hide · turn it back on under Layers
            </span>
          </span>
        )}
        {runRunning && <Chip tone="sim"><Loader2 size={11} className="animate-spin" /> Simulation running</Chip>}
        {colourMode === 'map' && basemap.loading && <Chip><Loader2 size={11} className="animate-spin" /> Loading street map</Chip>}
        {colourMode === 'map' && basemap.error && <Chip tone="warn">Street map unavailable: {basemap.error.message}</Chip>}
        {extent.loading && wantExtent && <Chip><Loader2 size={11} className="animate-spin" /> Loading flood polygons (≈15 MB, once)</Chip>}
      </div>

      {/* legend */}
      {frame && (legend ? (
        <div className="absolute bottom-3 left-3 z-10 w-56 max-w-[calc(100%-1.5rem)] space-y-1.5 rounded-lg border border-line-strong bg-paper/95 p-2.5 text-[11px] text-muted shadow-lg">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-ink">Legend</span>
            <button type="button" onClick={() => setLegend(false)} className="text-[10px] text-mangrove hover:underline">Hide</button>
          </div>
          {colourMode === 'elevation' && (
            <div>
              <div>Ground elevation (m)</div>
              <div className="h-1.5 rounded-sm" style={{ background: `linear-gradient(90deg, ${ELEVATION_STOPS.join(',')})` }} />
              <div className="flex justify-between font-mono text-[10px]"><span>{fmt(frame.lo)}</span><span>{fmt(frame.hi)}</span></div>
            </div>
          )}
          {colourMode === 'relief' && <Swatch colour={PLAIN_COLOUR} label="Terrain (shaded relief)" />}
          {colourMode === 'map' && <div>Terrain: Copernicus DEM, draped with the street map</div>}
          {showDepth && overlayCrop && (
            <div>
              <div>Simulated flood depth, deepest cell (m)</div>
              <div className="h-1.5 rounded-sm" style={{ background: `linear-gradient(90deg, ${DEPTH_STOPS.join(',')})` }} />
              <div className="flex justify-between font-mono text-[10px]"><span>0</span><span>{DEPTH_MAX_M}+</span></div>
            </div>
          )}
          {extentFeatures && <Swatch colour={EXTENT_COLOUR} label="Simulated flood extent" />}
          {lineLayers.map((l) => <Swatch key={l.name} colour={l.colour} label={l.label} line />)}
          {buildingFeatures && <Swatch colour={BUILDING_COLOUR} label="Building footprints (no heights)" />}
          {area?.geometry && <Swatch colour={AREA_COLOUR} label="Selected boundary" line />}
          <div className="border-t border-line pt-1 font-mono text-[10px] text-faint">{crop.cell_size_m} m blocks · heights ×{exaggeration}</div>
        </div>
      ) : (
        <button type="button" onClick={() => setLegend(true)} className="absolute bottom-3 left-3 z-10 rounded-md border border-line-strong bg-paper/95 px-2.5 py-1 text-xs font-medium text-ink shadow hover:bg-paper-2">Legend</button>
      ))}
      <div className="pointer-events-none absolute bottom-1 right-2 z-10 text-[10px] text-faint">
        {colourMode === 'map' && basemap.data ? `${BASEMAP_ATTRIBUTION} · ` : ''}DEM © Copernicus (ESA/Airbus)
      </div>
    </div>
  )
}

function Chip({ children, tone }) {
  const cls = tone === 'sim' ? 'border-violet/40 text-violet-ink' : tone === 'warn' ? 'border-lime/50 text-lime-ink' : 'border-line-strong text-ink'
  return <span className={`inline-flex items-center gap-1 rounded-full border bg-paper/90 px-2.5 py-1 text-[11px] shadow ${cls}`}>{children}</span>
}

function Group({ title, children }) {
  return (
    <div className="mb-3 space-y-1.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-faint">{title}</div>
      {children}
    </div>
  )
}

function Swatch({ colour, label, line }) {
  return (
    <div className="flex items-center gap-2">
      <span className={line ? 'h-0.5 w-4 shrink-0' : 'h-2.5 w-4 shrink-0 rounded-sm'} style={{ background: colour }} />
      <span className="truncate">{label}</span>
    </div>
  )
}

function IconButton({ label, onClick, children, active }) {
  return (
    <button type="button" onClick={onClick} title={label} aria-label={label} aria-pressed={active}
            className={`rounded-md border p-2 shadow-lg transition-colors ${active ? 'border-mangrove bg-mangrove text-ivory' : 'border-line-strong bg-paper/95 text-ink hover:bg-paper-2'}`}>
      {children}
    </button>
  )
}

function Toggle({ checked, onChange, label, disabled, swatch, status }) {
  return (
    <label className={`flex items-center gap-2 ${disabled ? 'text-faint' : 'text-ink'}`}>
      <input type="checkbox" checked={checked && !disabled} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="accent-[#1A73E8]" />
      {swatch && <span className="h-0.5 w-3.5 shrink-0" style={{ background: swatch }} />}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {status && <span className="shrink-0 font-mono text-[10px] text-faint">{status}</span>}
    </label>
  )
}
