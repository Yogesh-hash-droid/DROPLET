import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 10000 })

export async function fetchLatestReading() {
  const { data } = await api.get('/readings/latest')
  return data
}

export async function fetchDevices() {
  const { data } = await api.get('/devices')
  return data
}

export async function fetchHistory({ limit = 100, startDate, endDate } = {}) {
  const params = { limit }
  if (startDate) params.start_date = startDate
  if (endDate) params.end_date = endDate
  const { data } = await api.get('/readings/history', { params })
  return data
}

export async function fetchConfig() {
  const { data } = await api.get('/config')
  return data
}

export async function saveConfig(config, adminKey) {
  // P2 admin authentication: the key travels ONLY in the X-Admin-Key request
  // header (never in the payload), is never logged, and is never persisted by
  // this module (no localStorage/sessionStorage/cookies).
  const headers = adminKey ? { 'X-Admin-Key': adminKey } : {}
  const { data } = await api.put('/config', config, { headers })
  return data
}

export async function fetchLatestPrediction() {
  const { data } = await api.get('/predictions/latest')
  return data
}

export async function fetchHealth() {
  const { data } = await axios.get('/health', { timeout: 5000 })
  return data
}

export function apiErrorMessage(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  if (error?.message) return error.message
  return 'Unknown API error'
}
