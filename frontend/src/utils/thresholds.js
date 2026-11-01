/**
 * Client-side mirror of the backend Safety Rule Engine bands
 * (backend/app/services/safety_service.py), used only to colour individual
 * sensor cards. The authoritative verdict is always the API's `safety_status`.
 *
 * TDS:           WARNING (max, max*1.5],                   UNSAFE > max*1.5
 * Turbidity:     WARNING (max, max*2],                     UNSAFE > max*2
 */
export function evaluateParameter(key, value, config) {
  if (value == null || !config) return 'UNKNOWN'

  switch (key) {
    case 'tds': {
      if (value > config.tds_max * 1.5) return 'UNSAFE'
      if (value > config.tds_max) return 'WARNING'
      return 'SAFE'
    }
    case 'turbidity': {
      if (value > config.turbidity_max * 2.0) return 'UNSAFE'
      if (value > config.turbidity_max) return 'WARNING'
      return 'SAFE'
    }
    default:
      return 'UNKNOWN'
  }
}

export function thresholdText(key, config) {
  if (!config) return ''
  switch (key) {
    case 'tds':
      return `max ${config.tds_max} ppm`
    case 'turbidity':
      return `max ${config.turbidity_max} NTU`
    case 'temperature':
      return `safe ${config.temperature_min}–${config.temperature_max} °C`
    default:
      return ''
  }
}
