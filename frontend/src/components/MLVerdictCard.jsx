import { ShieldAlert, ShieldCheck, TriangleAlert } from 'lucide-react'
import { ML_DISCLAIMER } from '../utils/constants.js'
import { formatConfidence } from '../utils/format.js'
import SafetyBadge from './SafetyBadge.jsx'

const ICONS = { SAFE: ShieldCheck, WARNING: TriangleAlert, UNSAFE: ShieldAlert }

export default function MLVerdictCard({ prediction, confidence, safetyStatus, mlStatus, mlStatusReason }) {
  const disagrees =
    prediction != null &&
    safetyStatus != null &&
    ((prediction === 'POTABLE' && safetyStatus !== 'SAFE') ||
      (prediction === 'NOT POTABLE' && safetyStatus === 'SAFE'))

  return (
    <section className="ml-card" data-testid="ml-verdict">
      <header className="ml-card__head">
        <h3>ML Potability Prediction</h3>
        <span className="experimental-badge" title="Weak prototype model — advisory only">
          EXPERIMENTAL / ADVISORY
        </span>
      </header>

      {prediction == null ? (
        <p className="ml-card__empty">
          ML <strong>UNAVAILABLE</strong>
          {mlStatusReason === 'PH_NOT_MEASURED' ? ' — pH is not measured in this hardware mode.' : ' for this reading.'}
          {' '}Safety verdict above still applies.
        </p>
      ) : (
        <>
          <div className="ml-card__verdict">
            <span className={`ml-card__prediction ${prediction === 'POTABLE' ? 'ml-card__prediction--yes' : 'ml-card__prediction--no'}`}>
              {prediction}
            </span>
            <span className="ml-card__confidence">
              confidence <strong>{formatConfidence(confidence)}</strong>
            </span>
          </div>

          <div className="confidence-bar" aria-hidden="true">
            <div className="confidence-bar__fill" style={{ width: `${Math.round((confidence ?? 0) * 100)}%` }} />
          </div>
        </>
      )}

      {safetyStatus && (
        <div className={`ml-card__disagreement ${disagrees ? '' : 'ml-card__disagreement--agree'}`}>
          <SafetyBadge status={safetyStatus} size="sm" />
          <span>
            {disagrees ? (
              <>
                Rule engine says <strong>{safetyStatus}</strong> while ML says <strong>{prediction}</strong>.
                The safety verdict is authoritative.
              </>
            ) : (
              <>Rule engine verdict: <strong>{safetyStatus}</strong>. It stays authoritative; the ML verdict never changes it.</>
            )}
          </span>
        </div>
      )}

      <p className="ml-card__disclaimer">{ML_DISCLAIMER}</p>
    </section>
  )
}
