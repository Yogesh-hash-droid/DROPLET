import { scoreBand, formatValue } from '../utils/format.js'

export default function ScoreGauge({ score, screeningStatus }) {
  const band = scoreBand(score)
  const hasScore = score != null
  const clamped = hasScore ? Math.max(0, Math.min(100, Number(score))) : 0
  // Semi-circular arc, 180 degrees, radius 80
  const radius = 80
  const circumference = Math.PI * radius
  const filled = (clamped / 100) * circumference

  return (
    <div className="score-gauge" data-testid="score-gauge">
      <svg viewBox="0 0 200 115" role="img" aria-label={`Water quality score ${hasScore ? clamped.toFixed(1) : 'unavailable'}`}>
        <path
          d={`M 20 100 A ${radius} ${radius} 0 0 1 180 100`}
          fill="none"
          stroke="#1e293b"
          strokeWidth="16"
          strokeLinecap="round"
        />
        <path
          d={`M 20 100 A ${radius} ${radius} 0 0 1 180 100`}
          fill="none"
          stroke={band.color}
          strokeWidth="16"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          className="score-gauge__progress"
        />
      </svg>
      <div className="score-gauge__center">
        <span className="score-gauge__value">{hasScore ? formatValue(clamped, 1) : '—'}</span>
        <span className="score-gauge__band" style={{ color: band.color }}>
          {screeningStatus || band.label}
        </span>
        <span className="score-gauge__caption">Water Quality Score (0-100)</span>
      </div>
    </div>
  )
}
