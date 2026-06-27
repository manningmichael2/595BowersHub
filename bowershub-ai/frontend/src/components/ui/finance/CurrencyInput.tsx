import {
  NumberField,
  Label as AriaLabel,
  Input as AriaInput,
  type NumberFieldProps,
} from 'react-aria-components'
import { cn } from '../cn'

export interface CurrencyInputProps extends Omit<NumberFieldProps, 'children'> {
  label?: string
  /** ISO 4217 code (default USD). */
  currency?: string
  placeholder?: string
  className?: string
}

/**
 * CurrencyInput — locale-aware money field over React Aria's NumberField
 * (R2.5). Handles currency formatting, parsing, and step semantics; digits are
 * tabular for alignment. Exposed through the finance UI boundary — call-sites
 * never import react-aria-components directly.
 */
export function CurrencyInput({
  label,
  currency = 'USD',
  placeholder,
  className,
  ...props
}: CurrencyInputProps) {
  return (
    <NumberField
      formatOptions={{ style: 'currency', currency, currencyDisplay: 'symbol' }}
      className={cn('flex flex-col gap-1', className)}
      {...props}
    >
      {label && <AriaLabel className="text-sm font-medium text-text">{label}</AriaLabel>}
      <AriaInput
        placeholder={placeholder}
        className={cn(
          'h-10 w-full rounded-md border border-border bg-background px-3 text-sm tabular-nums text-text',
          'placeholder:text-text-muted',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-background',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      />
    </NumberField>
  )
}
