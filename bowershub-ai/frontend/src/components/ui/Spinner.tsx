import { Loader2 } from 'lucide-react'
import { cn } from './cn'

export interface SpinnerProps extends React.SVGProps<SVGSVGElement> {
  /** Accessible label announced to screen readers. */
  label?: string
}

/**
 * Spinner — loading indicator (R2.6). `animate-spin` collapses under
 * prefers-reduced-motion (R1.5 global rule). Exposes role=status + label.
 */
export function Spinner({ className, label = 'Loading', ...props }: SpinnerProps) {
  return (
    <Loader2
      role="status"
      aria-label={label}
      className={cn('h-4 w-4 animate-spin text-text-muted', className)}
      {...props}
    />
  )
}
