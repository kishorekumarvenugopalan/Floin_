// One function per verified backend endpoint (see README "Integrated endpoints").
import { apiUrl, request } from './api'

// System and catalog
export const getHealth = (opts) => request('/health', { ...opts, timeoutMs: 15000 })
export const listDatasets = (params, opts) => request('/datasets', { params, ...opts })
export const getDataset = (name, opts) => request(`/datasets/${encodeURIComponent(name)}`, opts)

// Map data (read-only)
export const listLayers = (opts) => request('/layers', opts)
export const getLayerGeojson = (name, params, opts) =>
  request(`/layers/${encodeURIComponent(name)}/geojson`, { params, timeoutMs: 120000, ...opts })
export const listRasters = (opts) => request('/rasters', opts)
export const getRasterPreview = (name, maxSize = 1600, opts) =>
  request(`/rasters/${encodeURIComponent(name)}/preview`, { params: { max_size: maxSize }, timeoutMs: 60000, ...opts })
export const getTerrainGrid = (maxSize = 256, opts) =>
  request('/terrain/grid', { params: { max_size: maxSize }, timeoutMs: 60000, ...opts })
export const getChirpsRainfall = (opts) => request('/rainfall/chirps', { timeoutMs: 60000, ...opts })

// Simulations
export const listSimulations = (limit = 20, opts) => request('/simulations', { params: { limit }, ...opts })
export const createSimulation = (body, opts) => request('/simulations', { method: 'POST', body, ...opts })
export const getSimulation = (id, opts) => request(`/simulations/${encodeURIComponent(id)}`, opts)
export const getSimulationResults = (id, opts) => request(`/simulations/${encodeURIComponent(id)}/results`, opts)
export const getSimulationRisk = (id, opts) => request(`/simulations/${encodeURIComponent(id)}/risk`, opts)
export const getSimulationWards = (id, opts) =>
  request(`/simulations/${encodeURIComponent(id)}/wards`, { timeoutMs: 60000, ...opts })
export const getOutputPreview = (id, output, maxSize = 1600, opts) =>
  request(`/simulations/${encodeURIComponent(id)}/outputs/${output}/preview`, {
    params: { max_size: maxSize }, timeoutMs: 60000, ...opts,
  })
export const getTerrainOverlay = (id, maxSize = 256, opts) =>
  request(`/simulations/${encodeURIComponent(id)}/terrain-overlay`, { params: { max_size: maxSize }, timeoutMs: 60000, ...opts })

// Validation
export const listValidations = (limit = 20, opts) => request('/validation', { params: { limit }, ...opts })
export const getValidation = (id, opts) => request(`/validation/${encodeURIComponent(id)}`, opts)
export const runValidation2015 = (antecedentConditions, opts) =>
  request('/validation/2015', { method: 'POST', body: { antecedent_conditions: antecedentConditions }, ...opts })

// PNG overlays are loaded by <img>/Leaflet directly, so they need absolute URLs.
export const absoluteUrl = (path) => apiUrl(path)
