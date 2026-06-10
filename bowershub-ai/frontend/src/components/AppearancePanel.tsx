/**
 * AppearancePanel — Settings → Appearance section.
 *
 * Implements task 19.2:
 *   - Theme grid bound to `useSettingsStore().effectiveTheme`, populated
 *     from `GET /api/themes`. Highlights the user's currently effective
 *     theme, marks the platform default, and badges presets vs. custom.
 *   - "Use platform default" button → POST /api/settings/reset-theme via
 *     `useSettingsStore.resetTheme()`.
 *   - Text size buttons: four labeled buttons (Small, Medium, Large,
 *     Extra Large) rendered each at its corresponding scale as a live
 *     preview, click calls `patch({text_size})`.
 *   - "Build a custom theme" button → opens `<ThemeBuilder>` (task 20.1).
 *     On save, the new theme is fetched into the grid and auto-selected
 *     so the user sees it apply immediately (R3.4).
 *   - One-time inline notice if the backend resolver fell back from the
 *     user's selected theme (R3.8) — detected via
 *     `effectiveTheme.id !== settings.theme_id` after settings load.
 *
 * _Requirements: R3.1, R3.2, R3.3, R3.8, R4.1, R4.2, R4.3, R12.2
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../services/api'
import { useAuthStore } from '../stores/auth'
import {
  useSettingsStore,
  type EffectiveTheme,
  type TextSize,
  type ThemeTokens,
} from '../stores/settings'
import ThemeBuilder from './ThemeBuilder'

// ---- Types ----------------------------------------------------------------

interface ThemeListEntry {
  id: number
  name: string
  slug: string
  is_preset: boolean
  owner_id: number | null
  tokens_json: ThemeTokens
  is_default: boolean
}

// ---- Constants ------------------------------------------------------------

const TEXT_SIZES: Array<{ value: TextSize; label: string; previewPx: number }> = [
  { value: 'small', label: 'Small', previewPx: 15 },
  { value: 'medium', label: 'Medium', previewPx: 17 },
  { value: 'large', label: 'Large', previewPx: 19 },
  { value: 'extra_large', label: 'Extra Large', previewPx: 21 },
]

// Tokens shown as a row of swatches on each theme card.
const SWATCH_TOKENS: Array<keyof ThemeTokens> = [
  'background',
  'surface',
  'primary',
  'accent',
  'text',
]

// Persist the dismissal of the fallback notice for the calendar day so the
// user only sees it once per day per browser (R3.8).
const FALLBACK_DISMISSED_KEY = 'bh.themeFallbackNotice'

// ---- Component ------------------------------------------------------------

export default function AppearancePanel() {
  const settings = useSettingsStore(s => s.settings)
  const effectiveTheme = useSettingsStore(s => s.effectiveTheme)
  const effectiveTextSize = useSettingsStore(s => s.effectiveTextSize)
  const isLoaded = useSettingsStore(s => s.isLoaded)
  const patch = useSettingsStore(s => s.patch)
  const resetTheme = useSettingsStore(s => s.resetTheme)

  const [themes, setThemes] = useState<ThemeListEntry[] | null>(null)
  const [themesError, setThemesError] = useState<string | null>(null)
  const [pendingThemeId, setPendingThemeId] = useState<number | null>(null)
  const [pendingTextSize, setPendingTextSize] = useState<TextSize | null>(null)
  const [savingDefault, setSavingDefault] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [showFallbackNotice, setShowFallbackNotice] = useState(false)
  const [builderOpen, setBuilderOpen] = useState(false)
  const [editingThemeId, setEditingThemeId] = useState<number | null>(null)
  const [editingThemeName, setEditingThemeName] = useState<string | null>(null)

  const currentUser = useAuthStore(s => s.user)
  const isAdmin = currentUser?.role === 'admin'

  // ---- Fetch themes ------------------------------------------------------

  const loadThemes = () => {
    return api
      .get('/api/themes')
      .then(res => {
        const data = res.data
        // Endpoint returns an array; tolerate `{themes: [...]}` envelope too.
        const list: ThemeListEntry[] = Array.isArray(data)
          ? data
          : Array.isArray(data?.themes)
            ? data.themes
            : []
        setThemes(list)
        setThemesError(null)
        return list
      })
      .catch(err => {
        setThemesError(
          err?.response?.data?.detail ||
            'Failed to load themes. Try again in a moment.',
        )
        setThemes([])
        return [] as ThemeListEntry[]
      })
  }

  useEffect(() => {
    let cancelled = false
    api
      .get('/api/themes')
      .then(res => {
        if (cancelled) return
        const data = res.data
        // Endpoint returns an array; tolerate `{themes: [...]}` envelope too.
        const list: ThemeListEntry[] = Array.isArray(data)
          ? data
          : Array.isArray(data?.themes)
            ? data.themes
            : []
        setThemes(list)
        setThemesError(null)
      })
      .catch(err => {
        if (cancelled) return
        setThemesError(
          err?.response?.data?.detail ||
            'Failed to load themes. Try again in a moment.',
        )
        setThemes([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  // ---- Backend-fallback detection (R3.8) ---------------------------------
  //
  // If the user persisted a `theme_id` but the resolver returned a different
  // id (theme deleted, made private to another owner, etc.) surface a
  // one-time inline notice explaining their theme was reset. Stored
  // dismissal in localStorage keyed to the calendar date so it doesn't spam.
  //
  // We check this exactly once after settings first finish loading. Without
  // this guard, the optimistic-update window inside `patch()` (where
  // settings.theme_id moves before effectiveTheme.id catches up to the
  // server's response) makes the notice flash on every legitimate theme
  // change.

  const fallbackChecked = useRef(false)

  useEffect(() => {
    if (!isLoaded) return
    if (fallbackChecked.current) return
    fallbackChecked.current = true

    const persistedId = settings.theme_id
    const effectiveId = effectiveTheme.id
    if (persistedId == null || effectiveId == null) return
    if (persistedId === effectiveId) return

    const today = new Date().toISOString().slice(0, 10)
    const key = `${FALLBACK_DISMISSED_KEY}:${persistedId}:${today}`
    try {
      if (localStorage.getItem(key) === '1') return
    } catch {
      // localStorage disabled — show anyway.
    }
    setShowFallbackNotice(true)
  }, [isLoaded, settings.theme_id, effectiveTheme.id])

  const dismissFallbackNotice = () => {
    setShowFallbackNotice(false)
    try {
      const today = new Date().toISOString().slice(0, 10)
      const key = `${FALLBACK_DISMISSED_KEY}:${settings.theme_id}:${today}`
      localStorage.setItem(key, '1')
    } catch {
      // non-fatal
    }
  }

  // ---- Derived state -----------------------------------------------------

  const selectedThemeId: number | null =
    pendingThemeId ?? effectiveTheme.id ?? null
  const selectedTextSize: TextSize = pendingTextSize ?? effectiveTextSize

  const sortedThemes = useMemo(() => {
    if (!themes) return []
    // Sort: presets first, then admin-published (owner_id null), then
    // personal themes; alphabetical within each group.
    return [...themes].sort((a, b) => {
      const groupA = a.is_preset ? 0 : a.owner_id == null ? 1 : 2
      const groupB = b.is_preset ? 0 : b.owner_id == null ? 1 : 2
      if (groupA !== groupB) return groupA - groupB
      return a.name.localeCompare(b.name)
    })
  }, [themes])

  // ---- Handlers ----------------------------------------------------------

  const onSelectTheme = async (theme: ThemeListEntry) => {
    if (theme.id === selectedThemeId) return
    // The user is intentionally picking a theme — they've seen and acted on
    // any prior fallback notice, so clear it now (don't wait for the next
    // load to forget about it).
    if (showFallbackNotice) setShowFallbackNotice(false)
    setErrorMsg(null)
    setPendingThemeId(theme.id)
    try {
      await patch({ theme_id: theme.id })
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Failed to apply theme.')
    } finally {
      setPendingThemeId(null)
    }
  }

  const onSelectTextSize = async (size: TextSize) => {
    if (size === selectedTextSize) return
    setErrorMsg(null)
    setPendingTextSize(size)
    try {
      await patch({ text_size: size })
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Failed to apply text size.')
    } finally {
      setPendingTextSize(null)
    }
  }

  const onResetToPlatformDefault = async () => {
    setErrorMsg(null)
    setSavingDefault(true)
    try {
      await resetTheme()
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Failed to reset theme.')
    } finally {
      setSavingDefault(false)
    }
  }

  // ---- Render ------------------------------------------------------------

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-medium text-gray-100">Appearance</h2>
        <p className="text-sm text-gray-400 mt-1">
          Theme and text size for the app. Changes apply to every device you
          sign into.
        </p>
      </div>

      {/* Backend-fallback notice (R3.8) */}
      {showFallbackNotice && (
        <div className="flex items-start justify-between gap-3 rounded-lg border border-amber-700/40 bg-amber-900/20 px-3 py-2 text-sm text-amber-200">
          <div>
            Your selected theme is no longer available, so we reset it to the
            platform default. Pick another theme below to override.
          </div>
          <button
            onClick={dismissFallbackNotice}
            className="shrink-0 text-amber-300/70 hover:text-amber-100"
            aria-label="Dismiss notice"
          >
            ✕
          </button>
        </div>
      )}

      {errorMsg && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/20 px-3 py-2 text-sm text-red-300">
          {errorMsg}
        </div>
      )}

      {/* ---------------- Theme section ---------------- */}
      <section className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-medium text-gray-200">Theme</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Choose a palette. Your selection follows you across devices.
            </p>
          </div>
          <button
            type="button"
            onClick={onResetToPlatformDefault}
            disabled={savingDefault || settings.theme_id == null}
            className="px-3 py-1.5 rounded-lg bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            title={
              settings.theme_id == null
                ? 'Already using the platform default'
                : 'Clear your override and use the admin-configured default'
            }
          >
            {savingDefault ? 'Resetting…' : 'Use platform default'}
          </button>
        </div>

        {themesError && (
          <div className="text-sm text-red-400">{themesError}</div>
        )}

        {themes == null ? (
          <ThemeGridSkeleton />
        ) : sortedThemes.length === 0 ? (
          <div className="text-sm text-gray-500 italic">
            No themes available.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sortedThemes.map(theme => (
              <ThemeCard
                key={theme.id}
                theme={theme}
                selected={theme.id === selectedThemeId}
                pending={theme.id === pendingThemeId}
                onSelect={() => onSelectTheme(theme)}
                onEdit={isAdmin ? () => {
                  setEditingThemeId(theme.id)
                  setEditingThemeName(theme.name)
                  setBuilderOpen(true)
                } : undefined}
              />
            ))}
          </div>
        )}

        <div>
          <button
            type="button"
            onClick={() => { setEditingThemeId(null); setEditingThemeName(null); setBuilderOpen(true) }}
            className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-200 hover:bg-gray-700 border border-gray-700"
            title="Build a personal theme — opens the color editor"
          >
            🎨 Build a custom theme
          </button>
        </div>
      </section>

      {/* ---------------- Text size section ---------------- */}
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium text-gray-200">Text size</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Applies to chat messages and rendered markdown. UI chrome stays
            the same size.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {TEXT_SIZES.map(opt => {
            const selected = opt.value === selectedTextSize
            const pending = opt.value === pendingTextSize
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => onSelectTextSize(opt.value)}
                disabled={pending}
                aria-pressed={selected}
                className={
                  'flex flex-col items-center justify-center gap-1 rounded-lg border px-3 py-3 transition-colors ' +
                  (selected
                    ? 'border-primary bg-primary/10 text-gray-100'
                    : 'border-gray-700 bg-gray-800/40 text-gray-300 hover:border-gray-600 hover:bg-gray-800/70')
                }
              >
                {/* Live preview: the label rendered at its own pixel size
                    (R4.2). We use inline styles instead of classes so the
                    preview matches the actual root font-size we apply on
                    selection — see the text-size effect in App.tsx. */}
                <span
                  className="font-medium leading-tight"
                  style={{ fontSize: `${opt.previewPx}px` }}
                >
                  {opt.label}
                </span>
                <span className="text-[10px] uppercase tracking-wider text-gray-500">
                  {pending ? 'Saving…' : selected ? 'Selected' : 'Preview'}
                </span>
              </button>
            )
          })}
        </div>
      </section>

      {/* ---------------- Theme builder modal ---------------- */}
      {builderOpen && (
        <ThemeBuilder
          themeId={editingThemeId ?? undefined}
          editMode={editingThemeId != null}
          initialName={editingThemeName ?? undefined}
          onClose={() => { setBuilderOpen(false); setEditingThemeId(null); setEditingThemeName(null) }}
          onSave={async (saved: any) => {
            // Refresh the list so the new/updated theme appears, then
            // auto-select it so the change is visible immediately (R3.4).
            await loadThemes()
            if (saved && typeof saved.id === 'number') {
              setPendingThemeId(saved.id)
              try {
                await patch({ theme_id: saved.id })
              } catch (err: any) {
                setErrorMsg(
                  err?.response?.data?.detail ||
                    'Theme saved, but failed to apply it. Pick it from the grid.',
                )
              } finally {
                setPendingThemeId(null)
              }
            }
            setEditingThemeId(null)
            setEditingThemeName(null)
          }}
        />
      )}
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function ThemeCard({
  theme,
  selected,
  pending,
  onSelect,
  onEdit,
}: {
  theme: ThemeListEntry
  selected: boolean
  pending: boolean
  onSelect: () => void
  onEdit?: () => void
}) {
  const tokens = theme.tokens_json || {}
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={pending}
      aria-pressed={selected}
      className={
        'group relative flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors ' +
        (selected
          ? 'border-primary ring-1 ring-primary/60 bg-primary/5'
          : 'border-gray-700 bg-gray-800/40 hover:border-gray-600 hover:bg-gray-800/70') +
        (pending ? ' opacity-60 cursor-wait' : '')
      }
    >
      {/* Admin edit button */}
      {onEdit && (
        <span
          onClick={(e) => { e.stopPropagation(); onEdit() }}
          className="absolute top-2 right-2 text-xs px-1.5 py-0.5 rounded bg-gray-700/80 text-gray-300 hover:bg-gray-600 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer z-10"
          title="Edit theme colors"
        >
          ✏️
        </span>
      )}
      {/* Mini preview tile rendered with the theme's actual tokens. */}
      <div
        className="rounded-md border h-16 w-full overflow-hidden flex items-stretch"
        style={{
          backgroundColor: tokens.background || '#0f172a',
          borderColor: tokens.border || '#334155',
        }}
      >
        <div
          className="flex-1 flex items-center justify-center"
          style={{ backgroundColor: tokens.surface || '#1e293b' }}
        >
          <span
            className="text-xs font-medium"
            style={{ color: tokens.text || '#f1f5f9' }}
          >
            Aa
          </span>
        </div>
        <div
          className="w-2"
          style={{ backgroundColor: tokens.primary || '#6366f1' }}
        />
        <div
          className="w-2"
          style={{ backgroundColor: tokens.accent || '#8b5cf6' }}
        />
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="text-sm text-gray-100 font-medium truncate">
          {theme.name}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {theme.is_preset ? (
            <span className="text-[10px] uppercase tracking-wider text-gray-400 bg-gray-700/60 px-1.5 py-0.5 rounded">
              Preset
            </span>
          ) : theme.owner_id == null ? (
            <span className="text-[10px] uppercase tracking-wider text-indigo-300 bg-indigo-900/40 px-1.5 py-0.5 rounded">
              Custom
            </span>
          ) : (
            <span className="text-[10px] uppercase tracking-wider text-emerald-300 bg-emerald-900/40 px-1.5 py-0.5 rounded">
              Yours
            </span>
          )}
        </div>
      </div>

      {/* Swatch row — quick visual diff between similar themes. */}
      <div className="flex items-center gap-1">
        {SWATCH_TOKENS.map(t => (
          <span
            key={t}
            className="h-2.5 w-2.5 rounded-full border border-black/20"
            style={{ backgroundColor: (tokens as any)[t] || '#000' }}
            title={String(t)}
          />
        ))}
      </div>

      <div className="flex items-center justify-between text-[11px] mt-0.5">
        {theme.is_default ? (
          <span className="text-amber-300">★ Platform default</span>
        ) : (
          <span className="text-gray-500">&nbsp;</span>
        )}
        {selected && <span className="text-primary">Active</span>}
      </div>
    </button>
  )
}

function ThemeGridSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-32 rounded-lg border border-gray-700 bg-gray-800/30 animate-pulse"
        />
      ))}
    </div>
  )
}

// Re-export the EffectiveTheme type so test files / siblings can import from here
// in a future iteration without bouncing through the store.
export type { EffectiveTheme }
