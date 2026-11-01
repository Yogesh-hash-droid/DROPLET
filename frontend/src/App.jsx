import { useEffect, useState } from 'react'
import { usePolling } from './hooks/usePolling.js'
import { useSSE } from './hooks/useSSE.js'
import { fetchConfig, fetchDevices, fetchHealth, fetchLatestReading } from './services/api.js'
import { timeAgo } from './utils/format.js'
import Header from './components/Header.jsx'
import Dashboard from './pages/Dashboard.jsx'
import HistoryPage from './pages/History.jsx'
import SettingsPage from './pages/Settings.jsx'

export default function App() {
  const [tab, setTab] = useState('dashboard')

  // SSE stream: real-time push of new readings (primary data source)
  const { data: sseData, connected: sseConnected, lastEvent: sseLastEvent } = useSSE()

  // HTTP polling: fallback and for endpoints with no SSE equivalent
  const polledLatest = usePolling(fetchLatestReading, 1000)  // 1s fallback poll for 1-second updates
  const health  = usePolling(fetchHealth, 15000)
  const devices = usePolling(fetchDevices, 5000)   // 5s to catch ONLINE→OFFLINE quickly
  const config  = usePolling(fetchConfig, 60000)

  // Merge SSE (instant) with polled latest (fallback).
  // SSE data wins when fresh (arrived within last 3s), else fall back to poll.
  const [latest, setLatest] = useState(null)
  const [latestError, setLatestError] = useState(null)
  const [latestUpdatedAt, setLatestUpdatedAt] = useState(null)

  useEffect(() => {
    if (sseData) {
      // SSE pushed a new reading — use it immediately
      setLatest(prev => ({ ...prev, ...sseData }))
      setLatestError(null)
      setLatestUpdatedAt(new Date().toISOString())
    }
  }, [sseData])

  useEffect(() => {
    // Polled data acts as baseline / first-load fill
    if (polledLatest.data && !sseData) {
      setLatest(polledLatest.data)
      setLatestError(polledLatest.error)
      setLatestUpdatedAt(polledLatest.updatedAt)
    } else if (polledLatest.error && !latest) {
      setLatestError(polledLatest.error)
    }
  }, [polledLatest.data, polledLatest.error, polledLatest.updatedAt])

  return (
    <div className="app">
      <Header
        mode={latest?.source}
        health={health.data}
        lastSeen={latest ? timeAgo(latest.timestamp) : health.error ? 'API unreachable' : 'loading…'}
        activeTab={tab}
        onTabChange={setTab}
        sseConnected={sseConnected}
      />

      <main className="app-main">
        {tab === 'dashboard' && (
          <Dashboard
            latest={latest}
            latestError={latestError}
            config={config.data}
            devices={devices.data}
            devicesError={devices.error}
            sseConnected={sseConnected}
            lastUpdatedAt={latestUpdatedAt}
          />
        )}
        {tab === 'history' && <HistoryPage />}
        {tab === 'settings' && <SettingsPage />}
      </main>

      <footer className="app-footer">
        <span>
          Educational prototype — not a substitute for certified laboratory water testing.
        </span>
        <span className="app-footer__mode">
          {latest?.source === 'ESP32' || latest?.source === 'ESP8266'
            ? `Data source: physical ${latest.source} hardware`
            : 'Data source: SIMULATION (software-generated, not real hardware)'}
          {' · '}
          <span className={`sse-indicator sse-indicator--${sseConnected}`}>
            {sseConnected === 'open' ? '● Live' : sseConnected === 'connecting' ? '○ Connecting…' : '○ Stream offline'}
          </span>
        </span>
      </footer>
    </div>
  )
}
