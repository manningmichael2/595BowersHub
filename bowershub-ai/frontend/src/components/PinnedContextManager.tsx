/**
 * PinnedContextManager — Workspace Settings → Pinned Context tab.
 *
 * Implements task 23.1:
 *   - List of pinned-context entries for a workspace, each row showing
 *     title, type badge (static / dynamic), priority, token estimate,
 *     and (for dynamic) last refresh timestamp.
 *   - Click a row to expand and see the full content (static) or the
 *     SQL query + most recent cached result (dynamic).
 *   - Admins (canEdit) get an Add entry form, Edit / Delete actions per
 *     row, and a "Refresh now" button on dynamic entries that calls
 *     `POST /api/workspaces/{id}/pinned-context/{eid}/refresh`.
 *   - Running token total at the top with a visual warning when total
 *     exceeds 75% of the workspace's pinned-context budget (R7.8).
 *     Default budget is 2000 tokens (per R15.3 in the custom-chat-app
 *     spec; the design doc reaffirms this default for R7.8).
 *
 * The list endpoint currently returns a plain array of entries; this
 * component computes the running total from the array and uses the
 * 2000-token default budget unless the API ever returns one explicitly
 * (we tolerate `{entries, total_token_estimate, budget}` envelope shape
 * for forward compatibility with the design doc).
 *
 * Props:
 *   - workspaceId: number
 *   - canEdit:     boolean (true → admin controls visible)
 *
 * _Requirements: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, R7.9
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../services/api'
import { budgetTone, type BudgetTone } from '../lib/budget'

// ---- Types ----------------------------------------------------------------

type ContextType = 'static' | 'dynamic'

interface PinnedEntry {
  id: number
  workspace_id: number
  context_type: ContextType
  title: string
  content: string | null
  query: string | null
  refresh_minutes: number
  cached_result: string | null
  cached_at: string | null
  priority: number
  token_estimate: number
  created_at: string
}

interface FormState {
  context_type: ContextType
  title: string
  content: string
  query: string
  refresh_minutes: number
  priority: number
}

const DEFAULT_BUDGET_TOKENS = 2000 // R7.8 / R15.3 default

const EMPTY_FORM: FormState = {
  context_type: 'static',
  title: '',
  content: '',
  query: '',
  refresh_minutes: 60,
  priority: 100,
}

// ---- Helpers --------------------------------------------------------------

function formatRelative(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'never'
  const now = Date.now()
  const seconds = Math.max(0, Math.floor((now - then) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function asEntries(payload: any): { entries: PinnedEntry[]; budget: number } {
  // The current backend returns an array; the design also defines a
  // `{entries, total_token_estimate, budget}` envelope. Tolerate both.
  if (Array.isArray(payload)) {
    return { entries: payload, budget: DEFAULT_BUDGET_TOKENS }
  }
  if (payload && Array.isArray(payload.entries)) {
    return {
      entries: payload.entries,
      budget:
        typeof payload.budget === 'number' && payload.budget > 0
          ? payload.budget
          : DEFAULT_BUDGET_TOKENS,
    }
  }
  return { entries: [], budget: DEFAULT_BUDGET_TOKENS }
}

function pickError(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return fallback
}

// ---- Component ------------------------------------------------------------

export interface PinnedContextManagerProps {
  workspaceId: number
  canEdit: boolean
}

export default function PinnedContextManager({
  workspaceId,
  canEdit,
}: PinnedContextManagerProps) {
  const [entries, setEntries] = useState<PinnedEntry[]>([])
  const [budget, setBudget] = useState<number>(DEFAULT_BUDGET_TOKENS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [refreshingId, setRefreshingId] = useState<number | null>(null)

  // Add / edit form state
  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // ---- Load entries -----------------------------------------------------

  const reload = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get(
        `/api/workspaces/${workspaceId}/pinned-context`,
      )
      const { entries: list, budget: b } = asEntries(res.data)
      setEntries(list)
      setBudget(b)
    } catch (err: any) {
      setError(pickError(err, 'Failed to load pinned context.'))
      setEntries([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .get(`/api/workspaces/${workspaceId}/pinned-context`)
      .then(res => {
        if (cancelled) return
        const { entries: list, budget: b } = asEntries(res.data)
        setEntries(list)
        setBudget(b)
      })
      .catch(err => {
        if (cancelled) return
        setError(pickError(err, 'Failed to load pinned context.'))
        setEntries([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [workspaceId])

  // ---- Derived ----------------------------------------------------------

  const sortedEntries = useMemo(
    () =>
      [...entries].sort(
        (a, b) => a.priority - b.priority || a.id - b.id,
      ),
    [entries],
  )

  const totalTokens = useMemo(
    () => entries.reduce((sum, e) => sum + (e.token_estimate || 0), 0),
    [entries],
  )

  const budgetPct = budget > 0 ? totalTokens / budget : 0
  const tone: BudgetTone = budgetTone(totalTokens, budget)
  const budgetToneClasses =
    tone === 'over'
      ? 'border-red-700/60 bg-red-900/20 text-red-200'
      : tone === 'warn'
        ? 'border-amber-700/60 bg-amber-900/20 text-amber-200'
        : 'border-gray-700 bg-gray-900/40 text-gray-300'

  // ---- Form helpers -----------------------------------------------------

  const openAdd = () => {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setFormOpen(true)
  }

  const openEdit = (entry: PinnedEntry) => {
    setEditingId(entry.id)
    setForm({
      context_type: entry.context_type,
      title: entry.title,
      content: entry.content || '',
      query: entry.query || '',
      refresh_minutes: entry.refresh_minutes,
      priority: entry.priority,
    })
    setFormError(null)
    setFormOpen(true)
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError(null)
  }

  const validateForm = (): string | null => {
    if (!form.title.trim()) return 'Title is required.'
    if (form.title.trim().length > 200) {
      return 'Title must be 200 characters or fewer.'
    }
    if (form.context_type === 'static') {
      if (!form.content.trim()) {
        return 'Static entries need content.'
      }
    } else {
      if (!form.query.trim()) {
        return 'Dynamic entries need a SQL query.'
      }
      if (form.refresh_minutes < 1 || form.refresh_minutes > 1440) {
        return 'Refresh interval must be between 1 and 1440 minutes.'
      }
    }
    if (form.priority < 1 || form.priority > 1000) {
      return 'Priority must be between 1 and 1000.'
    }
    return null
  }

  const submitForm = async () => {
    const v = validateForm()
    if (v) {
      setFormError(v)
      return
    }
    setSaving(true)
    setFormError(null)
    try {
      const isStatic = form.context_type === 'static'
      const payload: Record<string, unknown> = {
        title: form.title.trim(),
        priority: form.priority,
      }
      if (editingId === null) {
        // Create — context_type is required server-side.
        payload.context_type = form.context_type
      }
      if (isStatic) {
        payload.content = form.content
        // Don't send query for static entries on create; clear it on edit.
        if (editingId !== null) payload.query = null
      } else {
        payload.query = form.query
        payload.refresh_minutes = form.refresh_minutes
        if (editingId !== null) payload.content = null
      }

      if (editingId === null) {
        await api.post(
          `/api/workspaces/${workspaceId}/pinned-context`,
          payload,
        )
      } else {
        await api.patch(
          `/api/workspaces/${workspaceId}/pinned-context/${editingId}`,
          payload,
        )
      }
      closeForm()
      await reload()
    } catch (err: any) {
      setFormError(pickError(err, 'Failed to save entry.'))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (entry: PinnedEntry) => {
    const ok = window.confirm(
      `Delete pinned entry "${entry.title}"? This cannot be undone.`,
    )
    if (!ok) return
    try {
      await api.delete(
        `/api/workspaces/${workspaceId}/pinned-context/${entry.id}`,
      )
      await reload()
    } catch (err: any) {
      setError(pickError(err, 'Failed to delete entry.'))
    }
  }

  const handleRefresh = async (entry: PinnedEntry) => {
    if (entry.context_type !== 'dynamic') return
    setRefreshingId(entry.id)
    setError(null)
    try {
      const res = await api.post(
        `/api/workspaces/${workspaceId}/pinned-context/${entry.id}/refresh`,
      )
      // Server returns the updated cached_result/cached_at/token_estimate.
      // Reload the full list to keep totals + ordering consistent.
      const data = res.data
      if (data && typeof data === 'object') {
        setEntries(prev =>
          prev.map(e =>
            e.id === entry.id
              ? {
                  ...e,
                  cached_result:
                    typeof data.cached_result === 'string'
                      ? data.cached_result
                      : e.cached_result,
                  cached_at:
                    typeof data.cached_at === 'string'
                      ? data.cached_at
                      : e.cached_at,
                  token_estimate:
                    typeof data.token_estimate === 'number'
                      ? data.token_estimate
                      : e.token_estimate,
                }
              : e,
          ),
        )
      }
    } catch (err: any) {
      setError(pickError(err, 'Failed to refresh entry.'))
    } finally {
      setRefreshingId(null)
    }
  }

  // ---- Render -----------------------------------------------------------

  return (
    <div className="space-y-3">
      {/* Token budget bar */}
      <div className={`rounded-lg border px-3 py-2 ${budgetToneClasses}`}>
        <div className="flex items-center justify-between gap-2">
          <div className="text-sm font-medium">
            Token budget:{' '}
            <span className="font-mono">{totalTokens.toLocaleString()}</span>
            <span className="opacity-60"> / </span>
            <span className="font-mono">{budget.toLocaleString()}</span>
          </div>
          <div className="text-xs opacity-80">
            {(budgetPct * 100).toFixed(0)}%
          </div>
        </div>
        <div className="mt-1.5 h-1.5 rounded-full bg-black/30 overflow-hidden">
          <div
            className={
              'h-full transition-all ' +
              (tone === 'over'
                ? 'bg-red-400'
                : tone === 'warn'
                  ? 'bg-amber-400'
                  : 'bg-emerald-400')
            }
            style={{ width: `${Math.min(100, budgetPct * 100)}%` }}
          />
        </div>
        {tone !== 'ok' && (
          <div className="mt-1 text-xs opacity-80">
            {tone === 'over'
              ? 'Over budget. Pinned context may be truncated when sent to the model.'
              : 'Approaching the budget — consider trimming or splitting entries.'}
          </div>
        )}
      </div>

      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-300">
          {loading
            ? 'Loading…'
            : `${entries.length} ${entries.length === 1 ? 'entry' : 'entries'}`}
        </div>
        {canEdit && !formOpen && (
          <button
            type="button"
            onClick={openAdd}
            className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500"
          >
            + Add entry
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/20 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Add/Edit form */}
      {canEdit && formOpen && (
        <PinnedContextForm
          form={form}
          setForm={setForm}
          editing={editingId !== null}
          saving={saving}
          error={formError}
          onCancel={closeForm}
          onSubmit={submitForm}
        />
      )}

      {/* Entry list */}
      {!loading && entries.length === 0 && !formOpen && (
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-6 text-center text-sm text-gray-500">
          No pinned context entries yet.
          {canEdit && ' Click "Add entry" to create one.'}
        </div>
      )}

      <ul className="space-y-2">
        {sortedEntries.map(entry => {
          const expanded = expandedId === entry.id
          return (
            <li
              key={entry.id}
              className="rounded-lg border border-gray-800 bg-gray-900/40 overflow-hidden"
            >
              {/* Row header (clickable) */}
              <button
                type="button"
                onClick={() => setExpandedId(expanded ? null : entry.id)}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-800/50"
              >
                <TypeBadge type={entry.context_type} />
                <span className="flex-1 text-sm text-gray-100 font-medium truncate">
                  {entry.title}
                </span>
                <span className="text-[11px] text-gray-500 font-mono shrink-0">
                  P{entry.priority}
                </span>
                <span className="text-[11px] text-gray-500 font-mono shrink-0">
                  ~{entry.token_estimate.toLocaleString()}t
                </span>
                {entry.context_type === 'dynamic' && (
                  <span
                    className="text-[11px] text-gray-500 shrink-0"
                    title={entry.cached_at || ''}
                  >
                    {formatRelative(entry.cached_at)}
                  </span>
                )}
                <svg
                  className={
                    'w-4 h-4 text-gray-500 shrink-0 transition-transform ' +
                    (expanded ? 'rotate-180' : '')
                  }
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 9l-7 7-7-7"
                  />
                </svg>
              </button>

              {/* Expanded body */}
              {expanded && (
                <div className="border-t border-gray-800 px-3 py-3 space-y-3">
                  {entry.context_type === 'static' ? (
                    <Section label="Content">
                      <pre className="whitespace-pre-wrap break-words text-sm text-gray-200 font-mono">
                        {entry.content || '(empty)'}
                      </pre>
                    </Section>
                  ) : (
                    <>
                      <Section label="SQL query">
                        <pre className="whitespace-pre-wrap break-words text-sm text-gray-200 font-mono">
                          {entry.query || '(empty)'}
                        </pre>
                      </Section>
                      <Section
                        label={
                          entry.cached_at
                            ? `Cached result · ${formatRelative(entry.cached_at)}`
                            : 'Cached result'
                        }
                      >
                        <pre className="whitespace-pre-wrap break-words text-sm text-gray-300 font-mono">
                          {entry.cached_result || '(no cached result yet)'}
                        </pre>
                        <div className="mt-1 text-[11px] text-gray-500">
                          Refreshes every {entry.refresh_minutes} min
                        </div>
                      </Section>
                    </>
                  )}

                  {/* Action row */}
                  {canEdit && (
                    <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
                      {entry.context_type === 'dynamic' && (
                        <button
                          type="button"
                          onClick={() => handleRefresh(entry)}
                          disabled={refreshingId === entry.id}
                          className={
                            'px-2.5 py-1 rounded-md text-xs font-medium ' +
                            (refreshingId === entry.id
                              ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                              : 'bg-gray-800 text-gray-200 hover:bg-gray-700')
                          }
                        >
                          {refreshingId === entry.id
                            ? 'Refreshing…'
                            : '↻ Refresh now'}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => openEdit(entry)}
                        className="px-2.5 py-1 rounded-md text-xs font-medium bg-gray-800 text-gray-200 hover:bg-gray-700"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(entry)}
                        className="px-2.5 py-1 rounded-md text-xs font-medium bg-red-900/40 text-red-200 hover:bg-red-900/60"
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function TypeBadge({ type }: { type: ContextType }) {
  const tone =
    type === 'static'
      ? 'border-sky-700/60 bg-sky-900/30 text-sky-200'
      : 'border-violet-700/60 bg-violet-900/30 text-violet-200'
  return (
    <span
      className={
        'shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider border ' +
        tone
      }
    >
      {type}
    </span>
  )
}

function Section({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
        {label}
      </div>
      <div className="rounded-md border border-gray-800 bg-black/30 px-2 py-1.5 max-h-64 overflow-y-auto">
        {children}
      </div>
    </div>
  )
}

interface PinnedContextFormProps {
  form: FormState
  setForm: (next: FormState) => void
  editing: boolean
  saving: boolean
  error: string | null
  onCancel: () => void
  onSubmit: () => void
}

function PinnedContextForm({
  form,
  setForm,
  editing,
  saving,
  error,
  onCancel,
  onSubmit,
}: PinnedContextFormProps) {
  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm({ ...form, [key]: value })

  return (
    <form
      onSubmit={e => {
        e.preventDefault()
        onSubmit()
      }}
      className="rounded-lg border border-indigo-700/40 bg-indigo-900/10 p-3 space-y-3"
    >
      <div className="text-sm font-medium text-gray-100">
        {editing ? 'Edit entry' : 'New pinned-context entry'}
      </div>

      {/* Type (only on create) */}
      {!editing && (
        <div>
          <label className="block text-xs uppercase tracking-wider text-gray-500 mb-1">
            Type
          </label>
          <div className="flex gap-2">
            {(['static', 'dynamic'] as ContextType[]).map(t => (
              <button
                key={t}
                type="button"
                onClick={() => update('context_type', t)}
                className={
                  'px-3 py-1.5 rounded-md text-sm border ' +
                  (form.context_type === t
                    ? 'border-indigo-500 bg-indigo-600/20 text-indigo-200'
                    : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700')
                }
              >
                {t === 'static' ? 'Static text' : 'Dynamic SQL'}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Title */}
      <div>
        <label className="block text-xs uppercase tracking-wider text-gray-500 mb-1">
          Title
        </label>
        <input
          type="text"
          value={form.title}
          onChange={e => update('title', e.target.value)}
          maxLength={200}
          placeholder="e.g. Active projects"
          className="w-full bg-gray-800 border border-gray-700 rounded-md px-2 py-1.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/60"
        />
      </div>

      {/* Content (static) or Query (dynamic) */}
      {form.context_type === 'static' ? (
        <div>
          <label className="block text-xs uppercase tracking-wider text-gray-500 mb-1">
            Content
          </label>
          <textarea
            value={form.content}
            onChange={e => update('content', e.target.value)}
            rows={6}
            placeholder="Markdown or plain text"
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-2 py-1.5 text-sm font-mono text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/60"
          />
        </div>
      ) : (
        <>
          <div>
            <label className="block text-xs uppercase tracking-wider text-gray-500 mb-1">
              SQL query (SELECT only)
            </label>
            <textarea
              value={form.query}
              onChange={e => update('query', e.target.value)}
              rows={6}
              placeholder="SELECT name, status FROM inventory.projects WHERE active = true"
              spellCheck={false}
              className="w-full bg-gray-800 border border-gray-700 rounded-md px-2 py-1.5 text-sm font-mono text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/60"
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-wider text-gray-500 mb-1">
              Refresh every (minutes)
            </label>
            <input
              type="number"
              value={form.refresh_minutes}
              onChange={e =>
                update(
                  'refresh_minutes',
                  Math.max(1, Math.min(1440, Number(e.target.value) || 0)),
                )
              }
              min={1}
              max={1440}
              className="w-32 bg-gray-800 border border-gray-700 rounded-md px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/60"
            />
            <span className="ml-2 text-xs text-gray-500">1 — 1440</span>
          </div>
        </>
      )}

      {/* Priority */}
      <div>
        <label className="block text-xs uppercase tracking-wider text-gray-500 mb-1">
          Priority
        </label>
        <input
          type="number"
          value={form.priority}
          onChange={e =>
            update(
              'priority',
              Math.max(1, Math.min(1000, Number(e.target.value) || 0)),
            )
          }
          min={1}
          max={1000}
          className="w-32 bg-gray-800 border border-gray-700 rounded-md px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/60"
        />
        <span className="ml-2 text-xs text-gray-500">
          lower = surfaces earlier in context (1 — 1000)
        </span>
      </div>

      {error && (
        <div className="rounded-md border border-red-700/40 bg-red-900/20 px-2.5 py-1.5 text-xs text-red-300">
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded-md text-sm bg-gray-800 text-gray-300 hover:bg-gray-700"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className={
            'px-3 py-1.5 rounded-md text-sm font-medium ' +
            (saving
              ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
              : 'bg-indigo-600 text-white hover:bg-indigo-500')
          }
        >
          {saving ? 'Saving…' : editing ? 'Save changes' : 'Create entry'}
        </button>
      </div>
    </form>
  )
}
