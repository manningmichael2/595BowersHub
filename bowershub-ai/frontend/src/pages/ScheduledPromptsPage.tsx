/**
 * ScheduledPromptsPage — Standalone page at `/scheduled-prompts`.
 *
 * Implements task 28.1:
 *   - Lists every scheduled prompt the caller has access to via
 *     `GET /api/scheduled-prompts`.
 *   - Columns: name, workspace, schedule (human-readable from the
 *     backend's `cron_human`, with the raw expression as a tooltip),
 *     delivery method, enabled toggle, last run status, actions.
 *   - Actions per row: Edit, Run Now, Disable / Enable, Delete.
 *   - Click a row to expand its last-10 log entries via
 *     `GET /api/scheduled-prompts/{id}/log?limit=10`.
 *   - "New scheduled prompt" button opens `<ScheduledPromptForm>` inline
 *     above the table (form is task 28.2 — already implemented).
 *
 * The backend (`backend/services/scheduled_prompts.py`) already supplies
 * `cron_human` so we don't pull in an extra `cronstrue` frontend
 * dependency for the listing path. The form (28.2) does its own
 * client-side cron preview while editing.
 *
 * _Requirements: R11.1, R11.7, R11.8, R11.9, R11.10_
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'
import ScheduledPromptForm, {
  type ScheduledPrompt,
} from '../components/ScheduledPromptForm'

// ---- Types ----------------------------------------------------------------

interface ScheduledPromptLogEntry {
  id: number
  executed_at: string | null
  success: boolean
  response_snippet: string | null
  error_message: string | null
}

type RunNowResponse = {
  ok?: boolean
  status?: string
  response_snippet?: string | null
  error?: string
}

// ---- Helpers --------------------------------------------------------------

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  // Show in local time. Date + 24h-style time is concise and unambiguous.
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function pickError(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  }
  return fallback
}

// ---- Page -----------------------------------------------------------------

type FormMode =
  | { kind: 'closed' }
  | { kind: 'create' }
  | { kind: 'edit'; promptId: number }

export default function ScheduledPromptsPage() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const workspaces = useWorkspaceStore(s => s.workspaces)
  const fetchWorkspaces = useWorkspaceStore(s => s.fetchWorkspaces)

  const [prompts, setPrompts] = useState<ScheduledPrompt[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [formMode, setFormMode] = useState<FormMode>({ kind: 'closed' })

  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [logsByPromptId, setLogsByPromptId] = useState<
    Record<number, { loading: boolean; error: string | null; entries: ScheduledPromptLogEntry[] }>
  >({})

  // Per-row action state — tracks which rows have an in-flight write so we
  // can disable buttons and surface inline status text.
  const [rowBusy, setRowBusy] = useState<Record<number, string>>({})
  const [rowFlash, setRowFlash] = useState<Record<number, { text: string; tone: 'ok' | 'err' }>>({})

  // ---- Data loading -------------------------------------------------------

  const loadPrompts = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await api.get('/api/scheduled-prompts')
      setPrompts((res.data as ScheduledPrompt[]) || [])
    } catch (err) {
      setLoadError(pickError(err, 'Failed to load scheduled prompts.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPrompts()
  }, [loadPrompts])

  useEffect(() => {
    if (workspaces.length === 0) {
      fetchWorkspaces().catch(() => {
        // Workspace name lookup degrades to the numeric id if this fails.
      })
    }
  }, [workspaces.length, fetchWorkspaces])

  const workspaceNameById = useMemo(() => {
    const m = new Map<number, string>()
    for (const w of workspaces) m.set(w.id, w.name)
    return m
  }, [workspaces])

  // ---- Row actions --------------------------------------------------------

  const flash = (id: number, text: string, tone: 'ok' | 'err') => {
    setRowFlash(prev => ({ ...prev, [id]: { text, tone } }))
    window.setTimeout(() => {
      setRowFlash(prev => {
        const next = { ...prev }
        delete next[id]
        return next
      })
    }, 4000)
  }

  const setBusy = (id: number, label: string | null) => {
    setRowBusy(prev => {
      const next = { ...prev }
      if (label) next[id] = label
      else delete next[id]
      return next
    })
  }

  const handleToggle = async (p: ScheduledPrompt) => {
    setBusy(p.id, p.is_enabled ? 'Disabling…' : 'Enabling…')
    try {
      const res = await api.post(`/api/scheduled-prompts/${p.id}/toggle`, {
        enabled: !p.is_enabled,
      })
      const updated = res.data as ScheduledPrompt
      setPrompts(prev => prev.map(x => (x.id === p.id ? { ...x, ...updated } : x)))
      flash(p.id, updated.is_enabled ? 'Enabled' : 'Disabled', 'ok')
    } catch (err) {
      flash(p.id, pickError(err, 'Toggle failed.'), 'err')
    } finally {
      setBusy(p.id, null)
    }
  }

  const handleRunNow = async (p: ScheduledPrompt) => {
    setBusy(p.id, 'Running…')
    try {
      const res = await api.post(`/api/scheduled-prompts/${p.id}/run-now`)
      const data = res.data as RunNowResponse
      const status = data.status || (data.ok ? 'success' : 'queued')
      flash(p.id, `Run started · ${status}`, 'ok')
      // If the row is currently expanded, refresh its log so the new entry
      // shows up at the top.
      if (expandedId === p.id) {
        await loadLog(p.id, { force: true })
      }
      // Refresh the row's last_run / last_status fields by reloading the
      // list — cheap enough for a list this size and keeps things honest.
      loadPrompts().catch(() => {})
    } catch (err) {
      flash(p.id, pickError(err, 'Run failed.'), 'err')
    } finally {
      setBusy(p.id, null)
    }
  }

  const handleDelete = async (p: ScheduledPrompt) => {
    const ok = window.confirm(
      `Delete scheduled prompt "${p.name}"? This cannot be undone.`,
    )
    if (!ok) return
    setBusy(p.id, 'Deleting…')
    try {
      await api.delete(`/api/scheduled-prompts/${p.id}`)
      setPrompts(prev => prev.filter(x => x.id !== p.id))
      if (expandedId === p.id) setExpandedId(null)
    } catch (err) {
      flash(p.id, pickError(err, 'Delete failed.'), 'err')
    } finally {
      setBusy(p.id, null)
    }
  }

  // ---- Log expansion ------------------------------------------------------

  const loadLog = useCallback(
    async (id: number, opts: { force?: boolean } = {}) => {
      const existing = logsByPromptId[id]
      if (existing && !opts.force) return
      setLogsByPromptId(prev => ({
        ...prev,
        [id]: { loading: true, error: null, entries: existing?.entries ?? [] },
      }))
      try {
        const res = await api.get(`/api/scheduled-prompts/${id}/log?limit=10`)
        setLogsByPromptId(prev => ({
          ...prev,
          [id]: {
            loading: false,
            error: null,
            entries: (res.data as ScheduledPromptLogEntry[]) || [],
          },
        }))
      } catch (err) {
        setLogsByPromptId(prev => ({
          ...prev,
          [id]: {
            loading: false,
            error: pickError(err, 'Failed to load log.'),
            entries: existing?.entries ?? [],
          },
        }))
      }
    },
    [logsByPromptId],
  )

  const toggleExpand = (p: ScheduledPrompt) => {
    if (expandedId === p.id) {
      setExpandedId(null)
      return
    }
    setExpandedId(p.id)
    loadLog(p.id).catch(() => {})
  }

  // ---- Form callbacks -----------------------------------------------------

  const handleFormSave = (saved: ScheduledPrompt) => {
    setPrompts(prev => {
      const idx = prev.findIndex(x => x.id === saved.id)
      if (idx === -1) return [saved, ...prev]
      const next = [...prev]
      next[idx] = { ...next[idx], ...saved }
      return next
    })
    setFormMode({ kind: 'closed' })
    flash(saved.id, 'Saved', 'ok')
  }

  // ---- Render -------------------------------------------------------------

  return (
    <div className="min-h-screen bg-[#1a1a2e] text-gray-200 flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-800 px-4 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400"
          aria-label="Back"
        >
          ← Back
        </button>
        <h1 className="text-lg font-medium flex items-center gap-2">
          <span aria-hidden="true">⏰</span>
          Scheduled prompts
        </h1>
        <div className="ml-auto">
          <button
            type="button"
            onClick={() => setFormMode({ kind: 'create' })}
            disabled={formMode.kind !== 'closed'}
            className={
              'px-3 py-1.5 rounded-md text-sm font-medium ' +
              (formMode.kind !== 'closed'
                ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                : 'bg-indigo-600 text-white hover:bg-indigo-500')
            }
          >
            + New scheduled prompt
          </button>
        </div>
      </div>

      <div className="flex-1 max-w-5xl w-full mx-auto p-4 md:p-6 space-y-4">
        <p className="text-sm text-gray-400">
          Run a saved prompt on a cron schedule. Results either get pinned to
          the workspace conversation or pushed to your phone via Pushover.
        </p>

        {/* Inline form panel — render above the table so it stays visible
            on small screens without scrolling. */}
        {formMode.kind !== 'closed' && (
          <ScheduledPromptForm
            existingPromptId={
              formMode.kind === 'edit' ? formMode.promptId : undefined
            }
            onSave={handleFormSave}
            onCancel={() => setFormMode({ kind: 'closed' })}
          />
        )}

        {/* Load state */}
        {loading && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-6 text-sm text-gray-400">
            Loading scheduled prompts…
          </div>
        )}

        {!loading && loadError && (
          <div className="rounded-lg border border-red-700/40 bg-red-900/20 p-4 space-y-3">
            <div className="text-sm text-red-300">{loadError}</div>
            <button
              type="button"
              onClick={loadPrompts}
              className="px-3 py-1.5 rounded-md text-sm bg-gray-800 text-gray-200 hover:bg-gray-700"
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !loadError && prompts.length === 0 && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-8 text-center space-y-3">
            <div className="text-3xl" aria-hidden="true">⏰</div>
            <div className="text-sm text-gray-300">
              No scheduled prompts yet.
            </div>
            <div className="text-xs text-gray-500">
              Create one to have BowersHub AI run a prompt on a schedule and
              deliver the result to a workspace or to your phone.
            </div>
            <button
              type="button"
              onClick={() => setFormMode({ kind: 'create' })}
              className="px-3 py-1.5 rounded-md text-sm bg-indigo-600 text-white hover:bg-indigo-500"
            >
              + New scheduled prompt
            </button>
          </div>
        )}

        {/* Table */}
        {!loading && !loadError && prompts.length > 0 && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-900/70 text-xs uppercase tracking-wider text-gray-500">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Name</th>
                    <th className="text-left px-3 py-2 font-medium">Workspace</th>
                    <th className="text-left px-3 py-2 font-medium">Schedule</th>
                    <th className="text-left px-3 py-2 font-medium">Delivery</th>
                    <th className="text-left px-3 py-2 font-medium">Enabled</th>
                    <th className="text-left px-3 py-2 font-medium">Last run</th>
                    <th className="text-right px-3 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {prompts.map(p => {
                    const isExpanded = expandedId === p.id
                    const busyLabel = rowBusy[p.id]
                    const flashEntry = rowFlash[p.id]
                    const wsName =
                      workspaceNameById.get(p.workspace_id) ??
                      `Workspace ${p.workspace_id}`
                    const scheduleHuman =
                      p.cron_human && p.cron_human.length > 0
                        ? p.cron_human
                        : p.cron_expression
                    return (
                      <PromptRow
                        key={p.id}
                        prompt={p}
                        workspaceName={wsName}
                        scheduleHuman={scheduleHuman}
                        isExpanded={isExpanded}
                        busyLabel={busyLabel}
                        flashEntry={flashEntry}
                        onToggleExpand={() => toggleExpand(p)}
                        onEdit={() =>
                          setFormMode({ kind: 'edit', promptId: p.id })
                        }
                        onRunNow={() => handleRunNow(p)}
                        onToggle={() => handleToggle(p)}
                        onDelete={() => handleDelete(p)}
                        logState={logsByPromptId[p.id]}
                      />
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Footer hint — admin-only nudge that scheduled prompts are stored
            as `bh_hooks` rows under the hood. Helps with debugging without
            cluttering the UI for regular users. */}
        {user?.role === 'admin' && prompts.length > 0 && (
          <div className="text-[11px] text-gray-600">
            Scheduled prompts are stored as
            <code className="mx-1 px-1 py-0.5 rounded bg-gray-800 text-gray-400">
              bh_hooks
            </code>
            rows with
            <code className="mx-1 px-1 py-0.5 rounded bg-gray-800 text-gray-400">
              event_type=schedule
            </code>
            and
            <code className="mx-1 px-1 py-0.5 rounded bg-gray-800 text-gray-400">
              action_type=call_ai
            </code>
            .
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Row ------------------------------------------------------------------

interface PromptRowProps {
  prompt: ScheduledPrompt
  workspaceName: string
  scheduleHuman: string
  isExpanded: boolean
  busyLabel: string | undefined
  flashEntry: { text: string; tone: 'ok' | 'err' } | undefined
  onToggleExpand: () => void
  onEdit: () => void
  onRunNow: () => void
  onToggle: () => void
  onDelete: () => void
  logState:
    | { loading: boolean; error: string | null; entries: ScheduledPromptLogEntry[] }
    | undefined
}

function PromptRow({
  prompt,
  workspaceName,
  scheduleHuman,
  isExpanded,
  busyLabel,
  flashEntry,
  onToggleExpand,
  onEdit,
  onRunNow,
  onToggle,
  onDelete,
  logState,
}: PromptRowProps) {
  const isBusy = !!busyLabel
  const lastStatus = prompt.last_status

  return (
    <>
      <tr
        className={
          'border-t border-gray-800 transition-colors ' +
          (isExpanded ? 'bg-indigo-900/10' : 'hover:bg-gray-800/40')
        }
      >
        {/* Name + chevron — clicking the name toggles the log expansion. */}
        <td className="px-3 py-2 align-top">
          <button
            type="button"
            onClick={onToggleExpand}
            className="flex items-start gap-1.5 text-left text-gray-100 hover:text-white"
            aria-expanded={isExpanded}
          >
            <span
              className={
                'mt-0.5 inline-block transition-transform ' +
                (isExpanded ? 'rotate-90 text-indigo-300' : 'text-gray-500')
              }
              aria-hidden="true"
            >
              ▸
            </span>
            <span className="font-medium">{prompt.name}</span>
          </button>
          {flashEntry && (
            <div
              className={
                'mt-1 text-[11px] ' +
                (flashEntry.tone === 'ok'
                  ? 'text-emerald-300'
                  : 'text-red-300')
              }
            >
              {flashEntry.text}
            </div>
          )}
        </td>

        {/* Workspace */}
        <td className="px-3 py-2 align-top text-gray-300">{workspaceName}</td>

        {/* Schedule — show the human form, with the raw expression as a
            tooltip and as a small monospace line below. */}
        <td className="px-3 py-2 align-top">
          <div
            className="text-gray-200"
            title={prompt.cron_expression}
          >
            {scheduleHuman}
          </div>
          {scheduleHuman !== prompt.cron_expression && (
            <div className="font-mono text-[11px] text-gray-500">
              {prompt.cron_expression}
            </div>
          )}
        </td>

        {/* Delivery */}
        <td className="px-3 py-2 align-top">
          <DeliveryBadge method={prompt.delivery_method} />
        </td>

        {/* Enabled toggle */}
        <td className="px-3 py-2 align-top">
          <button
            type="button"
            onClick={onToggle}
            disabled={isBusy}
            className={
              'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ' +
              (prompt.is_enabled
                ? 'bg-emerald-900/30 text-emerald-300'
                : 'bg-gray-800 text-gray-400') +
              (isBusy ? ' opacity-60 cursor-wait' : ' hover:opacity-80')
            }
            aria-pressed={prompt.is_enabled}
          >
            <span
              className={
                'inline-block w-2 h-2 rounded-full ' +
                (prompt.is_enabled ? 'bg-emerald-400' : 'bg-gray-500')
              }
            />
            {prompt.is_enabled ? 'Enabled' : 'Disabled'}
          </button>
        </td>

        {/* Last run */}
        <td className="px-3 py-2 align-top">
          <div className="text-gray-300">{formatTimestamp(prompt.last_run)}</div>
          {lastStatus && (
            <div
              className={
                'text-[11px] ' +
                (lastStatus === 'success'
                  ? 'text-emerald-400'
                  : lastStatus === 'error'
                    ? 'text-red-400'
                    : 'text-gray-500')
              }
            >
              {lastStatus}
            </div>
          )}
        </td>

        {/* Actions */}
        <td className="px-3 py-2 align-top text-right">
          <div className="inline-flex flex-wrap justify-end gap-1.5">
            <RowAction onClick={onEdit} disabled={isBusy} label="Edit" />
            <RowAction
              onClick={onRunNow}
              disabled={isBusy}
              label={busyLabel === 'Running…' ? 'Running…' : 'Run now'}
              tone="primary"
            />
            <RowAction
              onClick={onToggle}
              disabled={isBusy}
              label={prompt.is_enabled ? 'Disable' : 'Enable'}
            />
            <RowAction
              onClick={onDelete}
              disabled={isBusy}
              label={busyLabel === 'Deleting…' ? 'Deleting…' : 'Delete'}
              tone="danger"
            />
          </div>
        </td>
      </tr>

      {/* Expanded log row */}
      {isExpanded && (
        <tr className="bg-gray-950/60 border-t border-gray-800">
          <td colSpan={7} className="px-3 py-3">
            <PromptLog
              promptId={prompt.id}
              promptTemplate={prompt.prompt_template}
              state={logState}
            />
          </td>
        </tr>
      )}
    </>
  )
}

// ---- Sub-components -------------------------------------------------------

function DeliveryBadge({ method }: { method: string }) {
  if (method === 'pushover') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-amber-900/30 px-2 py-0.5 text-xs text-amber-300">
        <span aria-hidden="true">📲</span> Pushover
      </span>
    )
  }
  // Default to "pin" rendering — the backend constrains this to {pin, pushover}.
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-indigo-900/30 px-2 py-0.5 text-xs text-indigo-300">
      <span aria-hidden="true">📌</span> Pinned in workspace
    </span>
  )
}

interface RowActionProps {
  label: string
  onClick: () => void
  disabled?: boolean
  tone?: 'default' | 'primary' | 'danger'
}

function RowAction({ label, onClick, disabled, tone = 'default' }: RowActionProps) {
  const toneClass =
    tone === 'danger'
      ? 'bg-red-900/30 text-red-300 hover:bg-red-900/50'
      : tone === 'primary'
        ? 'bg-indigo-900/30 text-indigo-200 hover:bg-indigo-900/50'
        : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={
        'px-2 py-1 rounded-md text-xs ' +
        toneClass +
        (disabled ? ' opacity-50 cursor-not-allowed' : '')
      }
    >
      {label}
    </button>
  )
}

interface PromptLogProps {
  promptId: number
  promptTemplate: string
  state:
    | { loading: boolean; error: string | null; entries: ScheduledPromptLogEntry[] }
    | undefined
}

function PromptLog({ promptId, promptTemplate, state }: PromptLogProps) {
  if (!state || state.loading) {
    return <div className="text-xs text-gray-500">Loading log entries…</div>
  }
  if (state.error) {
    return <div className="text-xs text-red-400">{state.error}</div>
  }
  return (
    <div className="space-y-3">
      {/* Show the prompt template up top — useful when triaging a row. */}
      {promptTemplate && (
        <details className="rounded border border-gray-800 bg-gray-900/40">
          <summary className="cursor-pointer px-2 py-1 text-[11px] uppercase tracking-wider text-gray-500 hover:text-gray-300">
            Prompt template
          </summary>
          <pre className="px-2 py-2 text-xs whitespace-pre-wrap text-gray-300">
            {promptTemplate}
          </pre>
        </details>
      )}

      <div>
        <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
          Last 10 runs
        </div>
        {state.entries.length === 0 ? (
          <div className="text-xs text-gray-500 italic">
            No runs yet for prompt #{promptId}.
          </div>
        ) : (
          <ul className="space-y-1.5">
            {state.entries.map(entry => (
              <li
                key={entry.id}
                className={
                  'rounded border px-2.5 py-1.5 text-xs ' +
                  (entry.success
                    ? 'border-emerald-900/40 bg-emerald-950/20'
                    : 'border-red-900/40 bg-red-950/20')
                }
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-gray-400">
                    {formatTimestamp(entry.executed_at)}
                  </span>
                  <span
                    className={
                      'rounded-full px-1.5 py-0.5 text-[10px] ' +
                      (entry.success
                        ? 'bg-emerald-900/40 text-emerald-300'
                        : 'bg-red-900/40 text-red-300')
                    }
                  >
                    {entry.success ? 'success' : 'error'}
                  </span>
                </div>
                {entry.response_snippet && (
                  <div className="mt-1 whitespace-pre-wrap text-gray-300">
                    {entry.response_snippet}
                  </div>
                )}
                {entry.error_message && (
                  <div className="mt-1 whitespace-pre-wrap text-red-300">
                    {entry.error_message}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
