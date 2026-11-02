import { Activity, Droplets, FlaskConical, Microchip, MonitorSmartphone, Settings2 } from 'lucide-react'

const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: Droplets },
  { id: 'history', label: 'History', icon: Activity },
  { id: 'settings', label: 'Settings', icon: Settings2 },
]

export default function Header({ mode, health, lastSeen, activeTab, onTabChange }) {
  const healthy = health?.status === 'healthy'
  const modeIsHardware = mode === 'ARDUINO_UNO' || mode === 'ESP32' || mode === 'ESP8266'

  return (
    <header className="app-header">
      <div className="app-header__brand">
        <span className="app-header__logo" aria-hidden="true">
          <Droplets size={26} strokeWidth={2.2} />
        </span>
        <div>
          <h1>Smart Water Quality Monitoring</h1>
          <p className="app-header__subtitle">Rule-based safety + experimental ML potability prediction</p>
        </div>
      </div>

      <div className="app-header__badges">
        <span
          className={`mode-badge ${modeIsHardware ? 'mode-badge--hardware' : 'mode-badge--simulation'}`}
          title={
            modeIsHardware
              ? `Data from the physical ${mode === 'ARDUINO_UNO' ? 'Arduino Uno' : mode} sensor node`
              : 'SIMULATION = software-generated data from simulator/, not real hardware'
          }
        >
          {modeIsHardware ? <Microchip size={15} /> : <MonitorSmartphone size={15} />}
          {modeIsHardware ? (mode === 'ARDUINO_UNO' ? 'ARDUINO UNO' : 'REAL HARDWARE') : 'SIMULATION'}
        </span>

        <span className={`health-badge ${healthy ? 'health-badge--ok' : 'health-badge--down'}`}>
          <span className={`health-dot ${healthy ? 'health-dot--ok' : 'health-dot--down'}`} />
          {healthy ? 'API healthy' : health ? 'API degraded' : 'API unreachable'}
        </span>

        <span className="header-lastseen" title={lastSeen}>
          Last reading: {lastSeen || '—'}
        </span>
      </div>

      <nav className="app-nav" aria-label="Primary">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className={`app-nav__btn ${activeTab === id ? 'app-nav__btn--active' : ''}`}
            onClick={() => onTabChange(id)}
            aria-current={activeTab === id ? 'page' : undefined}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </nav>
    </header>
  )
}
