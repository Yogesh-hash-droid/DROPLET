import { describe, expect, it } from 'vitest'
import { evaluateParameter, thresholdText } from './thresholds.js'

const CONFIG = {
  ph_min: 6.5,
  ph_max: 8.5,
  tds_max: 500,
  turbidity_max: 5,
  temperature_min: 10,
  temperature_max: 35,
}

describe('evaluateParameter mirrors backend safety bands', () => {
  it('TDS bands', () => {
    expect(evaluateParameter('tds', 500, CONFIG)).toBe('SAFE')
    expect(evaluateParameter('tds', 600, CONFIG)).toBe('WARNING')
    expect(evaluateParameter('tds', 751, CONFIG)).toBe('UNSAFE')
  })

  it('turbidity bands', () => {
    expect(evaluateParameter('turbidity', 5, CONFIG)).toBe('SAFE')
    expect(evaluateParameter('turbidity', 7.5, CONFIG)).toBe('WARNING')
    expect(evaluateParameter('turbidity', 10.1, CONFIG)).toBe('UNSAFE')
  })

  it('handles missing value or config', () => {
    expect(evaluateParameter('tds', null, CONFIG)).toBe('UNKNOWN')
    expect(evaluateParameter('tds', 7, null)).toBe('UNKNOWN')
  })
})

describe('thresholdText', () => {
  it('summarises configured thresholds', () => {
    expect(thresholdText('tds', CONFIG)).toBe('max 500 ppm')
    expect(thresholdText('tds', null)).toBe('')
  })
})
