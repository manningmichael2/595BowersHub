/**
 * ThemeBuilder — modal for building and saving a custom theme palette.
 *
 * Implements task 20.1:
 *   - Color pickers (HTML <input type="color"> + paired hex text field)
 *     for every required token: background, surface, primary, accent,
 *     text, text_muted, border, danger, success.
 *   - Live preview pane: renders a fake user message + assistant message
 *     and a sidebar fragment using the working tokens, so the user sees
 *     exactly how the palette will look in the chat UI.
 *   - Contrast badge: live `ok` / `warn` / `block` indicator computed
 *     against the same WCAG formula and thresholds the backend uses
 *     (`backend/services/theme_validator.contrast_decision`). The pure
 *     helper lives in `lib/contrast.ts` so it can be reused / tested
 *     independently.
 *   - Save button is disabled when contrast is `block`. Sends a `POST
 *     /api/themes` request — `publish=false` for regular users,
 *     `publish=true` exposed as an admin-only checkbox.
 *   - Mobile: full-screen sheet. Desktop: centered modal.
 *
 * Props:
 *   - themeId?:  optional id of an existing theme to seed the editor
 *                with (currently only used on `loadInitial` — task 20
 *                doesn't ship a "save changes to existing theme" path,
 *                so when `themeId` is set the form is pre-populated and
 *                Save still issues POST → creates a new theme).
 *   - onSave:    callback fired with the created theme so the parent
 *                can refresh its list / select the new theme.
 *   - onClose:   close-the-modal callback.
 *
 * _Requirements: R1.4, R1.6, R1.7, R1.8, R3.4
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../services/api'
import { useAuthStore } from '../stores/auth'
import {
  contrastDecision,
  contrastRatio,
  isValidHex,
  normalizeHex,
  type ContrastDecision,
} from '../lib/contrast'
import type { ThemeTokens } from '../stores/settings'

// ---- Types ----------------------------------------------------------------

export interface ThemeBuilderProps {
  themeId?: number
  onSave: (theme: any) => void
  onClose: () => void
}

interface TokenField {
  key: keyof ThemeTokens
  label: string
  hint: string
}

// Order matches design.md "Database Changes" → tokens_json fields and the
// REQUIRED_TOKEN_KEYS tuple in `theme_validator.py`.
const TOKEN_FIELDS: TokenField[] = [
  { key: 'background', label: 'Background', hint: 'Page background' },
  { key: 'surface', label: 'Surface', hint: 'Cards, panels, inputs' },
  { key: 'primary', label: 'Primary', hint: 'Buttons, links, send' },
  { key: 'accent', label: 'Accent', hint: 'Highlights, active state' },
  { key: 'text', label: 'Text', hint: 'Default body text' },
  { key: 'text_muted', label: 'Muted text', hint: 'Timestamps, captions' },
  { key: 'border', label: 'Border', hint: 'Dividers, outlines' },
  { key: 'danger', label: 'Danger', hint: 'Errors, destructive actions' },
  { key: 'success', label: 'Success', hint: 'Confirmations, online status' },
]

// Default starting palette — Dark Navy preset shape. Used when there's no
// `themeId` and we haven't yet loaded the user's effective theme.
const DEFAULT_TOKENS: ThemeTokens = {
  background: '#0f172a',
  surface: '#1e293b',
  primary: '#6366f1',
  accent: '#8b5cf6',
  text: '#f1f5f9',
  text_muted: '#94a3b8',
  border: '#334155',
  danger: '#ef4444',
  success: '#10b981',
}

// ---- Component ------------------------------------------------------------

export default function ThemeBuilder({ themeId, onSave, onClose }: ThemeBuilderProps) {
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'

  const [name, setName] = useState('')
  const [tokens, setTokens] = useState<ThemeTokens>(DEFAULT_TOKENS)
  // Mirror tokens with a parallel "raw text" map so the user can type
  // freely (e.g. `#abc12`) without us snapping back to the last-valid
  // value. The committed tokens only update once the input is a valid hex.
  const [rawText, setRawText] = useState<Record<string, string>>(
    Object.fromEntries(TOKEN_FIELDS.map(f => [f.key, DEFAULT_TOKENS[f.key]])),
  )
  const [publish, setPublish] = useState(false)
  const [saving, setSaving] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const dialogRef = useRef<HTMLDivElement>(null)

  // ---- Seed from existing theme (optional) ------------------------------

  useEffect(() => {
    if (!themeId) return
    let cancelled = false
    setLoading(true)
    api
      .get('/api/themes')
      .then(res => {
        if (cancelled) return
        const list: any[] = Array.isArray(res.data)
          ? res.data
          : Array.isArray(res.data?.themes)
            ? res.data.themes
            : []
        const found = list.find(t => t.id === themeId)
        if (found?.tokens_json) {
          const seeded: ThemeTokens = { ...DEFAULT_TOKENS, ...found.tokens_json }
          setTokens(seeded)
          setRawText(
            Object.fromEntries(TOKEN_FIELDS.map(f => [f.key, seeded[f.key]])),
          )
          if (typeof found.name === 'string') {
            setName(`${found.name} (copy)`)
          }
        }
      })
      .catch(() => {
        // Non-fatal — fall back to DEFAULT_TOKENS.
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [themeId])

  // ---- Keyboard / focus handling ----------------------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // ---- Derived state ----------------------------------------------------

  const decision: ContrastDecision = useMemo(
    () => contrastDecision(tokens.text, tokens.background),
    [tokens.text, tokens.background],
  )

  const ratio: number | null = useMemo(() => {
    try {
      return contrastRatio(tokens.text, tokens.background)
    } catch {
      return null
    }
  }, [tokens.text, tokens.background])

  const allHexValid = TOKEN_FIELDS.every(f => isValidHex(tokens[f.key]))
  const canSave =
    !saving && name.trim().length > 0 && allHexValid && decision !== 'block'

  // ---- Handlers ---------------------------------------------------------

  const updateToken = (key: keyof ThemeTokens, raw: string) => {
    // Update the raw text immediately so the input remains responsive.
    setRawText(prev => ({ ...prev, [key]: raw }))

    // Only update the committed token (which drives preview + contrast)
    // once the value is a valid hex. This prevents the preview from
    // flashing through invalid intermediate values like `#1`, `#12`, etc.
    if (isValidHex(raw)) {
      setTokens(prev => ({ ...prev, [key]: normalizeHex(raw) }))
    }
  }

  // The native color picker emits `#rrggbb` already, so we can update both
  // raw text AND committed tokens together — no need for the validity guard.
  const updateFromPicker = (key: keyof ThemeTokens, value: string) => {
    setRawText(prev => ({ ...prev, [key]: value }))
    setTokens(prev => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    if (!canSave) return
    setSaving(true)
    setErrorMsg(null)
    try {
      const res = await api.post('/api/themes', {
        name: name.trim(),
        tokens_json: tokens,
        publish: isAdmin && publish,
      })
      onSave(res.data)
      onClose()
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      let msg = 'Failed to save theme.'
      if (typeof detail === 'string') msg = detail
      else if (detail && typeof detail === 'object' && detail.message) {
        msg = detail.message
        if (Array.isArray(detail.errors) && detail.errors.length > 0) {
          msg +=
            ' (' +
            detail.errors.map((e: any) => `${e.field}: ${e.message}`).join('; ') +
            ')'
        }
      }
      setErrorMsg(msg)
    } finally {
      setSaving(false)
    }
  }

  // ---- Render -----------------------------------------------------------

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="theme-builder-title"
      onClick={e => {
        // Click outside the dialog closes it on desktop (where the modal
        // doesn't fill the screen). On mobile it's full-screen so this
        // never triggers.
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        className="relative flex flex-col w-full sm:max-w-5xl sm:rounded-2xl bg-gray-900 border border-gray-700 shadow-2xl max-h-screen sm:max-h-[90vh] overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-gray-700 shrink-0">
          <h2 id="theme-builder-title" className="text-lg font-medium text-gray-100">
            🎨 Build a custom theme
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-gray-200"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-5">
            {/* ---------------- Editor column ---------------- */}
            <section className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-200 mb-1">
                  Theme name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="My theme"
                  maxLength={100}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/60"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {TOKEN_FIELDS.map(field => {
                  const raw = rawText[field.key]
                  const valid = isValidHex(raw)
                  // The native color picker requires a 6-digit hex with `#`.
                  // If the current value is invalid we still show a usable
                  // swatch (the last committed valid token) so the picker
                  // doesn't blow away the user's typing on click.
                  const pickerValue = (valid ? normalizeHex(raw) : tokens[field.key]).slice(0, 7)
                  return (
                    <div key={field.key as string}>
                      <label
                        htmlFor={`token-${String(field.key)}`}
                        className="flex items-baseline justify-between text-sm text-gray-200 mb-1"
                      >
                        <span>{field.label}</span>
                        <span className="text-[10px] uppercase tracking-wider text-gray-500">
                          {field.hint}
                        </span>
                      </label>
                      <div
                        className={
                          'flex items-center gap-2 rounded-lg border px-2 py-1.5 ' +
                          (valid
                            ? 'border-gray-700 bg-gray-800'
                            : 'border-red-700/60 bg-red-900/10')
                        }
                      >
                        <input
                          type="color"
                          value={pickerValue}
                          onChange={e => updateFromPicker(field.key, e.target.value)}
                          aria-label={`${field.label} color picker`}
                          className="h-7 w-9 rounded cursor-pointer border-none bg-transparent p-0"
                        />
                        <input
                          id={`token-${String(field.key)}`}
                          type="text"
                          value={raw}
                          onChange={e => updateToken(field.key, e.target.value)}
                          spellCheck={false}
                          autoCapitalize="none"
                          autoComplete="off"
                          className="flex-1 bg-transparent text-sm font-mono text-gray-100 placeholder-gray-500 focus:outline-none"
                          placeholder="#000000"
                        />
                      </div>
                      {!valid && (
                        <div className="text-[11px] text-red-400 mt-0.5">
                          Use a 6- or 8-digit hex like <code>#1a2b3c</code>.
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Contrast badge (R1.7, R1.8) */}
              <ContrastBadge decision={decision} ratio={ratio} />

              {isAdmin && (
                <label className="flex items-start gap-2 mt-2 text-sm text-gray-300 select-none">
                  <input
                    type="checkbox"
                    checked={publish}
                    onChange={e => setPublish(e.target.checked)}
                    className="mt-0.5 accent-indigo-500"
                  />
                  <div>
                    <div className="text-gray-200">Publish to all users</div>
                    <div className="text-xs text-gray-500">
                      Admin only. Other users will be able to select this theme.
                      Leave unchecked to save it as a personal theme.
                    </div>
                  </div>
                </label>
              )}
            </section>

            {/* ---------------- Preview column ---------------- */}
            <section className="space-y-3">
              <div className="text-sm font-medium text-gray-200">Live preview</div>
              <ThemePreview tokens={tokens} />
              <p className="text-xs text-gray-500">
                Preview uses your working palette. The chat UI applies the
                selected theme everywhere (sidebar, headers, inputs) once you
                save and select it.
              </p>
            </section>
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 px-5 py-3 border-t border-gray-700 shrink-0 bg-gray-900/80">
          <div className="text-xs text-gray-500">
            {loading
              ? 'Loading existing theme…'
              : decision === 'block'
                ? 'Fix the contrast warning above before saving.'
                : decision === 'warn'
                  ? 'Theme will save with a contrast warning.'
                  : 'Ready to save.'}
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300 hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!canSave}
              className={
                'px-4 py-1.5 rounded-lg text-sm font-medium ' +
                (canSave
                  ? 'bg-indigo-600 text-white hover:bg-indigo-500'
                  : 'bg-gray-800 text-gray-500 cursor-not-allowed')
              }
              title={
                decision === 'block'
                  ? 'Cannot save — text/background contrast is too low'
                  : !name.trim()
                    ? 'Give the theme a name first'
                    : !allHexValid
                      ? 'Fix invalid hex values first'
                      : 'Save theme'
              }
            >
              {saving ? 'Saving…' : 'Save theme'}
            </button>
          </div>
        </div>

        {errorMsg && (
          <div className="px-5 py-2 border-t border-red-700/40 bg-red-900/20 text-sm text-red-300">
            {errorMsg}
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function ContrastBadge({
  decision,
  ratio,
}: {
  decision: ContrastDecision
  ratio: number | null
}) {
  const cfg = {
    ok: {
      label: 'OK',
      tone: 'border-emerald-700/60 bg-emerald-900/30 text-emerald-200',
      caption: 'Text contrast is comfortable to read.',
    },
    warn: {
      label: 'Warn',
      tone: 'border-amber-700/60 bg-amber-900/30 text-amber-200',
      caption:
        'Contrast is below the 4.5:1 recommendation — readable but may strain.',
    },
    block: {
      label: 'Block',
      tone: 'border-red-700/60 bg-red-900/30 text-red-200',
      caption:
        'Contrast is below 2.0:1 — text would be unreadable. Save is disabled.',
    },
  }[decision]

  return (
    <div className={'rounded-lg border px-3 py-2 ' + cfg.tone}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium">
          Contrast: <span className="uppercase tracking-wider">{cfg.label}</span>
          {ratio !== null && (
            <span className="ml-2 text-xs opacity-75">
              {ratio.toFixed(2)}:1
            </span>
          )}
        </div>
      </div>
      <div className="text-xs opacity-80 mt-0.5">{cfg.caption}</div>
    </div>
  )
}

function ThemePreview({ tokens }: { tokens: ThemeTokens }) {
  // Apply the working palette via inline styles so the preview is fully
  // isolated from the app's current CSS variables.
  return (
    <div
      className="rounded-xl border overflow-hidden shadow-lg"
      style={{ borderColor: tokens.border }}
    >
      <div className="grid grid-cols-[7rem_1fr] min-h-[14rem]">
        {/* Sidebar fragment */}
        <div
          className="p-3 flex flex-col gap-2 text-xs"
          style={{
            background: tokens.surface,
            color: tokens.text,
            borderRight: `1px solid ${tokens.border}`,
          }}
        >
          <div className="font-semibold">Workspaces</div>
          <div
            className="rounded-md px-2 py-1.5"
            style={{ background: tokens.primary, color: tokens.background }}
          >
            General
          </div>
          <div
            className="rounded-md px-2 py-1.5"
            style={{ color: tokens.text_muted }}
          >
            Finance
          </div>
          <div
            className="rounded-md px-2 py-1.5"
            style={{ color: tokens.text_muted }}
          >
            Woodshop
          </div>
          <div className="mt-auto text-[10px]" style={{ color: tokens.text_muted }}>
            Press · to focus
          </div>
        </div>

        {/* Chat area */}
        <div
          className="p-3 flex flex-col gap-2"
          style={{ background: tokens.background, color: tokens.text }}
        >
          <div
            className="text-[11px] uppercase tracking-wider"
            style={{ color: tokens.text_muted }}
          >
            Today
          </div>

          {/* User message */}
          <div className="flex justify-end">
            <div
              className="max-w-[85%] rounded-2xl rounded-br-md px-3 py-2 text-sm"
              style={{ background: tokens.primary, color: tokens.background }}
            >
              How's my spending tracking this month?
            </div>
          </div>

          {/* Assistant message */}
          <div className="flex justify-start">
            <div
              className="max-w-[85%] rounded-2xl rounded-bl-md px-3 py-2 text-sm border"
              style={{
                background: tokens.surface,
                color: tokens.text,
                borderColor: tokens.border,
              }}
            >
              You're at <strong style={{ color: tokens.accent }}>$1,847</strong>{' '}
              MTD across all categories. Groceries are{' '}
              <span style={{ color: tokens.success }}>under budget</span>, dining
              is <span style={{ color: tokens.danger }}>over by $42</span>.
            </div>
          </div>

          {/* Input row */}
          <div
            className="mt-auto flex items-center gap-2 rounded-xl border px-2 py-1.5"
            style={{ background: tokens.surface, borderColor: tokens.border }}
          >
            <span className="text-sm" style={{ color: tokens.text_muted }}>
              Type a message…
            </span>
            <button
              type="button"
              className="ml-auto rounded-lg px-2.5 py-1 text-xs font-medium"
              style={{ background: tokens.primary, color: tokens.background }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
