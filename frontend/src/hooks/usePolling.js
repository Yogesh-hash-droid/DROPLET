import { useCallback, useEffect, useRef, useState } from 'react'
import { apiErrorMessage } from '../services/api.js'

/**
 * Generic polling hook: fetches `fetcher` immediately, then every
 * `intervalMs` ms. Errors are surfaced (never swallowed) and keep the
 * previous data visible.
 */
export function usePolling(fetcher, intervalMs = 5000, { enabled = true } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refresh = useCallback(async () => {
    try {
      const result = await fetcherRef.current()
      setData(result)
      setError(null)
      setUpdatedAt(new Date().toISOString())
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return undefined
    let cancelled = false
    const tick = () => {
      if (!cancelled) refresh()
    }
    tick()
    const id = setInterval(tick, intervalMs)
    const onVisible = () => {
      if (document.visibilityState === 'visible') tick()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [enabled, intervalMs, refresh])

  return { data, error, loading, updatedAt, refresh }
}
