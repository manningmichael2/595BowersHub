/**
 * Feature: dashboard-integration, Property 4: Stale data caching on failure
 *
 * Validates: Requirements 6.2
 *
 * For any widget that has previously fetched data successfully, if the next
 * fetch attempt fails, the widget SHALL display the previously cached data
 * and mark itself as stale with the timestamp of the last successful fetch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor, cleanup } from '@testing-library/react'
import * as fc from 'fast-check'
import { useDashboardWidget } from '../hooks/useDashboardWidget'

// Mock the auth store
vi.mock('../stores/auth', () => ({
  useAuthStore: {
    getState: () => ({ accessToken: 'test-token' }),
  },
}))

describe('Feature: dashboard-integration, Property 4: Stale data caching on failure', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('should retain cached data and mark stale when fetch fails after a successful fetch', async () => {
    const POLLING_INTERVAL = 60000

    // Arbitrary to generate error types
    const errorTypeArb = fc.oneof(
      fc.constant({ type: 'network' as const, status: 0, statusText: '' }),
      fc.record({
        type: fc.constant('http' as const),
        status: fc.integer({ min: 400, max: 599 }),
        statusText: fc.constantFrom('Bad Request', 'Unauthorized', 'Forbidden', 'Not Found', 'Internal Server Error', 'Service Unavailable'),
      }),
      fc.constant({ type: 'timeout' as const, status: 0, statusText: '' })
    )

    await fc.assert(
      fc.asyncProperty(
        fc.jsonValue().filter((v) => v !== null && typeof v === 'object'),
        errorTypeArb,
        async (successData, errorType) => {
          // Clean up any previous renders
          cleanup()
          vi.clearAllTimers()
          vi.restoreAllMocks()
          vi.useFakeTimers()

          const mockFetch = vi.fn()
          vi.stubGlobal('fetch', mockFetch)

          // Step a: Mock fetch to return the generated data (success)
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => successData,
          })

          // Step b: Render the useDashboardWidget hook
          const { result, unmount } = renderHook(() =>
            useDashboardWidget({
              endpoint: '/api/dashboard/test-widget',
              pollingInterval: POLLING_INTERVAL,
              timeout: 10000,
            })
          )

          // Step c: Wait for the initial successful fetch to complete
          await act(async () => {
            // Flush promises for the fetch to resolve
            await vi.advanceTimersByTimeAsync(1)
          })

          // Verify initial successful state
          expect(result.current.data).toEqual(successData)
          expect(result.current.isStale).toBe(false)
          expect(result.current.error).toBeNull()
          expect(result.current.lastFetched).toBeInstanceOf(Date)

          // Capture the timestamp of the successful fetch
          const successTimestamp = result.current.lastFetched!.getTime()

          // Step d: Mock fetch to fail with the generated error type
          if (errorType.type === 'network') {
            mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))
          } else if (errorType.type === 'http') {
            mockFetch.mockResolvedValueOnce({
              ok: false,
              status: errorType.status,
              statusText: errorType.statusText,
            })
          } else {
            // timeout - mock fetch that hangs until aborted
            mockFetch.mockImplementationOnce(
              (_url: string, options?: { signal?: AbortSignal }) => {
                return new Promise((_, reject) => {
                  if (options?.signal) {
                    const onAbort = () => {
                      const err = new DOMException('The operation was aborted.', 'AbortError')
                      reject(err)
                    }
                    if (options.signal.aborted) {
                      onAbort()
                    } else {
                      options.signal.addEventListener('abort', onAbort)
                    }
                  }
                })
              }
            )
          }

          // Step e: Trigger a re-fetch by advancing timers past polling interval
          await act(async () => {
            await vi.advanceTimersByTimeAsync(POLLING_INTERVAL)
          })

          // For timeout errors, advance past the timeout threshold
          if (errorType.type === 'timeout') {
            await act(async () => {
              await vi.advanceTimersByTimeAsync(10001)
            })
          }

          // Flush remaining microtasks
          await act(async () => {
            await vi.advanceTimersByTimeAsync(1)
          })

          // Step f: Assert data still equals the original successful response
          expect(result.current.data).toEqual(successData)

          // Step g: Assert isStale is true
          expect(result.current.isStale).toBe(true)

          // Step h: Assert lastFetched is the timestamp of the successful fetch
          expect(result.current.lastFetched).toBeInstanceOf(Date)
          expect(result.current.lastFetched!.getTime()).toBe(successTimestamp)

          // Step i: Assert error contains a message about the failure
          expect(result.current.error).not.toBeNull()
          expect(typeof result.current.error).toBe('string')
          expect(result.current.error!.length).toBeGreaterThan(0)

          // Clean up this iteration
          unmount()
        }
      ),
      { numRuns: 100 }
    )
  }, 120000) // 2 minute timeout for 100 property runs
})
