import { useCallback, useEffect, useRef, useState } from 'react'
import { isAbort } from '../services/api'

/**
 * Run an async API call when `deps` change. Obsolete requests are aborted, so a slow
 * earlier response can never overwrite a newer one.
 * `fn(signal)` must return a promise. Pass `enabled = false` to skip the call.
 */
export function useApi(fn, deps = [], { enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled })
  const [nonce, setNonce] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, error: null, loading: false })
      return undefined
    }
    const controller = new AbortController()
    setState((s) => ({ ...s, loading: true, error: null }))
    fnRef.current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, error: null, loading: false })
      })
      .catch((error) => {
        if (!controller.signal.aborted && !isAbort(error)) setState({ data: null, error, loading: false })
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { ...state, reload }
}

/** Call `fn` every `intervalMs` while `active` is true (first call immediately). */
export function usePolling(fn, intervalMs, active) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => {
    if (!active) return undefined
    const controller = new AbortController()
    let timer
    const tick = async () => {
      try {
        await fnRef.current(controller.signal)
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(tick, intervalMs)
      }
    }
    tick()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [intervalMs, active])
}
