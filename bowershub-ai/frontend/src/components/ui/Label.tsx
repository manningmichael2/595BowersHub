import { forwardRef } from 'react'
import { cn } from './cn'

/**
 * Label — form label primitive (R2.3). Pair with Input/Textarea via `htmlFor`.
 */
export const Label = forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn('text-sm font-medium text-text peer-disabled:opacity-50', className)}
      {...props}
    />
  ),
)
Label.displayName = 'Label'
