import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { PARAMS } from '../utils/constants.js'
import { formatTimestamp } from '../utils/format.js'

function MiniChart({ param, readings, height = 190 }) {
  const points = [...readings]
    .reverse()
    .map((r) => ({
      time: r.timestamp,
      value: r[param.key],
    }))
    .filter((p) => p.value != null)

  return (
    <div className="chart-panel">
      <div className="chart-panel__title" style={{ color: param.color }}>
        {param.label} {param.unit ? `(${param.unit})` : ''}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={points} margin={{ top: 6, right: 12, bottom: 4, left: -18 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
          <XAxis
            dataKey="time"
            tickFormatter={(t) => formatTimestamp(t).split(', ')[1] || formatTimestamp(t)}
            stroke="#64748b"
            fontSize={11}
            minTickGap={48}
          />
          <YAxis stroke="#64748b" fontSize={11} width={54} domain={['auto', 'auto']} />
          <Tooltip
            labelFormatter={(t) => formatTimestamp(t)}
            formatter={(value) => [value, param.label]}
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={param.color}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function TrendChart({ readings = [], selectedKeys, onToggleKey }) {
  const visible = PARAMS.filter((p) => selectedKeys.includes(p.key))

  return (
    <section className="trend-section">
      <div className="trend-section__head">
        <h3>Telemetry Trends</h3>
        <div className="trend-toggles">
          {PARAMS.map((p) => (
            <button
              key={p.key}
              type="button"
              className={`trend-toggle ${selectedKeys.includes(p.key) ? 'trend-toggle--on' : ''}`}
              style={selectedKeys.includes(p.key) ? { borderColor: p.color, color: p.color } : undefined}
              onClick={() => onToggleKey(p.key)}
              aria-pressed={selectedKeys.includes(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {readings.length === 0 ? (
        <p className="empty-note">No readings in the selected time range. Start the simulator to generate data.</p>
      ) : (
        <div className={`trend-grid trend-grid--${visible.length}`}>
          {visible.map((p) => (
            <MiniChart key={p.key} param={p} readings={readings} />
          ))}
        </div>
      )}
    </section>
  )
}
