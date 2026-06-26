import { useState, FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../stores/auth'

export default function RegisterPage() {
  const [searchParams] = useSearchParams()
  const inviteToken = searchParams.get('token') || ''

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const { register, isLoading, error, clearError } = useAuthStore()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await register(email, password, displayName, inviteToken)
    } catch {}
  }

  if (!inviteToken) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-text mb-2">Invalid Invite</h1>
          <p className="text-text-muted">You need a valid invite link to register.</p>
          <a href="/login" className="text-primary text-sm mt-4 inline-block hover:underline">
            Back to login
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-text mb-2">Join BowersHub AI</h1>
          <p className="text-text-muted text-sm">Create your account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger/40 rounded-lg px-4 py-2 text-sm text-danger">
              {error}
              <button onClick={clearError} className="float-right text-danger hover:brightness-125">×</button>
            </div>
          )}

          <div>
            <label className="block text-sm text-text-muted mb-1">Display Name</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-text text-sm focus:outline-none focus:border-primary transition-colors"
              placeholder="Your name"
              required
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm text-text-muted mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-text text-sm focus:outline-none focus:border-primary transition-colors"
              placeholder="you@example.com"
              required
            />
          </div>

          <div>
            <label className="block text-sm text-text-muted mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-text text-sm focus:outline-none focus:border-primary transition-colors"
              placeholder="Min 8 characters"
              required
              minLength={8}
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-primary hover:brightness-110 disabled:opacity-50 text-on-primary font-medium py-2.5 rounded-lg transition-[filter] text-sm"
          >
            {isLoading ? 'Creating account...' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  )
}
