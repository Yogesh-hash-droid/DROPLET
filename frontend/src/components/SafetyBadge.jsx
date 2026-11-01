export default function SafetyBadge({ status, size = 'md' }) {
  const cls = `safety-badge safety-badge--${(status || 'unknown').toLowerCase()} safety-badge--${size}`
  return (
    <span className={cls} data-testid="safety-badge">
      {status || 'UNKNOWN'}
    </span>
  )
}
