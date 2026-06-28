import { forwardRef } from 'react'
import { cn } from './cn'

/**
 * Input — text field primitive (R2.3). Tokenized surface/border/text + a
 * tokenized focus ring. The `.bg-background` class outspecifies the global
 * `input { background-color: var(--color-surface) }` rule in index.css, so the
 * field reads against the page background for depth.
 */
export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = 'text', ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text',
        'placeholder:text-text-muted',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-background',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
