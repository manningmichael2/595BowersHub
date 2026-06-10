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
    <div className="min-h-screen bg-[#1a1a2e] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-white mb-2">Reset Password</h1>
          <p className="text-gray-400 text-sm">Enter your email and we'll send a reset link.</p>
        </div>

        {sent ? (
          <div className="bg-green-900/30 border border-green-800 rounded-lg px-4 py-4 text-sm text-green-300 text-center">
            <p className="font-medium">Check your email</p>
            <p className="text-green-400 mt-1">If that email is registered, you'll receive a reset link shortly.</p>
            <a href="/login" className="inline-block mt-4 text-indigo-400 hover:text-indigo-300 text-sm">
              ← Back to login
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
              <label className="block text-sm text-gray-400 mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-[#0f0f1a] border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 text-sm focus:outline-none focus:border-indigo-500"
                placeholder="you@example.com"
                required
                autoFocus
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
            >
              {loading ? 'Sending...' : 'Send Reset Link'}
            </button>

            <p className="text-center text-xs text-gray-600 mt-4">
              <a href="/login" className="text-indigo-400 hover:text-indigo-300">← Back to login</a>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
