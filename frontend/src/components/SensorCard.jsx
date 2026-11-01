import { evaluateParameter, thresholdText } from '../utils/thresholds.js'
import { formatValue } from '../utils/format.js'
import SafetyBadge from './SafetyBadge.jsx'

export default function SensorCard({ param, value, config }) {
  const status = evaluateParameter(param.key, value, config)

  return (
    <article className={`sensor-card sensor-card--${status.toLowerCase()}`}>
      <div className="sensor-card__head">
        <span className="sensor-card__label">{param.label}</span>
        <SafetyBadge status={status === 'UNKNOWN' ? null : status} size="sm" />
      </div>
      <div className="sensor-card__value">
        <span className="sensor-card__number" style={{ color: param.color }}>
          {formatValue(value, param.decimals)}
        </span>
        {param.unit ? <span className="sensor-card__unit">{param.unit}</span> : null}
      </div>
      <div className="sensor-card__threshold">{thresholdText(param.key, config)}</div>
    </article>
  )
}
