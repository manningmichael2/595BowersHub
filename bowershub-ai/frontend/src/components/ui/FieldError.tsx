import { cn } from './cn'

/**
 * FieldError — inline form-field validation message (R2.6). Renders nothing
 * when there's no error, so call-sites can pass a possibly-empty value
 * directly. Announced via role=alert.
 */
export function FieldError({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  if (!children) return null
  return (
    <p role="alert" className={cn('mt-1 text-xs text-danger', className)} {...props}>
      {children}
    </p>
  )
}
