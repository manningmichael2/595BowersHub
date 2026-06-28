import { useEffect, useState } from 'react'
import { api } from '../../services/api'

// ---- Generic data-loading wrapper ----------------------------------------

export function useEndpointData<T = any>(path: string, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.get(path)
      setData(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load')
      setData(null)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, isLoading, error, reload }
}

export function SectionStateGuard({
  isLoading,
  error,
  children,
}: {
  isLoading: boolean
  error: string | null
  children: React.ReactNode
}) {
  if (isLoading) {
    return <div className="text-center text-text-muted py-12">Loading...</div>
  }
  if (error) {
    return (
      <div className="bg-danger/30 border border-danger rounded-lg px-4 py-3 text-sm text-danger">
        Error: {error}
      </div>
    )
  }
  return <>{children}</>
}
