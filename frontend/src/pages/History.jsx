import { useMemo, useState } from 'react'
import { TIME_RANGES } from '../utils/constants.js'
import { usePolling } from '../hooks/usePolling.js'
import { fetchHistory } from '../services/api.js'
import { rangeStartIso, timeAgo } from '../utils/format.js'
import TrendChart from '../components/TrendChart.jsx'
import HistoryTable from '../components/HistoryTable.jsx'
import { ErrorBanner, LoadingNote } from '../components/StatusBanner.jsx'

export default function HistoryPage() {
  const [rangeId, setRangeId] = useState('24h')
  const [selectedKeys, setSelectedKeys] = useState(['tds', 'turbidity'])
  const range = TIME_RANGES.find((r) => r.id === rangeId) || TIME_RANGES[2]

  const fetcher = useMemo(
    () => () => fetchHistory({ limit: range.limit, startDate: rangeStartIso(range.hours) }),
    [range],
  )
  const { data, error, loading, updatedAt } = usePolling(fetcher, 10000)

  const toggleKey = (key) =>
    setSelectedKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>History &amp; Logs</h2>
          <p className="muted">
            {data ? `${data.length} readings in the last ${range.label}` : 'Loading…'}
            {updatedAt ? ` · refreshed ${timeAgo(updatedAt)}` : ''}
          </p>
        </div>
        <div className="range-picker" role="group" aria-label="Time range">
          {TIME_RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              className={`range-btn ${r.id === rangeId ? 'range-btn--active' : ''}`}
              onClick={() => setRangeId(r.id)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <ErrorBanner error={error} />
      <LoadingNote loading={loading} data={data} />

      {data && data.length > 0 && (
        <TrendChart
          readings={data}
          selectedKeys={selectedKeys}
          onToggleKey={toggleKey}
        />
      )}

      {data && <HistoryTable readings={data} />}
    </div>
  )
}
