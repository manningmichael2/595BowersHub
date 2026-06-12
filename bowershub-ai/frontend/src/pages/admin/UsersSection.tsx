import { useState } from 'react'
import { api } from '../../services/api'
import { useEndpointData, SectionStateGuard } from './AdminCommon'

export default function UsersSection() {
  const { data, isLoading, error, reload } = useEndpointData<any[]>('/api/admin/users')
  const [showInvite, setShowInvite] = useState(false)
  const [inviteUrl, setInviteUrl] = useState<string | null>(null)
  const [role, setRole] = useState('member')

  const createInvite = async () => {
    try {
      const res = await api.post('/api/auth/invite', { role })
      setInviteUrl(res.data.invite_url)
    } catch (err: any) {
      alert('Failed to create invite: ' + (err.response?.data?.detail || 'Unknown error'))
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
              className="px-3 py-1.5 rounded-lg bg-indigo-600 text-sm text-white hover:bg-indigo-500"
            >
              + Invite User
            </button>
          </div>

          {showInvite && (
            <div className="bg-[#0f0f1a] rounded-lg border border-gray-700 p-4 mb-4">
              <h3 className="font-medium mb-3">Create Invite Link</h3>
              {!inviteUrl ? (
                <div className="flex items-center gap-3">
                  <select
                    value={role}
                    onChange={e => setRole(e.target.value)}
                    className="bg-[#1a1a2e] border border-gray-700 rounded px-3 py-1.5 text-sm"
                  >
                    <option value="admin">Admin</option>
                    <option value="member">Member</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <button
                    onClick={createInvite}
                    className="px-3 py-1.5 rounded bg-indigo-600 text-sm hover:bg-indigo-500"
                  >
                    Generate Link
                  </button>
                  <button
                    onClick={() => setShowInvite(false)}
                    className="px-3 py-1.5 rounded bg-gray-700 text-sm hover:bg-gray-600"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-gray-400 mb-2">
                    Share this link (expires in 72 hours):
                  </p>
                  <div className="flex gap-2">
                    <input
                      readOnly
                      value={inviteUrl}
                      className="flex-1 bg-[#1a1a2e] border border-gray-700 rounded px-3 py-1.5 text-sm font-mono"
                      onClick={e => (e.target as HTMLInputElement).select()}
                    />
                    <button
                      onClick={() => navigator.clipboard.writeText(inviteUrl)}
                      className="px-3 py-1.5 rounded bg-gray-700 text-sm hover:bg-gray-600"
                    >
                      Copy
                    </button>
                    <button
                      onClick={() => {
                        setShowInvite(false)
                        setInviteUrl(null)
                        reload()
                      }}
                      className="px-3 py-1.5 rounded bg-gray-700 text-sm hover:bg-gray-600"
                    >
                      Done
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Email</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Name</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Role</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Status</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Last Login</th>
                </tr>
              </thead>
              <tbody>
                {data.map((u: any) => (
                  <tr key={u.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-4 py-3 text-gray-300">{u.email}</td>
                    <td className="px-4 py-3 text-gray-300">{u.display_name}</td>
                    <td className="px-4 py-3">
                      <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400">
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-xs ${u.is_active ? 'text-green-400' : 'text-red-400'}`}
                      >
                        {u.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {u.last_login_at
                        ? new Date(u.last_login_at).toLocaleDateString()
                        : 'Never'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </SectionStateGuard>
  )
}
