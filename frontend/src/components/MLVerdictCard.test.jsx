import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import MLVerdictCard from './MLVerdictCard.jsx'
import { ML_DISCLAIMER } from '../utils/constants.js'

describe('MLVerdictCard', () => {
  it('shows the advisory badge, prediction, confidence and disclaimer', () => {
    render(<MLVerdictCard prediction="POTABLE" confidence={0.5676} safetyStatus="SAFE" />)
    expect(screen.getByText('EXPERIMENTAL / ADVISORY')).toBeInTheDocument()
    expect(screen.getByText('POTABLE')).toBeInTheDocument()
    expect(screen.getByText('56.8%')).toBeInTheDocument()
    expect(screen.getByText(ML_DISCLAIMER)).toBeInTheDocument()
    expect(screen.queryByText(/authoritative verdict/i)).not.toBeInTheDocument()
  })

  it('highlights a safety/ML disagreement and states safety is authoritative', () => {
    render(<MLVerdictCard prediction="POTABLE" confidence={0.67} safetyStatus="UNSAFE" />)
    expect(screen.getByText(/safety verdict is authoritative/i)).toBeInTheDocument()
    expect(screen.getByTestId('safety-badge')).toHaveTextContent('UNSAFE')
    expect(screen.getByText('POTABLE', { selector: '.ml-card__prediction' })).toBeInTheDocument()
  })

  it('handles a missing ML verdict without claiming potability', () => {
    render(
      <MLVerdictCard
        prediction={null}
        confidence={null}
        safetyStatus="UNSAFE"
        mlStatus="UNAVAILABLE"
        mlStatusReason="PH_NOT_MEASURED"
      />,
    )
    expect(screen.getByTestId('ml-verdict')).toHaveTextContent('ML UNAVAILABLE')
    expect(screen.getByTestId('ml-verdict')).toHaveTextContent('pH is not measured')
    expect(screen.queryByText('POTABLE')).not.toBeInTheDocument()
    expect(screen.getByTestId('safety-badge')).toHaveTextContent('UNSAFE')
  })
})
