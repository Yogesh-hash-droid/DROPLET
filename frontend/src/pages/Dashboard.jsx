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

export default function Dashboard({
  latest,
  latestError,
  config,
  devices = [],
  devicesError,
  sseConnected,
  lastUpdatedAt,
}) {
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
  const latestAgeMs = latest?.timestamp
    ? Math.max(0, Date.now() - (parseUtcDate(latest.timestamp)?.getTime() || 0))
    : Infinity

  // ONLINE if server reports ONLINE (from 5s heartbeat window), OR if we received a reading within 5 seconds
  const isOnline = device?.status === 'ONLINE' || latestAgeMs <= 5000
  const effectiveLastSeen = latest?.timestamp || device?.last_seen

  // "No data" state: reading older than 10 seconds
  const isStale = latestAgeMs > 10000 && latest !== null

  // Sensor hardware subsystem status
  const sensorStatus = latest?.sensor_status || (latest?.tds != null && latest?.turbidity != null ? 'ok' : 'sensor_fault')
  const sensorStatusLabel =
    sensorStatus === 'ok'
      ? 'OK (Active)'
      : sensorStatus === 'ads1115_not_found'
      ? 'ADC Offline'
      : sensorStatus === 'read_error'
      ? 'Read Error'
      : sensorStatus === 'serial_fault'
      ? 'Serial Timeout'
      : sensorStatus

  const sensorStatusClass = sensorStatus === 'ok' ? 'text-ok' : 'text-bad'

  // Hardware Connection / Serial Interface
  const isUno = latest?.source === 'ARDUINO_UNO' || latest?.source == null
  const wifiRssi = latest?.wifi_rssi
  const wifiStrengthLabel =
    wifiRssi == null
      ? 'USB Serial @ 9600'
      : wifiRssi >= -65
      ? `${wifiRssi} dBm (Strong)`
      : wifiRssi >= -75
      ? `${wifiRssi} dBm (Good)`
      : wifiRssi >= -85
      ? `${wifiRssi} dBm (Fair)`
      : `${wifiRssi} dBm (Weak)`

  return (
    <div className="page">
      <ErrorBanner error={latestError} />
      {history.error && (
        <ErrorBanner error={`history: ${history.error}`} />
      )}
      {devicesError && <ErrorBanner error={`devices: ${devicesError}`} />}
      <LoadingNote loading={!latest && !latestError} data={latest} />

      {/* Connection status banner */}
      <div className="connection-status-bar">
        <span className={`sse-dot sse-dot--${sseConnected}`} />
        <span className="muted">
          {sseConnected === 'open'
            ? 'Live stream connected'
            : sseConnected === 'connecting'
            ? 'Connecting to live stream…'
            : 'Live stream offline — using polling fallback'}
        </span>
        {lastUpdatedAt && (
          <span className="muted" style={{ marginLeft: 'auto' }}>
            Last update: {timeAgo(lastUpdatedAt)}
          </span>
        )}
      </div>

      {/* Sensor fault banner — Arduino Uno focused */}
      {sensorStatus !== 'ok' && (
        <div className="fault-banner">
          <div className="fault-banner__icon">⚠️</div>
          <div className="fault-banner__body">
            <strong>Device online, but sensor data is unavailable.</strong>
            <p>
              {sensorStatus === 'serial_fault'
                ? 'Arduino Uno serial stream timeout. Verify USB cable, COM port, and that the gateway script is running.'
                : sensorStatus === 'ads1115_not_found'
                ? 'Analog sensor input not detected on A0/A1. Check sensor wiring and 5V power rail.'
                : 'Sensor read error. Check wiring on A0/A1 and sensor 5V power supply.'}
            </p>
          </div>
        </div>
      )}

      {isStale && (
        <div className="stale-banner">
          ⚠️ No new data for {Math.round(latestAgeMs / 1000)}s — device may be offline.
        </div>
      )}

      {latest && (
        <>
          <section className="dashboard-top">
            <div className="dashboard-top__meta">
              <h2>Latest Reading</h2>
              <p className="muted">
                {latest.device_id} · <span className={`source-tag source-tag--${latest.source?.toLowerCase()}`}>{latest.source === 'ARDUINO_UNO' ? 'ARDUINO UNO' : latest.source}</span>{' '}
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
              <span className="muted">Sensor module</span>
              <strong className={sensorStatusClass}>
                {sensorStatusLabel}
              </strong>
              <span className="muted">
                {latest?.source === 'ARDUINO_UNO' || !latest?.source
                  ? 'Arduino Uno 10-bit ADC (A0/A1)'
                  : `${latest.source} ADC Module`}
              </span>
            </div>

            <div className="info-panel dashboard-status-card">
              <span className="muted">
                {isUno && wifiRssi == null ? 'Data interface' : 'Wi-Fi signal'}
              </span>
              <strong>
                {isUno && wifiRssi == null ? 'USB Serial @ 9600' : wifiStrengthLabel}
              </strong>
              <span className="muted">
                {isUno && wifiRssi == null
                  ? 'Arduino Uno USB Gateway'
                  : latest.uptime != null
                  ? `${latest.uptime}s uptime`
                  : 'Serial / Cloud Gateway'}
              </span>
            </div>

            <div className="info-panel dashboard-status-card">
              <span className="muted">Screening status</span>
              <strong className={latest.screening_status === 'GOOD' ? 'text-ok' : latest.screening_status ? 'text-warn' : ''}>
                {latest.screening_status || 'UNAVAILABLE'}
              </strong>
              <span className="muted">TDS + turbidity preliminary screening</span>
            </div>

            {(latest.ph == null || latest.temperature == null) && (
              <div className="info-panel dashboard-status-card">
                <span className="muted">Unmeasured sensors</span>
                <strong>pH / temperature</strong>
                <span className="muted">
                  Not measured — Arduino Uno two-sensor setup
                </span>
              </div>
            )}
          </section>

          <section className="sensor-grid">
            {PARAMS.map((p) => (
              <SensorCard
                key={p.key}
                param={p}
                value={latest[p.key]}
                config={config}
                sensorStatus={sensorStatus}
              />
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
