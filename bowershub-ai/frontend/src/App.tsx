import { useEffect, useState, lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/auth'
import { useSettingsStore } from './stores/settings'
import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import SettingsPage from './pages/SettingsPage'
import AdminConsolePage from './pages/AdminConsolePage'
import ScheduledPromptsPage from './pages/ScheduledPromptsPage'
import QuickCaptureOverlay from './components/QuickCaptureOverlay'
import QuickCapturePage from './pages/QuickCapturePage'
import ToolFramePage from './pages/ToolFramePage'
import DashboardPage from './pages/DashboardPage'
import BottomTabBar from './components/BottomTabBar'
import TopNav from './components/TopNav'

// Lazy-loaded DB Browser — code-split to avoid impacting chat page load
const DbBrowserPage = lazy(() => import('./pages/DbBrowserPage'))
// Lazy-loaded Finance Review — code-split, only loaded when visited
const FinanceReviewPage = lazy(() => import('./pages/FinanceReviewPage'))
// Lazy-loaded Net Worth (accounting) — code-split, only loaded when visited
const NetWorthPage = lazy(() => import('./pages/NetWorthPage'))

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

    // Compute --color-on-primary: text color to use ON TOP of bg-primary.
    // If primary is light (like Mono's #ffffff), text on it must be dark.
    if (typeof tokens.primary === 'string' && tokens.primary.length >= 7) {
      const hex = tokens.primary.replace('#', '')
      const r = parseInt(hex.slice(0, 2), 16) / 255
      const g = parseInt(hex.slice(2, 4), 16) / 255
      const b = parseInt(hex.slice(4, 6), 16) / 255
      // Relative luminance (sRGB)
      const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
      root.style.setProperty('--color-on-primary', lum > 0.5 ? '#111111' : '#ffffff')
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
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <>
      {/* Desktop top navigation bar */}
      <TopNav />

      <Routes>
        <Route path="/login" element={<Navigate to="/dashboard" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin/*" element={<AdminConsolePage />} />
        <Route path="/quick-capture" element={<QuickCapturePage />} />
        <Route path="/scheduled-prompts" element={<ScheduledPromptsPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/finance/review" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><FinanceReviewPage /></Suspense>} />
        <Route path="/finance/net-worth" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><NetWorthPage /></Suspense>} />
        <Route path="/tools/:toolId" element={<ToolFramePage />} />
        <Route path="/db/*" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><DbBrowserPage /></Suspense>} />
        <Route path="/chat/*" element={<AppShell />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/*" element={<AppShell />} />
      </Routes>

      {/* Hotkey-triggered Quick Capture overlay. The `/quick-capture`
          route mounts its own copy via QuickCapturePage, so we render
          this one only when the user opened it via Ctrl/Cmd+Shift+K. */}
      {quickCaptureOpen && (
        <QuickCaptureOverlay onClose={() => setQuickCaptureOpen(false)} />
      )}

      {/* Bottom tab bar - mobile only */}
      <BottomTabBar />
    </>
  )
}

export default App
