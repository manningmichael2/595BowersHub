import { useEffect, useState } from 'react'
import { api } from '../../services/api'

export default function ApiRegistrySection() {
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

  if (loading) return <p className="text-text-muted">Loading...</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">API Registry (Toolbox)</h2>
        <button
          onClick={() => setEditing({ name: '', base_url: '', description: '', auth_type: 'none', endpoints: [], is_active: true, notes: '' })}
          className="px-3 py-1.5 bg-primary text-on-primary rounded-lg text-sm hover:bg-primary/90"
        >
          + Add API
        </button>
      </div>

      {msg && <p className="text-success text-sm mb-2">{msg}</p>}

      <div className="space-y-2">
        {apis.map((a) => (
          <div key={a.id} className={`rounded-lg p-3 flex items-start gap-3 ${a.is_active ? 'bg-surface/50' : 'bg-surface/20 opacity-60'}`}>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm text-primary">{a.name}</span>
                <span className="text-xs text-text-muted">{a.auth_type !== 'none' ? `🔑 ${a.auth_type}` : '🌐 no auth'}</span>
                {a.usage_count > 0 && <span className="text-xs text-success">{a.usage_count} calls</span>}
              </div>
              <p className="text-sm text-text-muted mt-0.5 line-clamp-2">{a.description}</p>
              <p className="text-xs text-text-muted font-mono mt-1">{a.base_url}</p>
              {a.endpoints && a.endpoints.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {a.endpoints.map((ep: any, i: number) => (
                    <span key={i} className="text-xs bg-surface-light text-text-muted px-1.5 py-0.5 rounded">
                      {ep.name || ep.path}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex gap-1 shrink-0">
              <button onClick={() => toggle(a)} className={`text-xs px-2 py-1 ${a.is_active ? 'text-success' : 'text-danger'}`}>
                {a.is_active ? 'ON' : 'OFF'}
              </button>
              <button onClick={() => setEditing(a)} className="text-xs text-text-muted hover:text-white px-2 py-1">
                Edit
              </button>
              <button onClick={() => remove(a.id, a.name)} className="text-xs text-danger hover:text-danger px-2 py-1">
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
    <div className="fixed inset-0 bg-background/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface rounded-xl p-6 w-full max-w-xl space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-medium">{entry.id ? 'Edit API' : 'Register New API'}</h3>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-text-muted">Name</label>
            <input
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              disabled={!!entry.id}
              className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
              placeholder="my-api"
            />
          </div>
          <div>
            <label className="text-xs text-text-muted">Auth Type</label>
            <select
              value={form.auth_type}
              onChange={e => setForm({ ...form, auth_type: e.target.value })}
              className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            >
              <option value="none">None (public)</option>
              <option value="api_key">API Key</option>
              <option value="bearer">Bearer Token</option>
              <option value="header">Custom Header</option>
            </select>
          </div>
        </div>

        <div>
          <label className="text-xs text-text-muted">Base URL</label>
          <input
            value={form.base_url}
            onChange={e => setForm({ ...form, base_url: e.target.value })}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            placeholder="https://api.example.com/v1"
          />
        </div>

        <div>
          <label className="text-xs text-text-muted">Description (what this API does — Haiku reads this)</label>
          <textarea
            value={form.description}
            onChange={e => setForm({ ...form, description: e.target.value })}
            rows={3}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            placeholder="What data does this API provide? Be specific so the AI knows when to use it."
          />
        </div>

        <div>
          <label className="text-xs text-text-muted">Endpoints (JSON array)</label>
          <textarea
            value={endpointsText}
            onChange={e => setEndpointsText(e.target.value)}
            rows={8}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1 font-mono"
            placeholder='[{"name": "search", "path": "/search", "method": "GET", "description": "Search for items", "params": {"q": "search query"}}]'
          />
        </div>

        <div>
          <label className="text-xs text-text-muted">Notes (for you — not shown to AI)</label>
          <input
            value={form.notes || ''}
            onChange={e => setForm({ ...form, notes: e.target.value })}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            placeholder="Free tier limits, gotchas, etc."
          />
        </div>

        <div className="flex gap-2 justify-end pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-text-muted hover:text-white">
            Cancel
          </button>
          <button onClick={handleSave} className="px-4 py-2 bg-primary text-on-primary rounded-lg text-sm hover:bg-primary/90">
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
