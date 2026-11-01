export const PARAMS = [
  { key: 'tds', label: 'TDS', unit: 'ppm', decimals: 1, color: '#a78bfa' },
  { key: 'turbidity', label: 'Turbidity', unit: 'NTU', decimals: 2, color: '#f472b6' },
]

export const PARAM_BY_KEY = Object.fromEntries(PARAMS.map((p) => [p.key, p]))

export const TIME_RANGES = [
  { id: '1h', label: '1h', hours: 1, limit: 200 },
  { id: '6h', label: '6h', hours: 6, limit: 500 },
  { id: '24h', label: '24h', hours: 24, limit: 800 },
  { id: '7d', label: '7d', hours: 24 * 7, limit: 1000 },
]

export const SAFETY_COLORS = {
  SAFE: '#22c55e',
  WARNING: '#f59e0b',
  UNSAFE: '#ef4444',
}

export const ML_DISCLAIMER =
  'EXPERIMENTAL / ADVISORY ML prediction from a weak prototype model (test ROC-AUC 0.5522, POTABLE recall 0.0864). It is NOT a guarantee that water is safe to drink and it never overrides the Safety Rule Engine.'

export const POLL_INTERVAL_MS = 1000
export const HISTORY_POLL_INTERVAL_MS = 5000
