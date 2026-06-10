/**
 * TextareaField — resizable textarea for notes, JSON, and long-text columns.
 *
 * In normal mode, renders a resizable textarea with configurable rows.
 * In compact mode, renders a truncated single-line read-only display
 * (textareas don't fit inline cell editing).
 *
 * _Requirements: 8.9_
 */

import type { FieldComponentProps } from './TextField'

export default function TextareaField({
  value,
  onChange,
  compact = false,
  readOnly = false,
  placeholder,
}: FieldComponentProps) {
  if (compact) {
    // In compact mode, textarea falls back to a single-line read-only display
    return (
      <span
        className="text-xs truncate w-full block"
        style={{ color: 'var(--color-text-muted)', lineHeight: '36px' }}
        title={value ?? ''}
      >
        {value ? String(value).slice(0, 50) : '—'}
      </span>
    )
  }

  const baseInputStyle: React.CSSProperties = {
    backgroundColor: 'var(--color-background)',
    color: 'var(--color-text)',
    border: '1px solid var(--color-border)',
    height: 'auto',
    minHeight: '72px',
    resize: 'vertical',
  }

  return (
    <textarea
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      disabled={readOnly}
      placeholder={placeholder ?? undefined}
      rows={3}
      style={baseInputStyle}
      className="w-full text-xs rounded px-2 py-1.5 outline-none"
    />
  )
}
