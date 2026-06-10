/**
 * TextField — text input for text/varchar/char columns.
 *
 * Renders a standard text input with optional prefix/suffix display.
 * Supports compact mode (inline cell editing) and normal mode (detail form).
 *
 * _Requirements: 8.2_
 */

export interface FieldComponentProps {
  value: any
  onChange: (value: any) => void
  compact?: boolean
  readOnly?: boolean
  prefix?: string | null
  suffix?: string | null
  placeholder?: string | null
  min?: number | null
  max?: number | null
  step?: number | null
  options?: string[] | null
}

export default function TextField({
  value,
  onChange,
  compact = false,
  readOnly = false,
  prefix,
  suffix,
  placeholder,
}: FieldComponentProps) {
  const baseInputStyle = getInputStyle(compact)

  return (
    <div className="flex items-center gap-1 w-full">
      {prefix && !compact && (
        <span className="text-xs shrink-0" style={{ color: 'var(--color-text-muted)' }}>
          {prefix}
        </span>
      )}
      <input
        type="text"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={readOnly}
        placeholder={placeholder ?? undefined}
        style={baseInputStyle}
        className={inputClassName(compact)}
      />
      {suffix && !compact && (
        <span className="text-xs shrink-0" style={{ color: 'var(--color-text-muted)' }}>
          {suffix}
        </span>
      )}
    </div>
  )
}

// ---- Helpers ---------------------------------------------------------------

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
