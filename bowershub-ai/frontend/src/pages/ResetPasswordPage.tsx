import { useState, FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../services/api'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirm) {
      setError('Passwords don\'t match')
      return
    }
    if (!token) {
      setError('Invalid reset link — no token found')
      return
    }

    setLoading(true)
    try {
      await api.post('/api/auth/reset-password', { token, new_password: password })
      setDone(true)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Reset failed — link may be expired')
    }
    setLoading(false)
  }

  if (!token) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center">
          <p className="text-danger mb-4">Invalid reset link — no token in URL.</p>
          <a href="/forgot-password" className="text-primary hover:brightness-125 text-sm">
            Request a new reset link
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-text mb-2">Set New Password</h1>
          <p className="text-text-muted text-sm">Choose a new password for your account.</p>
        </div>

        {done ? (
          <div className="bg-success/10 border border-success/40 rounded-lg px-4 py-4 text-sm text-success text-center">
            <p className="font-medium">Password reset ✓</p>
            <p className="mt-1 opacity-90">You can now log in with your new password.</p>
            <a href="/login" className="inline-block mt-4 bg-primary hover:brightness-110 text-on-primary px-4 py-2 rounded-lg text-sm transition-[filter]">
              Go to Login
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
              <label className="block text-sm text-text-muted mb-1">New Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-text text-sm focus:outline-none focus:border-primary transition-colors"
                placeholder="At least 8 characters"
                required
                minLength={8}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-sm text-text-muted mb-1">Confirm Password</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-text text-sm focus:outline-none focus:border-primary transition-colors"
                placeholder="Type it again"
                required
                minLength={8}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:brightness-110 disabled:opacity-50 text-on-primary font-medium py-2.5 rounded-lg transition-[filter] text-sm"
            >
              {loading ? 'Resetting...' : 'Reset Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
