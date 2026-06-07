import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/auth'
import { useSettingsStore } from './stores/settings'
import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import SettingsPage from './pages/SettingsPage'
import AdminConsolePage from './pages/AdminConsolePage'
import ScheduledPromptsPage from './pages/ScheduledPromptsPage'
import QuickCaptureOverlay from './components/QuickCaptureOverlay'
import QuickCapturePage from './pages/QuickCapturePage'
import ToolFramePage from './pages/ToolFramePage'

/**
 * Theme tokens we apply as CSS custom properties on `:root`.
 *
 * Mapping mirrors the keys in `EffectiveTheme.tokens_json` (settings store),
 * with one rename: `text_muted` → `--color-text-muted` (hyphen, not
 * underscore, to match Tailwind/CSS convention).
 */
const TOKEN_TO_CSS_VAR: Array<[keyof import('./stores/settings').ThemeTokens, string]> = [
  ['background', '--color-background'],
  ['surface', '--color-surface'],
  ['primary', '--color-primary'],
  ['accent', '--color-accent'],
  ['text', '--color-text'],
  ['text_muted', '--color-text-muted'],
  ['border', '--color-border'],
  ['danger', '--color-danger'],
  ['success', '--color-success'],
]

function App() {
  const { user } = useAuthStore()
  const loadSettings = useSettingsStore(s => s.loadSettings)
  const effectiveTheme = useSettingsStore(s => s.effectiveTheme)
  const effectiveTextSize = useSettingsStore(s => s.effectiveTextSize)

  // Quick Capture overlay visibility. Driven by the global Ctrl/Cmd+Shift+K
  // hotkey below. The `/quick-capture` route mounts its own copy of the
  // overlay (via QuickCapturePage) so this state is only for the in-app
  // hotkey path — nothing on this state needs to know about share-target
  // navigations.
  const [quickCaptureOpen, setQuickCaptureOpen] = useState(false)

  // Fetch the user's resolved settings (theme + text size + voice + morning card)
  // once we know who they are. The store already hydrates `effectiveTheme` from
  // localStorage so the first paint uses the right colors even before this
  // network call resolves.
  useEffect(() => {
    if (user) {
      loadSettings().catch(() => {
        // Errors are surfaced via the store's `error` field; the cached theme
        // remains in effect so the UI stays usable.
      })
    }
  }, [user, loadSettings])

  // Apply theme tokens to `:root` as CSS custom properties. Re-runs whenever
  // the effective theme changes (initial hydrate, network load, or theme picker
  // patch), which lets Tailwind utilities like `bg-surface` / `text-text-muted`
  // resolve to the active palette.
  useEffect(() => {
    const root = document.documentElement
    const tokens = effectiveTheme.tokens_json
    if (!tokens) return
    for (const [tokenKey, cssVar] of TOKEN_TO_CSS_VAR) {
      const value = tokens[tokenKey]
      if (typeof value === 'string' && value.length > 0) {
        root.style.setProperty(cssVar, value)
      }
    }
    // Mirror `surface` to its light/dark convenience variants so any
    // surface-* utilities (used by older chrome) follow the active theme
    // instead of staying frozen at the index.css defaults.
    if (typeof tokens.surface === 'string') {
      root.style.setProperty('--color-surface-light', tokens.surface)
      root.style.setProperty('--color-surface-dark', tokens.background || tokens.surface)
    }
  }, [effectiveTheme])

  // Apply the user's text-size preference globally by exposing a single
  // CSS custom property `--bh-text-base` on the root element. The Tailwind
  // `text-*` utilities are overridden in index.css to compute against that
  // variable, so changing it scales every piece of text in the app while
  // leaving padding/gap/width values (which use the html `rem` unit) at
  // their fixed sizes. This keeps layouts stable when the user picks a
  // larger size — chrome no longer outgrows the viewport.
  useEffect(() => {
    const root = document.documentElement
    const px =
      effectiveTextSize === 'small'
        ? 15
        : effectiveTextSize === 'large'
          ? 19
          : effectiveTextSize === 'extra_large'
            ? 21
            : 17 // medium
    root.style.setProperty('--bh-text-base', `${px}px`)
    // Clear any leftover root font-size override from a previous build —
    // we don't want to scale rem anymore.
    root.style.fontSize = ''
  }, [effectiveTextSize])

  // Global keyboard shortcut: Ctrl+Shift+K (or Cmd+Shift+K on macOS) opens
  // the Quick Capture overlay from anywhere in the app (R9.1). The handler
  // is only attached when a user is logged in — otherwise the overlay's
  // workspace lookup would have nothing to anchor to.
  //
  // We deliberately gate on `e.shiftKey && e.code === 'KeyK'` (not
  // `e.key === 'K'`) so the binding survives keyboard layouts where Shift
  // changes the printable character. We also skip if any other modal-like
  // element has captured focus (currently we just trust the overlay's own
  // Escape handler to compete cleanly — if multiple modals stack later we
  // can revisit). AppShell already uses Ctrl/Cmd+K (no Shift) for the
  // search palette, so requiring Shift keeps the two bindings distinct.
  useEffect(() => {
    if (!user) return
    const handler = (e: KeyboardEvent) => {
      const isMod = e.ctrlKey || e.metaKey
      if (!isMod || !e.shiftKey) return
      // `code` is layout-independent; `key` would be 'K' here too but
      // checking code is more robust.
      if (e.code !== 'KeyK' && e.key !== 'K' && e.key !== 'k') return
      e.preventDefault()
      setQuickCaptureOpen(prev => !prev)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [user])

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <>
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin/*" element={<AdminConsolePage />} />
        <Route path="/quick-capture" element={<QuickCapturePage />} />
        <Route path="/scheduled-prompts" element={<ScheduledPromptsPage />} />
        <Route path="/tools/:toolId" element={<ToolFramePage />} />
        <Route path="/*" element={<AppShell />} />
      </Routes>

      {/* Hotkey-triggered Quick Capture overlay. The `/quick-capture`
          route mounts its own copy via QuickCapturePage, so we render
          this one only when the user opened it via Ctrl/Cmd+Shift+K. */}
      {quickCaptureOpen && (
        <QuickCaptureOverlay onClose={() => setQuickCaptureOpen(false)} />
      )}
    </>
  )
}

export default App
