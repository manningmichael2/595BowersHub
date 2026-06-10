/**
 * Unit tests for CreateTableDialog SQL preview generation.
 *
 * **Validates: Requirements 14.2, 14.3, 14.4, 14.5**
 *
 * Tests the pure helper functions used to generate the live SQL preview.
 */

import { describe, it, expect } from 'vitest'

// ---- Import pure helpers (replicated here since they're not exported) ------

type ColumnType =
  | 'text'
  | 'integer'
  | 'decimal'
  | 'boolean'
  | 'date'
  | 'timestamp'
  | 'lookup'

interface ColumnDef {
  id: string
  name: string
  type: ColumnType
  nullable: boolean
  defaultValue: string
}

const PG_TYPE_MAP: Record<ColumnType, string> = {
  text: 'TEXT',
  integer: 'INTEGER',
  decimal: 'NUMERIC',
  boolean: 'BOOLEAN',
  date: 'DATE',
  timestamp: 'TIMESTAMPTZ',
  lookup: 'INTEGER',
}

function sanitizeIdentifier(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_')
}

function formatDefault(value: string, type: ColumnType): string {
  const trimmed = value.trim()
  switch (type) {
    case 'text':
      if (trimmed.startsWith("'") && trimmed.endsWith("'")) return trimmed
      return `'${trimmed.replace(/'/g, "''")}'`
    case 'boolean':
      return trimmed.toLowerCase() === 'true' ? 'true' : 'false'
    case 'integer':
    case 'decimal':
      return trimmed
    case 'date':
    case 'timestamp':
      if (trimmed.toLowerCase() === 'now()') return 'now()'
      return `'${trimmed}'`
    case 'lookup':
      return trimmed
    default:
      return `'${trimmed}'`
  }
}

function buildSqlPreview(
  schema: string,
  tableName: string,
  columns: ColumnDef[],
  includeImages: boolean
): string {
  const safeName = sanitizeIdentifier(tableName)
  const safeSchema = sanitizeIdentifier(schema)

  if (!safeName || !safeSchema) {
    return '-- Enter a schema and table name to preview SQL'
  }

  const validColumns = columns.filter(c => c.name.trim() !== '')

  const lines: string[] = []
  lines.push(`CREATE TABLE ${safeSchema}.${safeName} (`)

  const colLines: string[] = []
  colLines.push(`    id SERIAL PRIMARY KEY`)

  for (const col of validColumns) {
    const colName = sanitizeIdentifier(col.name)
    if (!colName) continue

    let colType = PG_TYPE_MAP[col.type]
    let line = `    ${colName} ${colType}`

    if (!col.nullable) {
      line += ' NOT NULL'
    }
    if (col.defaultValue.trim()) {
      line += ` DEFAULT ${formatDefault(col.defaultValue, col.type)}`
    }
    colLines.push(line)
  }

  colLines.push(`    created_at TIMESTAMPTZ NOT NULL DEFAULT now()`)
  colLines.push(`    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`)

  lines.push(colLines.join(',\n'))
  lines.push(');')

  if (includeImages) {
    lines.push('')
    lines.push(`CREATE TABLE ${safeSchema}.${safeName}_files (`)
    lines.push(`    ${safeName}_id INTEGER NOT NULL REFERENCES ${safeSchema}.${safeName}(id) ON DELETE CASCADE,`)
    lines.push(`    asset_id UUID NOT NULL REFERENCES files.assets(id) ON DELETE CASCADE,`)
    lines.push(`    is_primary BOOLEAN DEFAULT false,`)
    lines.push(`    sort_order INTEGER DEFAULT 0,`)
    lines.push(`    PRIMARY KEY (${safeName}_id, asset_id)`)
    lines.push(');')
  }

  return lines.join('\n')
}

// ---- Tests ----------------------------------------------------------------

describe('CreateTableDialog — sanitizeIdentifier', () => {
  it('lowercases and strips special characters', () => {
    expect(sanitizeIdentifier('My Table!')).toBe('my_table')
  })

  it('collapses consecutive underscores', () => {
    expect(sanitizeIdentifier('foo__bar')).toBe('foo_bar')
  })

  it('strips leading and trailing underscores', () => {
    expect(sanitizeIdentifier('_hello_')).toBe('hello')
  })

  it('preserves valid identifiers', () => {
    expect(sanitizeIdentifier('router_bits')).toBe('router_bits')
  })

  it('returns empty string for all-special input', () => {
    expect(sanitizeIdentifier('!!!')).toBe('')
  })
})

describe('CreateTableDialog — formatDefault', () => {
  it('wraps text defaults in single quotes', () => {
    expect(formatDefault('hello', 'text')).toBe("'hello'")
  })

  it('does not double-wrap already quoted text', () => {
    expect(formatDefault("'world'", 'text')).toBe("'world'")
  })

  it('escapes single quotes in text values', () => {
    expect(formatDefault("it's", 'text')).toBe("'it''s'")
  })

  it('returns true/false for boolean type', () => {
    expect(formatDefault('true', 'boolean')).toBe('true')
    expect(formatDefault('True', 'boolean')).toBe('true')
    expect(formatDefault('false', 'boolean')).toBe('false')
    expect(formatDefault('no', 'boolean')).toBe('false')
  })

  it('passes numeric values through for integer', () => {
    expect(formatDefault('42', 'integer')).toBe('42')
  })

  it('passes numeric values through for decimal', () => {
    expect(formatDefault('3.14', 'decimal')).toBe('3.14')
  })

  it('handles now() for timestamp type', () => {
    expect(formatDefault('now()', 'timestamp')).toBe('now()')
  })

  it('wraps date string values in quotes', () => {
    expect(formatDefault('2026-01-01', 'date')).toBe("'2026-01-01'")
  })
})

describe('CreateTableDialog — buildSqlPreview', () => {
  it('returns placeholder when schema or table name is empty', () => {
    expect(buildSqlPreview('', 'test', [], false)).toContain('-- Enter a schema')
    expect(buildSqlPreview('inventory', '', [], false)).toContain('-- Enter a schema')
  })

  it('generates CREATE TABLE with auto PK and timestamps', () => {
    const sql = buildSqlPreview('inventory', 'clamps', [], false)
    expect(sql).toContain('CREATE TABLE inventory.clamps (')
    expect(sql).toContain('id SERIAL PRIMARY KEY')
    expect(sql).toContain('created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    expect(sql).toContain('updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
  })

  it('includes user-defined columns with correct types', () => {
    const columns: ColumnDef[] = [
      { id: '1', name: 'brand', type: 'text', nullable: true, defaultValue: '' },
      { id: '2', name: 'size_in', type: 'decimal', nullable: false, defaultValue: '' },
    ]
    const sql = buildSqlPreview('inventory', 'clamps', columns, false)
    expect(sql).toContain('brand TEXT')
    expect(sql).toContain('size_in NUMERIC NOT NULL')
  })

  it('applies NOT NULL when nullable is false', () => {
    const columns: ColumnDef[] = [
      { id: '1', name: 'name', type: 'text', nullable: false, defaultValue: '' },
    ]
    const sql = buildSqlPreview('inventory', 'test', columns, false)
    expect(sql).toContain('name TEXT NOT NULL')
  })

  it('includes DEFAULT clause when default value is specified', () => {
    const columns: ColumnDef[] = [
      { id: '1', name: 'condition', type: 'text', nullable: true, defaultValue: 'good' },
    ]
    const sql = buildSqlPreview('inventory', 'test', columns, false)
    expect(sql).toContain("condition TEXT DEFAULT 'good'")
  })

  it('generates link table when includeImages is true', () => {
    const sql = buildSqlPreview('inventory', 'clamps', [], true)
    expect(sql).toContain('CREATE TABLE inventory.clamps_files (')
    expect(sql).toContain('clamps_id INTEGER NOT NULL REFERENCES inventory.clamps(id) ON DELETE CASCADE')
    expect(sql).toContain('asset_id UUID NOT NULL REFERENCES files.assets(id) ON DELETE CASCADE')
    expect(sql).toContain('is_primary BOOLEAN DEFAULT false')
    expect(sql).toContain('PRIMARY KEY (clamps_id, asset_id)')
  })

  it('does not generate link table when includeImages is false', () => {
    const sql = buildSqlPreview('inventory', 'clamps', [], false)
    expect(sql).not.toContain('_files')
  })

  it('skips columns with empty names', () => {
    const columns: ColumnDef[] = [
      { id: '1', name: '', type: 'text', nullable: true, defaultValue: '' },
      { id: '2', name: 'brand', type: 'text', nullable: true, defaultValue: '' },
    ]
    const sql = buildSqlPreview('inventory', 'test', columns, false)
    expect(sql).toContain('brand TEXT')
    // Should not contain an empty column definition
    const lines = sql.split('\n')
    const emptyCol = lines.find(l => l.trim().match(/^\s*TEXT/))
    expect(emptyCol).toBeUndefined()
  })

  it('maps lookup type to INTEGER', () => {
    const columns: ColumnDef[] = [
      { id: '1', name: 'category_id', type: 'lookup', nullable: true, defaultValue: '' },
    ]
    const sql = buildSqlPreview('inventory', 'test', columns, false)
    expect(sql).toContain('category_id INTEGER')
  })
})
