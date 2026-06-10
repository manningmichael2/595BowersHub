/**
 * FractionField — fraction input for woodworking measurement columns.
 *
 * Displays decimal values as fractions (e.g., 0.375 → "3/8\"") and accepts
 * fraction or decimal input, storing as decimal. Uses a lookup table of
 * common woodworking fractions with denominators 2, 4, 8, 16, 32, 64.
 *
 * _Requirements: 8.3_
 */

import { useState, useEffect, useRef } from 'react'

// ---- Props -----------------------------------------------------------------

interface FractionFieldProps {
  value: any // decimal number from DB (e.g., 0.375)
  onChange: (value: number | null) => void
  compact?: boolean
  readOnly?: boolean
  suffix?: string | null // typically '"' for inches
}

// ---- Fraction Lookup Table -------------------------------------------------

/**
 * All fractions with denominators 2, 4, 8, 16, 32, 64 (from 1/64 to 63/64).
 * Each entry is [numerator, denominator, decimal].
 * Entries are sorted by decimal value for binary search.
 */
const FRACTION_TABLE: Array<[number, number, number]> = buildFractionTable()

function buildFractionTable(): Array<[number, number, number]> {
  const entries: Array<[number, number, number]> = []
  const seen = new Set<number>()

  // Generate all fractions for denominators 2, 4, 8, 16, 32, 64
  for (const denom of [2, 4, 8, 16, 32, 64]) {
    for (let num = 1; num < denom; num++) {
      const decimal = num / denom
      // Skip duplicates (e.g., 2/4 = 1/2)
      // Use a rounded key to avoid floating-point comparison issues
      const key = Math.round(decimal * 1_000_000)
      if (!seen.has(key)) {
        seen.add(key)
        // Store the reduced fraction
        const g = gcd(num, denom)
        entries.push([num / g, denom / g, decimal])
      }
    }
  }

  // Sort by decimal value
  entries.sort((a, b) => a[2] - b[2])
  return entries
}

function gcd(a: number, b: number): number {
  while (b !== 0) {
    const t = b
    b = a % b
    a = t
  }
  return a
}

// ---- Conversion Functions (exported for testing in task 6.8) ---------------

/**
 * Convert a decimal value to a fraction display string.
 *
 * Examples:
 * - 0.375 → "3/8"
 * - 1.375 → "1-3/8"
 * - 2.0 → "2"
 * - 0.0 → "0"
 * - null/undefined → ""
 *
 * Finds the closest fraction from the lookup table.
 */
export function decimalToFraction(decimal: number | null | undefined): string {
  if (decimal == null || isNaN(decimal)) return ''
  if (decimal === 0) return '0'

  const isNegative = decimal < 0
  const absValue = Math.abs(decimal)

  // Separate whole number and fractional part
  const wholeNumber = Math.floor(absValue)
  const fractionalPart = absValue - wholeNumber

  let fractionStr = ''

  if (fractionalPart < 1e-9) {
    // No fractional part — just a whole number
    fractionStr = String(wholeNumber)
  } else {
    // Find the closest fraction in the lookup table
    const closest = findClosestFraction(fractionalPart)

    if (closest) {
      const [num, denom] = closest
      if (wholeNumber > 0) {
        fractionStr = `${wholeNumber}-${num}/${denom}`
      } else {
        fractionStr = `${num}/${denom}`
      }
    } else {
      // Fallback: display as decimal if no close fraction match
      fractionStr = String(absValue)
    }
  }

  return isNegative ? `-${fractionStr}` : fractionStr
}

/**
 * Find the closest fraction in the lookup table.
 * Returns [numerator, denominator] or null if no fraction is close enough.
 * Tolerance: 1/128 (half of 1/64 = ~0.0078)
 */
function findClosestFraction(fractional: number): [number, number] | null {
  const tolerance = 1 / 128

  let bestDist = Infinity
  let bestEntry: [number, number, number] | null = null

  for (const entry of FRACTION_TABLE) {
    const dist = Math.abs(entry[2] - fractional)
    if (dist < bestDist) {
      bestDist = dist
      bestEntry = entry
    }
  }

  if (bestEntry && bestDist <= tolerance) {
    return [bestEntry[0], bestEntry[1]]
  }

  return null
}

/**
 * Parse a fraction or decimal string into a numeric decimal value.
 *
 * Supported formats:
 * - "3/8" or "3/8\"" → 0.375
 * - "1-3/8" or "1-3/8\"" → 1.375
 * - "0.375" or ".375" → 0.375
 * - "3" → 3.0
 * - "" → null
 *
 * Returns null if the input cannot be parsed.
 */
export function fractionToDecimal(input: string): number | null {
  if (!input || input.trim() === '') return null

  // Strip trailing quote marks (inch symbol) and whitespace
  let cleaned = input.trim().replace(/["″'']+$/, '').trim()

  if (cleaned === '') return null

  // Try mixed number: "1-3/8" or "12-1/4"
  const mixedMatch = cleaned.match(/^(-?\d+)\s*[-–]\s*(\d+)\s*\/\s*(\d+)$/)
  if (mixedMatch) {
    const whole = parseInt(mixedMatch[1], 10)
    const num = parseInt(mixedMatch[2], 10)
    const denom = parseInt(mixedMatch[3], 10)
    if (denom === 0) return null
    const sign = whole < 0 ? -1 : 1
    return sign * (Math.abs(whole) + num / denom)
  }

  // Try plain fraction: "3/8"
  const fractionMatch = cleaned.match(/^(-?\d+)\s*\/\s*(\d+)$/)
  if (fractionMatch) {
    const num = parseInt(fractionMatch[1], 10)
    const denom = parseInt(fractionMatch[2], 10)
    if (denom === 0) return null
    return num / denom
  }

  // Try decimal: "0.375", ".375", "3", "1.5"
  const numVal = parseFloat(cleaned)
  if (!isNaN(numVal) && isFinite(numVal)) {
    return numVal
  }

  return null
}

// ---- Component -------------------------------------------------------------

export default function FractionField({
  value,
  onChange,
  compact = false,
  readOnly = false,
  suffix = null,
}: FractionFieldProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // When entering edit mode, show the fraction string as starting value
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  // Build display string
  const displaySuffix = suffix ?? ''
  const displayValue = value != null ? decimalToFraction(Number(value)) : ''
  const displayText = displayValue ? `${displayValue}${displaySuffix}` : '—'

  const handleStartEdit = () => {
    if (readOnly) return
    setEditText(displayValue)
    setIsEditing(true)
  }

  const handleCommit = () => {
    setIsEditing(false)
    const parsed = fractionToDecimal(editText)
    // Only call onChange if actually changed
    if (parsed !== value) {
      onChange(parsed)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleCommit()
    } else if (e.key === 'Escape') {
      setIsEditing(false)
    }
  }

  // ---- Compact mode (inline cell) ----
  if (compact) {
    if (isEditing) {
      return (
        <input
          ref={inputRef}
          type="text"
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onBlur={handleCommit}
          onKeyDown={handleKeyDown}
          style={{
            backgroundColor: 'transparent',
            color: 'var(--color-text)',
            border: 'none',
            height: '36px',
            padding: '0 4px',
          }}
          className="w-full text-xs outline-none bg-transparent"
        />
      )
    }

    return (
      <span
        onClick={handleStartEdit}
        className="text-xs w-full block cursor-pointer truncate"
        style={{
          color: value != null ? 'var(--color-text)' : 'var(--color-text-muted)',
          lineHeight: '36px',
          padding: '0 4px',
        }}
        title={value != null ? `${displayValue}${displaySuffix} (${value})` : undefined}
      >
        {displayText}
      </span>
    )
  }

  // ---- Normal mode (detail form) ----
  if (isEditing) {
    return (
      <div className="flex items-center gap-1 w-full">
        <input
          ref={inputRef}
          type="text"
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onBlur={handleCommit}
          onKeyDown={handleKeyDown}
          placeholder="e.g. 3/8 or 0.375"
          style={{
            backgroundColor: 'var(--color-background)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-primary)',
          }}
          className="w-full text-xs rounded px-2 py-1.5 outline-none"
        />
        {suffix && (
          <span className="text-xs shrink-0" style={{ color: 'var(--color-text-muted)' }}>
            {suffix}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 w-full">
      <div
        onClick={handleStartEdit}
        style={{
          backgroundColor: 'var(--color-background)',
          color: value != null ? 'var(--color-text)' : 'var(--color-text-muted)',
          border: '1px solid var(--color-border)',
          cursor: readOnly ? 'default' : 'pointer',
        }}
        className="w-full text-xs rounded px-2 py-1.5"
        title={value != null ? `Decimal: ${value}` : undefined}
      >
        {displayText}
      </div>
    </div>
  )
}
