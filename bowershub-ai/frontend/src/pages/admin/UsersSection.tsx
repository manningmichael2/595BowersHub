import { useState } from 'react'
import { api } from '../../services/api'
import { toast } from '../../stores/toast'
import { useEndpointData, SectionStateGuard } from './AdminCommon'

const ROLES = ['admin', 'member', 'viewer']

interface UserWorkspace {
  id: number
  name: string
  icon: string | null
  member: boolean
  role: string | null
}

export default function UsersSection() {
  const { data, isLoading, error, reload } = useEndpointData<any[]>('/api/admin/users')
  const [showInvite, setShowInvite] = useState(false)
  const [inviteUrl, setInviteUrl] = useState<string | null>(null)
  const [role, setRole] = useState('member')
  const [savingId, setSavingId] = useState<number | null>(null)

  // Per-user workspace management: which user's panel is open + its workspace list.
  const [wsUserId, setWsUserId] = useState<number | null>(null)
  const [wsList, setWsList] = useState<UserWorkspace[]>([])
  const [wsBusy, setWsBusy] = useState(false)

  const openWorkspaces = async (userId: number) => {
    if (wsUserId === userId) { setWsUserId(null); return }
    setWsUserId(userId)
    setWsList([])
    setWsBusy(true)
    try {
      const res = await api.get(`/api/admin/users/${userId}/workspaces`)
      setWsList(res.data)
    } catch (err: any) {
      toast.error('Failed to load workspaces: ' + (err.response?.data?.detail || 'Unknown error'))
      setWsUserId(null)
    } finally {
      setWsBusy(false)
    }
  }

  // Toggle a user's membership in one workspace, optimistically reflecting the change.
  const toggleWorkspace = async (userId: number, ws: UserWorkspace) => {
    setWsBusy(true)
    try {
      if (ws.member) {
        await api.delete(`/api/admin/users/${userId}/workspaces/${ws.id}`)
      } else {
        await api.put(`/api/admin/users/${userId}/workspaces/${ws.id}`, { role: 'member' })
      }
      setWsList(list => list.map(w =>
        w.id === ws.id ? { ...w, member: !w.member, role: w.member ? null : 'member' } : w))
    } catch (err: any) {
      toast.error('Failed to update workspace: ' + (err.response?.data?.detail || 'Unknown error'))
    } finally {
      setWsBusy(false)
    }
  }

  const createInvite = async () => {
    try {
      const res = await api.post('/api/auth/invite', { role })
      setInviteUrl(res.data.invite_url)
    } catch (err: any) {
      alert('Failed to create invite: ' + (err.response?.data?.detail || 'Unknown error'))
    }
  }

  // PATCH a user's role or active status. Surfaces the last-admin 409 (R2.1a) as
  // a clear toast rather than a silent failure; reloads on success.
  const patchUser = async (userId: number, patch: { role?: string; is_active?: boolean }) => {
    setSavingId(userId)
    try {
      await api.patch(`/api/admin/users/${userId}`, patch)
      await reload()
    } catch (err: any) {
      const detail = err.response?.data?.detail
      toast.error(
        err.response?.status === 409
          ? (detail || 'Cannot remove the last active admin')
          : `Failed to update user: ${detail || 'Unknown error'}`,
      )
    } finally {
      setSavingId(null)
    }
  }

  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-medium">Users ({data.length})</h2>
            <button
              onClick={() => {
                setShowInvite(true)
                setInviteUrl(null)
              }}
              className="px-3 py-1.5 rounded-lg bg-primary text-sm text-on-primary hover:bg-primary/90"
            >
              + Invite User
            </button>
          </div>

          {showInvite && (
            <div className="bg-background rounded-lg border border-border p-4 mb-4">
              <h3 className="font-medium mb-3">Create Invite Link</h3>
              {!inviteUrl ? (
                <div className="flex items-center gap-3">
                  <select
                    value={role}
                    onChange={e => setRole(e.target.value)}
                    className="bg-surface border border-border rounded px-3 py-1.5 text-sm"
                  >
                    <option value="admin">Admin</option>
                    <option value="member">Member</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <button
                    onClick={createInvite}
                    className="px-3 py-1.5 rounded bg-primary text-sm hover:bg-primary/90"
                  >
                    Generate Link
                  </button>
                  <button
                    onClick={() => setShowInvite(false)}
                    className="px-3 py-1.5 rounded bg-surface-light text-sm hover:bg-surface-light"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-text-muted mb-2">
                    Share this link (expires in 72 hours):
                  </p>
                  <div className="flex gap-2">
                    <input
                      readOnly
                      value={inviteUrl}
                      className="flex-1 bg-surface border border-border rounded px-3 py-1.5 text-sm font-mono"
                      onClick={e => (e.target as HTMLInputElement).select()}
                    />
                    <button
                      onClick={() => navigator.clipboard.writeText(inviteUrl)}
                      className="px-3 py-1.5 rounded bg-surface-light text-sm hover:bg-surface-light"
                    >
                      Copy
                    </button>
                    <button
                      onClick={() => {
                        setShowInvite(false)
                        setInviteUrl(null)
                        reload()
                      }}
                      className="px-3 py-1.5 rounded bg-surface-light text-sm hover:bg-surface-light"
                    >
                      Done
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="bg-background rounded-lg border border-border overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Email</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Name</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Role</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Status</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Last Login</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Workspaces</th>
                </tr>
              </thead>
              <tbody>
                {data.map((u: any) => (
                  <tr key={u.id} className="border-b border-border/50 hover:bg-surface-light/30">
                    <td className="px-4 py-3 text-text-muted">{u.email}</td>
                    <td className="px-4 py-3 text-text-muted">{u.display_name}</td>
                    <td className="px-4 py-3">
                      <select
                        aria-label={`Role for ${u.email}`}
                        value={u.role}
                        disabled={savingId === u.id}
                        onChange={e => patchUser(u.id, { role: e.target.value })}
                        className="bg-surface border border-border rounded px-2 py-1 text-xs disabled:opacity-50"
                      >
                        {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        disabled={savingId === u.id}
                        onClick={() => patchUser(u.id, { is_active: !u.is_active })}
                        title={u.is_active ? 'Deactivate user' : 'Reactivate user'}
                        className={`text-xs px-2 py-0.5 rounded border disabled:opacity-50 ${
                          u.is_active
                            ? 'text-success border-success hover:bg-success/90/30'
                            : 'text-danger border-danger hover:bg-danger/90/30'
                        }`}
                      >
                        {u.is_active ? 'Active' : 'Inactive'}
                      </button>
                    </td>
                    <td className="px-4 py-3 text-text-muted text-xs">
                      {u.last_login_at
                        ? new Date(u.last_login_at).toLocaleDateString()
                        : 'Never'}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openWorkspaces(u.id)}
                        aria-expanded={wsUserId === u.id}
                        className="text-xs px-2 py-0.5 rounded border border-border text-text-muted hover:bg-surface-light/50"
                      >
                        {wsUserId === u.id ? 'Hide' : 'Manage'}
                      </button>
                    </td>
                  </tr>
                ))}
                {wsUserId !== null && data.some((u: any) => u.id === wsUserId) && (
                  <tr className="border-b border-border/50 bg-surface-light/20">
                    <td colSpan={6} className="px-4 py-3">
                      <div className="text-xs text-text-muted mb-2">
                        Shared workspaces for{' '}
                        <span className="text-text font-medium">
                          {data.find((u: any) => u.id === wsUserId)?.display_name}
                        </span>
                      </div>
                      {wsBusy && wsList.length === 0 ? (
                        <div className="text-xs text-text-muted">Loading…</div>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {wsList.map(ws => (
                            <label
                              key={ws.id}
                              className="flex items-center gap-2 px-2 py-1 rounded border border-border bg-surface text-xs cursor-pointer hover:bg-surface-light/50"
                            >
                              <input
                                type="checkbox"
                                checked={ws.member}
                                disabled={wsBusy}
                                onChange={() => toggleWorkspace(wsUserId, ws)}
                              />
                              <span>{ws.icon} {ws.name}</span>
                            </label>
                          ))}
                          {wsList.length === 0 && (
                            <span className="text-xs text-text-muted">No workspaces exist yet.</span>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </SectionStateGuard>
  )
}
