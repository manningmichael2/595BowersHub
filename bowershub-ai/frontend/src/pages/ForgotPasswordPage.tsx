import { useState, FormEvent } from 'react'
import { api } from '../services/api'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post('/api/auth/request-password-reset', { email })
      setSent(true)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Something went wrong')
    }
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-text mb-2">Reset Password</h1>
          <p className="text-text-muted text-sm">Enter your email and we'll send a reset link.</p>
        </div>

        {sent ? (
          <div className="bg-success/10 border border-success/40 rounded-lg px-4 py-4 text-sm text-success text-center">
            <p className="font-medium">Check your email</p>
            <p className="mt-1 opacity-90">If that email is registered, you'll receive a reset link shortly.</p>
            <a href="/login" className="inline-block mt-4 text-primary hover:brightness-125 text-sm">
              ← Back to login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="bg-danger/10 border border-danger/40 rounded-lg px-4 py-2 text-sm text-danger">
                {error}
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

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:brightness-110 disabled:opacity-50 text-on-primary font-medium py-2.5 rounded-lg transition-[filter] text-sm"
            >
              {loading ? 'Sending...' : 'Send Reset Link'}
            </button>

            <p className="text-center text-xs text-text-muted mt-4">
              <a href="/login" className="text-primary hover:brightness-125">← Back to login</a>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
