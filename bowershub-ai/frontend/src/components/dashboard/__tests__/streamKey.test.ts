import { describe, it, expect } from 'vitest'
import { endpointToStreamKey } from '../streamKey'

/**
 * The V2 dashboard feeds each widget from the SSE cache keyed by the publisher's
 * endpoint-function name. This pins the REST-endpoint → cache-key mapping for
 * all 13 streamed widgets — a mismatch would silently leave a widget stuck on
 * its loading state.
 */
describe('endpointToStreamKey', () => {
  // endpoint (REST route from the widget registry) → publisher cache key
  const cases: Array<[string, string]> = [
    ['/api/dashboard/system-health', 'system_health'],
    ['/api/dashboard/containers', 'containers'],
    ['/api/dashboard/tailscale', 'tailscale'],
    ['/api/dashboard/weather', 'weather'],
    ['/api/dashboard/news', 'news'],
    ['/api/dashboard/sports-scores', 'sports_scores'],
    ['/api/dashboard/api-spend', 'api_spend'],
    ['/api/dashboard/inventory', 'inventory'],
    ['/api/dashboard/knowledge', 'knowledge'],
    ['/api/dashboard/emails', 'emails'],
    ['/api/dashboard/finance/summary', 'finance_summary'],
    ['/api/dashboard/finance/balances', 'finance_balances'],
    ['/api/dashboard/finance/recent-transactions', 'finance_recent_transactions'],
  ]

  it.each(cases)('%s → %s', (endpoint, key) => {
    expect(endpointToStreamKey(endpoint)).toBe(key)
  })

  it('is idempotent on an already-bare key', () => {
    expect(endpointToStreamKey('finance_summary')).toBe('finance_summary')
  })
})
