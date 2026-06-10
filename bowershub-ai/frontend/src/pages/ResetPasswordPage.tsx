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
      <div className="min-h-screen bg-[#1a1a2e] flex items-center justify-center px-4">
        <div className="text-center">
          <p className="text-red-400 mb-4">Invalid reset link — no token in URL.</p>
          <a href="/forgot-password" className="text-indigo-400 hover:text-indigo-300 text-sm">
            Request a new reset link
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#1a1a2e] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-white mb-2">Set New Password</h1>
          <p className="text-gray-400 text-sm">Choose a new password for your account.</p>
        </div>

        {done ? (
          <div className="bg-green-900/30 border border-green-800 rounded-lg px-4 py-4 text-sm text-green-300 text-center">
            <p className="font-medium">Password reset ✓</p>
            <p className="text-green-400 mt-1">You can now log in with your new password.</p>
            <a href="/login" className="inline-block mt-4 bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm">
              Go to Login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-2 text-sm text-red-300">
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm text-gray-400 mb-1">New Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-[#0f0f1a] border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 text-sm focus:outline-none focus:border-indigo-500"
                placeholder="At least 8 characters"
                required
                minLength={8}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">Confirm Password</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="w-full bg-[#0f0f1a] border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 text-sm focus:outline-none focus:border-indigo-500"
                placeholder="Type it again"
                required
                minLength={8}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
            >
              {loading ? 'Resetting...' : 'Reset Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
