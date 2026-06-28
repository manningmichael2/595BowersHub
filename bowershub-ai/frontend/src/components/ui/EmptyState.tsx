import type { ReactNode } from 'react'
import { cn } from './cn'

export interface EmptyStateProps {
  /** Optional icon/illustration (e.g. a Lucide icon element). */
  icon?: ReactNode
  title: string
  description?: ReactNode
  /** Optional CTA (e.g. a <Button/>). */
  action?: ReactNode
  className?: string
}

/**
 * EmptyState — the "nothing here yet" primitive (R2.6), so surfaces stop
 * re-inventing empty copy/layout. Tokenized, centered.
 */
export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 p-8 text-center',
        className,
      )}
    >
      {icon && <div className="text-text-muted">{icon}</div>}
      <h3 className="text-sm font-medium text-text">{title}</h3>
      {description && <p className="max-w-sm text-sm text-text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
