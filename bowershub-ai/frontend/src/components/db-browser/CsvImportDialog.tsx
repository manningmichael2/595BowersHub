/**
 * CsvImportDialog — modal dialog for importing CSV data into the active table.
 *
 * Flow:
 * 1. User picks a .csv file via file input
 * 2. Frontend parses headers + first 5 rows for preview (browser-side)
 * 3. Column mapping UI: each CSV column → table column dropdown or "Skip"
 * 4. Auto-maps CSV columns to table columns by case-insensitive name match
 * 5. Preview table shows mapped column names
 * 6. "Import" button triggers store.importCsv(), shows progress
 * 7. On completion: displays imported count, failed count, error details
 *
 * _Requirements: 30.2, 30.3_
 */

import { useState, useMemo, useEffect, useCallback } from 'react'
import { useDbBrowserStore, type ImportResult } from '../../stores/db-browser'
import { useIsAdmin } from '../../hooks/useIsAdmin'

// ---- Props ----------------------------------------------------------------

interface CsvImportDialogProps {
  open: boolean
  onClose: () => void
}

// ---- CSV Parsing Helpers --------------------------------------------------

/**
 * Parse a CSV string into rows of string arrays.
 * Handles quoted fields (including embedded commas and newlines within quotes).
 */
function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let current = ''
  let inQuotes = false
  let row: string[] = []

  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    const next = text[i + 1]

    if (inQuotes) {
      if (char === '"' && next === '"') {
        // Escaped quote
        current += '"'
        i++
      } else if (char === '"') {
        inQuotes = false
      } else {
        current += char
      }
    } else {
      if (char === '"') {
        inQuotes = true
      } else if (char === ',') {
        row.push(current.trim())
        current = ''
      } else if (char === '\n' || (char === '\r' && next === '\n')) {
        row.push(current.trim())
        current = ''
        if (row.length > 0 && !(row.length === 1 && row[0] === '')) {
          rows.push(row)
        }
        row = []
        if (char === '\r') i++ // skip \n in \r\n
      } else {
        current += char
      }
    }
  }

  // Handle last field/row
  if (current || row.length > 0) {
    row.push(current.trim())
    if (row.length > 0 && !(row.length === 1 && row[0] === '')) {
      rows.push(row)
    }
  }

  return rows
}

/**
 * Read a File object as text.
 */
function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error('Failed to read file'))
    reader.readAsText(file)
  })
}

// ---- Component ------------------------------------------------------------

export default function CsvImportDialog({ open, onClose }: CsvImportDialogProps) {
  const isAdmin = useIsAdmin()
  const columns = useDbBrowserStore(s => s.columns)
  const importCsv = useDbBrowserStore(s => s.importCsv)
  const activeSchema = useDbBrowserStore(s => s.activeSchema)
  const activeTable = useDbBrowserStore(s => s.activeTable)

  // Local state
  const [file, setFile] = useState<File | null>(null)
  const [csvHeaders, setCsvHeaders] = useState<string[]>([])
  const [previewRows, setPreviewRows] = useState<string[][]>([])
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({})
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)

  // Table column names for the mapping dropdowns
  const tableColumnNames = useMemo(
    () => columns.map(c => c.column_name),
    [columns]
  )

  // Reset all state when dialog opens/closes
  useEffect(() => {
    if (open) {
      setFile(null)
      setCsvHeaders([])
      setPreviewRows([])
      setColumnMapping({})
      setImporting(false)
      setResult(null)
      setError(null)
      setParseError(null)
    }
  }, [open])

  // Auto-map CSV headers to table columns by case-insensitive name match
  const autoMap = useCallback(
    (headers: string[]) => {
      const mapping: Record<string, string> = {}
      for (const header of headers) {
        const normalized = header.toLowerCase().replace(/[^a-z0-9_]/g, '_')
        const match = tableColumnNames.find(
          col => col.toLowerCase() === normalized || col.toLowerCase() === header.toLowerCase()
        )
        mapping[header] = match ?? '__skip__'
      }
      setColumnMapping(mapping)
    },
    [tableColumnNames]
  )

  // Handle file selection
  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      setResult(null)
      setError(null)
      setParseError(null)

      const selected = e.target.files?.[0]
      if (!selected) {
        setFile(null)
        setCsvHeaders([])
        setPreviewRows([])
        setColumnMapping({})
        return
      }

      setFile(selected)

      try {
        const text = await readFileAsText(selected)
        const allRows = parseCsv(text)

        if (allRows.length === 0) {
          setParseError('CSV file is empty or could not be parsed.')
          setCsvHeaders([])
          setPreviewRows([])
          setColumnMapping({})
          return
        }

        const headers = allRows[0]
        const dataRows = allRows.slice(1, 6) // first 5 data rows for preview

        setCsvHeaders(headers)
        setPreviewRows(dataRows)
        autoMap(headers)
      } catch (err: any) {
        setParseError(err?.message || 'Failed to parse CSV file.')
        setCsvHeaders([])
        setPreviewRows([])
        setColumnMapping({})
      }
    },
    [autoMap]
  )

  // Handle column mapping change
  const handleMappingChange = useCallback((csvColumn: string, tableColumn: string) => {
    setColumnMapping(prev => ({ ...prev, [csvColumn]: tableColumn }))
  }, [])

  // Handle Import
  const handleImport = useCallback(async () => {
    if (!file) return

    setImporting(true)
    setError(null)
    setResult(null)

    try {
      // Build the mapping: only include non-skipped columns
      const mapping: Record<string, string> = {}
      for (const [csvCol, tableCol] of Object.entries(columnMapping)) {
        if (tableCol && tableCol !== '__skip__') {
          mapping[csvCol] = tableCol
        }
      }

      const importResult = await importCsv(file, mapping)
      setResult(importResult)
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Import failed'
      setError(message)
    } finally {
      setImporting(false)
    }
  }, [file, columnMapping, importCsv])

  // Count how many columns are mapped (not skipped)
  const mappedCount = useMemo(
    () => Object.values(columnMapping).filter(v => v && v !== '__skip__').length,
    [columnMapping]
  )

  // Close on Escape key
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !importing) {
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose, importing])

  if (!open || !isAdmin) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !importing) onClose()
      }}
    >
      <div
        className="w-full max-w-3xl max-h-[85vh] flex flex-col rounded-lg shadow-xl mx-4"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
        }}
      >
        {/* Header */}
        <div
          className="shrink-0 flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <h3
            className="text-sm font-semibold"
            style={{ color: 'var(--color-text)' }}
          >
            Import CSV — {activeSchema}.{activeTable}
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={importing}
            className="text-sm px-2 py-1 rounded transition-opacity hover:opacity-70 disabled:opacity-40"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
          {/* Step 1: File Picker */}
          {!result && (
            <div className="space-y-1">
              <label
                className="text-xs font-medium"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Select CSV File
              </label>
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={handleFileChange}
                disabled={importing}
                className="block w-full text-xs file:mr-3 file:px-3 file:py-1.5 file:rounded file:border-0 file:text-xs file:font-medium file:cursor-pointer"
                style={{
                  color: 'var(--color-text)',
                }}
              />
            </div>
          )}

          {/* Parse Error */}
          {parseError && (
            <div
              className="px-3 py-2 text-xs rounded"
              style={{
                backgroundColor: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
                color: 'var(--color-error)',
                border: '1px solid color-mix(in srgb, var(--color-error) 30%, transparent)',
              }}
            >
              {parseError}
            </div>
          )}

          {/* Step 2: Column Mapping */}
          {csvHeaders.length > 0 && !result && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p
                  className="text-xs font-medium"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Column Mapping ({mappedCount} of {csvHeaders.length} mapped)
                </p>
              </div>

              <div className="space-y-2">
                {csvHeaders.map((header) => (
                  <div
                    key={header}
                    className="flex items-center gap-2"
                  >
                    <span
                      className="text-xs w-1/3 truncate shrink-0 font-mono"
                      style={{ color: 'var(--color-text)' }}
                      title={header}
                    >
                      {header}
                    </span>
                    <span
                      className="text-xs shrink-0"
                      style={{ color: 'var(--color-text-muted)' }}
                    >
                      →
                    </span>
                    <select
                      value={columnMapping[header] || '__skip__'}
                      onChange={(e) => handleMappingChange(header, e.target.value)}
                      disabled={importing}
                      className="flex-1 text-xs px-2 py-1.5 rounded outline-none"
                      style={{
                        backgroundColor: 'var(--color-background)',
                        color: columnMapping[header] === '__skip__'
                          ? 'var(--color-text-muted)'
                          : 'var(--color-text)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      <option value="__skip__">— Skip —</option>
                      {tableColumnNames.map(col => (
                        <option key={col} value={col}>
                          {col}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Step 3: Preview Table */}
          {previewRows.length > 0 && !result && (
            <div className="space-y-2">
              <p
                className="text-xs font-medium"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Preview (first {previewRows.length} row{previewRows.length !== 1 ? 's' : ''})
              </p>
              <div className="overflow-x-auto rounded" style={{ border: '1px solid var(--color-border)' }}>
                <table className="w-full text-xs">
                  <thead>
                    <tr style={{ backgroundColor: 'var(--color-background)' }}>
                      {csvHeaders.map((header) => {
                        const mapped = columnMapping[header]
                        const isSkipped = !mapped || mapped === '__skip__'
                        return (
                          <th
                            key={header}
                            className="px-2 py-1.5 text-left font-medium whitespace-nowrap"
                            style={{
                              color: isSkipped ? 'var(--color-text-muted)' : 'var(--color-text)',
                              opacity: isSkipped ? 0.5 : 1,
                              borderBottom: '1px solid var(--color-border)',
                            }}
                          >
                            {isSkipped ? (
                              <span className="line-through">{header}</span>
                            ) : (
                              mapped
                            )}
                          </th>
                        )
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {previewRows.map((row, rowIdx) => (
                      <tr key={rowIdx}>
                        {row.map((cell, cellIdx) => {
                          const mapped = columnMapping[csvHeaders[cellIdx]]
                          const isSkipped = !mapped || mapped === '__skip__'
                          return (
                            <td
                              key={cellIdx}
                              className="px-2 py-1 whitespace-nowrap max-w-[200px] truncate"
                              style={{
                                color: 'var(--color-text)',
                                opacity: isSkipped ? 0.3 : 1,
                                borderBottom: rowIdx < previewRows.length - 1 ? '1px solid var(--color-border)' : undefined,
                              }}
                              title={cell}
                            >
                              {cell || <span style={{ color: 'var(--color-text-muted)' }}>—</span>}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Import Progress */}
          {importing && (
            <div className="flex items-center gap-2 py-2">
              <div
                className="w-4 h-4 border-2 border-t-transparent rounded-full animate-spin"
                style={{ borderColor: 'var(--color-primary)', borderTopColor: 'transparent' }}
              />
              <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                Importing…
              </span>
            </div>
          )}

          {/* Import Results */}
          {result && (
            <div className="space-y-3">
              {/* Success summary */}
              <div
                className="px-3 py-2 rounded"
                style={{
                  backgroundColor: result.failed_rows.length === 0
                    ? 'color-mix(in srgb, var(--color-success) 10%, transparent)'
                    : 'color-mix(in srgb, var(--color-warning) 10%, transparent)',
                  border: `1px solid ${result.failed_rows.length === 0 ? 'color-mix(in srgb, var(--color-success) 30%, transparent)' : 'color-mix(in srgb, var(--color-warning) 30%, transparent)'}`,
                }}
              >
                <p className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
                  Import Complete
                </p>
                <div className="mt-1 text-xs space-y-0.5" style={{ color: 'var(--color-text-muted)' }}>
                  <p>Total rows: <span className="font-medium" style={{ color: 'var(--color-text)' }}>{result.total_rows}</span></p>
                  <p>
                    Imported: <span className="font-medium" style={{ color: 'var(--color-success)' }}>{result.imported_rows}</span>
                  </p>
                  {result.failed_rows.length > 0 && (
                    <p>
                      Failed: <span className="font-medium" style={{ color: 'var(--color-error)' }}>{result.failed_rows.length}</span>
                    </p>
                  )}
                </div>
              </div>

              {/* Error details */}
              {result.failed_rows.length > 0 && (
                <div className="space-y-1">
                  <p
                    className="text-xs font-medium"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    Errors ({result.failed_rows.length})
                  </p>
                  <div
                    className="max-h-40 overflow-y-auto rounded text-xs space-y-1 p-2"
                    style={{
                      backgroundColor: 'var(--color-background)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    {result.failed_rows.map((fail, idx) => (
                      <div key={idx} className="flex gap-2">
                        <span
                          className="shrink-0 font-mono"
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          Line {fail.line_number}:
                        </span>
                        <span style={{ color: 'var(--color-error)' }}>{fail.error}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* API Error */}
          {error && (
            <div
              className="px-3 py-2 text-xs rounded"
              style={{
                backgroundColor: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
                color: 'var(--color-error)',
                border: '1px solid color-mix(in srgb, var(--color-error) 30%, transparent)',
              }}
            >
              {error}
            </div>
          )}
        </div>

        {/* Footer with action buttons */}
        <div
          className="shrink-0 flex items-center justify-end gap-2 px-4 py-3 border-t"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={importing}
            className="text-xs px-3 py-1.5 rounded transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button
              type="button"
              onClick={handleImport}
              disabled={importing || !file || mappedCount === 0}
              className="text-xs px-3 py-1.5 rounded transition-opacity hover:opacity-80 disabled:opacity-40"
              style={{
                backgroundColor: 'var(--color-primary)',
                color: 'var(--color-on-primary, #fff)',
              }}
            >
              {importing ? 'Importing…' : `Import${file ? ` (${mappedCount} columns)` : ''}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
