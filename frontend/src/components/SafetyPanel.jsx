import { AlertTriangle, ShieldAlert, ShieldCheck, TriangleAlert } from 'lucide-react'
import SafetyBadge from './SafetyBadge.jsx'

const ICONS = { SAFE: ShieldCheck, WARNING: TriangleAlert, UNSAFE: ShieldAlert }

export default function SafetyPanel({ status, warningMessage, violatedParameters = [] }) {
  const Icon = ICONS[status] || AlertTriangle

  return (
    <section className={`safety-panel safety-panel--${(status || 'unknown').toLowerCase()}`} data-testid="safety-panel">
      <div className="safety-panel__head">
        <Icon size={30} />
        <div>
          <span className="safety-panel__label">Safety Rule Engine</span>
          <div className="safety-panel__status">
            <SafetyBadge status={status} />
            <span className="safety-panel__authoritative">authoritative verdict</span>
          </div>
        </div>
      </div>

      {warningMessage ? (
        <p className="safety-panel__message">{warningMessage}</p>
      ) : (
        <p className="safety-panel__message safety-panel__message--ok">All parameters within configured thresholds.</p>
      )}

      {violatedParameters.length > 0 && (
        <div className="safety-panel__violations">
          Violated:{' '}
          {violatedParameters.map((p) => (
            <span key={p} className="violation-chip">{p}</span>
          ))}
        </div>
      )}
    </section>
  )
}
