/**
 * Property 1: Widget rendering matches registry
 * Feature: dashboard-integration, Property 1: Widget rendering matches registry
 *
 * Validates: Requirements 2.3, 2.4
 *
 * For any set of widget_keys returned by the backend widget registry, the dashboard
 * SHALL render a widget if and only if that widget_key has a corresponding entry in
 * the client-side component map. Unknown keys are silently skipped without errors.
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { getWidgetComponent } from '../components/dashboard/WidgetRegistry'

/** The 12 known widget keys that have corresponding React components */
const KNOWN_KEYS = [
  'weather',
  'finance_summary',
  'finance_balances',
  'recent_transactions',
  'system_health',
  'containers',
  'inventory',
  'knowledge_base',
  'recent_emails',
  'tailscale_devices',
  'api_spend',
  'sports_scores',
] as const

describe('Feature: dashboard-integration, Property 1: Widget rendering matches registry', () => {
  describe('unit tests: getWidgetComponent for known keys', () => {
    it.each(KNOWN_KEYS)('returns a defined WidgetDefinition for known key "%s"', (key) => {
      const result = getWidgetComponent(key)
      expect(result).toBeDefined()
      expect(result).toHaveProperty('component')
    })
  })

  describe('unit tests: getWidgetComponent for unknown keys', () => {
    it('returns undefined for an empty string', () => {
      expect(getWidgetComponent('')).toBeUndefined()
    })

    it('returns undefined for a random unknown key', () => {
      expect(getWidgetComponent('nonexistent_widget_xyz')).toBeUndefined()
    })

    it('returns undefined for a key with wrong casing', () => {
      expect(getWidgetComponent('Weather')).toBeUndefined()
      expect(getWidgetComponent('WEATHER')).toBeUndefined()
    })
  })

  describe('property test: widget rendering matches registry', () => {
    /**
     * Arbitrary that generates random sets of widget_keys: a mix of known keys
     * (sampled from the 12 real ones) and unknown random strings.
     */
    const widgetKeySetArb: fc.Arbitrary<string[]> = fc
      .tuple(
        // Sample some known keys (0 to 12)
        fc.subarray([...KNOWN_KEYS], { minLength: 0 }),
        // Generate some unknown random strings (0 to 10)
        fc.array(
          fc.stringMatching(/^[a-z][a-z0-9_]{2,20}$/).filter(
            (s) => !(KNOWN_KEYS as readonly string[]).includes(s)
          ),
          { minLength: 0, maxLength: 10 }
        )
      )
      .map(([known, unknown]) => [...known, ...unknown])

    it('getWidgetComponent returns a definition iff the key is in the known set (property-based)', () => {
      fc.assert(
        fc.property(widgetKeySetArb, (keys) => {
          for (const key of keys) {
            const result = getWidgetComponent(key)
            const isKnown = (KNOWN_KEYS as readonly string[]).includes(key)

            if (isKnown) {
              // Known keys MUST return a WidgetDefinition with a component
              expect(result).toBeDefined()
              expect(result).toHaveProperty('component')
            } else {
              // Unknown keys MUST return undefined (silently skipped)
              expect(result).toBeUndefined()
            }
          }
        }),
        { numRuns: 100 }
      )
    })

    it('getWidgetComponent never throws regardless of input (property-based)', () => {
      fc.assert(
        fc.property(fc.string(), (key) => {
          // The function should NEVER throw, regardless of what string is passed
          expect(() => getWidgetComponent(key)).not.toThrow()
        }),
        { numRuns: 100 }
      )
    })
  })
})
