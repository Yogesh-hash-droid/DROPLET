import { useState } from 'react'
import { usePolling } from './hooks/usePolling.js'
import { fetchConfig, fetchDevices, fetchHealth, fetchLatestReading } from './services/api.js'
import { timeAgo } from './utils/format.js'
import Header from './components/Header.jsx'
import Dashboard from './pages/Dashboard.jsx'
import HistoryPage from './pages/History.jsx'
import SettingsPage from './pages/Settings.jsx'

export default function App() {
  const [tab, setTab] = useState('dashboard')

  const health = usePolling(fetchHealth, 15000)
  const latest = usePolling(fetchLatestReading, 5000)
  const devices = usePolling(fetchDevices, 15000)
  const config = usePolling(fetchConfig, 60000)

  return (
    <div className="app">
      <Header
        mode={latest.data?.source}
        health={health.data}
        lastSeen={latest.data ? timeAgo(latest.data.timestamp) : health.error ? 'API unreachable' : 'loading…'}
        activeTab={tab}
        onTabChange={setTab}
      />

      <main className="app-main">
        {tab === 'dashboard' && (
          <Dashboard
            latest={latest.data}
            latestError={latest.error}
            config={config.data}
            devices={devices.data}
            devicesError={devices.error}
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
          {latest.data?.source === 'ESP32' || latest.data?.source === 'ESP8266'
            ? `Data source: physical ${latest.data.source} hardware`
            : 'Data source: SIMULATION (software-generated, not real hardware)'}
        </span>
      </footer>
    </div>
  )
}
