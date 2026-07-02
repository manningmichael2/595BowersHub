import React from 'react'

// --- Types ---

export interface WidgetShellProps {
  displayName: string
  isLoading: boolean
  error: string | null
  isStale: boolean
  lastFetched: Date | null
  /** Manual refresh. Omitted for stream-fed widgets (V2), which have no
   *  per-widget fetch — the refresh control is then hidden. */
  onRefresh?: () => void
  children: React.ReactNode
}

// --- Sub-components ---

function StaleBadge({ lastFetched }: { lastFetched: Date | null }) {
  const timeAgo = lastFetched ? getRelativeTime(lastFetched) : 'unknown'

  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
      style={{
        backgroundColor: 'color-mix(in srgb, var(--color-accent) 20%, transparent)',
        color: 'var(--color-accent)',
      }}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-current" />
      Stale · {timeAgo}
    </span>
  )
}

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-2" aria-label="Loading widget content">
      <div
        className="h-4 w-3/4 animate-pulse rounded"
        style={{ backgroundColor: 'var(--color-border)' }}
      />
      <div
        className="h-4 w-1/2 animate-pulse rounded"
        style={{ backgroundColor: 'var(--color-border)' }}
      />
      <div
        className="h-4 w-5/6 animate-pulse rounded"
        style={{ backgroundColor: 'var(--color-border)' }}
      />
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div
      className="flex items-center gap-2 rounded-md p-3 text-sm"
      style={{
        backgroundColor: 'color-mix(in srgb, var(--color-danger) 10%, transparent)',
        color: 'var(--color-danger)',
      }}
      role="alert"
    >
      <span aria-hidden="true">⚠</span>
      <span>{message}</span>
    </div>
  )
}

// --- Error Boundary ---

interface WidgetErrorBoundaryProps {
  children: React.ReactNode
  onRetry?: () => void
}

interface WidgetErrorBoundaryState {
  hasError: boolean
}

class WidgetErrorBoundary extends React.Component<
  WidgetErrorBoundaryProps,
  WidgetErrorBoundaryState
> {
  state: WidgetErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): WidgetErrorBoundaryState {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="flex flex-col items-center justify-center gap-3 rounded-lg p-6 text-center"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <p
            className="text-sm font-medium"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Widget unavailable
          </p>
          <button
            onClick={() => {
              this.setState({ hasError: false })
              this.props.onRetry?.()
            }}
            className="min-h-[44px] min-w-[44px] rounded-md px-4 py-2 text-sm font-medium transition-opacity hover:opacity-80"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary)',
            }}
          >
            Tap to retry
          </button>
        </div>
      )
    }

    return this.props.children
  }
}

// --- Main Component ---

function WidgetShell({
  displayName,
  isLoading,
  error,
  isStale,
  lastFetched,
  onRefresh,
  children,
}: WidgetShellProps) {
  return (
    <div
      className="flex flex-col overflow-hidden rounded-lg h-full"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-4 py-3"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <h3
          className="flex-1 truncate text-sm font-semibold"
          style={{ color: 'var(--color-text)' }}
        >
          {displayName}
        </h3>

        {isStale && <StaleBadge lastFetched={lastFetched} />}

        {onRefresh && (
          <button
            onClick={onRefresh}
            aria-label={`Refresh ${displayName}`}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-lg transition-opacity hover:opacity-70"
            style={{ color: 'var(--color-text-muted)' }}
          >
            ↻
          </button>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        {isLoading ? (
          <LoadingSkeleton />
        ) : error && !isStale ? (
          <ErrorState message={error} />
        ) : (
          children
        )}
      </div>
    </div>
  )
}

// --- Exported Wrapper (with Error Boundary) ---

function WidgetShellWithBoundary(props: WidgetShellProps) {
  return (
    <WidgetErrorBoundary onRetry={props.onRefresh}>
      <WidgetShell {...props} />
    </WidgetErrorBoundary>
  )
}

export default WidgetShellWithBoundary
export { WidgetShellWithBoundary as WidgetShell }

// --- Helpers ---

function getRelativeTime(date: Date): string {
  const now = Date.now()
  const diffMs = now - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)

  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDays = Math.floor(diffHr / 24)
  return `${diffDays}d ago`
}
