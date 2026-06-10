/**
 * UrlField — URL input with clickable link icon.
 *
 * Renders a URL-type input with an external link icon button that opens
 * the URL in a new tab when the value is non-empty.
 * Supports compact mode (inline cell editing) and normal mode (detail form).
 *
 * _Requirements: 8.7_
 */

import type { FieldComponentProps } from './TextField'

export default function UrlField({
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
        type="url"
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
      {value && !compact && (
        <a
          href={value}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 text-xs hover:opacity-80"
          style={{ color: 'var(--color-primary)' }}
          title="Open link"
        >
          ↗
        </a>
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
