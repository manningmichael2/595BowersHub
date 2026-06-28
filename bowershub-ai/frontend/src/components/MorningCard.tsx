/**
 * MorningCard — proactive briefing surface at the top of ChatArea.
 *
 * Renders the parsed morning briefing for the user's chosen morning-card
 * workspace. Visibility ownership:
 *   - Parent (ChatArea) decides whether to mount us at all by comparing
 *     `activeWorkspace.id` against `settings.morning_card_workspace_id`
 *     and respecting `settings.morning_card_disabled` (R8.9).
 *   - We own the per-day dismissal state (R8.6) using the helpers in
 *     `lib/morning_card.ts`. Once dismissed for the current calendar day
 *     in this browser, the card hides until tomorrow.
 *
 * Data flow:
 *   - On mount (or workspaceId change) GET /api/briefing/latest. If the
 *     backend returns `briefing_id: null` we render a "Generate today's
 *     briefing" CTA that POSTs to /api/briefing/generate-now and
 *     refreshes our briefing state inline (R8.3, R8.4).
 *   - Sections come pre-parsed from the backend
 *     (`backend/services/briefing_summary.py`) using the canonical keys
 *     `weather | yesterday_spending | inbox | schedule | anything_else`.
 *     Each key gets an icon (☀ 💸 📥 📅 ✨) per design.md.
 *   - Sections the briefing omitted come through with `content === "—"`
 *     and we render them with a muted placeholder style (R8.7).
 *
 * Props:
 *   - workspaceId: number — the workspace whose briefing we should fetch.
 *
 * State:
 *   - briefing: latest /api/briefing/latest response (or null while
 *     loading / on initial error).
 *   - dismissed: boolean — true once the user clicks ✕ today, persisted
 *     via `dismiss_today` so reload doesn't bring it back the same day.
 *
 * _Requirements: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../services/api'
import {
  dismiss_today,
  is_visible,
  read_dismiss_set,
  today_iso,
} from '../lib/morning_card'

// ---- Types ----------------------------------------------------------------

interface ParsedSection {
  key: string
  label: string
  content: string
}

interface BriefingResponse {
  briefing_id: number | null
  content?: string
  generated_at?: string
  age_hours?: number
  parsed_sections?: ParsedSection[]
}

interface MorningCardProps {
  workspaceId: number
}

// ---- Constants ------------------------------------------------------------

// Section-key → emoji. Keys are produced by
// backend/services/briefing_summary.py::EXPECTED_SECTIONS so any addition
// there should be mirrored here. Unknown keys fall back to `•`.
const SECTION_ICONS: Record<string, string> = {
  weather: '☀',
  yesterday_spending: '💸',
  inbox: '📥',
  schedule: '📅',
  anything_else: '✨',
  finance_insights: '💡',
}

// Mirrors backend MISSING_PLACEHOLDER. We compare with this literal so the
// section tile knows when to mute the content (R8.7).
const MISSING_PLACEHOLDER = '—'

// ---- Component ------------------------------------------------------------

export default function MorningCard({ workspaceId }: MorningCardProps) {
  const [briefing, setBriefing] = useState<BriefingResponse | null>(null)
  // Initial dismissed value reads from localStorage so a hard refresh after
  // dismissing doesn't immediately re-show the card.
  const [dismissed, setDismissed] = useState<boolean>(() =>
    read_dismiss_set().has(today_iso()),
  )
  const [loading, setLoading] = useState<boolean>(true)
  const [generating, setGenerating] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // ---- Load latest briefing on mount / workspace change ------------------

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .get(`/api/briefing/latest?workspace_id=${workspaceId}`)
      .then(res => {
        if (cancelled) return
        setBriefing(res.data || { briefing_id: null })
      })
      .catch(err => {
        if (cancelled) return
        setError(
          err?.response?.data?.detail ||
            'Failed to load morning briefing.',
        )
        setBriefing({ briefing_id: null })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [workspaceId])

  // ---- Visibility decision ----------------------------------------------
  //
  // Bail out *before* render when the user has dismissed for today. When a
  // briefing is loaded we additionally consult `is_visible` so we honor the
  // 24-hour freshness rule (R8.5) — the backend already filters but the
  // helper makes the contract explicit and testable. While loading or when
  // there's no briefing yet, we still render so the user sees the
  // "Generate today's briefing" affordance (R8.3).

  const visible = useMemo(() => {
    if (dismissed) return false
    if (loading || briefing == null) return true
    if (briefing.briefing_id == null) return true
    const age = briefing.age_hours ?? 0
    return is_visible(age, read_dismiss_set(), today_iso())
  }, [dismissed, loading, briefing])

  if (!visible) return null

  // ---- Handlers ----------------------------------------------------------

  const onDismiss = () => {
    dismiss_today(today_iso())
    setDismissed(true)
  }

  const onGenerateNow = async () => {
    setGenerating(true)
    setError(null)
    try {
      const res = await api.post(
        `/api/briefing/generate-now?workspace_id=${workspaceId}`,
      )
      setBriefing(res.data || { briefing_id: null })
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          'Briefing service is unavailable. Try again later.',
      )
    } finally {
      setGenerating(false)
    }
  }

  // ---- Render ------------------------------------------------------------

  const hasBriefing =
    briefing != null && briefing.briefing_id != null
  const sections: ParsedSection[] =
    (hasBriefing && briefing?.parsed_sections) || []

  return (
    <div
      className="mb-4 rounded-lg border border-primary/40 bg-primary/30 p-4 shadow-sm"
      role="region"
      aria-label="Morning briefing"
      data-testid="morning-card"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg" aria-hidden>
            🌅
          </span>
          <h3 className="text-sm font-medium text-text truncate">
            Good morning
          </h3>
          {hasBriefing && briefing?.generated_at && (
            <span className="text-[11px] text-text-muted shrink-0">
              {formatGeneratedAt(briefing.generated_at)}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-text-muted hover:text-text text-sm rounded p-0.5"
          aria-label="Dismiss morning briefing for today"
          title="Dismiss for today"
        >
          ✕
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded border border-danger/40 bg-danger/20 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {loading && briefing == null ? (
        <div className="text-sm text-text-muted" data-testid="morning-card-loading">
          Loading briefing…
        </div>
      ) : !hasBriefing ? (
        <NoBriefingState
          generating={generating}
          onGenerateNow={onGenerateNow}
        />
      ) : (
        <BriefingSections sections={sections} />
      )}
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function NoBriefingState({
  generating,
  onGenerateNow,
}: {
  generating: boolean
  onGenerateNow: () => void
}) {
  return (
    <div className="space-y-2">
      <p className="text-sm text-text-muted">
        No briefing yet today. Generate one to see weather, yesterday's
        spending, your inbox, today's schedule, and more.
      </p>
      <button
        type="button"
        onClick={onGenerateNow}
        disabled={generating}
        className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-on-primary text-sm disabled:opacity-50 disabled:cursor-wait"
        data-testid="morning-card-generate"
      >
        {generating ? 'Generating…' : "Generate today's briefing"}
      </button>
    </div>
  )
}

function BriefingSections({ sections }: { sections: ParsedSection[] }) {
  if (sections.length === 0) {
    return (
      <div className="text-sm text-text-muted italic">
        Briefing has no content.
      </div>
    )
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {sections.map(section => (
        <SectionTile key={section.key} section={section} />
      ))}
    </div>
  )
}

function SectionTile({ section }: { section: ParsedSection }) {
  const icon = SECTION_ICONS[section.key] || '•'
  const isMissing = section.content.trim() === MISSING_PLACEHOLDER
  return (
    <div
      className="rounded border border-border bg-surface p-2.5"
      data-section-key={section.key}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-base shrink-0" aria-hidden>
          {icon}
        </span>
        <span className="text-xs font-medium text-text-muted uppercase tracking-wider">
          {section.label}
        </span>
      </div>
      <div
        className={
          'text-sm whitespace-pre-wrap break-words ' +
          (isMissing ? 'text-text-muted italic' : 'text-text')
        }
      >
        {section.content}
      </div>
    </div>
  )
}

// ---- Helpers --------------------------------------------------------------

function formatGeneratedAt(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}
