/**
 * Property 3: Widget failure independence
 * Feature: dashboard-integration, Property 3: Widget failure independence
 *
 * Validates: Requirements 6.1
 *
 * For any set of dashboard widgets being rendered, if one widget's data fetch
 * fails (timeout, HTTP error, or exception), all other widgets on the same
 * page SHALL continue to render their data unaffected.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import * as fc from 'fast-check'
import { useDashboardWidget } from '../hooks/useDashboardWidget'

// Mock the auth store so the hook doesn't try to read real auth state
vi.mock('../stores/auth', () => ({
  useAuthStore: {
    getState: () => ({ accessToken: 'test-token' }),
  },
}))

/** Failure modes that a widget fetch can encounter */
type FailureMode = 'http-error' | 'network-error'

interface WidgetScenario {
  endpoint: string
  shouldFail: boolean
  failureMode: FailureMode
  expectedData: Record<string, unknown>
}

/**
 * Arbitrary that generates a set of 3-8 widget scenarios where at least one
 * widget fails and at least one succeeds.
 */
const widgetScenariosArb: fc.Arbitrary<WidgetScenario[]> = fc
  .integer({ min: 3, max: 8 })
  .chain((count) =>
    fc.tuple(
      // Generate unique endpoint paths
      fc.uniqueArray(
        fc.stringMatching(/^\/api\/dashboard\/[a-z]{3,10}$/),
        { minLength: count, maxLength: count }
      ),
      // Generate data payloads for successful widgets
      fc.array(
        fc.dictionary(
          fc.stringMatching(/^[a-z_]{2,8}$/),
          fc.oneof(fc.integer({ min: 0, max: 1000 }), fc.constant('value'), fc.boolean())
        ),
        { minLength: count, maxLength: count }
      ),
      // Randomly select which widgets should fail (at least 1 fail, at least 1 success)
      fc.array(fc.boolean(), { minLength: count, maxLength: count }).filter(
        (bools) => bools.some((b) => b) && bools.some((b) => !b)
      ),
      // Pick failure modes for each
      fc.array(
        fc.constantFrom<FailureMode>('http-error', 'network-error'),
        { minLength: count, maxLength: count }
      )
    )
  )
  .map(([endpoints, dataPayloads, failures, failureModes]) =>
    endpoints.map((endpoint, i): WidgetScenario => ({
      endpoint,
      shouldFail: failures[i],
      failureMode: failureModes[i],
      expectedData: dataPayloads[i],
    }))
  )

describe('Feature: dashboard-integration, Property 3: Widget failure independence', () => {
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('succeeding widgets retain their data when other widgets fail (property-based)', async () => {
    await fc.assert(
      fc.asyncProperty(widgetScenariosArb, async (scenarios) => {
        // Configure fetch mock based on each widget's scenario
        globalThis.fetch = vi.fn((url: string | URL | Request, _options?: RequestInit) => {
          const urlStr = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url
          const scenario = scenarios.find((s) => s.endpoint === urlStr)

          if (!scenario || !scenario.shouldFail) {
            // Successful response
            const data = scenario ? scenario.expectedData : {}
            return Promise.resolve(
              new Response(JSON.stringify(data), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
              })
            )
          }

          // Apply the failure mode
          switch (scenario.failureMode) {
            case 'http-error':
              return Promise.resolve(
                new Response('Internal Server Error', {
                  status: 500,
                  statusText: 'Internal Server Error',
                })
              )
            case 'network-error':
              return Promise.reject(new TypeError('Failed to fetch'))
          }
        }) as typeof globalThis.fetch

        // Render hooks for all widgets concurrently
        const hookResults = scenarios.map((scenario) =>
          renderHook(() =>
            useDashboardWidget({
              endpoint: scenario.endpoint,
              pollingInterval: 600000, // Very long to avoid re-fetch
              timeout: 5000, // Won't trigger since our mocks resolve immediately
            })
          )
        )

        // Wait for all hooks to finish loading
        await waitFor(
          () => {
            for (const result of hookResults) {
              expect(result.result.current.isLoading).toBe(false)
            }
          },
          { timeout: 3000 }
        )

        // Assert: each widget's state is independent
        for (let i = 0; i < scenarios.length; i++) {
          const scenario = scenarios[i]
          const hookResult = hookResults[i].result.current

          if (!scenario.shouldFail) {
            // Successful widgets must have their data intact and no error
            expect(hookResult.data).toEqual(scenario.expectedData)
            expect(hookResult.error).toBeNull()
          } else {
            // Failed widgets should have an error
            expect(hookResult.error).not.toBeNull()
            // Data should be null since there's no cached value (first fetch)
            expect(hookResult.data).toBeNull()
          }
        }

        // Cleanup
        hookResults.forEach((result) => result.unmount())
      }),
      { numRuns: 100 }
    )
  }, 60000) // 60s timeout for the full PBT run
})
