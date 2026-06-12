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
