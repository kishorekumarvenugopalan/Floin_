// Central HTTP client for the FLOIN FastAPI backend.
// Every request goes through `request`, which adds a timeout, supports cancellation
// and turns backend error bodies ({error, message}) into ApiError instances.

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
export const API_PREFIX = '/api/v1'

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'network_error', details = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

function describeValidationErrors(detail) {
  // FastAPI 422 bodies: {detail: [{loc: [...], msg: "..."}]}
  if (!Array.isArray(detail)) return null
  return detail.map((d) => `${(d.loc || []).filter((p) => p !== 'body').join('.') || 'request'}: ${d.msg}`).join('; ')
}

export function apiUrl(path) {
  return `${API_BASE_URL}${path.startsWith('/api/') ? '' : API_PREFIX}${path}`
}

export async function request(path, { method = 'GET', body, params, signal, timeoutMs = 30000 } = {}) {
  const url = new URL(apiUrl(path))
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  })

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new DOMException('timeout', 'TimeoutError')), timeoutMs)
  const onAbort = () => controller.abort(signal.reason)
  signal?.addEventListener('abort', onAbort)

  let response
  try {
    response = await fetch(url, {
      method,
      signal: controller.signal,
      headers: body ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    if (signal?.aborted) throw err // caller cancelled: let them ignore it
    if (err?.name === 'TimeoutError' || controller.signal.reason?.name === 'TimeoutError') {
      throw new ApiError(`The backend did not respond within ${Math.round(timeoutMs / 1000)} s (${path}).`, { code: 'timeout' })
    }
    throw new ApiError(`Cannot reach the FLOIN backend at ${API_BASE_URL}. Is the API running?`, { code: 'network_error' })
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }

  let payload = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      if (!response.ok) throw new ApiError(`HTTP ${response.status} from ${path}`, { status: response.status, code: 'http_error' })
      throw new ApiError(`Malformed JSON from ${path}`, { status: response.status, code: 'malformed_response' })
    }
  }
  if (!response.ok) {
    const message =
      payload?.message || describeValidationErrors(payload?.detail) || payload?.detail || `HTTP ${response.status} from ${path}`
    throw new ApiError(message, { status: response.status, code: payload?.error || 'http_error', details: payload })
  }
  return payload
}

export const isAbort = (err) => err?.name === 'AbortError' || err?.name === 'CanceledError'
