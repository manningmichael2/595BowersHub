import { forwardRef } from 'react'
import { cn } from './cn'

/**
 * Textarea — multi-line field primitive (R2.3). Mirrors Input's tokens with a
 * sensible min-height and vertical resize.
 */
export const Textarea = forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      'flex min-h-[80px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-text',
      'placeholder:text-text-muted',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-background',
      'disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...props}
  />
))
Textarea.displayName = 'Textarea'
