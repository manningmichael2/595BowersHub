/**
 * Unit tests for the DB sidebar's pure organization helpers: favorites
 * resolution, hidden-table filtering, search, and stale-key handling.
 */
import { describe, it, expect } from 'vitest'
import { buildFavoriteEntries, buildSchemaGroups } from '../SchemaSidebar'

const t = (name: string) => ({ name, column_count: 0, row_count: 0, has_link_table: false })

const SCHEMAS = [
  { name: 'finance', tables: [t('transactions'), t('accounts'), t('budgets')] },
  { name: 'public', tables: [t('bh_users'), t('bh_users_files')] },
]

describe('buildFavoriteEntries', () => {
  it('resolves favorite keys to tables, sorted by name', () => {
    const favs = new Set(['finance.transactions', 'public.bh_users'])
    const out = buildFavoriteEntries(SCHEMAS, favs, '')
    expect(out.map(e => `${e.schema}.${e.table.name}`)).toEqual([
      'public.bh_users', 'finance.transactions', // bh_users < transactions
    ])
  })

  it('skips stale keys that no longer match a table', () => {
    const favs = new Set(['finance.transactions', 'finance.deleted_table'])
    const out = buildFavoriteEntries(SCHEMAS, favs, '')
    expect(out.map(e => e.table.name)).toEqual(['transactions'])
  })

  it('applies the search filter', () => {
    const favs = new Set(['finance.transactions', 'finance.accounts'])
    const out = buildFavoriteEntries(SCHEMAS, favs, 'acc')
    expect(out.map(e => e.table.name)).toEqual(['accounts'])
  })
})

describe('buildSchemaGroups', () => {
  it('hides hidden tables unless showHidden, and reports hiddenCount', () => {
    const hidden = new Set(['public.bh_users_files'])
    const groups = buildSchemaGroups(SCHEMAS, hidden, false, '')
    const pub = groups.find(g => g.name === 'public')!
    expect(pub.tables.map(t => t.name)).toEqual(['bh_users'])
    expect(pub.hiddenCount).toBe(1)

    const shown = buildSchemaGroups(SCHEMAS, hidden, true, '')
    expect(shown.find(g => g.name === 'public')!.tables.map(t => t.name))
      .toEqual(['bh_users', 'bh_users_files'])
  })

  it('search filters tables and drops empty groups', () => {
    const groups = buildSchemaGroups(SCHEMAS, new Set(), false, 'budget')
    expect(groups).toHaveLength(1)
    expect(groups[0].name).toBe('finance')
    expect(groups[0].tables.map(t => t.name)).toEqual(['budgets'])
  })

  it('with no search, keeps every schema (even empty after hide)', () => {
    const hidden = new Set(['public.bh_users', 'public.bh_users_files'])
    const groups = buildSchemaGroups(SCHEMAS, hidden, false, '')
    expect(groups.map(g => g.name)).toEqual(['finance', 'public'])
    expect(groups.find(g => g.name === 'public')!.tables).toHaveLength(0)
  })
})
