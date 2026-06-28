/**
 * ScheduledPromptForm — Create / edit a scheduled prompt.
 *
 * Implements task 28.2:
 *   - Fields: name, target workspace (limited to those the user has access
 *     to), prompt-template textarea, schedule (raw cron input + friendly
 *     preset picker), delivery-method radio (`pin` / `pushover`).
 *   - Friendly preset picker covers "every day at HH:MM",
 *     "weekly on <weekday> at HH:MM", and "monthly on day D at HH:MM",
 *     each translating to a 5-field cron expression client-side.
 *   - Client-side cron validation gives the user instant feedback. The
 *     backend is still authoritative — a 400 from POST/PATCH is surfaced
 *     inline alongside a link to the cron-expression help.
 *   - On submit, POSTs to `/api/scheduled-prompts` (or PATCHes when
 *     `existingPromptId` is set) and calls `onSave(prompt)` with the
 *     server response. On cancel, calls `onCancel()`.
 *
 * Props:
 *   - existingPromptId?: number  // when provided, loads the prompt and
 *                                // PATCHes on save; otherwise creates.
 *   - onSave:    (prompt) => void
 *   - onCancel:  () => void
 *   - workspaceId?: number       // optional default-selected workspace
 *
 * _Requirements: R11.2, R11.3, R11.11_
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../services/api'
import { useWorkspaceStore } from '../stores/workspace'

// ---- Types ----------------------------------------------------------------

type DeliveryMethod = 'pin' | 'pushover'

type ScheduleMode = 'daily' | 'weekly' | 'monthly' | 'custom'

export interface ScheduledPrompt {
  id: number
  name: string
  workspace_id: number
  prompt_template: string
  cron_expression: string
  cron_human?: string
  delivery_method: DeliveryMethod
  is_enabled: boolean
  last_run: string | null
  last_status: string | null
  description?: string | null
}

export interface ScheduledPromptFormProps {
  existingPromptId?: number
  workspaceId?: number
  onSave: (prompt: ScheduledPrompt) => void
  onCancel: () => void
}

interface FormState {
  name: string
  workspace_id: number | null
  prompt_template: string
  delivery_method: DeliveryMethod
  scheduleMode: ScheduleMode
  // Friendly-picker state. The cron expression is derived from these for
  // daily / weekly / monthly modes; for `custom`, the raw `cron_custom`
  // value is used as-is.
  hour: number              // 0..23
  minute: number            // 0..59
  weekday: number           // 0 (Sun) .. 6 (Sat) — used in weekly mode
  monthDay: number          // 1..31         — used in monthly mode
  cron_custom: string
}

const DEFAULT_FORM: FormState = {
  name: '',
  workspace_id: null,
  prompt_template: '',
  delivery_method: 'pin',
  scheduleMode: 'daily',
  hour: 7,
  minute: 0,
  weekday: 1, // Monday
  monthDay: 1,
  cron_custom: '0 7 * * *',
}

const WEEKDAYS = [
  { value: 0, label: 'Sunday' },
  { value: 1, label: 'Monday' },
  { value: 2, label: 'Tuesday' },
  { value: 3, label: 'Wednesday' },
  { value: 4, label: 'Thursday' },
  { value: 5, label: 'Friday' },
  { value: 6, label: 'Saturday' },
] as const

// ---- Cron helpers ---------------------------------------------------------

/**
 * Build a 5-field cron expression from the friendly-picker fields.
 * Standard order: minute hour day-of-month month day-of-week.
 */
function buildCron(form: FormState): string {
  const m = clamp(form.minute, 0, 59)
  const h = clamp(form.hour, 0, 23)
  switch (form.scheduleMode) {
    case 'daily':
      return `${m} ${h} * * *`
    case 'weekly':
      return `${m} ${h} * * ${clamp(form.weekday, 0, 6)}`
    case 'monthly':
      return `${m} ${h} ${clamp(form.monthDay, 1, 31)} * *`
    case 'custom':
      return form.cron_custom.trim()
  }
}

/**
 * Lightweight cron validator. Recognizes the standard 5-field format
 * with `*`, lists, ranges, and step values per field. This is *not* a
 * full croniter replacement — the backend re-validates with croniter
 * (R11.11) and is the authoritative check. The point here is to catch
 * obvious mistakes before round-tripping to the server.
 */
function validateCronClient(expr: string): { ok: true } | { ok: false; reason: string } {
  const trimmed = (expr || '').trim()
  if (!trimmed) return { ok: false, reason: 'Cron expression is required.' }
  const fields = trimmed.split(/\s+/)
  if (fields.length !== 5) {
    return { ok: false, reason: 'Cron must have 5 space-separated fields.' }
  }
  const ranges: Array<[number, number]> = [
    [0, 59], // minute
    [0, 23], // hour
    [1, 31], // day-of-month
    [1, 12], // month
    [0, 7],  // day-of-week (0 and 7 both mean Sunday)
  ]
  for (let i = 0; i < 5; i++) {
    const f = fields[i]
    const [lo, hi] = ranges[i]
    if (!isValidCronField(f, lo, hi)) {
      return { ok: false, reason: `Field ${i + 1} ("${f}") is not a valid cron value.` }
    }
  }
  return { ok: true }
}

function isValidCronField(field: string, lo: number, hi: number): boolean {
  if (!field) return false
  // Comma-separated list: each part validated independently.
  return field.split(',').every(part => isValidCronPart(part, lo, hi))
}

function isValidCronPart(part: string, lo: number, hi: number): boolean {
  // Step expression: `*/N` or `lo-hi/N` or `N/M`.
  if (part.includes('/')) {
    const [head, stepStr] = part.split('/')
    if (head === undefined || stepStr === undefined) return false
    const step = Number(stepStr)
    if (!Number.isInteger(step) || step <= 0) return false
    if (head === '*' || head === '') return true
    return isValidCronPart(head, lo, hi) // recurse to validate the head
  }
  if (part === '*') return true
  if (part.includes('-')) {
    const [aStr, bStr] = part.split('-')
    const a = Number(aStr)
    const b = Number(bStr)
    if (!Number.isInteger(a) || !Number.isInteger(b)) return false
    if (a < lo || b > hi || a > b) return false
    return true
  }
  const n = Number(part)
  return Number.isInteger(n) && n >= lo && n <= hi
}

/**
 * Build a friendly description for the cron expression. Covers the
 * common "every day at H:MM", "every week on Day at H:MM", and
 * "every month on the Nth at H:MM" patterns produced by the friendly
 * picker. Falls back to the raw expression for anything else — the
 * backend supplies a real human-readable form (`cron_human`) when the
 * row is fetched, so this is just instant feedback while editing.
 */
function describeCron(expr: string): string {
  const v = validateCronClient(expr)
  if (!v.ok) return ''
  const fields = expr.trim().split(/\s+/)
  const [min, hr, dom, mon, dow] = fields
  const minN = Number(min)
  const hrN = Number(hr)
  const isSimpleTime =
    Number.isInteger(minN) && Number.isInteger(hrN) && minN >= 0 && hrN >= 0
  if (!isSimpleTime) return expr
  const time = formatTime(hrN, minN)

  // Daily: minute hour * * *
  if (dom === '*' && mon === '*' && dow === '*') {
    return `Every day at ${time}`
  }
  // Weekly: minute hour * * D
  if (dom === '*' && mon === '*' && /^[0-7]$/.test(dow)) {
    const dayName = WEEKDAYS[Number(dow) % 7]?.label ?? dow
    return `Every ${dayName} at ${time}`
  }
  // Monthly: minute hour D * *
  if (mon === '*' && dow === '*' && /^\d{1,2}$/.test(dom)) {
    return `On day ${dom} of every month at ${time}`
  }
  return expr
}

function formatTime(hour: number, minute: number): string {
  const h = clamp(hour, 0, 23)
  const m = clamp(minute, 0, 59)
  const hh = h.toString().padStart(2, '0')
  const mm = m.toString().padStart(2, '0')
  return `${hh}:${mm}`
}

function clamp(n: number, lo: number, hi: number): number {
  if (Number.isNaN(n)) return lo
  return Math.max(lo, Math.min(hi, Math.trunc(n)))
}

/**
 * Best-effort reverse mapping: given a cron expression, infer which
 * picker mode it came from and fill the other fields. Used when
 * loading an existing prompt for editing so the friendly picker stays
 * in sync where possible.
 */
function inferModeFromCron(expr: string): Partial<FormState> {
  const v = validateCronClient(expr)
  if (!v.ok) {
    return { scheduleMode: 'custom', cron_custom: expr }
  }
  const fields = expr.trim().split(/\s+/)
  const [min, hr, dom, mon, dow] = fields
  const minN = Number(min)
  const hrN = Number(hr)
  const simple = Number.isInteger(minN) && Number.isInteger(hrN)
  if (!simple) return { scheduleMode: 'custom', cron_custom: expr }

  if (dom === '*' && mon === '*' && dow === '*') {
    return { scheduleMode: 'daily', hour: hrN, minute: minN, cron_custom: expr }
  }
  if (dom === '*' && mon === '*' && /^[0-7]$/.test(dow)) {
    return {
      scheduleMode: 'weekly',
      hour: hrN,
      minute: minN,
      weekday: Number(dow) % 7,
      cron_custom: expr,
    }
  }
  if (mon === '*' && dow === '*' && /^\d{1,2}$/.test(dom)) {
    return {
      scheduleMode: 'monthly',
      hour: hrN,
      minute: minN,
      monthDay: Number(dom),
      cron_custom: expr,
    }
  }
  return { scheduleMode: 'custom', cron_custom: expr }
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

// ---- Component ------------------------------------------------------------

export default function ScheduledPromptForm({
  existingPromptId,
  workspaceId,
  onSave,
  onCancel,
}: ScheduledPromptFormProps) {
  const workspaces = useWorkspaceStore(s => s.workspaces)
  const fetchWorkspaces = useWorkspaceStore(s => s.fetchWorkspaces)

  const [form, setForm] = useState<FormState>({
    ...DEFAULT_FORM,
    workspace_id:
      typeof workspaceId === 'number' ? workspaceId : DEFAULT_FORM.workspace_id,
  })
  const [loading, setLoading] = useState<boolean>(!!existingPromptId)
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Hydrate workspaces if the store is empty.
  useEffect(() => {
    if (workspaces.length === 0) {
      fetchWorkspaces().catch(() => {
        // The store handles its own errors; we just leave workspace_id null
        // and the user can retry via the cancel/reopen flow.
      })
    }
  }, [workspaces.length, fetchWorkspaces])

  // If editing, load the existing prompt.
  useEffect(() => {
    if (!existingPromptId) return
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    api
      .get(`/api/scheduled-prompts/${existingPromptId}`)
      .then(res => {
        if (cancelled) return
        const p = res.data as ScheduledPrompt
        const inferred = inferModeFromCron(p.cron_expression || '')
        setForm(prev => ({
          ...prev,
          name: p.name || '',
          workspace_id: p.workspace_id,
          prompt_template: p.prompt_template || '',
          delivery_method: (p.delivery_method as DeliveryMethod) || 'pin',
          cron_custom: p.cron_expression || prev.cron_custom,
          ...inferred,
        }))
      })
      .catch(err => {
        if (cancelled) return
        // The backend service exposes only list/create/update/delete/log
        // by hook id; fall back to listing-and-finding if /:id 404s.
        if (err?.response?.status === 404 || err?.response?.status === 405) {
          api
            .get('/api/scheduled-prompts')
            .then(res2 => {
              if (cancelled) return
              const list = (res2.data as ScheduledPrompt[]) || []
              const p = list.find(x => x.id === existingPromptId)
              if (!p) {
                setLoadError('Scheduled prompt not found.')
                return
              }
              const inferred = inferModeFromCron(p.cron_expression || '')
              setForm(prev => ({
                ...prev,
                name: p.name || '',
                workspace_id: p.workspace_id,
                prompt_template: p.prompt_template || '',
                delivery_method: (p.delivery_method as DeliveryMethod) || 'pin',
                cron_custom: p.cron_expression || prev.cron_custom,
                ...inferred,
              }))
            })
            .catch(err2 => {
              if (cancelled) return
              setLoadError(pickError(err2, 'Failed to load scheduled prompt.'))
            })
            .finally(() => {
              if (!cancelled) setLoading(false)
            })
          return
        }
        setLoadError(pickError(err, 'Failed to load scheduled prompt.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [existingPromptId])

  const cronExpression = useMemo(() => buildCron(form), [form])
  const cronValidation = useMemo(
    () => validateCronClient(cronExpression),
    [cronExpression],
  )
  const cronHuman = useMemo(() => describeCron(cronExpression), [cronExpression])

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm(prev => ({ ...prev, [key]: value }))

  const validate = (): string | null => {
    if (!form.name.trim()) return 'Name is required.'
    if (form.name.trim().length > 200) return 'Name must be 200 characters or fewer.'
    if (typeof form.workspace_id !== 'number') return 'Pick a target workspace.'
    if (!form.prompt_template.trim()) return 'Prompt template is required.'
    if (!cronValidation.ok) return cronValidation.reason
    return null
  }

  const submit = async () => {
    const err = validate()
    if (err) {
      setSubmitError(err)
      return
    }
    setSaving(true)
    setSubmitError(null)
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        prompt_template: form.prompt_template,
        cron_expression: cronExpression,
        delivery_method: form.delivery_method,
      }
      let res
      if (existingPromptId) {
        res = await api.patch(
          `/api/scheduled-prompts/${existingPromptId}`,
          payload,
        )
      } else {
        // workspace_id is only valid on create — the backend rejects it on PATCH.
        payload.workspace_id = form.workspace_id
        res = await api.post('/api/scheduled-prompts', payload)
      }
      onSave(res.data as ScheduledPrompt)
    } catch (e: any) {
      setSubmitError(pickError(e, 'Failed to save scheduled prompt.'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-surface p-6 text-sm text-text-muted">
        Loading scheduled prompt…
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="rounded-lg border border-danger/40 bg-danger/20 p-4 space-y-3">
        <div className="text-sm text-danger">{loadError}</div>
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 rounded-md text-sm bg-surface text-text hover:bg-surface-light"
          >
            Close
          </button>
        </div>
      </div>
    )
  }

  return (
    <form
      onSubmit={e => {
        e.preventDefault()
        submit()
      }}
      className="rounded-lg border border-primary/40 bg-primary/10 p-4 space-y-4"
    >
      <div className="text-sm font-medium text-text">
        {existingPromptId ? 'Edit scheduled prompt' : 'New scheduled prompt'}
      </div>

      {/* Name */}
      <div>
        <label className="block text-xs uppercase tracking-wider text-text-muted mb-1">
          Name
        </label>
        <input
          type="text"
          value={form.name}
          onChange={e => update('name', e.target.value)}
          maxLength={200}
          placeholder="e.g. Morning briefing"
          className="w-full bg-surface border border-border rounded-md px-2 py-1.5 text-sm text-text placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-primary/60 focus:border-primary/60"
        />
      </div>

      {/* Workspace */}
      <div>
        <label className="block text-xs uppercase tracking-wider text-text-muted mb-1">
          Target workspace
        </label>
        <select
          value={form.workspace_id ?? ''}
          onChange={e =>
            update(
              'workspace_id',
              e.target.value === '' ? null : Number(e.target.value),
            )
          }
          disabled={!!existingPromptId}
          className="w-full bg-surface border border-border rounded-md px-2 py-1.5 text-sm text-text disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-primary/60 focus:border-primary/60"
        >
          <option value="">— select a workspace —</option>
          {workspaces.map(w => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        {existingPromptId && (
          <div className="mt-1 text-[11px] text-text-muted">
            The target workspace is fixed once a scheduled prompt is created.
          </div>
        )}
      </div>

      {/* Prompt template */}
      <div>
        <label className="block text-xs uppercase tracking-wider text-text-muted mb-1">
          Prompt template
        </label>
        <textarea
          value={form.prompt_template}
          onChange={e => update('prompt_template', e.target.value)}
          rows={5}
          placeholder="e.g. Summarize yesterday's spending and flag anything over $100."
          className="w-full bg-surface border border-border rounded-md px-2 py-1.5 text-sm font-mono text-text placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-primary/60 focus:border-primary/60"
        />
      </div>

      {/* Schedule */}
      <div className="space-y-3">
        <div className="text-xs uppercase tracking-wider text-text-muted">
          Schedule
        </div>

        {/* Mode picker */}
        <div className="flex flex-wrap gap-2">
          {(
            [
              { id: 'daily', label: 'Every day' },
              { id: 'weekly', label: 'Weekly' },
              { id: 'monthly', label: 'Monthly' },
              { id: 'custom', label: 'Custom cron' },
            ] as Array<{ id: ScheduleMode; label: string }>
          ).map(opt => (
            <button
              key={opt.id}
              type="button"
              onClick={() => update('scheduleMode', opt.id)}
              className={
                'px-3 py-1.5 rounded-md text-sm border ' +
                (form.scheduleMode === opt.id
                  ? 'border-primary bg-primary/20 text-primary'
                  : 'border-border bg-surface text-text-muted hover:bg-surface-light')
              }
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Mode-specific fields */}
        {form.scheduleMode !== 'custom' && (
          <div className="flex flex-wrap items-end gap-3">
            <TimePicker
              hour={form.hour}
              minute={form.minute}
              onChange={(h, m) =>
                setForm(prev => ({ ...prev, hour: h, minute: m }))
              }
            />
            {form.scheduleMode === 'weekly' && (
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-text-muted mb-1">
                  Day of week
                </label>
                <select
                  value={form.weekday}
                  onChange={e => update('weekday', Number(e.target.value))}
                  className="bg-surface border border-border rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-primary/60 focus:border-primary/60"
                >
                  {WEEKDAYS.map(d => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {form.scheduleMode === 'monthly' && (
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-text-muted mb-1">
                  Day of month
                </label>
                <input
                  type="number"
                  value={form.monthDay}
                  onChange={e =>
                    update('monthDay', clamp(Number(e.target.value) || 1, 1, 31))
                  }
                  min={1}
                  max={31}
                  className="w-24 bg-surface border border-border rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-primary/60 focus:border-primary/60"
                />
              </div>
            )}
          </div>
        )}

        {form.scheduleMode === 'custom' && (
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-text-muted mb-1">
              Cron expression (5 fields: minute hour day-of-month month day-of-week)
            </label>
            <input
              type="text"
              value={form.cron_custom}
              onChange={e => update('cron_custom', e.target.value)}
              spellCheck={false}
              placeholder="0 7 * * *"
              className="w-full bg-surface border border-border rounded-md px-2 py-1.5 text-sm font-mono text-text placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-primary/60 focus:border-primary/60"
            />
          </div>
        )}

        {/* Cron preview / validation */}
        <div
          className={
            'rounded-md border px-2.5 py-1.5 text-xs ' +
            (cronValidation.ok
              ? 'border-success/40 bg-success/10 text-success'
              : 'border-warning/40 bg-warning/10 text-warning')
          }
        >
          {cronValidation.ok ? (
            <>
              <span className="font-mono">{cronExpression}</span>
              {cronHuman && cronHuman !== cronExpression && (
                <span className="opacity-80"> · {cronHuman}</span>
              )}
            </>
          ) : (
            <>
              {cronValidation.reason}{' '}
              <a
                href="https://crontab.guru/"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-warning"
              >
                cron help
              </a>
            </>
          )}
        </div>
      </div>

      {/* Delivery method */}
      <div>
        <div className="text-xs uppercase tracking-wider text-text-muted mb-1">
          Delivery method
        </div>
        <div className="flex flex-wrap gap-2">
          {(
            [
              {
                id: 'pin' as const,
                label: 'Pin in workspace',
                desc: 'Pinned system message in the workspace conversation.',
              },
              {
                id: 'pushover' as const,
                label: 'Pushover',
                desc: 'Push notification on your phone (truncated to 1000 chars).',
              },
            ] as Array<{ id: DeliveryMethod; label: string; desc: string }>
          ).map(opt => {
            const active = form.delivery_method === opt.id
            return (
              <label
                key={opt.id}
                className={
                  'flex-1 min-w-[14rem] cursor-pointer rounded-md border px-3 py-2 ' +
                  (active
                    ? 'border-primary bg-primary/20 text-primary'
                    : 'border-border bg-surface text-text-muted hover:bg-surface-light')
                }
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="delivery_method"
                    value={opt.id}
                    checked={active}
                    onChange={() => update('delivery_method', opt.id)}
                    className="accent-primary"
                  />
                  <span className="text-sm font-medium">{opt.label}</span>
                </div>
                <div className="ml-6 mt-0.5 text-[11px] opacity-80">
                  {opt.desc}
                </div>
              </label>
            )
          })}
        </div>
      </div>

      {submitError && (
        <div className="rounded-md border border-danger/40 bg-danger/20 px-3 py-2 text-sm text-danger">
          {submitError}{' '}
          {/* Surface a help link for cron-shaped errors. */}
          {/invalid|cron/i.test(submitError) && (
            <a
              href="https://crontab.guru/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-danger"
            >
              cron help
            </a>
          )}
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded-md text-sm bg-surface text-text-muted hover:bg-surface-light"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving || !cronValidation.ok}
          className={
            'px-3 py-1.5 rounded-md text-sm font-medium ' +
            (saving || !cronValidation.ok
              ? 'bg-surface text-text-muted cursor-not-allowed'
              : 'bg-primary text-on-primary hover:bg-primary/90')
          }
        >
          {saving ? 'Saving…' : existingPromptId ? 'Save changes' : 'Create prompt'}
        </button>
      </div>
    </form>
  )
}

// ---- Sub-components -------------------------------------------------------

interface TimePickerProps {
  hour: number
  minute: number
  onChange: (hour: number, minute: number) => void
}

function TimePicker({ hour, minute, onChange }: TimePickerProps) {
  const value = `${clamp(hour, 0, 23).toString().padStart(2, '0')}:${clamp(
    minute,
    0,
    59,
  )
    .toString()
    .padStart(2, '0')}`
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wider text-text-muted mb-1">
        Time
      </label>
      <input
        type="time"
        value={value}
        onChange={e => {
          const [hStr, mStr] = e.target.value.split(':')
          const h = clamp(Number(hStr) || 0, 0, 23)
          const m = clamp(Number(mStr) || 0, 0, 59)
          onChange(h, m)
        }}
        className="bg-surface border border-border rounded-md px-2 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-primary/60 focus:border-primary/60"
      />
    </div>
  )
}

// Exposed for tests in 28.3.
export const __testing__ = {
  buildCron,
  validateCronClient,
  describeCron,
  inferModeFromCron,
}
