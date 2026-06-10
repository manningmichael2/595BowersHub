/**
 * BooleanField — Yes/No toggle for boolean columns.
 *
 * Renders a pair of toggle buttons (Yes/No) with an optional clear button.
 * Handles various truthy/falsy input values (true, 'true', 1, etc.).
 * Supports compact mode (smaller buttons) and normal mode (standard buttons with clear).
 *
 * _Requirements: 8.6_
 */

import type { FieldComponentProps } from './TextField'

export default function BooleanField({
  value,
  onChange,
  compact = false,
  readOnly = false,
}: FieldComponentProps) {
  const boolVal = value === true || value === 'true' || value === 1
    ? true
    : value === false || value === 'false' || value === 0
      ? false
      : null

  const buttonBase = compact
    ? 'px-2 py-0.5 text-xs rounded'
    : 'px-3 py-1 text-xs rounded'

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        disabled={readOnly}
        onClick={() => onChange(true)}
        className={buttonBase}
        style={{
          backgroundColor: boolVal === true ? 'var(--color-primary)' : 'var(--color-background)',
          color: boolVal === true ? 'var(--color-on-primary, #fff)' : 'var(--color-text)',
          border: '1px solid var(--color-border)',
          opacity: readOnly ? 0.5 : 1,
          cursor: readOnly ? 'not-allowed' : 'pointer',
        }}
      >
        Yes
      </button>
      <button
        type="button"
        disabled={readOnly}
        onClick={() => onChange(false)}
        className={buttonBase}
        style={{
          backgroundColor: boolVal === false ? 'var(--color-primary)' : 'var(--color-background)',
          color: boolVal === false ? 'var(--color-on-primary, #fff)' : 'var(--color-text)',
          border: '1px solid var(--color-border)',
          opacity: readOnly ? 0.5 : 1,
          cursor: readOnly ? 'not-allowed' : 'pointer',
        }}
      >
        No
      </button>
      {boolVal !== null && !compact && (
        <button
          type="button"
          disabled={readOnly}
          onClick={() => onChange(null)}
          className="text-xs px-1 opacity-60 hover:opacity-100"
          style={{ color: 'var(--color-text-muted)' }}
          title="Clear"
        >
          ✕
        </button>
      )}
    </div>
  )
}
