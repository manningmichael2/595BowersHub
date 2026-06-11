/**
 * AdminConsolePage — Admin console with sidebar navigation.
 *
 * Implements task 29.1: replaces the old `AdminPanel.tsx` as the admin
 * entry. Sidebar lists the existing admin sections (Users, Workspaces,
 * Skills, Cost, Audit Log) plus two new sections from this spec:
 *
 *   - Theme Management — list view backed by /api/themes that lets
 *     admins publish themes globally and set the platform default
 *     (POST /api/themes, POST /api/themes/{id}/set-platform-default,
 *     DELETE /api/themes/{id}). Reuses <ThemeBuilder> with the admin
 *     publish checkbox for new-theme creation.
 *   - Icon Management — embeds the existing <IconUploader> component.
 *
 * Each section is a nested child route under `/admin/*` so deep links
 * survive page reloads. Non-admin users hitting any admin route are
 * redirected to `/` (R12.5).
 *
 * _Requirements: R1.2, R1.3, R12.5, R12.6, R12.7
 */
import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation, Link } from 'react-router-dom'
import { useAuthStore } from '../stores/auth'
import { api } from '../services/api'
import IconUploader from '../components/IconUploader'
import ThemeBuilder from '../components/ThemeBuilder'
import type { ThemeTokens } from '../stores/settings'

// ---- Sidebar configuration -----------------------------------------------

interface SectionDef {
  slug: string
  label: string
  icon: string
}

const SECTIONS: SectionDef[] = [
  { slug: 'users', label: 'Users', icon: '👥' },
  { slug: 'workspaces', label: 'Workspaces', icon: '🏠' },
  { slug: 'skills', label: 'Skills', icon: '🔧' },
  { slug: 'commands', label: 'Slash Commands', icon: '⌨️' },
  { slug: 'patterns', label: 'Routing Patterns', icon: '🔀' },
  { slug: 'api-registry', label: 'API Registry', icon: '🔌' },
  { slug: 'models', label: 'Models', icon: '🤖' },
  { slug: 'cost', label: 'Cost', icon: '💰' },
  { slug: 'audit', label: 'Audit Log', icon: '📋' },
  { slug: 'themes', label: 'Theme Management', icon: '🎨' },
  { slug: 'icon', label: 'Icon Management', icon: '🖼️' },
]

// ---- Page shell ----------------------------------------------------------

export default function AdminConsolePage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()

  // Admin gate (R12.5). Any non-admin who lands on /admin/* gets bounced
  // home — same behavior as the old `AdminPanel`.
  useEffect(() => {
    if (user && user.role !== 'admin') {
      navigate('/', { replace: true })
    }
  }, [user, navigate])

  if (!user || user.role !== 'admin') {
    return null
  }

  // Derive the active sidebar entry from the URL so refresh keeps the
  // selected section. The `/admin` index is treated as `users`.
  const path = location.pathname
  const activeSlug =
    SECTIONS.find(s => path === `/admin/${s.slug}` || path.startsWith(`/admin/${s.slug}/`))?.slug
    ?? 'users'

  return (
    <div className="h-screen flex flex-col bg-[#1a1a2e] text-gray-200">
      {/* Header */}
      <div className="border-b border-gray-800 px-4 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400"
        >
          ← Back
        </button>
        <h1 className="text-lg font-medium">Admin Console</h1>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Sidebar */}
        <nav className="w-56 border-r border-gray-800 p-2 overflow-y-auto shrink-0 hidden md:block">
          <ul className="space-y-1">
            {SECTIONS.map(section => {
              const isActive = section.slug === activeSlug
              return (
                <li key={section.slug}>
                  <Link
                    to={`/admin/${section.slug}`}
                    className={
                      'flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ' +
                      (isActive
                        ? 'bg-indigo-500/10 text-indigo-200 border-l-2 border-indigo-500'
                        : 'text-gray-400 hover:bg-gray-800/60 hover:text-gray-200 border-l-2 border-transparent')
                    }
                  >
                    <span>{section.icon}</span>
                    <span>{section.label}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Mobile: horizontal tab strip in place of the sidebar */}
        <div className="md:hidden border-b border-gray-800 px-2 overflow-x-auto shrink-0 absolute top-12 left-0 right-0 z-10 bg-[#1a1a2e]">
          <div className="flex gap-1 min-w-max py-1">
            {SECTIONS.map(section => {
              const isActive = section.slug === activeSlug
              return (
                <Link
                  key={section.slug}
                  to={`/admin/${section.slug}`}
                  className={
                    'px-3 py-1.5 text-xs rounded-lg whitespace-nowrap ' +
                    (isActive
                      ? 'bg-indigo-500/15 text-indigo-200'
                      : 'text-gray-400 hover:bg-gray-800/60')
                  }
                >
                  <span className="mr-1">{section.icon}</span>
                  {section.label}
                </Link>
              )
            })}
          </div>
        </div>

        {/* Content */}
        <main className="flex-1 overflow-y-auto md:pt-0 pt-9">
          <div className="max-w-6xl mx-auto p-4 md:p-6">
            <Routes>
              <Route index element={<Navigate to="users" replace />} />
              <Route path="users" element={<UsersSection />} />
              <Route path="workspaces" element={<WorkspacesSection />} />
              <Route path="skills" element={<SkillsSection />} />
              <Route path="commands" element={<SlashCommandsSection />} />
              <Route path="patterns" element={<PatternsSection />} />
              <Route path="api-registry" element={<ApiRegistrySection />} />
              <Route path="models" element={<ModelsSection />} />
              <Route path="cost" element={<CostSection />} />
              <Route path="audit" element={<AuditSection />} />
              <Route path="themes" element={<ThemeManagementSection />} />
              <Route path="icon" element={<IconManagementSection />} />
              <Route path="*" element={<Navigate to="users" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}

// ---- Generic data-loading wrapper ----------------------------------------

function useEndpointData<T = any>(path: string, deps: any[] = []) {
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

function SectionStateGuard({
  isLoading,
  error,
  children,
}: {
  isLoading: boolean
  error: string | null
  children: React.ReactNode
}) {
  if (isLoading) {
    return <div className="text-center text-gray-500 py-12">Loading...</div>
  }
  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-3 text-sm text-red-300">
        Error: {error}
      </div>
    )
  }
  return <>{children}</>
}

// ---- Users section -------------------------------------------------------

function UsersSection() {
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

// ---- Workspaces section --------------------------------------------------

function WorkspacesSection() {
  const { data, isLoading, error } = useEndpointData<any[]>('/api/workspaces')
  const [editing, setEditing] = useState<any>(null)
  const [allSkills, setAllSkills] = useState<any[]>([])
  const [workspaceSkills, setWorkspaceSkills] = useState<Set<number>>(new Set())
  const [saving, setSaving] = useState(false)

  const openEditor = async (ws: any) => {
    setEditing(ws)
    try {
      const skillsRes = await api.get('/api/skills')
      setAllSkills(skillsRes.data || [])
      const wsRes = await api.get(`/api/workspaces/${ws.id}/skills`)
      setWorkspaceSkills(new Set((wsRes.data || []).map((s: any) => s.id)))
    } catch {
      setWorkspaceSkills(new Set())
    }
  }

  const toggleSkill = (skillId: number) => {
    const next = new Set(workspaceSkills)
    if (next.has(skillId)) next.delete(skillId)
    else next.add(skillId)
    setWorkspaceSkills(next)
  }

  const saveSkills = async () => {
    if (!editing) return
    setSaving(true)
    try {
      await api.post(`/api/workspaces/${editing.id}/skills`, {
        skill_ids: Array.from(workspaceSkills),
      })
      setEditing(null)
    } catch (err: any) {
      alert('Failed to save: ' + (err.response?.data?.detail || 'Unknown error'))
    }
    setSaving(false)
  }

  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && (
        <div>
          <h2 className="text-lg font-medium mb-4">Workspaces ({data.length})</h2>
          <div className="grid gap-3 grid-cols-1 md:grid-cols-2">
            {data.map((w: any) => (
              <div
                key={w.id}
                className="bg-[#0f0f1a] rounded-lg border border-gray-800 p-4"
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-2xl">{w.icon || '💬'}</span>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-200">{w.name}</h3>
                    <p className="text-xs text-gray-500 truncate">{w.description}</p>
                  </div>
                </div>
                <div className="flex gap-3 mt-3 text-xs text-gray-500">
                  <span>👥 {w.user_count} users</span>
                  <span>🔧 {w.skill_count} skills</span>
                </div>
                <button
                  onClick={() => openEditor(w)}
                  className="mt-3 w-full text-sm py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-300"
                >
                  Edit Skills
                </button>
              </div>
            ))}
          </div>

          {editing && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
              onClick={() => setEditing(null)}
            >
              <div
                className="bg-[#1a1a2e] border border-gray-700 rounded-xl shadow-2xl max-w-lg w-full mx-4 max-h-[80vh] flex flex-col"
                onClick={e => e.stopPropagation()}
              >
                <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between shrink-0">
                  <h3 className="font-medium">Edit Skills: {editing.name}</h3>
                  <button
                    onClick={() => setEditing(null)}
                    className="text-gray-400 hover:text-white"
                  >
                    ×
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto px-5 py-3">
                  <p className="text-xs text-gray-500 mb-3">
                    Toggle which skills are available to users in this workspace.
                  </p>
                  {allSkills.map(s => (
                    <label
                      key={s.id}
                      className="flex items-start gap-3 py-2 hover:bg-gray-800/30 rounded px-2 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={workspaceSkills.has(s.id)}
                        onChange={() => toggleSkill(s.id)}
                        className="mt-1"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-gray-200">{s.name}</div>
                        <div className="text-xs text-gray-500">{s.description}</div>
                      </div>
                    </label>
                  ))}
                </div>
                <div className="px-5 py-3 border-t border-gray-800 flex justify-end gap-2 shrink-0">
                  <button
                    onClick={() => setEditing(null)}
                    className="px-3 py-1.5 rounded bg-gray-700 text-sm hover:bg-gray-600"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={saveSkills}
                    disabled={saving}
                    className="px-3 py-1.5 rounded bg-indigo-600 text-sm hover:bg-indigo-500 disabled:bg-gray-700"
                  >
                    {saving ? 'Saving...' : 'Save'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </SectionStateGuard>
  )
}

// ---- Skills section ------------------------------------------------------

function SkillsSection() {
  const { data, isLoading, error } = useEndpointData<any[]>('/api/skills')
  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && (
        <div>
          <h2 className="text-lg font-medium mb-4">Skills ({data.length})</h2>
          <div className="grid gap-3">
            {data.map((s: any) => (
              <div
                key={s.id}
                className="bg-[#0f0f1a] rounded-lg border border-gray-800 p-4"
              >
                <div className="flex justify-between items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-medium text-gray-200">{s.name}</h3>
                      {s.restricted_users && s.restricted_users.length > 0 && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-900/30 text-yellow-400">
                          🔒 restricted
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-400 mt-1">{s.description}</p>
                    <div className="mt-2 text-xs text-gray-600 font-mono break-all">
                      {s.http_method} {s.webhook_url}
                    </div>
                  </div>
                  <span
                    className={`text-xs px-2 py-0.5 rounded shrink-0 ${
                      s.is_active
                        ? 'bg-green-900/30 text-green-400'
                        : 'bg-red-900/30 text-red-400'
                    }`}
                  >
                    {s.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </SectionStateGuard>
  )
}

// ---- Cost section --------------------------------------------------------

// ---- Models section ------------------------------------------------------

interface AdminModel {
  id: number                            // numeric row id — the PATCH key
  model_id: string
  provider: string
  display_name: string
  input_cost_per_mtok: number | null    // $/MTok (admin-only — not in the public DTO)
  output_cost_per_mtok: number | null
  ref_input_cost: number | null         // canonical reference from bh_model_price_rules (0006)
  ref_output_cost: number | null
  needs_price_confirmation: boolean
  is_active: boolean
  roles: string[]
}

function ModelsSection() {
  // Admin catalog view (/api/admin/models, prices + per-row canonical reference) with
  // inline editing — prices save on blur/Enter; flagged rows get a one-click Confirm.
  const { data, isLoading, error, reload } = useEndpointData<AdminModel[]>('/api/admin/models')
  const [refreshing, setRefreshing] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const handleRefresh = async () => {
    setRefreshing(true)
    setResult(null)
    setActionError(null)
    try {
      const res = await api.post('/api/admin/models/refresh')
      const s = res.data
      setResult(
        `Refresh ${s.complete ? 'complete' : 'partial (some sources errored — nothing deactivated)'} — ` +
          `${s.added} added, ${s.reactivated} reactivated, ${s.deactivated} deactivated, ` +
          `${s.price_flagged} price-flagged.`,
      )
      await reload()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Refresh failed')
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-sm font-medium text-gray-300">Model Catalog</h3>
          <p className="text-xs text-gray-500 mt-0.5 max-w-xl">
            DB-driven model list with operator-owned prices ($/MTok). Edit a price (saves on
            Enter or when you click away) or, for a flagged row whose price already matches the
            reference, just hit <span className="text-amber-300">Confirm</span>. The reference
            column is Anthropic's published rate. Refresh discovers models from the Anthropic
            Models API + Ollama, preserving your prices.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-3 py-2 rounded-lg text-sm bg-indigo-500/15 text-indigo-200 hover:bg-indigo-500/25 border border-indigo-500/30 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
        >
          {refreshing ? 'Refreshing…' : '↻ Refresh now'}
        </button>
      </div>

      {result && (
        <div className="bg-green-900/20 border border-green-800 rounded-lg px-4 py-2 text-sm text-green-300 mb-4">
          {result}
        </div>
      )}
      {actionError && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-2 text-sm text-red-300 mb-4">
          {actionError}
        </div>
      )}

      <SectionStateGuard isLoading={isLoading} error={error}>
        <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-4 py-2 text-gray-400">Model ID</th>
                <th className="text-left px-3 py-2 text-gray-400">Provider</th>
                <th className="text-left px-3 py-2 text-gray-400">Roles</th>
                <th className="text-right px-3 py-2 text-gray-400">In $/MTok</th>
                <th className="text-right px-3 py-2 text-gray-400">Out $/MTok</th>
                <th className="text-right px-3 py-2 text-gray-400">Reference</th>
                <th className="text-left px-3 py-2 text-gray-400"></th>
              </tr>
            </thead>
            <tbody>
              {data && data.length > 0 ? (
                data.map(m => <ModelRow key={m.id} model={m} onSaved={reload} />)
              ) : (
                <tr>
                  <td colSpan={7} className="px-4 py-4 text-center text-gray-500">
                    No models
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionStateGuard>
    </div>
  )
}

function fmtRate(v: number | null): string {
  return v == null ? '' : String(Number(v))
}

function ModelRow({ model, onSaved }: { model: AdminModel; onSaved: () => Promise<void> | void }) {
  const [inCost, setInCost] = useState(fmtRate(model.input_cost_per_mtok))
  const [outCost, setOutCost] = useState(fmtRate(model.output_cost_per_mtok))
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const dirty = inCost !== fmtRate(model.input_cost_per_mtok) || outCost !== fmtRate(model.output_cost_per_mtok)
  const valid = inCost.trim() !== '' && outCost.trim() !== '' && !isNaN(Number(inCost)) && !isNaN(Number(outCost))

  const patch = async (body: Record<string, unknown>) => {
    setBusy(true)
    setErr(null)
    try {
      await api.patch(`/api/admin/models/${model.id}`, body)
      await onSaved()
      setFlash(true)
      setTimeout(() => setFlash(false), 1500)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Failed')
    } finally {
      setBusy(false)
    }
  }

  // Commit an edit on blur / Enter — only when changed + valid. Editing a price is an
  // explicit confirmation, so clear the unconfirmed flag at the same time.
  const commitEdit = () => {
    if (!dirty || !valid || busy) return
    patch({ input_cost_per_mtok: Number(inCost), output_cost_per_mtok: Number(outCost), needs_price_confirmation: false })
  }
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
  }

  const refIn = model.ref_input_cost
  const refOut = model.ref_output_cost
  const refStr = refIn == null ? '—' : `$${Number(refIn).toFixed(2)} / $${Number(refOut).toFixed(2)}`
  const matchesRef =
    refIn != null &&
    Number(model.input_cost_per_mtok) === Number(refIn) &&
    Number(model.output_cost_per_mtok) === Number(refOut)

  const cell = 'w-20 bg-[#1a1a2e] border border-gray-700 rounded px-2 py-1 text-right text-gray-200 focus:border-indigo-500 focus:outline-none'
  return (
    <tr className={'border-b border-gray-800/50 ' + (model.is_active ? '' : 'opacity-50')}>
      <td className="px-4 py-2 text-gray-300 font-mono text-xs">
        {model.model_id}
        {model.needs_price_confirmation && (
          <span className="ml-2 text-amber-400" title="Provisional price — Confirm, or edit to set">⚠</span>
        )}
        {!model.is_active && <span className="ml-2 text-gray-600">(inactive)</span>}
      </td>
      <td className="px-3 py-2 text-gray-400">{model.provider}</td>
      <td className="px-3 py-2 text-indigo-300 text-xs">{model.roles?.join(', ')}</td>
      <td className="px-3 py-2 text-right">
        <input className={cell} value={inCost} disabled={busy} inputMode="decimal"
               onChange={e => setInCost(e.target.value)} onBlur={commitEdit} onKeyDown={onKey} />
      </td>
      <td className="px-3 py-2 text-right">
        <input className={cell} value={outCost} disabled={busy} inputMode="decimal"
               onChange={e => setOutCost(e.target.value)} onBlur={commitEdit} onKeyDown={onKey} />
      </td>
      <td className={'px-3 py-2 text-right text-xs whitespace-nowrap ' + (matchesRef ? 'text-gray-500' : 'text-amber-300')}
          title={matchesRef ? 'matches reference' : 'differs from reference'}>
        {refStr}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {model.needs_price_confirmation && !dirty && (
          <button onClick={() => patch({ needs_price_confirmation: false })} disabled={busy}
                  className="px-2.5 py-1 rounded text-xs bg-amber-500/15 text-amber-200 hover:bg-amber-500/25 border border-amber-500/30 disabled:opacity-40">
            {busy ? '…' : 'Confirm'}
          </button>
        )}
        {flash && <span className="text-green-400 text-xs">✓ saved</span>}
        {err && <span className="text-red-400 text-xs">{err}</span>}
      </td>
    </tr>
  )
}

// ---- Cost section --------------------------------------------------------

function CostSection() {
  const { data, isLoading, error } = useEndpointData<any>('/api/admin/cost?days=7')
  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && <CostSectionInner data={data} />}
    </SectionStateGuard>
  )
}

function CostSectionInner({ data }: { data: any }) {
  const weekTotal = data.daily?.reduce((s: number, d: any) => s + d.total, 0) || 0
  const totalCalls = data.daily?.reduce((s: number, d: any) => s + d.calls, 0) || 0

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 p-4">
          <div className="text-sm text-gray-500">Today</div>
          <div className="text-2xl font-bold text-white mt-1">
            ${(data.today_total || 0).toFixed(4)}
          </div>
        </div>
        <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 p-4">
          <div className="text-sm text-gray-500">7-Day Total</div>
          <div className="text-2xl font-bold text-white mt-1">${weekTotal.toFixed(4)}</div>
        </div>
        <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 p-4">
          <div className="text-sm text-gray-500">Total Calls</div>
          <div className="text-2xl font-bold text-white mt-1">{totalCalls}</div>
        </div>
      </div>

      <h3 className="text-sm font-medium text-gray-400 mb-3">Daily Breakdown</h3>
      <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto mb-6">
        <table className="w-full text-sm min-w-[400px]">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-4 py-2 text-gray-400">Date</th>
              <th className="text-right px-4 py-2 text-gray-400">Cost</th>
              <th className="text-right px-4 py-2 text-gray-400">Calls</th>
            </tr>
          </thead>
          <tbody>
            {data.daily?.length > 0 ? (
              data.daily.map((d: any) => (
                <tr key={d.day} className="border-b border-gray-800/50">
                  <td className="px-4 py-2 text-gray-300">{d.day}</td>
                  <td className="px-4 py-2 text-right text-gray-300">
                    ${d.total.toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-500">{d.calls}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={3} className="px-4 py-4 text-center text-gray-500">
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h3 className="text-sm font-medium text-gray-400 mb-3">By Model</h3>
      <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto mb-6">
        <table className="w-full text-sm min-w-[500px]">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-4 py-2 text-gray-400">Model</th>
              <th className="text-right px-4 py-2 text-gray-400">Cost</th>
              <th className="text-right px-4 py-2 text-gray-400">Calls</th>
              <th className="text-right px-4 py-2 text-gray-400">Tokens (in/out)</th>
            </tr>
          </thead>
          <tbody>
            {data.by_model?.length > 0 ? (
              data.by_model.map((m: any) => (
                <tr key={m.model} className="border-b border-gray-800/50">
                  <td className="px-4 py-2 text-gray-300 font-mono text-xs">{m.model}</td>
                  <td className="px-4 py-2 text-right text-gray-300">
                    ${m.total.toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-500">{m.calls}</td>
                  <td className="px-4 py-2 text-right text-gray-500 text-xs">
                    {m.input_tokens}/{m.output_tokens}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4} className="px-4 py-4 text-center text-gray-500">
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h3 className="text-sm font-medium text-gray-400 mb-3">By Source</h3>
      <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-sm min-w-[400px]">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-4 py-2 text-gray-400">Source</th>
              <th className="text-right px-4 py-2 text-gray-400">Cost</th>
              <th className="text-right px-4 py-2 text-gray-400">Calls</th>
            </tr>
          </thead>
          <tbody>
            {data.by_source?.length > 0 ? (
              data.by_source.map((s: any) => (
                <tr key={s.source} className="border-b border-gray-800/50">
                  <td className="px-4 py-2 text-gray-300">{s.source}</td>
                  <td className="px-4 py-2 text-right text-gray-300">
                    ${s.total.toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-500">{s.calls}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={3} className="px-4 py-4 text-center text-gray-500">
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---- Audit section -------------------------------------------------------

function AuditSection() {
  const { data, isLoading, error } = useEndpointData<any[]>('/api/admin/audit?limit=50')
  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      {data && (
        <div>
          {data.length === 0 ? (
            <div>
              <h2 className="text-lg font-medium mb-4">Audit Log</h2>
              <div className="text-center text-gray-500 py-12 bg-[#0f0f1a] rounded-lg border border-gray-800">
                No activity logged yet. Admin actions (creating users, modifying
                skills, etc.) will appear here.
              </div>
            </div>
          ) : (
            <div>
              <h2 className="text-lg font-medium mb-4">Recent Activity ({data.length})</h2>
              <div className="space-y-2">
                {data.map((entry: any) => (
                  <div
                    key={entry.id}
                    className="bg-[#0f0f1a] rounded-lg border border-gray-800 px-4 py-3 flex items-center gap-3 flex-wrap"
                  >
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400 shrink-0">
                      {entry.action}
                    </span>
                    <span className="text-sm text-gray-300 flex-1 min-w-0 truncate">
                      {entry.user_email || 'System'}
                    </span>
                    {entry.target_type && (
                      <span className="text-xs text-gray-500 shrink-0">
                        {entry.target_type} #{entry.target_id}
                      </span>
                    )}
                    <span className="text-xs text-gray-600 shrink-0">
                      {new Date(entry.created_at).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </SectionStateGuard>
  )
}

// ---- Theme Management section --------------------------------------------

interface ThemeListEntry {
  id: number
  name: string
  slug: string
  is_preset: boolean
  owner_id: number | null
  tokens_json: ThemeTokens
  is_default: boolean
}

function ThemeManagementSection() {
  const [themes, setThemes] = useState<ThemeListEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [builderOpen, setBuilderOpen] = useState(false)

  const loadThemes = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.get('/api/themes')
      const list: ThemeListEntry[] = Array.isArray(res.data)
        ? res.data
        : Array.isArray(res.data?.themes)
          ? res.data.themes
          : []
      setThemes(list)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load themes')
      setThemes([])
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadThemes()
  }, [])

  const setPlatformDefault = async (theme: ThemeListEntry) => {
    if (theme.is_default) return
    if (theme.owner_id != null) {
      setError('Only published (admin) themes can be set as the platform default.')
      return
    }
    setError(null)
    setActionMsg(null)
    setBusyId(theme.id)
    try {
      await api.post(`/api/themes/${theme.id}/set-platform-default`)
      setActionMsg(`Set "${theme.name}" as the platform default.`)
      await loadThemes()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to set platform default')
    } finally {
      setBusyId(null)
    }
  }

  const deleteTheme = async (theme: ThemeListEntry) => {
    if (theme.is_preset) {
      setError('Preset themes cannot be deleted.')
      return
    }
    if (
      !window.confirm(
        `Delete "${theme.name}"? Any users currently using this theme will fall back to the platform default.`,
      )
    ) {
      return
    }
    setError(null)
    setActionMsg(null)
    setBusyId(theme.id)
    try {
      const res = await api.delete(`/api/themes/${theme.id}`)
      const affected = res.data?.affected_user_count ?? 0
      setActionMsg(
        affected > 0
          ? `Deleted "${theme.name}". ${affected} user(s) reset to the platform default.`
          : `Deleted "${theme.name}".`,
      )
      await loadThemes()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete theme')
    } finally {
      setBusyId(null)
    }
  }

  const sorted = (themes ?? []).slice().sort((a, b) => {
    const groupA = a.is_preset ? 0 : a.owner_id == null ? 1 : 2
    const groupB = b.is_preset ? 0 : b.owner_id == null ? 1 : 2
    if (groupA !== groupB) return groupA - groupB
    return a.name.localeCompare(b.name)
  })

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-medium text-gray-100">Theme Management</h2>
          <p className="text-sm text-gray-400 mt-1">
            Manage published themes and the platform default. Personal themes
            owned by other users are not listed here.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setBuilderOpen(true)}
          className="px-3 py-1.5 rounded-lg bg-indigo-600 text-sm text-white hover:bg-indigo-500"
        >
          + New theme
        </button>
      </div>

      {actionMsg && (
        <div className="rounded-lg border border-emerald-700/40 bg-emerald-900/20 px-3 py-2 text-sm text-emerald-300">
          {actionMsg}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/20 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {isLoading && themes == null ? (
        <div className="text-center text-gray-500 py-12">Loading themes...</div>
      ) : sorted.length === 0 ? (
        <div className="text-sm text-gray-500 italic">No themes available.</div>
      ) : (
        <div className="bg-[#0f0f1a] rounded-lg border border-gray-800 overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-4 py-3 text-gray-400 font-medium">Theme</th>
                <th className="text-left px-4 py-3 text-gray-400 font-medium">Type</th>
                <th className="text-left px-4 py-3 text-gray-400 font-medium">Default</th>
                <th className="text-right px-4 py-3 text-gray-400 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(theme => {
                const tokens = theme.tokens_json || ({} as ThemeTokens)
                const isBusy = busyId === theme.id
                const canDelete = !theme.is_preset
                const canSetDefault = theme.owner_id == null && !theme.is_default
                return (
                  <tr key={theme.id} className="border-b border-gray-800/50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div
                          className="h-8 w-12 rounded border flex overflow-hidden shrink-0"
                          style={{ borderColor: tokens.border || '#334155' }}
                        >
                          <div
                            className="flex-1"
                            style={{ background: tokens.background || '#0f172a' }}
                          />
                          <div
                            className="flex-1"
                            style={{ background: tokens.surface || '#1e293b' }}
                          />
                          <div
                            className="w-2"
                            style={{ background: tokens.primary || '#6366f1' }}
                          />
                          <div
                            className="w-2"
                            style={{ background: tokens.accent || '#8b5cf6' }}
                          />
                        </div>
                        <div className="min-w-0">
                          <div className="text-gray-200 font-medium truncate">
                            {theme.name}
                          </div>
                          <div className="text-xs text-gray-500 font-mono truncate">
                            {theme.slug}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {theme.is_preset ? (
                        <span className="text-[10px] uppercase tracking-wider text-gray-400 bg-gray-700/60 px-1.5 py-0.5 rounded">
                          Preset
                        </span>
                      ) : theme.owner_id == null ? (
                        <span className="text-[10px] uppercase tracking-wider text-indigo-300 bg-indigo-900/40 px-1.5 py-0.5 rounded">
                          Published
                        </span>
                      ) : (
                        <span className="text-[10px] uppercase tracking-wider text-emerald-300 bg-emerald-900/40 px-1.5 py-0.5 rounded">
                          Personal
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {theme.is_default ? (
                        <span className="text-amber-300 text-xs">★ Platform default</span>
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex gap-2">
                        <button
                          type="button"
                          onClick={() => setPlatformDefault(theme)}
                          disabled={isBusy || !canSetDefault}
                          className="px-2.5 py-1 rounded bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                          title={
                            theme.is_default
                              ? 'Already the platform default'
                              : theme.owner_id != null
                                ? 'Only published themes can be set as default'
                                : 'Set as platform default'
                          }
                        >
                          {isBusy ? '…' : 'Set default'}
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteTheme(theme)}
                          disabled={isBusy || !canDelete}
                          className="px-2.5 py-1 rounded bg-red-900/40 text-xs text-red-200 hover:bg-red-800/60 disabled:opacity-40 disabled:cursor-not-allowed"
                          title={
                            theme.is_preset
                              ? 'Preset themes cannot be deleted'
                              : 'Delete theme'
                          }
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {builderOpen && (
        <ThemeBuilder
          onClose={() => setBuilderOpen(false)}
          onSave={async () => {
            setActionMsg('Theme saved.')
            await loadThemes()
          }}
        />
      )}
    </div>
  )
}

// ---- Icon Management section ---------------------------------------------

function IconManagementSection() {
  return <IconUploader />
}

// ---- Slash Commands section ------------------------------------------------

function SlashCommandsSection() {
  const [commands, setCommands] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<any | null>(null)
  const [msg, setMsg] = useState('')

  const load = async () => {
    try {
      const res = await api.get('/api/admin/slash-commands')
      setCommands(res.data || [])
    } catch { setCommands([]) }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const save = async (cmd: any) => {
    try {
      if (cmd.id) {
        await api.patch(`/api/admin/slash-commands/${cmd.id}`, {
          description: cmd.description,
          flags: cmd.flags,
          is_active: cmd.is_active,
        })
      } else {
        await api.post('/api/admin/slash-commands', cmd)
      }
      setMsg('Saved ✓')
      setEditing(null)
      await load()
      setTimeout(() => setMsg(''), 2000)
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || 'Error saving')
    }
  }

  const remove = async (id: number, name: string) => {
    if (!confirm(`Delete ${name}?`)) return
    await api.delete(`/api/admin/slash-commands/${id}`)
    await load()
  }

  if (loading) return <p className="text-gray-400">Loading...</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Slash Commands</h2>
        <button
          onClick={() => setEditing({ command: '/', description: '', flags: [], is_active: true })}
          className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500"
        >
          + Add Command
        </button>
      </div>

      {msg && <p className="text-green-400 text-sm mb-2">{msg}</p>}

      <div className="space-y-2">
        {commands.map((cmd) => (
          <div key={cmd.id} className="bg-gray-800/50 rounded-lg p-3 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <code className="text-indigo-300 font-mono text-sm">{cmd.command}</code>
                {!cmd.is_active && <span className="text-xs text-red-400">(disabled)</span>}
                {cmd.skill_name && <span className="text-xs text-gray-500">→ {cmd.skill_name}</span>}
                {cmd.workspace_name && <span className="text-xs text-yellow-600">({cmd.workspace_name})</span>}
              </div>
              <p className="text-sm text-gray-400 mt-0.5">{cmd.description}</p>
              {cmd.flags && cmd.flags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {cmd.flags.map((f: any, i: number) => (
                    <span key={i} className="text-xs bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded">
                      {f.flag}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex gap-1 shrink-0">
              <button onClick={() => setEditing(cmd)} className="text-xs text-gray-400 hover:text-white px-2 py-1">
                Edit
              </button>
              <button onClick={() => remove(cmd.id, cmd.command)} className="text-xs text-red-400 hover:text-red-300 px-2 py-1">
                ✕
              </button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <CommandEditor
          command={editing}
          onSave={save}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

function CommandEditor({ command, onSave, onClose }: { command: any, onSave: (c: any) => void, onClose: () => void }) {
  const [form, setForm] = useState(command)
  const [flagsText, setFlagsText] = useState(
    JSON.stringify(command.flags || [], null, 2)
  )

  const handleSave = () => {
    let flags = []
    try { flags = JSON.parse(flagsText) } catch {}
    onSave({ ...form, flags })
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-xl p-6 w-full max-w-lg space-y-4">
        <h3 className="text-lg font-medium">{command.id ? 'Edit Command' : 'New Command'}</h3>

        <div>
          <label className="text-xs text-gray-400">Command</label>
          <input
            value={form.command}
            onChange={e => setForm({ ...form, command: e.target.value })}
            disabled={!!command.id}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            placeholder="/mycommand"
          />
        </div>

        <div>
          <label className="text-xs text-gray-400">Description</label>
          <input
            value={form.description}
            onChange={e => setForm({ ...form, description: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            placeholder="What this command does"
          />
        </div>

        <div>
          <label className="text-xs text-gray-400">Flags (JSON array)</label>
          <textarea
            value={flagsText}
            onChange={e => setFlagsText(e.target.value)}
            rows={5}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1 font-mono"
            placeholder='[{"flag": "--example", "description": "What it does"}]'
          />
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={e => setForm({ ...form, is_active: e.target.checked })}
            />
            Active
          </label>
        </div>

        <div className="flex gap-2 justify-end pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-white">
            Cancel
          </button>
          <button onClick={handleSave} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500">
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- API Registry section --------------------------------------------------

function ApiRegistrySection() {
  const [apis, setApis] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<any | null>(null)
  const [msg, setMsg] = useState('')

  const load = async () => {
    try {
      const res = await api.get('/api/admin/api-registry')
      setApis(res.data || [])
    } catch { setApis([]) }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const toggle = async (apiEntry: any) => {
    await api.patch(`/api/admin/api-registry/${apiEntry.id}`, { is_active: !apiEntry.is_active })
    await load()
  }

  const remove = async (id: number, name: string) => {
    if (!confirm(`Delete API "${name}"?`)) return
    await api.delete(`/api/admin/api-registry/${id}`)
    await load()
  }

  const save = async (entry: any) => {
    try {
      if (entry.id) {
        await api.patch(`/api/admin/api-registry/${entry.id}`, {
          description: entry.description,
          base_url: entry.base_url,
          endpoints: entry.endpoints,
          is_active: entry.is_active,
          notes: entry.notes,
        })
      } else {
        await api.post('/api/admin/api-registry', entry)
      }
      setMsg('Saved ✓')
      setEditing(null)
      await load()
      setTimeout(() => setMsg(''), 2000)
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || 'Error saving')
    }
  }

  if (loading) return <p className="text-gray-400">Loading...</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">API Registry (Toolbox)</h2>
        <button
          onClick={() => setEditing({ name: '', base_url: '', description: '', auth_type: 'none', endpoints: [], is_active: true, notes: '' })}
          className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500"
        >
          + Add API
        </button>
      </div>

      {msg && <p className="text-green-400 text-sm mb-2">{msg}</p>}

      <div className="space-y-2">
        {apis.map((a) => (
          <div key={a.id} className={`rounded-lg p-3 flex items-start gap-3 ${a.is_active ? 'bg-gray-800/50' : 'bg-gray-800/20 opacity-60'}`}>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm text-indigo-300">{a.name}</span>
                <span className="text-xs text-gray-500">{a.auth_type !== 'none' ? `🔑 ${a.auth_type}` : '🌐 no auth'}</span>
                {a.usage_count > 0 && <span className="text-xs text-green-500">{a.usage_count} calls</span>}
              </div>
              <p className="text-sm text-gray-400 mt-0.5 line-clamp-2">{a.description}</p>
              <p className="text-xs text-gray-500 font-mono mt-1">{a.base_url}</p>
              {a.endpoints && a.endpoints.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {a.endpoints.map((ep: any, i: number) => (
                    <span key={i} className="text-xs bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded">
                      {ep.name || ep.path}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex gap-1 shrink-0">
              <button onClick={() => toggle(a)} className={`text-xs px-2 py-1 ${a.is_active ? 'text-green-400' : 'text-red-400'}`}>
                {a.is_active ? 'ON' : 'OFF'}
              </button>
              <button onClick={() => setEditing(a)} className="text-xs text-gray-400 hover:text-white px-2 py-1">
                Edit
              </button>
              <button onClick={() => remove(a.id, a.name)} className="text-xs text-red-400 hover:text-red-300 px-2 py-1">
                ✕
              </button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <ApiEditor
          entry={editing}
          onSave={save}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

function ApiEditor({ entry, onSave, onClose }: { entry: any, onSave: (e: any) => void, onClose: () => void }) {
  const [form, setForm] = useState(entry)
  const [endpointsText, setEndpointsText] = useState(
    JSON.stringify(entry.endpoints || [], null, 2)
  )

  const handleSave = () => {
    let endpoints = []
    try { endpoints = JSON.parse(endpointsText) } catch {}
    onSave({ ...form, endpoints })
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-xl p-6 w-full max-w-xl space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-medium">{entry.id ? 'Edit API' : 'Register New API'}</h3>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400">Name</label>
            <input
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              disabled={!!entry.id}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
              placeholder="my-api"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400">Auth Type</label>
            <select
              value={form.auth_type}
              onChange={e => setForm({ ...form, auth_type: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            >
              <option value="none">None (public)</option>
              <option value="api_key">API Key</option>
              <option value="bearer">Bearer Token</option>
              <option value="header">Custom Header</option>
            </select>
          </div>
        </div>

        <div>
          <label className="text-xs text-gray-400">Base URL</label>
          <input
            value={form.base_url}
            onChange={e => setForm({ ...form, base_url: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            placeholder="https://api.example.com/v1"
          />
        </div>

        <div>
          <label className="text-xs text-gray-400">Description (what this API does — Haiku reads this)</label>
          <textarea
            value={form.description}
            onChange={e => setForm({ ...form, description: e.target.value })}
            rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            placeholder="What data does this API provide? Be specific so the AI knows when to use it."
          />
        </div>

        <div>
          <label className="text-xs text-gray-400">Endpoints (JSON array)</label>
          <textarea
            value={endpointsText}
            onChange={e => setEndpointsText(e.target.value)}
            rows={8}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1 font-mono"
            placeholder='[{"name": "search", "path": "/search", "method": "GET", "description": "Search for items", "params": {"q": "search query"}}]'
          />
        </div>

        <div>
          <label className="text-xs text-gray-400">Notes (for you — not shown to AI)</label>
          <input
            value={form.notes || ''}
            onChange={e => setForm({ ...form, notes: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            placeholder="Free tier limits, gotchas, etc."
          />
        </div>

        <div className="flex gap-2 justify-end pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-white">
            Cancel
          </button>
          <button onClick={handleSave} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500">
            Save
          </button>
        </div>
      </div>
    </div>
  )
}


// ---- Routing Patterns section ----------------------------------------------

function PatternsSection() {
  const [patterns, setPatterns] = useState<any[]>([])
  const [skills, setSkills] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<any | null>(null)
  const [msg, setMsg] = useState('')

  const load = async () => {
    try {
      const [pRes, sRes] = await Promise.all([
        api.get('/api/admin/patterns'),
        api.get('/api/skills'),
      ])
      setPatterns(pRes.data || [])
      setSkills(sRes.data || [])
    } catch { setPatterns([]) }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const save = async (pattern: any) => {
    try {
      if (pattern.id) {
        await api.patch(`/api/admin/patterns/${pattern.id}`, {
          rule: pattern.rule,
          rule_type: pattern.rule_type,
          skill_id: pattern.skill_id,
          param_template: pattern.param_template,
          description: pattern.description,
          priority: pattern.priority,
          is_active: pattern.is_active,
        })
      } else {
        await api.post('/api/admin/patterns', pattern)
      }
      setMsg('Saved ✓')
      setEditing(null)
      await load()
      setTimeout(() => setMsg(''), 2000)
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || 'Error saving')
    }
  }

  const remove = async (id: number, rule: string) => {
    if (!confirm(`Delete pattern "${rule.slice(0, 40)}"?`)) return
    await api.delete(`/api/admin/patterns/${id}`)
    await load()
  }

  if (loading) return <p className="text-gray-400">Loading...</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-semibold">Routing Patterns</h2>
          <p className="text-sm text-gray-400 mt-1">Regex/keyword rules that route messages to skills at L1 (instant, no AI cost). Evaluated before the classifier.</p>
        </div>
        <button
          onClick={() => setEditing({ rule: '', rule_type: 'regex', skill_id: skills[0]?.id, param_template: {}, description: '', priority: 100, is_active: true })}
          className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500"
        >
          + Add Pattern
        </button>
      </div>

      {msg && <p className="text-green-400 text-sm mb-2">{msg}</p>}

      {patterns.length === 0 ? (
        <div className="bg-gray-800/30 rounded-lg p-6 text-center text-gray-400">
          <p>No patterns configured yet.</p>
          <p className="text-sm mt-2">Patterns let you route messages to skills instantly via regex — no AI call needed.</p>
          <p className="text-sm mt-1">Example: <code className="text-indigo-300">(?i)\bweather\b</code> → weather skill</p>
        </div>
      ) : (
        <div className="space-y-2">
          {patterns.map((p) => (
            <div key={p.id} className={`rounded-lg p-3 flex items-start gap-3 ${p.is_active ? 'bg-gray-800/50' : 'bg-gray-800/20 opacity-60'}`}>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <code className="text-sm text-indigo-300 font-mono break-all">{p.rule}</code>
                  <span className="text-xs text-gray-500 shrink-0">({p.rule_type})</span>
                  <span className="text-xs text-gray-500 shrink-0">pri:{p.priority}</span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-green-400">→ {p.skill_name}</span>
                  {p.workspace_name && <span className="text-xs text-yellow-600">({p.workspace_name})</span>}
                </div>
                {p.description && <p className="text-xs text-gray-500 mt-0.5">{p.description}</p>}
              </div>
              <div className="flex gap-1 shrink-0">
                <button onClick={() => setEditing(p)} className="text-xs text-gray-400 hover:text-white px-2 py-1">
                  Edit
                </button>
                <button onClick={() => remove(p.id, p.rule)} className="text-xs text-red-400 hover:text-red-300 px-2 py-1">
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <PatternEditor
          pattern={editing}
          skills={skills}
          onSave={save}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

function PatternEditor({ pattern, skills, onSave, onClose }: { pattern: any, skills: any[], onSave: (p: any) => void, onClose: () => void }) {
  const [form, setForm] = useState(pattern)
  const [paramsText, setParamsText] = useState(
    JSON.stringify(pattern.param_template || {}, null, 2)
  )
  const [testInput, setTestInput] = useState('')
  const [testResult, setTestResult] = useState<string | null>(null)

  const testRegex = () => {
    if (!form.rule || !testInput) return
    try {
      const re = new RegExp(form.rule, 'i')
      const match = re.exec(testInput)
      setTestResult(match ? `✓ Match: "${match[0]}"` : '✗ No match')
    } catch (e: any) {
      setTestResult(`Error: ${e.message}`)
    }
  }

  const handleSave = () => {
    let param_template = {}
    try { param_template = JSON.parse(paramsText) } catch {}
    onSave({ ...form, param_template })
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-xl p-6 w-full max-w-lg space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-medium">{pattern.id ? 'Edit Pattern' : 'New Pattern'}</h3>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400">Type</label>
            <select
              value={form.rule_type}
              onChange={e => setForm({ ...form, rule_type: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            >
              <option value="regex">Regex</option>
              <option value="keyword">Keyword</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400">Priority (lower = first)</label>
            <input
              type="number"
              value={form.priority}
              onChange={e => setForm({ ...form, priority: parseInt(e.target.value) || 100 })}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            />
          </div>
        </div>

        <div>
          <label className="text-xs text-gray-400">Rule (regex or keyword)</label>
          <input
            value={form.rule}
            onChange={e => setForm({ ...form, rule: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1 font-mono"
            placeholder="(?i)\btiger(s)?\b.*(score|game|play)"
          />
        </div>

        <div>
          <label className="text-xs text-gray-400">Test your regex</label>
          <div className="flex gap-2 mt-1">
            <input
              value={testInput}
              onChange={e => { setTestInput(e.target.value); setTestResult(null) }}
              className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              placeholder="Type a test message..."
            />
            <button onClick={testRegex} className="px-3 py-2 bg-gray-700 rounded text-sm hover:bg-gray-600">
              Test
            </button>
          </div>
          {testResult && (
            <p className={`text-xs mt-1 ${testResult.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>
              {testResult}
            </p>
          )}
        </div>

        <div>
          <label className="text-xs text-gray-400">Routes to skill</label>
          <select
            value={form.skill_id}
            onChange={e => setForm({ ...form, skill_id: parseInt(e.target.value) })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
          >
            {skills.map(s => (
              <option key={s.id} value={s.id}>{s.name} — {s.description?.slice(0, 50)}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs text-gray-400">Description (optional)</label>
          <input
            value={form.description || ''}
            onChange={e => setForm({ ...form, description: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1"
            placeholder="What this pattern catches"
          />
        </div>

        <div>
          <label className="text-xs text-gray-400">Param template (JSON — use $1, $2 for capture groups)</label>
          <textarea
            value={paramsText}
            onChange={e => setParamsText(e.target.value)}
            rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mt-1 font-mono"
            placeholder='{"team": "$1"}'
          />
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={e => setForm({ ...form, is_active: e.target.checked })}
            />
            Active
          </label>
        </div>

        <div className="flex gap-2 justify-end pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-white">
            Cancel
          </button>
          <button onClick={handleSave} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-500">
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
