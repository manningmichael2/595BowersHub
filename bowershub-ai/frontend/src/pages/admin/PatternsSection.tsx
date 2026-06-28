import { useEffect, useState } from 'react'
import { api } from '../../services/api'

export default function PatternsSection() {
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

  if (loading) return <p className="text-text-muted">Loading...</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-semibold">Routing Patterns</h2>
          <p className="text-sm text-text-muted mt-1">Regex/keyword rules that route messages to skills at L1 (instant, no AI cost). Evaluated before the classifier.</p>
        </div>
        <button
          onClick={() => setEditing({ rule: '', rule_type: 'regex', skill_id: skills[0]?.id, param_template: {}, description: '', priority: 100, is_active: true })}
          className="px-3 py-1.5 bg-primary text-on-primary rounded-lg text-sm hover:bg-primary/90"
        >
          + Add Pattern
        </button>
      </div>

      {msg && <p className="text-success text-sm mb-2">{msg}</p>}

      {patterns.length === 0 ? (
        <div className="bg-surface/30 rounded-lg p-6 text-center text-text-muted">
          <p>No patterns configured yet.</p>
          <p className="text-sm mt-2">Patterns let you route messages to skills instantly via regex — no AI call needed.</p>
          <p className="text-sm mt-1">Example: <code className="text-primary">(?i)\bweather\b</code> → weather skill</p>
        </div>
      ) : (
        <div className="space-y-2">
          {patterns.map((p) => (
            <div key={p.id} className={`rounded-lg p-3 flex items-start gap-3 ${p.is_active ? 'bg-surface/50' : 'bg-surface/20 opacity-60'}`}>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <code className="text-sm text-primary font-mono break-all">{p.rule}</code>
                  <span className="text-xs text-text-muted shrink-0">({p.rule_type})</span>
                  <span className="text-xs text-text-muted shrink-0">pri:{p.priority}</span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-success">→ {p.skill_name}</span>
                  {p.workspace_name && <span className="text-xs text-warning">({p.workspace_name})</span>}
                </div>
                {p.description && <p className="text-xs text-text-muted mt-0.5">{p.description}</p>}
              </div>
              <div className="flex gap-1 shrink-0">
                <button onClick={() => setEditing(p)} className="text-xs text-text-muted hover:text-on-primary px-2 py-1">
                  Edit
                </button>
                <button onClick={() => remove(p.id, p.rule)} className="text-xs text-danger hover:text-danger px-2 py-1">
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
      <div className="bg-surface rounded-xl p-6 w-full max-w-lg space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-medium">{pattern.id ? 'Edit Pattern' : 'New Pattern'}</h3>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-text-muted">Type</label>
            <select
              value={form.rule_type}
              onChange={e => setForm({ ...form, rule_type: e.target.value })}
              className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            >
              <option value="regex">Regex</option>
              <option value="keyword">Keyword</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-text-muted">Priority (lower = first)</label>
            <input
              type="number"
              value={form.priority}
              onChange={e => setForm({ ...form, priority: parseInt(e.target.value) || 100 })}
              className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            />
          </div>
        </div>

        <div>
          <label className="text-xs text-text-muted">Rule (regex or keyword)</label>
          <input
            value={form.rule}
            onChange={e => setForm({ ...form, rule: e.target.value })}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1 font-mono"
            placeholder="(?i)\btiger(s)?\b.*(score|game|play)"
          />
        </div>

        <div>
          <label className="text-xs text-text-muted">Test your regex</label>
          <div className="flex gap-2 mt-1">
            <input
              value={testInput}
              onChange={e => { setTestInput(e.target.value); setTestResult(null) }}
              className="flex-1 bg-surface border border-border rounded px-3 py-2 text-sm"
              placeholder="Type a test message..."
            />
            <button onClick={testRegex} className="px-3 py-2 bg-surface-light rounded text-sm hover:bg-surface-light">
              Test
            </button>
          </div>
          {testResult && (
            <p className={`text-xs mt-1 ${testResult.startsWith('✓') ? 'text-success' : 'text-danger'}`}>
              {testResult}
            </p>
          )}
        </div>

        <div>
          <label className="text-xs text-text-muted">Routes to skill</label>
          <select
            value={form.skill_id}
            onChange={e => setForm({ ...form, skill_id: parseInt(e.target.value) })}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
          >
            {skills.map(s => (
              <option key={s.id} value={s.id}>{s.name} — {s.description?.slice(0, 50)}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs text-text-muted">Description (optional)</label>
          <input
            value={form.description || ''}
            onChange={e => setForm({ ...form, description: e.target.value })}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1"
            placeholder="What this pattern catches"
          />
        </div>

        <div>
          <label className="text-xs text-text-muted">Param template (JSON — use $1, $2 for capture groups)</label>
          <textarea
            value={paramsText}
            onChange={e => setParamsText(e.target.value)}
            rows={3}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm mt-1 font-mono"
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
