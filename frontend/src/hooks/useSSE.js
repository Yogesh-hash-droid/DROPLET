/**
 * useSSE — Server-Sent Events hook for real-time readings.
 *
 * Connects to GET /api/stream (SSE endpoint on the Render backend).
 * Falls back gracefully if EventSource is not supported or the stream errors.
 *
 * Connection lifecycle:
 *   - Opens EventSource on mount
 *   - Updates `data` on every message
 *   - Exposes `connected` state ('connecting' | 'open' | 'closed' | 'error')
 *   - Auto-reconnects via EventSource built-in backoff (browser-native, no code needed)
 *   - Cleans up on unmount
 *
 * Usage:
 *   const { data, connected } = useSSE()
 *   // `data` is the latest reading object parsed from JSON, or null
 *   // `connected` is 'open' when the stream is live
 */
import { useEffect, useRef, useState } from 'react'

const SSE_URL = (() => {
  const base = import.meta.env.VITE_API_BASE_URL || ''
  // e.g. https://droplet-api-byl8.onrender.com/api -> /api/stream
  // or empty (Vercel rewrite) -> /api/stream
  return base.replace(/\/api\/?$/, '') + '/api/stream'
})()

export function useSSE() {
  const [data, setData] = useState(null)
  const [connected, setConnected] = useState('connecting')
  const [lastEvent, setLastEvent] = useState(null)
  const esRef = useRef(null)

  useEffect(() => {
    if (typeof EventSource === 'undefined') {
      setConnected('error')
      return
    }

    let es
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      es = new EventSource(SSE_URL)
      esRef.current = es

      es.onopen = () => {
        if (!cancelled) setConnected('open')
      }

      es.onmessage = (event) => {
        if (cancelled) return
        try {
          const parsed = JSON.parse(event.data)
          setData(parsed)
          setLastEvent(new Date().toISOString())
          setConnected('open')
        } catch {
          // Heartbeat comment lines `: heartbeat` are not onmessage events,
          // but malformed data should be silently ignored.
        }
      }

      es.onerror = () => {
        if (cancelled) return
        setConnected('error')
        // EventSource will auto-reconnect after a browser-managed backoff.
        // We just reflect the state; no manual retry needed.
      }
    }

    connect()

    return () => {
      cancelled = true
      if (es) {
        es.close()
        setConnected('closed')
      }
    }
  }, []) // SSE_URL is module-level constant

  return { data, connected, lastEvent }
}
