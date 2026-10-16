import { useMemo } from 'react'
import { useApi } from './useApi'
import { depthOverlay, terrainGrid } from '../services/cache'
import { getLayerGeojson } from '../services/floinApi'
import { areaKm2, bboxInside, featureTouchesArea, MODEL_BBOX, pointInGeometry } from '../utils/geo'
import { lonLatToUtm, utmToLonLat } from '../utils/utm'

/**
 * Cells of a backend block grid (terrain/grid or terrain-overlay) whose centres lie inside
 * the area. Grid rows run north to south in UTM 44N.
 */
export function cellsInArea(grid, area) {
  if (!grid || !area?.geometry) return []
  const [left, , , top] = grid.bounds_projected
  const cell = grid.cell_size_m
  const [w, s, e, n] = area.bbox
  // Bounding rows/cols from the area's UTM extent (corners projected).
  const corners = [[w, s], [w, n], [e, s], [e, n]].map(([lon, lat]) => lonLatToUtm(lon, lat, 44))
  const minE = Math.min(...corners.map((c) => c[0])), maxE = Math.max(...corners.map((c) => c[0]))
  const minN = Math.min(...corners.map((c) => c[1])), maxN = Math.max(...corners.map((c) => c[1]))
  const c0 = Math.max(0, Math.floor((minE - left) / cell)), c1 = Math.min(grid.width - 1, Math.ceil((maxE - left) / cell))
  const r0 = Math.max(0, Math.floor((top - maxN) / cell)), r1 = Math.min(grid.height - 1, Math.ceil((top - minN) / cell))
  const out = []
  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) {
      const [lon, lat] = utmToLonLat(left + (c + 0.5) * cell, top - (r + 0.5) * cell)
      if (pointInGeometry([lon, lat], area.geometry, area.bbox)) out.push([r, c])
    }
  }
  return out
}

function stats(values) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  return { min: sorted[0], max: sorted[sorted.length - 1], median: sorted[Math.floor(sorted.length / 2)], n: values.length }
}

/** Real, area-specific facts for the selected locality. Anything not computable is null. */
export function useAreaStats(area) {
  const enabled = !!area?.geometry
  const bboxParam = area?.bbox ? area.bbox.map((v) => v.toFixed(5)).join(',') : null
  const terrain = useApi((signal) => terrainGrid(signal), [], { enabled })
  const hydro = useApi(async (signal) => {
    const names = ['gcc_basin_rivers', 'gcc_buckingham_canal', 'gcc_basin_macro_drains', 'gcc_basin_micro_drains', 'gcc_storm_water_drains_2023']
    const results = await Promise.all(names.map((n) => getLayerGeojson(n, { bbox: bboxParam, limit: 20000 }, { signal })))
    return Object.fromEntries(names.map((n, i) => [n, results[i]]))
  }, [bboxParam], { enabled })
  const roads = useApi((signal) => getLayerGeojson('osm_roads', { bbox: bboxParam, limit: 20000 }, { signal }), [bboxParam], { enabled })
  const buildings = useApi((signal) => getLayerGeojson('osm_buildings', { bbox: bboxParam, limit: 20000 }, { signal }), [bboxParam], { enabled })

  const elevation = useMemo(() => {
    if (!terrain.data || !area?.geometry) return null
    const values = cellsInArea(terrain.data, area).map(([r, c]) => terrain.data.values[r][c]).filter((v) => v !== null)
    return { ...stats(values), cellSize: terrain.data.cell_size_m }
  }, [terrain.data, area])

  const count = (fc) => (fc ? { n: fc.features.filter((f) => featureTouchesArea(f.geometry, area.geometry, area.bbox)).length, truncated: fc.properties.truncated } : null)
  const hydroCounts = useMemo(() => hydro.data && Object.fromEntries(Object.entries(hydro.data).map(([k, fc]) => [k, count(fc)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hydro.data, area])
  const roadCount = useMemo(() => count(roads.data), [roads.data, area]) // eslint-disable-line react-hooks/exhaustive-deps
  const buildingCount = useMemo(() => count(buildings.data), [buildings.data, area]) // eslint-disable-line react-hooks/exhaustive-deps

  return {
    areaKm2: area?.geometry ? areaKm2(area.geometry) : null,
    insideModel: area?.bbox ? bboxInside(area.bbox, MODEL_BBOX) : null,
    elevation, elevationState: terrain,
    hydro: hydroCounts, hydroState: hydro,
    roads: roadCount, roadsState: roads,
    buildings: buildingCount, buildingsState: buildings,
  }
}

/**
 * Selected-area summary of a simulation run.
 *  - wards: exact per-ward figures stored by the backend (simulation_ward_summary)
 *  - blocks: estimate from the run's flood_depth raster, block statistics on the 90 m grid
 */
export function useAreaRunSummary(area, sid, wardsFc) {
  const overlay = useApi((signal) => depthOverlay(sid, signal), [sid], { enabled: !!sid && !!area?.geometry })
  const terrain = useApi((signal) => terrainGrid(signal), [], { enabled: !!sid && !!area?.geometry })

  const wardTotals = useMemo(() => {
    if (!wardsFc || !area?.wardIds?.length || area.kind === 'osm') return null
    const ids = new Set(area.wardIds)
    const rows = wardsFc.features.filter((f) => ids.has(f.id)).map((f) => f.properties)
    if (!rows.length) return null
    return {
      wards: rows.length,
      flooded_area_km2: rows.reduce((s, r) => s + r.flooded_area_km2, 0),
      buildings_affected: rows.reduce((s, r) => s + r.buildings_affected, 0),
      road_km: rows.reduce((s, r) => s + r.road_km, 0),
      area_km2: rows.reduce((s, r) => s + r.ward_area_km2, 0),
    }
  }, [wardsFc, area])

  const blocks = useMemo(() => {
    if (!overlay.data || !terrain.data || !area?.geometry) return null
    if (overlay.data.depth_mean.length !== terrain.data.height) return null
    const cells = cellsInArea(terrain.data, area)
    const cellArea = (overlay.data.cell_size_m ** 2) / 1e6
    let flooded = 0, max = 0, wetCells = 0
    for (const [r, c] of cells) {
      const share = overlay.data.flooded_share[r][c]
      const dmax = overlay.data.depth_max[r][c]
      if (share != null) flooded += share * cellArea
      if (dmax != null && dmax > max) max = dmax
      if (share != null && share >= 0.5) wetCells++
    }
    return { cells: cells.length, flooded_km2: flooded, max_depth_m: max, wet_blocks: wetCells, cell_size_m: overlay.data.cell_size_m }
  }, [overlay.data, terrain.data, area])

  return { wardTotals, blocks, loading: overlay.loading || terrain.loading, error: overlay.error || terrain.error }
}
