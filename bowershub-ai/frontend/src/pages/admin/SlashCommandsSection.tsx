import { useEffect, useState } from 'react'
import { api } from '../../services/api'

export default function SlashCommandsSection() {
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

  if (loading) return <p className="text-text-muted">Loading...</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Slash Commands</h2>
        <button
          onClick={() => setEditing({ command: '/', description: '', flags: [], is_active: true })}
          className="px-3 py-1.5 bg-primary text-on-primary rounded-lg text-sm hover:bg-primary/90"
        >
          + Add Command
        </button>
      </div>

      {msg && <p className="text-success text-sm mb-2">{msg}</p>}

      <div className="space-y-2">
        {commands.map((cmd) => (
          <div key={cmd.id} className="bg-surface/50 rounded-lg p-3 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <code className="text-primary font-mono text-sm">{cmd.command}</code>
                {!cmd.is_active && <span className="text-xs text-danger">(disabled)</span>}
                {cmd.skill_name && <span className="text-xs text-text-muted">→ {cmd.skill_name}</span>}
                {cmd.workspace_name && <span className="text-xs text-warning">({cmd.workspace_name})</span>}
              </div>
              <p className="text-sm text-text-muted mt-0.5">{cmd.description}</p>
              {cmd.flags && cmd.flags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {cmd.flags.map((f: any, i: number) => (
                    <span key={i} className="text-xs bg-surface-light text-text-muted px-1.5 py-0.5 rounded">
                      {f.flag}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex gap-1 shrink-0">
              <button onClick={() => setEditing(cmd)} className="text-xs text-text-muted hover:text-on-primary px-2 py-1">
                Edit
              </button>
              <button onClick={() => remove(cmd.id, cmd.command)} className="text-xs text-danger hover:text-danger px-2 py-1">
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
      <div className="bg-surface rounded-xl p-6 w-full max-w-lg space-y-4">
        <h3 className="text-lg font-medium">{command.id ? 'Edit Command' : 'New Command'}</h3>

        <div>
          <label className="text-xs text-text-muted">Command</label>
          <input
            value={form.command}
            onChange={e => setForm({ ...form, command: e.target.value })}
            disabled={!!command.id}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            placeholder="/mycommand"
          />
        </div>

        <div>
          <label className="text-xs text-text-muted">Description</label>
          <input
            value={form.description}
            onChange={e => setForm({ ...form, description: e.target.value })}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            placeholder="What this command does"
          />
        </div>

        <div>
          <label className="text-xs text-text-muted">Flags (JSON array)</label>
          <textarea
            value={flagsText}
            onChange={e => setFlagsText(e.target.value)}
            rows={5}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1 font-mono"
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
          <button onClick={onClose} className="px-4 py-2 text-sm text-text-muted hover:text-on-primary">
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
