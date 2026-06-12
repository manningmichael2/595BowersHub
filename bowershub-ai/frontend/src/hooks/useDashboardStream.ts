import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuthStore } from '../stores/auth'

export function useDashboardStream() {
  const [isConnected, setIsConnected] = useState(false)
  const [widgetData, setWidgetData] = useState<Record<string, any>>({})
  const abortControllerRef = useRef<AbortController | null>(null)

  const connect = useCallback(async () => {
    if (abortControllerRef.current) return // Already connecting/connected

    const token = useAuthStore.getState().accessToken
    if (!token) return

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const response = await fetch('/api/dashboard/stream', {
        headers: {
          'Authorization': `Bearer ${token}`
        },
        signal: controller.signal
      })

      if (!response.ok || !response.body) {
        throw new Error('Failed to connect to SSE stream')
      }

      setIsConnected(true)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        
        // Keep the last partial chunk in the buffer
        buffer = lines.pop() || ''

        for (const chunk of lines) {
          if (chunk.startsWith('data: ')) {
            const jsonStr = chunk.substring(6)
            try {
              const payload = JSON.parse(jsonStr)
              if (payload.type === 'hydration' || payload.type === 'update') {
                setWidgetData(payload.state)
              }
            } catch (e) {
              console.error('Failed to parse SSE payload', e)
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        console.error('Dashboard SSE stream error:', err)
      }
    } finally {
      setIsConnected(false)
      abortControllerRef.current = null
    }
  }, [])

  const disconnect = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setIsConnected(false)
  }, [])

  useEffect(() => {
    // Initial connection
    connect()

    // Handle visibility changes for mobile resilience
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        connect()
      } else {
        disconnect()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      disconnect()
    }
  }, [connect, disconnect])

  return { isConnected, widgetData }
}
