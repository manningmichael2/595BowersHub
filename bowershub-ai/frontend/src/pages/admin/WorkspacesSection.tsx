import { useState } from 'react'
import { api } from '../../services/api'
import { useEndpointData, SectionStateGuard } from './AdminCommon'

export default function WorkspacesSection() {
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
                className="bg-background rounded-lg border border-border p-4"
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-2xl">{w.icon || '💬'}</span>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-text">{w.name}</h3>
                    <p className="text-xs text-text-muted truncate">{w.description}</p>
                  </div>
                </div>
                <div className="flex gap-3 mt-3 text-xs text-text-muted">
                  <span>👥 {w.user_count} users</span>
                  <span>🔧 {w.skill_count} skills</span>
                </div>
                <button
                  onClick={() => openEditor(w)}
                  className="mt-3 w-full text-sm py-1.5 rounded bg-surface hover:bg-surface-light text-text-muted"
                >
                  Edit Skills
                </button>
              </div>
            ))}
          </div>

          {editing && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-background/60"
              onClick={() => setEditing(null)}
            >
              <div
                className="bg-surface border border-border rounded-xl shadow-2xl max-w-lg w-full mx-4 max-h-[80vh] flex flex-col"
                onClick={e => e.stopPropagation()}
              >
                <div className="px-5 py-4 border-b border-border flex items-center justify-between shrink-0">
                  <h3 className="font-medium">Edit Skills: {editing.name}</h3>
                  <button
                    onClick={() => setEditing(null)}
                    className="text-text-muted hover:text-white"
                  >
                    ×
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto px-5 py-3">
                  <p className="text-xs text-text-muted mb-3">
                    Toggle which skills are available to users in this workspace.
                  </p>
                  {allSkills.map(s => (
                    <label
                      key={s.id}
                      className="flex items-start gap-3 py-2 hover:bg-surface-light/30 rounded px-2 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={workspaceSkills.has(s.id)}
                        onChange={() => toggleSkill(s.id)}
                        className="mt-1"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-text">{s.name}</div>
                        <div className="text-xs text-text-muted">{s.description}</div>
                      </div>
                    </label>
                  ))}
                </div>
                <div className="px-5 py-3 border-t border-border flex justify-end gap-2 shrink-0">
                  <button
                    onClick={() => setEditing(null)}
                    className="px-3 py-1.5 rounded bg-surface-light text-sm hover:bg-surface-light"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={saveSkills}
                    disabled={saving}
                    className="px-3 py-1.5 rounded bg-primary text-sm hover:bg-primary/90 disabled:bg-surface-light"
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
