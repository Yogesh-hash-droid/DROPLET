import { usePolling } from '../hooks/usePolling.js'
import { fetchConfig, fetchHealth, fetchLatestPrediction } from '../services/api.js'
import { formatTimestamp, timeAgo, formatConfidence } from '../utils/format.js'
import ThresholdSettingsForm from '../components/ThresholdSettingsForm.jsx'
import { ErrorBanner } from '../components/StatusBanner.jsx'
import { ML_DISCLAIMER } from '../utils/constants.js'

export default function SettingsPage() {
  const config = usePolling(fetchConfig, 60000)
  const health = usePolling(fetchHealth, 30000)
  const prediction = usePolling(fetchLatestPrediction, 30000)

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Threshold Settings</h2>
          <p className="muted">
            Current configuration
            {config.data ? ` (updated ${formatTimestamp(config.data.updated_at)})` : ''}
          </p>
        </div>
      </div>

      <ErrorBanner error={config.error} />
      <ThresholdSettingsForm config={config.data} onSaved={(updated) => config.refresh()} />

      <section className="settings-panels">
        <div className="info-panel">
          <h3>System Status</h3>
          {health.data ? (
            <ul className="info-list">
              <li><span>Service</span><strong>{health.data.service}</strong></li>
              <li><span>Status</span><strong className={health.data.status === 'healthy' ? 'text-ok' : 'text-warn'}>
                {health.data.status}</strong></li>
              <li><span>Database</span><strong className={health.data.database === 'connected' ? 'text-ok' : 'text-warn'}>
                {health.data.database}</strong></li>
              <li><span>Environment</span><strong>{health.data.environment}</strong></li>
              <li><span>API version</span><strong>{health.data.version}</strong></li>
              <li><span>Server time</span><strong>{formatTimestamp(health.data.timestamp)}</strong></li>
            </ul>
          ) : (
            <p className="empty-note">{health.error ? `API unreachable: ${health.error}` : 'Loading…'}</p>
          )}
        </div>

        <div className="info-panel">
          <h3>Latest ML Verdict <span className="experimental-badge">EXPERIMENTAL</span></h3>
          {prediction.error ? (
            <p className="empty-note">{prediction.error}</p>
          ) : prediction.data ? (
            <ul className="info-list">
              <li><span>Prediction</span><strong>{prediction.data.prediction}</strong></li>
              <li><span>Confidence</span><strong>{formatConfidence(prediction.data.confidence)}</strong></li>
              <li><span>Rule-engine safety</span><strong>{prediction.data.safety_status}</strong></li>
              <li><span>Quality score</span><strong>{prediction.data.quality_score}</strong></li>
              <li><span>Input features</span><strong>
                pH {prediction.data.input_features?.ph}, TDS {prediction.data.input_features?.tds}, Turbidity {prediction.data.input_features?.turbidity}
              </strong></li>
              <li><span>Temperature used by model</span><strong>{String(prediction.data.temperature_used)}</strong></li>
              <li><span>Recorded</span><strong>{formatTimestamp(prediction.data.timestamp)}</strong></li>
              <li><span>Fetched</span><strong>{timeAgo(prediction.updatedAt)}</strong></li>
            </ul>
          ) : (
            <p className="empty-note">Loading…</p>
          )}
          <p className="form-hint">{ML_DISCLAIMER}</p>
        </div>
      </section>
    </div>
  )
}
