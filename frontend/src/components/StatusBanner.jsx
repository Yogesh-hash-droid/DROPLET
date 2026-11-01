export function ErrorBanner({ error }) {
  if (!error) return null
  return (
    <div className="banner banner--error" role="alert">
      API error: {error}
    </div>
  )
}

export function LoadingNote({ loading, data }) {
  if (loading && !data) return <p className="empty-note">Loading…</p>
  return null
}
