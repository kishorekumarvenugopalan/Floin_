import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { getLayerGeojson } from '../services/floinApi'
import { titleZone } from '../services/localitySearch'
import { bboxOf, pointInGeometry } from '../utils/geo'

// The location the user is working on:
//  - GCC zone / ward polygons from the FLOIN database, or
//  - an OpenStreetMap boundary returned by Nominatim, or
//  - for an OSM place that is only a point, the GCC ward containing it (labelled as a stand-in), or
//  - a point clicked on the map (kept as a point; never turned into an invented area).
const AreaContext = createContext(null)
const STORAGE_KEY = 'floin.selectedArea'

function readStored() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
  } catch {
    return null
  }
}

export function AreaProvider({ children }) {
  const wardsApi = useApi((signal) => getLayerGeojson('wards_gcc', { simplify_m: 8, limit: 1000 }, { signal }), [])
  const [selection, setSelectionState] = useState(readStored)

  const wardById = useMemo(() => new Map((wardsApi.data?.features || []).map((f) => [f.id, f])), [wardsApi.data])

  const area = useMemo(() => resolveArea(selection, wardById), [selection, wardById])

  const setSelection = useCallback((sel) => {
    setSelectionState(sel)
    try {
      if (sel) localStorage.setItem(STORAGE_KEY, JSON.stringify(sel))
      else localStorage.removeItem(STORAGE_KEY)
    } catch {
      /* storage unavailable: selection lasts for this page load */
    }
  }, [])

  /** Turn a search result into a selection; OSM points are matched to the GCC ward containing them. */
  const selectResult = useCallback((result) => {
    if (result.kind === 'osm' && !result.hasBoundary) {
      const ward = (wardsApi.data?.features || []).find((f) => pointInGeometry(result.point, f.geometry))
      setSelection({ ...result, kind: 'osm-point', wardIds: ward ? [ward.id] : [], containingWard: ward?.properties.code ?? null })
    } else {
      setSelection(result)
    }
  }, [wardsApi.data, setSelection])

  /** A point clicked on the 3D map. */
  const pickPoint = useCallback(([lon, lat]) => {
    const ward = (wardsApi.data?.features || []).find((f) => pointInGeometry([lon, lat], f.geometry))
    setSelection({
      kind: 'map-point', id: `pt:${lon.toFixed(5)},${lat.toFixed(5)}`, label: 'Selected point',
      sublabel: `${lat.toFixed(5)}° N, ${lon.toFixed(5)}° E`, point: [lon, lat],
      wardIds: ward ? [ward.id] : [], containingWard: ward?.properties.code ?? null,
    })
  }, [wardsApi.data, setSelection])

  const value = {
    wards: wardsApi.data, wardsError: wardsApi.error, wardsLoading: wardsApi.loading, wardById, selection, area,
    selectResult, pickPoint, restore: setSelection, clear: () => setSelection(null),
  }
  return <AreaContext.Provider value={value}>{children}</AreaContext.Provider>
}

function resolveArea(sel, wardById) {
  if (!sel) return null
  const base = { id: sel.id, kind: sel.kind, label: sel.label, sublabel: sel.sublabel, point: sel.point || null, wardIds: sel.wardIds || [] }
  if (sel.kind === 'map-point') {
    const ward = wardById.get(sel.wardIds?.[0])
    return { ...base, geometry: null, bbox: null, boundarySource: 'Point clicked on the map',
      containingWard: ward ? { code: ward.properties.code, zone: titleZone(ward.properties.zone) } : null }
  }
  if (sel.kind === 'osm') {
    return { ...base, geometry: sel.geometry, bbox: bboxOf(sel.geometry), boundarySource: 'OpenStreetMap boundary via Nominatim', osmType: sel.osmType }
  }
  const wards = (sel.wardIds || []).map((id) => wardById.get(id)).filter(Boolean)
  if (!wards.length) {
    if (sel.kind === 'osm-point') {
      return { ...base, geometry: null, bbox: null, boundarySource: 'none', osmType: sel.osmType,
        note: 'OpenStreetMap has only a point for this place and it lies outside the GCC wards, so no boundary is available.' }
    }
    return { ...base, geometry: null, bbox: null, boundarySource: 'loading' }
  }
  const geometry = { type: 'MultiPolygon', coordinates: wards.flatMap((w) => (w.geometry.type === 'Polygon' ? [w.geometry.coordinates] : w.geometry.coordinates)) }
  const zones = [...new Set(wards.map((w) => titleZone(w.properties.zone)))]
  return {
    ...base,
    geometry,
    bbox: bboxOf(geometry),
    zones,
    wardCodes: wards.map((w) => w.properties.code),
    boundarySource: sel.kind === 'osm-point'
      ? `GCC ward ${sel.containingWard} containing the OSM point (stand-in: OpenStreetMap has no boundary for this place)`
      : 'GCC ward boundaries (FLOIN database)',
    osmType: sel.osmType,
  }
}

export function useArea() {
  const ctx = useContext(AreaContext)
  if (!ctx) throw new Error('useArea must be used inside AreaProvider')
  return ctx
}
