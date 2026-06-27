import { cn } from './cn'

/**
 * Skeleton — content placeholder (R2.6). Decorative (aria-hidden); size it with
 * the className. `animate-pulse` collapses under prefers-reduced-motion.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div aria-hidden className={cn('animate-pulse rounded-md bg-surface-light', className)} {...props} />
  )
}
