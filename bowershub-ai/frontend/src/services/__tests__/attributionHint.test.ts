/**
 * T-ATTR-1 (frontend): the attribution hint renders the right label and never
 * leaks "undefined"/blank for a NULL editor.
 */
import { describe, expect, it } from 'vitest'
import { attributionHint } from '../financeTransactions'

describe('attributionHint', () => {
  it('shows the human editor when one is recorded', () => {
    expect(attributionHint({ updated_by_name: 'Alice', user_category_override: true, source: null }))
      .toBe('Edited by Alice')
  })

  it('renders a NULL editor on a non-overridden row as "Bank sync"', () => {
    expect(attributionHint({ updated_by_name: null, user_category_override: false, source: 'sync' }))
      .toBe('Bank sync')
  })

  it('renders a historical manual edit (override, no editor) with no hint — never "undefined"', () => {
    const hint = attributionHint({ updated_by_name: null, user_category_override: true, source: null })
    expect(hint).toBeNull()
  })
})
