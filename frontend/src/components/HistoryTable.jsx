import { useState } from 'react'
import { PARAMS } from '../utils/constants.js'
import { formatValue, formatTimestamp } from '../utils/format.js'
import SafetyBadge from './SafetyBadge.jsx'

const STATUSES = ['ALL', 'SAFE', 'WARNING', 'UNSAFE']
const SOURCES = ['ALL', 'SIMULATION', 'ESP32', 'ESP8266']

export default function HistoryTable({ readings = [] }) {
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [sourceFilter, setSourceFilter] = useState('ALL')
  const [deviceQuery, setDeviceQuery] = useState('')
  const [onlyDisagreements, setOnlyDisagreements] = useState(false)

  const filtered = readings.filter((r) => {
    if (statusFilter !== 'ALL' && r.safety_status !== statusFilter) return false
    if (sourceFilter !== 'ALL' && r.source !== sourceFilter) return false
    if (deviceQuery && !String(r.device_id || '').toLowerCase().includes(deviceQuery.toLowerCase())) return false
    if (onlyDisagreements) {
      const disagree =
        r.prediction === 'POTABLE' && r.safety_status !== 'SAFE'
      if (!disagree) return false
    }
    return true
  })

  return (
    <section className="history-section">
      <div className="history-filters">
        <label className="filter-field">
          <span>Safety</span>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="filter-field">
          <span>Source</span>
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            {SOURCES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="filter-field">
          <span>Device</span>
          <input
            type="text"
            placeholder="search device id…"
            value={deviceQuery}
            onChange={(e) => setDeviceQuery(e.target.value)}
          />
        </label>
        <label className="filter-check">
          <input
            type="checkbox"
            checked={onlyDisagreements}
            onChange={(e) => setOnlyDisagreements(e.target.checked)}
          />
          Only safety/ML disagreements
        </label>
        <span className="filter-count">{filtered.length} of {readings.length} readings</span>
      </div>

      {filtered.length === 0 ? (
        <p className="empty-note">No readings match the current filters.</p>
      ) : (
        <div className="table-wrap">
          <table className="history-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Device</th>
                <th>Source</th>
                {PARAMS.map((p) => (
                  <th key={p.key}>{p.label}{p.unit ? ` (${p.unit})` : ''}</th>
                ))}
                <th>Score</th>
                <th>Screening</th>
                <th>Safety (rules)</th>
                <th>ML (advisory)</th>
                <th>Conf.</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id}>
                  <td className="cell-time">{formatTimestamp(r.timestamp)}</td>
                  <td>{r.device_id}</td>
                  <td>
                    <span className={`source-tag source-tag--${r.source.toLowerCase()}`}>{r.source}</span>
                  </td>
                  {PARAMS.map((p) => (
                    <td key={p.key}>{formatValue(r[p.key], p.decimals)}</td>
                  ))}
                  <td>{r.quality_score != null ? formatValue(r.quality_score, 1) : '—'}</td>
                  <td>{r.screening_status || 'UNAVAILABLE'}</td>
                  <td><SafetyBadge status={r.safety_status} size="sm" /></td>
                  <td>
                    {r.prediction ? (
                      <span className={`ml-tag ${r.prediction === 'POTABLE' ? 'ml-tag--potable' : 'ml-tag--not'}`}>
                        {r.prediction}
                      </span>
                    ) : (
                      <span className="muted">{r.ml_status === 'UNAVAILABLE' ? 'UNAVAILABLE' : '—'}</span>
                    )}
                  </td>
                  <td>{r.confidence != null ? `${(r.confidence * 100).toFixed(1)}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
