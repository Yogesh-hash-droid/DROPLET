import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import SensorCard from './SensorCard.jsx'
import { PARAM_BY_KEY } from '../utils/constants.js'

const CONFIG = {
  ph_min: 6.5,
  ph_max: 8.5,
  tds_max: 500,
  turbidity_max: 5,
  temperature_min: 10,
  temperature_max: 35,
}

describe('SensorCard', () => {
  it('renders a SAFE TDS reading with its threshold hint', () => {
    render(<SensorCard param={PARAM_BY_KEY.tds} value={250} config={CONFIG} />)
    expect(screen.getByText('TDS')).toBeInTheDocument()
    expect(screen.getByText('250.0')).toBeInTheDocument()
    expect(screen.getByText('max 500 ppm')).toBeInTheDocument()
    expect(screen.getByTestId('safety-badge')).toHaveTextContent('SAFE')
  })

  it('flags an unsafe TDS value', () => {
    render(<SensorCard param={PARAM_BY_KEY.tds} value={849} config={CONFIG} />)
    expect(screen.getByText('849.0')).toBeInTheDocument()
    expect(screen.getByText('ppm')).toBeInTheDocument()
    expect(screen.getByTestId('safety-badge')).toHaveTextContent('UNSAFE')
  })

  it('renders unknown status when config is missing', () => {
    render(<SensorCard param={PARAM_BY_KEY.turbidity} value={2.1} config={null} />)
    expect(screen.getByTestId('safety-badge')).toHaveTextContent('UNKNOWN')
  })
})
