import { describe, expect, it } from 'vitest'
import { formatConfidence, formatValue, rangeStartIso, scoreBand, timeAgo } from './format.js'

describe('format helpers', () => {
  it('formats values and confidence', () => {
    expect(formatValue(7.123, 2)).toBe('7.12')
    expect(formatValue(null, 2)).toBe('—')
    expect(formatValue('abc')).toBe('—')
    expect(formatConfidence(0.5676)).toBe('56.8%')
    expect(formatConfidence(null)).toBe('—')
  })

  it('classifies score bands', () => {
    expect(scoreBand(97).label).toBe('Excellent')
    expect(scoreBand(65).label).toBe('Good')
    expect(scoreBand(45).label).toBe('Moderate')
    expect(scoreBand(25).label).toBe('Poor')
    expect(scoreBand(5).label).toBe('Critical')
    expect(scoreBand(null).label).toBe('No score')
  })

  it('describes elapsed time', () => {
    expect(timeAgo(new Date(Date.now() - 7000).toISOString())).toBe('7s ago')
    expect(timeAgo(new Date(Date.now() - 90 * 1000).toISOString())).toBe('1m ago')
    expect(timeAgo(new Date(Date.now() - 3 * 3600 * 1000).toISOString())).toBe('3h ago')
    expect(timeAgo(null)).toBe('never')
  })

  it('computes range start timestamps in the past', () => {
    const start = new Date(rangeStartIso(24))
    const diffH = (Date.now() - start.getTime()) / 3600000
    expect(diffH).toBeGreaterThan(23.9)
    expect(diffH).toBeLessThanOrEqual(24.1)
  })
})
