/**
 * Phase 8: end-to-end UI tests using REAL payloads captured from the live
 * FastAPI backend (fixtures under src/test/fixtures/). Only the network layer
 * is mocked — no fabricated readings, no fake safety/ML values.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Dashboard from './Dashboard.jsx'
import HistoryPage from './History.jsx'
import SettingsPage from './Settings.jsx'
import latestUnsafePotable from '../test/fixtures/latest_unsafe_potable.json'
import historyLive from '../test/fixtures/history_live.json'
import configLive from '../test/fixtures/config_live.json'
import healthLive from '../test/fixtures/health_live.json'

vi.mock('../services/api.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    fetchHistory: vi.fn(async () => historyLive),
    fetchLatestReading: vi.fn(async () => latestUnsafePotable),
    fetchConfig: vi.fn(async () => configLive),
    fetchHealth: vi.fn(async () => healthLive),
    fetchLatestPrediction: vi.fn(async () => {
      const err = new Error('Request failed with status code 404')
      err.response = { data: { detail: 'No ML prediction stored yet.' } }
      throw err
    }),
    saveConfig: vi.fn(async (cfg) => ({ ...configLive, ...cfg })),
  }
})

const api = await import('../services/api.js')

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Dashboard (real backend payload)', () => {
  it('renders sensor cards, safety verdict, score, ML verdict and charts', async () => {
    render(<Dashboard latest={latestUnsafePotable} latestError={null} config={configLive} />)

    // Sensor cards with the two measured values from the real payload.
    expect(await screen.findByText('200.0')).toBeInTheDocument()
    expect(await screen.findByText('1.00')).toBeInTheDocument()

    // Rule-engine verdict is UNSAFE and marked authoritative
    const badges = screen.getAllByTestId('safety-badge')
    expect(badges.some((b) => b.textContent === 'UNSAFE')).toBe(true)
    expect(screen.getByTestId('safety-panel')).toBeInTheDocument()

    // Water Quality Score gauge shows the real score
    expect(screen.getByTestId('score-gauge')).toHaveTextContent('90.0')

    // ML verdict (POTABLE) + confidence from the real prediction row
    const ml = screen.getByTestId('ml-verdict')
    expect(ml).toHaveTextContent('POTABLE')
    expect(ml).toHaveTextContent('57.5%')
    expect(ml).toHaveTextContent(/EXPERIMENTAL \/ ADVISORY/)
    expect(ml).toHaveTextContent(/NOT a guarantee that water is safe to drink/i)

    // Safety vs ML disagreement is visible and safety stays authoritative
    expect(screen.getByText(/safety verdict is authoritative/i)).toBeInTheDocument()

    // Source badge shows SIMULATION (software data, not hardware)
    expect(screen.getAllByText('SIMULATION').length).toBeGreaterThan(0)

    // Charts render from real history data (Recharts SVG output)
    expect(await screen.findByText(/Turbidity \(NTU\)/)).toBeInTheDocument()
    expect(await screen.findByText(/TDS \(ppm\)/)).toBeInTheDocument()
  })

  it('surfaces API errors instead of hiding them', async () => {
    render(<Dashboard latest={null} latestError="connection refused" config={null} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('API error: connection refused')
  })

  it('handles an ESP8266 two-sensor reading without interpreting null ML as unsafe', async () => {
    const reading = {
      ...latestUnsafePotable,
      source: 'ESP8266',
      ph: null,
      temperature: null,
      prediction: null,
      confidence: null,
      ml_status: 'UNAVAILABLE',
      ml_status_reason: 'PH_NOT_MEASURED',
      screening_status: 'GOOD',
    }

    render(
      <Dashboard
        latest={reading}
        latestError={null}
        config={configLive}
        devices={[{
          device_id: reading.device_id,
          status: 'ONLINE',
          last_seen: reading.timestamp,
        }]}
      />,
    )

    expect(await screen.findByText('ESP8266')).toBeInTheDocument()
    expect(screen.getAllByText('GOOD').length).toBeGreaterThan(0)
    expect(screen.getByText('ONLINE')).toBeInTheDocument()
    expect(screen.getByTestId('ml-verdict')).toHaveTextContent('ML UNAVAILABLE')
    expect(screen.getByTestId('ml-verdict')).toHaveTextContent('pH is not measured')
    expect(screen.queryByText('NOT POTABLE')).not.toBeInTheDocument()
    expect(screen.getByText('pH / temperature')).toBeInTheDocument()
  })

  it('shows a loading state while no data has arrived yet', () => {
    render(<Dashboard latest={null} latestError={null} config={null} />)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
    expect(screen.queryByTestId('safety-panel')).not.toBeInTheDocument()
  })
})

describe('History page (real backend payload)', () => {
  it('renders rows and filters by safety status', async () => {
    const user = userEvent.setup()
    render(<HistoryPage />)

    expect((await screen.findAllByText('P8-EDGE')).length).toBeGreaterThan(0)
    const allRows = screen.getAllByRole('row').length - 1 // minus header
    expect(allRows).toBe(historyLive.length)

    await user.selectOptions(screen.getByLabelText('Safety'), 'UNSAFE')
    await waitFor(() => {
      const rows = screen.getAllByRole('row').length - 1
      const expected = historyLive.filter((r) => r.safety_status === 'UNSAFE').length
      expect(rows).toBe(expected)
    })

    await user.selectOptions(screen.getByLabelText('Safety'), 'ALL')
    await user.type(screen.getByLabelText('Device'), 'PHASE6')
    await waitFor(() => {
      const rows = screen.getAllByRole('row').length - 1
      const expected = historyLive.filter((r) => r.device_id.includes('PHASE6')).length
      expect(rows).toBe(expected)
    })
  })

  it('shows only safety/ML disagreements when requested', async () => {
    const user = userEvent.setup()
    render(<HistoryPage />)
    expect((await screen.findAllByText('P8-EDGE')).length).toBeGreaterThan(0)

    await user.click(screen.getByLabelText(/Only safety\/ML disagreements/))
    await waitFor(() => {
      const rows = screen.getAllByRole('row').length - 1
      const expected = historyLive.filter(
        (r) => r.prediction === 'POTABLE' && r.safety_status !== 'SAFE',
      ).length
      expect(rows).toBe(expected)
      expect(expected).toBeGreaterThan(0)
    })
  })

  it('shows an empty state when filters match nothing', async () => {
    const user = userEvent.setup()
    render(<HistoryPage />)
    expect((await screen.findAllByText('P8-EDGE')).length).toBeGreaterThan(0)

    await user.type(screen.getByLabelText('Device'), 'zzz-no-such-device')
    expect(await screen.findByText('No readings match the current filters.')).toBeInTheDocument()
  })
})

describe('Settings page (real backend payload)', () => {
  it('loads thresholds, system health and the ML disclaimer', async () => {
    render(<SettingsPage />)

    expect(await screen.findByLabelText('TDS max (ppm)')).toHaveValue(500)
    expect(await screen.findByText('healthy')).toBeInTheDocument()
    expect(screen.getByText('connected')).toBeInTheDocument()
    expect(screen.getByText(/No ML prediction stored yet/)).toBeInTheDocument()
    expect(screen.getAllByText(/EXPERIMENTAL \/ ADVISORY ML prediction/).length).toBeGreaterThan(0)
  })

  it('saves thresholds through the API and reports success', async () => {
    const user = userEvent.setup()
    render(<SettingsPage />)

    const field = await screen.findByLabelText('TDS max (ppm)')
    await user.clear(field)
    await user.type(field, '600')
    // P2: the admin key is typed into the (memory-only) field and sent as the
    // X-Admin-Key header by saveConfig.
    await user.type(await screen.findByLabelText('Admin key'), 'test-admin-key')
    await user.click(screen.getByRole('button', { name: 'Save thresholds' }))

    expect(await screen.findByText(/Thresholds saved/)).toBeInTheDocument()
    expect(api.saveConfig).toHaveBeenCalledWith(
      expect.objectContaining({ tds_max: 600 }),
      'test-admin-key',
    )
  })

  it('shows a clear 401 message when the admin key is rejected', async () => {
    api.saveConfig.mockImplementationOnce(() => {
      const err = new Error('Request failed with status code 401')
      err.response = { status: 401, data: { detail: 'Invalid admin key.' } }
      return Promise.reject(err)
    })
    const user = userEvent.setup()
    render(<SettingsPage />)

    const field = await screen.findByLabelText('TDS max (ppm)')
    await user.clear(field)
    await user.type(field, '600')
    await user.type(await screen.findByLabelText('Admin key'), 'wrong-key')
    await user.click(screen.getByRole('button', { name: 'Save thresholds' }))

    expect(await screen.findByText(/admin key is missing or incorrect/i)).toBeInTheDocument()
    // the key never appears in the rendered message
    expect(screen.queryByText(/wrong-key/)).not.toBeInTheDocument()
  })

  it('shows a clear 503 message when admin auth is not configured server-side', async () => {
    api.saveConfig.mockImplementationOnce(() => {
      const err = new Error('Request failed with status code 503')
      err.response = {
        status: 503,
        data: { detail: 'Configuration updates are disabled: admin authentication is not configured on the server.' },
      }
      return Promise.reject(err)
    })
    const user = userEvent.setup()
    render(<SettingsPage />)

    const field = await screen.findByLabelText('TDS max (ppm)')
    await user.clear(field)
    await user.type(field, '600')
    await user.type(await screen.findByLabelText('Admin key'), 'any-key')
    await user.click(screen.getByRole('button', { name: 'Save thresholds' }))

    expect(await screen.findByText(/not configured on the server \(HTTP 503\)/i)).toBeInTheDocument()
    expect(screen.queryByText(/any-key/)).not.toBeInTheDocument()
  })

  it('rejects a negative TDS threshold client-side without calling the API', async () => {
    const user = userEvent.setup()
    render(<SettingsPage />)

    const max = await screen.findByLabelText('TDS max (ppm)')
    await user.clear(max)
    await user.type(max, '-1')
    await user.click(screen.getByRole('button', { name: 'Save thresholds' }))

    expect(await screen.findByText(/thresholds cannot be negative/i)).toBeInTheDocument()
    expect(api.saveConfig).not.toHaveBeenCalled()
  })
})
