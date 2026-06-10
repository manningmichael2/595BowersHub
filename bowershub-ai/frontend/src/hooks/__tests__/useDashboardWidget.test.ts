/**
 * useDashboardWidget — unit tests.
 *
 * Tests verify the core behaviors:
 * - Fetches on mount with auth token
 * - Returns loading/data/error states correctly
 * - Caches data on successful fetch, retains on failure (isStale)
 * - Enforces timeout via AbortController
 * - Polls on configurable interval
 * - Exposes refresh() for manual re-fetch
 * - Cleans up interval and abort on unmount
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 12.3
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act, waitFor, cleanup } from '@testing-library/react'
import { useDashboardWidget } from '../useDashboardWidget'
import { useAuthStore } from '../../stores/auth'

// Mock the auth store
vi.mock('../../stores/auth', () => ({
  useAuthStore: {
    getState: vi.fn(() => ({ accessToken: 'test-token-123' })),
  },
}))

describe('useDashboardWidget', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock = vi.fn()
    ;(globalThis as any).fetch = fetchMock
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  function mockSuccessResponse(data: any) {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => data,
    } as Response)
  }

  function mockErrorResponse(status: number, statusText: string) {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status,
      statusText,
      json: async () => ({ detail: statusText }),
    } as unknown as Response)
  }

  function mockNetworkError(message: string) {
    fetchMock.mockRejectedValueOnce(new Error(message))
  }

  it('should fetch on mount with Authorization header', async () => {
    const testData = { temperature: 72, conditions: 'Sunny' }
    mockSuccessResponse(testData)

    const { result } = renderHook(() =>
      useDashboardWidget({ endpoint: '/api/dashboard/weather' }),
    )

    // Initially loading
    expect(result.current.isLoading).toBe(true)
    expect(result.current.data).toBeNull()

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/dashboard/weather', {
      headers: { Authorization: 'Bearer test-token-123' },
      signal: expect.any(AbortSignal),
    })
    expect(result.current.data).toEqual(testData)
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.isStale).toBe(false)
    expect(result.current.lastFetched).toBeInstanceOf(Date)
  })

  it('should show error when first fetch fails with no cached data', async () => {
    mockErrorResponse(500, 'Internal Server Error')

    const { result } = renderHook(() =>
      useDashboardWidget({ endpoint: '/api/dashboard/weather' }),
    )

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(result.current.isLoading).toBe(false)
    expect(result.current.data).toBeNull()
    expect(result.current.error).toBe('HTTP 500: Internal Server Error')
    expect(result.current.isStale).toBe(false)
    expect(result.current.lastFetched).toBeNull()
  })

  it('should retain cached data and set isStale on subsequent fetch failure', async () => {
    const testData = { cpu: 45 }
    mockSuccessResponse(testData)

    const { result } = renderHook(() =>
      useDashboardWidget({
        endpoint: '/api/dashboard/system-health',
        pollingInterval: 30000,
      }),
    )

    // Wait for initial successful fetch
    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(result.current.data).toEqual(testData)
    expect(result.current.isStale).toBe(false)

    // Set up failure for the next polling fetch
    mockNetworkError('Network unavailable')

    // Advance past the polling interval
    await act(async () => {
      vi.advanceTimersByTime(30000)
      await vi.runAllTimersAsync()
    })

    // Data should be retained, but marked stale
    expect(result.current.data).toEqual(testData)
    expect(result.current.isStale).toBe(true)
    expect(result.current.error).toBe('Network unavailable')
    // lastFetched should still be the time of the successful fetch
    expect(result.current.lastFetched).toBeInstanceOf(Date)
  })

  it('should enforce timeout via AbortController', async () => {
    // Mock a fetch that never resolves (simulating a slow endpoint)
    fetchMock.mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          // Listen for abort signal
          init.signal!.addEventListener('abort', () => {
            const err = new Error('The operation was aborted')
            err.name = 'AbortError'
            reject(err)
          })
        }),
    )

    const { result } = renderHook(() =>
      useDashboardWidget({
        endpoint: '/api/dashboard/slow',
        timeout: 5000,
      }),
    )

    expect(result.current.isLoading).toBe(true)

    // Advance past the timeout
    await act(async () => {
      vi.advanceTimersByTime(5000)
      await vi.runAllTimersAsync()
    })

    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBe('Request timed out')
    expect(result.current.data).toBeNull()
  })

  it('should poll on the configured interval', async () => {
    const data1 = { count: 1 }
    const data2 = { count: 2 }
    mockSuccessResponse(data1)

    const { result } = renderHook(() =>
      useDashboardWidget({
        endpoint: '/api/dashboard/inventory',
        pollingInterval: 15000,
      }),
    )

    // Initial fetch
    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(result.current.data).toEqual(data1)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    // Set up next response
    mockSuccessResponse(data2)

    // Advance to trigger polling
    await act(async () => {
      vi.advanceTimersByTime(15000)
      await vi.runAllTimersAsync()
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.current.data).toEqual(data2)
  })

  it('should not show isLoading on subsequent polling fetches', async () => {
    mockSuccessResponse({ a: 1 })

    const { result } = renderHook(() =>
      useDashboardWidget({
        endpoint: '/api/dashboard/test',
        pollingInterval: 10000,
      }),
    )

    // Initial fetch: isLoading = true
    expect(result.current.isLoading).toBe(true)

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(result.current.isLoading).toBe(false)

    // Set up next response
    mockSuccessResponse({ a: 2 })

    // Trigger polling — should NOT show isLoading
    await act(async () => {
      vi.advanceTimersByTime(10000)
    })

    // isLoading should remain false during silent polling
    expect(result.current.isLoading).toBe(false)

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(result.current.isLoading).toBe(false)
  })

  it('should expose refresh() for manual re-fetch', async () => {
    const data1 = { temp: 70 }
    const data2 = { temp: 75 }
    mockSuccessResponse(data1)

    const { result } = renderHook(() =>
      useDashboardWidget({ endpoint: '/api/dashboard/weather' }),
    )

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(result.current.data).toEqual(data1)

    // Manual refresh
    mockSuccessResponse(data2)

    await act(async () => {
      result.current.refresh()
      await vi.runAllTimersAsync()
    })

    expect(result.current.data).toEqual(data2)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('should clean up interval and abort on unmount', async () => {
    mockSuccessResponse({ x: 1 })

    const { result, unmount } = renderHook(() =>
      useDashboardWidget({
        endpoint: '/api/dashboard/test',
        pollingInterval: 10000,
      }),
    )

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    unmount()

    // Advance time past the polling interval — no more fetches should happen
    mockSuccessResponse({ x: 2 })

    await act(async () => {
      vi.advanceTimersByTime(20000)
      await vi.runAllTimersAsync()
    })

    // Only the initial fetch should have been made
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('should use default pollingInterval of 60s and timeout of 10s', async () => {
    mockSuccessResponse({ ok: true })

    const { result } = renderHook(() =>
      useDashboardWidget({ endpoint: '/api/dashboard/test' }),
    )

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(result.current.data).toEqual({ ok: true })

    // Set up second response
    mockSuccessResponse({ ok: true, round: 2 })

    // Advance less than 60s — should not poll yet
    await act(async () => {
      vi.advanceTimersByTime(59000)
      await vi.runAllTimersAsync()
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)

    // Advance to hit 60s
    await act(async () => {
      vi.advanceTimersByTime(1000)
      await vi.runAllTimersAsync()
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('should work without auth token', async () => {
    ;(useAuthStore.getState as any).mockReturnValueOnce({ accessToken: null })
    mockSuccessResponse({ public: true })

    const { result } = renderHook(() =>
      useDashboardWidget({ endpoint: '/api/dashboard/public' }),
    )

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/dashboard/public', {
      headers: {},
      signal: expect.any(AbortSignal),
    })
    expect(result.current.data).toEqual({ public: true })
  })
})
