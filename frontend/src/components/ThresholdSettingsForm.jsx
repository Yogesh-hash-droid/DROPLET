import { useEffect, useState } from 'react'
import { apiErrorMessage, saveConfig } from '../services/api.js'

const FIELDS = [
  { key: 'tds_max', label: 'TDS max (ppm)', step: '1' },
  { key: 'turbidity_max', label: 'Turbidity max (NTU)', step: '0.1' },
]

export default function ThresholdSettingsForm({ config, onSaved }) {
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)
  // P2 admin auth: held in React component memory ONLY - never written to
  // localStorage, sessionStorage, cookies, or any console statement.
  const [adminKey, setAdminKey] = useState('')

  useEffect(() => {
    if (config) {
      setForm({
        tds_max: config.tds_max,
        turbidity_max: config.turbidity_max,
      })
      setMessage(null)
    }
  }, [config])

  if (!form) return <p className="empty-note">Loading current thresholds…</p>

  const validate = () => {
    const n = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, Number(v)]))
    if (Object.values(n).some((v) => Number.isNaN(v))) return 'All fields must be numbers.'
    if (n.tds_max < 0 || n.turbidity_max < 0) return 'TDS and turbidity thresholds cannot be negative.'
    return null
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const error = validate()
    if (error) {
      setMessage({ type: 'error', text: error })
      return
    }
    setSaving(true)
    setMessage(null)
    try {
      const updated = await saveConfig(
        Object.fromEntries(Object.entries(form).map(([k, v]) => [k, Number(v)])),
        adminKey,
      )
      setMessage({ type: 'success', text: 'Thresholds saved. They take effect on the next reading evaluation.' })
      onSaved?.(updated)
    } catch (err) {
      // Clear, specific messages for the two auth outcomes. Neither message
      // (nor any other) ever contains the admin key.
      const status = err?.response?.status
      const text =
        status === 401
          ? 'Unauthorized: the admin key is missing or incorrect. The configuration was not changed.'
          : status === 503
            ? 'Admin authentication is not configured on the server (HTTP 503) - configuration updates are disabled. Nothing was saved.'
            : apiErrorMessage(err)
      setMessage({ type: 'error', text })
    } finally {
      setSaving(false)
    }
  }

  const dirty = config && FIELDS.some((f) => Number(form[f.key]) !== Number(config[f.key]))

  return (
    <form className="settings-form" onSubmit={handleSubmit}>
      <div className="settings-grid">
        {FIELDS.map((f) => (
          <label key={f.key} className="settings-field">
            <span>{f.label}</span>
            <input
              type="number"
              step={f.step}
              value={form[f.key]}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
            />
          </label>
        ))}
      </div>

      <label className="settings-field settings-field--admin-key">
        <span>Admin key</span>
        <input
          type="password"
          autoComplete="off"
          value={adminKey}
          onChange={(e) => setAdminKey(e.target.value)}
          placeholder="Required to save changes"
        />
      </label>
      <p className="form-hint">
        The admin key stays in memory for this page only - it is never stored in the browser and
        never appears in logs or messages.
      </p>

      {message && (
        <p className={`form-message form-message--${message.type}`} role="status">
          {message.text}
        </p>
      )}

      <div className="settings-actions">
        <button type="submit" className="btn btn--primary" disabled={saving}>
          {saving ? 'Saving…' : 'Save thresholds'}
        </button>
        <button
          type="button"
          className="btn"
          disabled={!dirty || saving}
          onClick={() => {
            setForm({
              tds_max: config.tds_max,
              turbidity_max: config.turbidity_max,
            })
            setMessage(null)
          }}
        >
          Reset
        </button>
      </div>

      <p className="form-hint">
        Values are validated by the API (boundary and cross-field checks). Changes apply to the next
        simulated reading — no backend restart required.
      </p>
    </form>
  )
}
