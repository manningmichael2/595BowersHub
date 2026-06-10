/**
 * NumberField — numeric input for integer and decimal columns.
 *
 * Renders a number input with optional prefix/suffix, min/max/step constraints.
 * Supports compact mode (inline cell editing) and normal mode (detail form).
 *
 * _Requirements: 8.4, 8.5_
 */

import type { FieldComponentProps } from './TextField'

export default function NumberField({
  value,
  onChange,
  compact = false,
  readOnly = false,
  prefix,
  suffix,
  placeholder,
  min,
  max,
  step,
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
        type="number"
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value
          if (raw === '') {
            onChange(null)
          } else {
            onChange(Number(raw))
          }
        }}
        disabled={readOnly}
        min={min ?? undefined}
        max={max ?? undefined}
        step={step ?? 'any'}
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
