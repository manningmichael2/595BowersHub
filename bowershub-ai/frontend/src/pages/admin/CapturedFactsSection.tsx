import { useState } from 'react'
import { api } from '../../services/api'
import { useEndpointData, SectionStateGuard } from './AdminCommon'

interface Fact {
  id: number
  name: string
  entity_type: string
  summary: string
  captured_by: string | null
  topic: string | null
  visibility: string
  created_at: string
}

interface FactsResponse {
  total: number
  facts: Fact[]
}

const TYPE_TONE: Record<string, string> = {
  preference: 'text-info',
  person: 'text-success',
  account: 'text-warning',
  fact: 'text-text',
  note: 'text-text-muted',
}

export default function CapturedFactsSection() {
  const { data, isLoading, error, reload } = useEndpointData<FactsResponse>(
    '/api/admin/captured-facts?limit=200',
  )
  const [deleting, setDeleting] = useState<number | null>(null)
  const [toggling, setToggling] = useState<number | null>(null)

  const toggleVisibility = async (f: Fact) => {
    const next = f.visibility === 'shared' ? 'private' : 'shared'
    setToggling(f.id)
    try {
      await api.patch(`/api/admin/captured-facts/${f.id}/visibility`, { visibility: next })
      await reload()
    } catch {
      alert('Failed to change visibility. Try again.')
    } finally {
      setToggling(null)
    }
  }

  const remove = async (f: Fact) => {
    if (!confirm(`Remove this auto-captured fact?\n\n“${f.summary}”`)) return
    setDeleting(f.id)
    try {
      await api.delete(`/api/admin/captured-facts/${f.id}`)
      await reload()
    } catch {
      alert('Failed to remove the fact. Try again.')
    } finally {
      setDeleting(null)
    }
  }

  const facts = data?.facts ?? []

  return (
    <SectionStateGuard isLoading={isLoading} error={error}>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium">Captured Facts</h2>
            <p className="text-sm text-text-muted mt-0.5">
              Facts the assistant auto-learned from conversations into semantic memory.
              Remove anything wrong or unwanted — it drops out of recall immediately.
            </p>
          </div>
          <button
            onClick={reload}
            className="text-sm px-3 py-1.5 rounded bg-surface hover:bg-surface-light text-text shrink-0"
          >
            ↻ Refresh
          </button>
        </div>

        {facts.length === 0 ? (
          <div className="bg-background border border-border rounded-lg px-4 py-6 text-sm text-text-muted text-center">
            Nothing auto-captured yet. As you chat, durable facts (preferences,
            people, accounts) are learned here automatically — no <code>/remember</code> needed.
          </div>
        ) : (
          <>
            <div className="text-xs text-text-muted">
              {data?.total ?? facts.length} fact{(data?.total ?? 0) !== 1 ? 's' : ''} learned
            </div>
            <div className="space-y-2">
              {facts.map(f => (
                <div
                  key={f.id}
                  className="bg-background rounded-lg border border-border px-4 py-3 flex items-start gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-text break-words">{f.summary}</div>
                    <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs text-text-muted">
                      <span className={`px-1.5 py-0.5 rounded bg-surface ${TYPE_TONE[f.entity_type] || 'text-text'}`}>
                        {f.entity_type}
                      </span>
                      {f.captured_by && <span>from {f.captured_by}</span>}
                      <span>{new Date(f.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => toggleVisibility(f)}
                    disabled={toggling === f.id}
                    title={f.visibility === 'shared'
                      ? 'Shared with the household — click to make private to its author'
                      : 'Private to its author — click to share with the household'}
                    className={`text-xs px-2.5 py-1 rounded bg-surface hover:bg-surface-light disabled:opacity-50 shrink-0 ${
                      f.visibility === 'shared' ? 'text-success' : 'text-text-muted'}`}
                  >
                    {toggling === f.id ? '…' : f.visibility === 'shared' ? '👥 Shared' : '🔒 Private'}
                  </button>
                  <button
                    onClick={() => remove(f)}
                    disabled={deleting === f.id}
                    className="text-xs px-2.5 py-1 rounded bg-surface hover:bg-danger/20 text-danger disabled:opacity-50 shrink-0"
                  >
                    {deleting === f.id ? '…' : 'Remove'}
                  </button>
                </div>
              ))}
            </div>
            <p className="text-xs text-text-muted">
              A weekly digest of new captures is sent via notifications. Per-user
              auto-capture can be turned off in Settings.
            </p>
          </>
        )}
      </div>
    </SectionStateGuard>
  )
}
