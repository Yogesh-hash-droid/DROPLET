export function parseUtcDate(value) {
  if (!value) return null
  if (value instanceof Date) return value
  let str = String(value).trim()
  if (!str) return null
  // If no timezone indicator (Z or +HH:MM/-HH:MM), treat as UTC timestamp
  if (!str.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(str)) {
    str += 'Z'
  }
  const d = new Date(str)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatTimestamp(value) {
  const d = parseUtcDate(value)
  if (!d) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function timeAgo(value) {
  const d = parseUtcDate(value)
  if (!d) return 'never'
  const diff = Math.max(0, Date.now() - d.getTime())
  const s = Math.floor(diff / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}


export function formatValue(value, decimals = 2) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(decimals)
}

export function formatConfidence(confidence) {
  if (confidence == null) return '—'
  return `${(Number(confidence) * 100).toFixed(1)}%`
}

export function scoreBand(score) {
  const s = Number(score)
  if (score == null || Number.isNaN(s)) return { label: 'No score', color: '#64748b' }
  if (s >= 80) return { label: 'Excellent', color: '#22c55e' }
  if (s >= 60) return { label: 'Good', color: '#84cc16' }
  if (s >= 40) return { label: 'Moderate', color: '#f59e0b' }
  if (s >= 20) return { label: 'Poor', color: '#f97316' }
  return { label: 'Critical', color: '#ef4444' }
}

export function rangeStartIso(hours) {
  return new Date(Date.now() - hours * 3600 * 1000).toISOString()
}
