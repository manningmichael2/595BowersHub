/**
 * SelectField — dropdown select for columns with static options.
 *
 * Renders a native HTML select element with the provided options list.
 * Used for fields like `condition` (new/excellent/good/fair/worn/damaged/broken)
 * and any other field with a configured options list.
 * Supports compact mode (inline cell editing) and normal mode (detail form).
 *
 * _Requirements: 8.2_
 */

import type { FieldComponentProps } from './TextField'

export default function SelectField({
  value,
  onChange,
  compact = false,
  readOnly = false,
  options,
}: FieldComponentProps) {
  const baseInputStyle = getInputStyle(compact)

  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value || null)}
      disabled={readOnly}
      style={baseInputStyle}
      className={inputClassName(compact)}
    >
      <option value="">—</option>
      {(options ?? []).map(opt => (
        <option key={opt} value={opt}>{opt}</option>
      ))}
    </select>
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
