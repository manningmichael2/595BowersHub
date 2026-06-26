import { useState, FormEvent } from 'react'
import { useAuthStore } from '../stores/auth'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { login, isLoading, error, clearError } = useAuthStore()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await login(email, password)
    } catch {}
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-text mb-2">BowersHub AI</h1>
          <p className="text-text-muted text-sm">Personal AI Assistant</p>
        </div>

        {/* Login form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger/40 rounded-lg px-4 py-2 text-sm text-danger">
              {error}
              <button onClick={clearError} className="float-right text-danger hover:brightness-125">×</button>
            </div>
          )}

          <div>
            <label className="block text-sm text-text-muted mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-text text-sm focus:outline-none focus:border-primary transition-colors"
              placeholder="you@example.com"
              required
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm text-text-muted mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-text text-sm focus:outline-none focus:border-primary transition-colors"
              placeholder="••••••••"
              required
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-primary hover:brightness-110 disabled:opacity-50 text-on-primary font-medium py-2.5 rounded-lg transition-[filter] text-sm"
          >
            {isLoading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="text-center text-xs text-text-muted mt-6">
          Need an account? Ask your admin for an invite link.
        </p>
        <p className="text-center text-xs mt-2">
          <a href="/forgot-password" className="text-primary hover:brightness-125">Forgot password?</a>
        </p>
      </div>
    </div>
  )
}
