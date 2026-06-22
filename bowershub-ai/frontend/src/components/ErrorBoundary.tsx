import React from 'react'
import { reportClientError } from '../lib/reportError'

interface Props {
  children: React.ReactNode
}

interface State {
  hasError: boolean
  error?: Error
}

/**
 * Top-level error boundary. Without this, any uncaught render error
 * white-screens the entire app. Catches the throw, logs it, and shows a
 * recoverable fallback instead of a blank page.
 */
export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Uncaught render error:', error, info.componentStack)
    reportClientError({
      message: error.message || 'Render error',
      stack: error.stack || info.componentStack || undefined,
    })
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <div className="min-h-screen flex items-center justify-center bg-neutral-950 text-neutral-100 p-6">
        <div className="max-w-md w-full text-center space-y-4">
          <h1 className="text-xl font-semibold">Something went wrong</h1>
          <p className="text-sm text-neutral-400">
            The app hit an unexpected error. Reloading usually fixes it.
          </p>
          {this.state.error?.message && (
            <pre className="text-xs text-left text-red-400 bg-neutral-900 rounded p-3 overflow-auto max-h-40">
              {this.state.error.message}
            </pre>
          )}
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}
