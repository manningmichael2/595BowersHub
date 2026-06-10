import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuthStore } from '../stores/auth'

export interface UseDashboardWidgetOptions {
  endpoint: string           // e.g., '/api/dashboard/weather'
  pollingInterval?: number   // ms, default 60000
  timeout?: number           // ms, default 10000
}

export interface UseDashboardWidgetResult<T = any> {
  data: T | null
  error: string | null
  isLoading: boolean
  isStale: boolean
  lastFetched: Date | null
  refresh: () => void
}

function useDashboardWidget<T = any>(options: UseDashboardWidgetOptions): UseDashboardWidgetResult<T> {
  const { endpoint, pollingInterval = 60000, timeout = 10000 } = options

  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [isStale, setIsStale] = useState<boolean>(false)
  const [lastFetched, setLastFetched] = useState<Date | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const hasFetchedOnceRef = useRef<boolean>(false)

  const fetchData = useCallback(async (isInitial: boolean = false) => {
    // Only show loading spinner on the very first fetch
    if (isInitial && !hasFetchedOnceRef.current) {
      setIsLoading(true)
    }

    // Abort any in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    const controller = new AbortController()
    abortControllerRef.current = controller

    const timeoutId = setTimeout(() => controller.abort(), timeout)

    try {
      const token = useAuthStore.getState().accessToken
      const headers: Record<string, string> = {}
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
      }

      const response = await fetch(endpoint, {
        headers,
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const json = await response.json()

      setData(json)
      setError(null)
      setIsStale(false)
      setLastFetched(new Date())
      hasFetchedOnceRef.current = true
    } catch (err: any) {
      clearTimeout(timeoutId)

      // Don't update state if the abort was due to unmount/cleanup
      if (err.name === 'AbortError') {
        // If this was a timeout (not a cleanup abort), treat as failure
        if (!controller.signal.aborted || controller === abortControllerRef.current) {
          const errorMessage = 'Request timed out'
          if (hasFetchedOnceRef.current) {
            // Have cached data — mark as stale
            setIsStale(true)
            setError(errorMessage)
          } else {
            // No cached data — show error
            setError(errorMessage)
          }
        }
      } else {
        const errorMessage = err.message || 'Failed to fetch data'
        if (hasFetchedOnceRef.current) {
          // Have cached data — mark as stale, keep data
          setIsStale(true)
          setError(errorMessage)
        } else {
          // No cached data — show error
          setError(errorMessage)
          setData(null)
        }
      }
    } finally {
      if (isInitial) {
        setIsLoading(false)
      }
    }
  }, [endpoint, timeout])

  // Initial fetch + polling setup
  useEffect(() => {
    // Reset state on endpoint change
    hasFetchedOnceRef.current = false
    setData(null)
    setError(null)
    setIsStale(false)
    setLastFetched(null)
    setIsLoading(true)

    // Fetch immediately
    fetchData(true)

    // Set up polling interval
    intervalRef.current = setInterval(() => {
      fetchData(false)
    }, pollingInterval)

    // Cleanup on unmount or when deps change
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [endpoint, pollingInterval, fetchData])

  const refresh = useCallback(() => {
    fetchData(false)
  }, [fetchData])

  return { data, error, isLoading, isStale, lastFetched, refresh }
}

export default useDashboardWidget
export { useDashboardWidget }
