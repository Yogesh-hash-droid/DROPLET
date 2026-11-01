import { evaluateParameter, thresholdText } from '../utils/thresholds.js'
import { formatValue } from '../utils/format.js'
import SafetyBadge from './SafetyBadge.jsx'

export default function SensorCard({ param, value, config, sensorStatus = 'ok' }) {
  const isFault = sensorStatus !== 'ok' && (param.key === 'tds' || param.key === 'turbidity')
  const status = isFault ? 'WARNING' : evaluateParameter(param.key, value, config)

  return (
    <article className={`sensor-card sensor-card--${status.toLowerCase()}`}>
      <div className="sensor-card__head">
        <span className="sensor-card__label">{param.label}</span>
        {isFault ? (
          <span className="safety-badge safety-badge--warning safety-badge--sm" data-testid="safety-badge">FAULT</span>
        ) : (
          <SafetyBadge status={status === 'UNKNOWN' ? null : status} size="sm" />
        )}
      </div>
      <div className="sensor-card__value">
        <span className="sensor-card__number" style={{ color: isFault ? 'var(--warn)' : param.color }}>
          {isFault ? 'FAULT' : formatValue(value, param.decimals)}
        </span>
        {param.unit && !isFault ? <span className="sensor-card__unit">{param.unit}</span> : null}
      </div>
      <div className="sensor-card__threshold">
        {isFault ? 'Hardware offline (check wiring)' : thresholdText(param.key, config)}
      </div>
    </article>
  )
}
