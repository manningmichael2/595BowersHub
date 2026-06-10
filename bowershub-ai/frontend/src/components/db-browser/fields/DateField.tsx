/**
 * DateField — native date/datetime picker for date and timestamp columns.
 *
 * Renders a native HTML date or datetime-local input.
 * Handles various input formats (ISO strings, Postgres timestamps).
 * Supports compact mode (inline cell editing) and normal mode (detail form).
 *
 * _Requirements: 8.8_
 */

import type { FieldComponentProps } from './TextField'

interface DateFieldProps extends FieldComponentProps {
  /** Whether to include time component (datetime-local vs date) */
  includeTime?: boolean
}

export default function DateField({
  value,
  onChange,
  compact = false,
  readOnly = false,
  includeTime = false,
}: DateFieldProps) {
  const baseInputStyle = getInputStyle(compact)

  return (
    <input
      type={includeTime ? 'datetime-local' : 'date'}
      value={formatDateValue(value, includeTime)}
      onChange={(e) => onChange(e.target.value || null)}
      disabled={readOnly}
      style={baseInputStyle}
      className={inputClassName(compact)}
    />
  )
}

// ---- Helpers ---------------------------------------------------------------

function formatDateValue(value: any, includeTime: boolean): string {
  if (!value) return ''
  const str = String(value)
  if (includeTime) {
    // datetime-local expects YYYY-MM-DDTHH:mm
    if (str.includes('T')) {
      return str.slice(0, 16)
    }
    // Postgres format: "2026-01-15 10:30:00"
    return str.replace(' ', 'T').slice(0, 16)
  }
  // date input expects YYYY-MM-DD
  return str.slice(0, 10)
}

function getInputStyle(compact: boolean): React.CSSProperties {
  return {
    backgroundColor: 'var(--color-background)',
    color: 'var(--color-text)',
    border: compact ? 'none' : '1px solid var(--color-border)',
    height: compact ? '36px' : undefined,
    padding: compact ? '0 4px' : undefined,
  }
}

function inputClassName(compact: boolean): string {
  const base = 'w-full text-xs outline-none'
  if (compact) {
    return `${base} bg-transparent`
  }
  return `${base} rounded px-2 py-1.5`
}
