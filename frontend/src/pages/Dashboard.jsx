import { useState } from 'react'
import { PARAMS } from '../utils/constants.js'
import { usePolling } from '../hooks/usePolling.js'
import { fetchHistory } from '../services/api.js'
import { formatTimestamp, timeAgo, parseUtcDate } from '../utils/format.js'

import SensorCard from '../components/SensorCard.jsx'
import ScoreGauge from '../components/ScoreGauge.jsx'
import SafetyPanel from '../components/SafetyPanel.jsx'
import MLVerdictCard from '../components/MLVerdictCard.jsx'
import TrendChart from '../components/TrendChart.jsx'
import { ErrorBanner, LoadingNote } from '../components/StatusBanner.jsx'

export default function Dashboard({ latest, latestError, config, devices = [], devicesError }) {
  const [selectedKeys, setSelectedKeys] = useState(['tds', 'turbidity'])
  const history = usePolling(() => fetchHistory({ limit: 200 }), 10000)
  const deviceList = devices ?? []

  const toggleKey = (key) =>
    setSelectedKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))

  const violatedParameters = latest?.parameter_rule_check
    ? Object.entries(latest.parameter_rule_check.parameters || {})
      .filter(([, parameter]) => parameter.status !== 'PASS')
      .map(([key]) => key === 'tds' ? 'TDS' : 'Turbidity')
    : []
  const device = latest ? deviceList.find((item) => item.device_id === latest.device_id) : null
  const latestAgeMs = latest?.timestamp ? Math.max(0, Date.now() - (parseUtcDate(latest.timestamp)?.getTime() || 0)) : Infinity
  const isOnline = device?.status === 'ONLINE' || latestAgeMs <= 35000
  const effectiveLastSeen = latest?.timestamp || device?.last_seen

  return (
    <div className="page">
      <ErrorBanner error={latestError} />
      {history.error && (
        <ErrorBanner error={`history: ${history.error}`} />
      )}
      {devicesError && <ErrorBanner error={`devices: ${devicesError}`} />}
      <LoadingNote loading={!latest && !latestError} data={latest} />

      {latest && (
        <>
          <section className="dashboard-top">
            <div className="dashboard-top__meta">
              <h2>Latest Reading</h2>
              <p className="muted">
                {latest.device_id} · <span className={`source-tag source-tag--${latest.source.toLowerCase()}`}>{latest.source}</span>{' '}
                · {formatTimestamp(latest.timestamp)} ({timeAgo(latest.timestamp)})
              </p>
            </div>
          </section>

          <section className="dashboard-status-row">
            <div className="info-panel dashboard-status-card">
              <span className="muted">Device connection</span>
              <strong className={isOnline ? 'text-ok' : 'text-warn'}>
                {isOnline ? 'ONLINE' : 'OFFLINE'}
              </strong>
              <span className="muted">
                {effectiveLastSeen ? `last seen ${timeAgo(effectiveLastSeen)}` : 'No device heartbeat available'}
              </span>
            </div>

            <div className="info-panel dashboard-status-card">
              <span className="muted">Screening status</span>
              <strong>{latest.screening_status || 'UNAVAILABLE'}</strong>
              <span className="muted">TDS + turbidity preliminary screening</span>
            </div>
            {(latest.ph == null || latest.temperature == null) && (
              <div className="info-panel dashboard-status-card">
                <span className="muted">Unmeasured sensors</span>
                <strong>pH / temperature</strong>
                <span className="muted">Not measured in ESP8266 two-sensor mode</span>
              </div>
            )}
          </section>

          <section className="sensor-grid">
            {PARAMS.map((p) => (
              <SensorCard key={p.key} param={p} value={latest[p.key]} config={config} />
            ))}
          </section>

          <section className="verdict-grid">
            <SafetyPanel
              status={latest.safety_status}
              warningMessage={latest.warning_message}
              violatedParameters={violatedParameters}
            />
            <ScoreGauge score={latest.quality_score} screeningStatus={latest.screening_status} />
            <MLVerdictCard
              prediction={latest.prediction}
              confidence={latest.confidence}
              safetyStatus={latest.safety_status}
              mlStatus={latest.ml_status}
              mlStatusReason={latest.ml_status_reason}
            />
          </section>

          <TrendChart
            readings={history.data || []}
            selectedKeys={selectedKeys}
            onToggleKey={toggleKey}
          />
        </>
      )}
    </div>
  )
}
