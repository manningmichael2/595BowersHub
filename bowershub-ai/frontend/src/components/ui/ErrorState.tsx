import type { ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import { cn } from './cn'
import { Button } from './Button'

export interface ErrorStateProps {
  title?: string
  message?: ReactNode
  /** When provided, renders a Retry button wired to this handler. */
  onRetry?: () => void
  retryLabel?: string
  className?: string
}

/**
 * ErrorState — the canonical "couldn't load — Retry" affordance (R2.6),
 * consolidating the pattern the 2026-06-22 hardening pass spread across stores.
 * Surfaces route their `error` field + retry through this instead of hand-rolling.
 */
export function ErrorState({
  title = 'Couldn’t load',
  message,
  onRetry,
  retryLabel = 'Retry',
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn('flex flex-col items-center justify-center gap-2 p-6 text-center', className)}
    >
      <AlertTriangle className="h-5 w-5 text-danger" aria-hidden />
      <h3 className="text-sm font-medium text-text">{title}</h3>
      {message && <p className="max-w-sm text-sm text-text-muted">{message}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-1" onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  )
}
