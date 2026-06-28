import { useEffect, lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/auth'
import { useSettingsStore } from './stores/settings'
import {
  setColorVar,
  normalizeThemeTokens,
  FOREGROUND_TEXT_ALIASES,
  FOREGROUND_COMPUTED_ALIASES,
} from './lib/themeTokens'
import { readableForeground } from './lib/contrast'
import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import SettingsPage from './pages/SettingsPage'
import AdminConsolePage from './pages/AdminConsolePage'
import ScheduledPromptsPage from './pages/ScheduledPromptsPage'
import QuickCapturePage from './pages/QuickCapturePage'
import ToolFramePage from './pages/ToolFramePage'
import DashboardPage from './pages/DashboardPage'
import ShellLayout from './components/shell/ShellLayout'
import { TEXT_SIZE_PX } from './lib/textSize'

// Lazy-loaded DB Browser — code-split to avoid impacting chat page load
const DbBrowserPage = lazy(() => import('./pages/DbBrowserPage'))
// Lazy-loaded Recurring (finance) — code-split, only loaded when visited
const RecurringPage = lazy(() => import('./pages/RecurringPage'))
// Lazy-loaded Net Worth (accounting) — code-split, only loaded when visited
const NetWorthPage = lazy(() => import('./pages/NetWorthPage'))
// Lazy-loaded Budgets — code-split, only loaded when visited
const BudgetsPage = lazy(() => import('./pages/BudgetsPage'))
import FinanceLayout from './components/FinanceLayout'
const TransactionsPage = lazy(() => import('./pages/TransactionsPage'))
const FinanceQaPage = lazy(() => import('./pages/FinanceQaPage'))
const InsightsPage = lazy(() => import('./pages/InsightsPage'))
const RetirementPlanner = lazy(() => import('./pages/RetirementPlanner'))

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
  ['warning', '--color-warning'],
  ['error', '--color-error'],
]

function App() {
  const { user } = useAuthStore()
  const loadSettings = useSettingsStore(s => s.loadSettings)
  const effectiveTheme = useSettingsStore(s => s.effectiveTheme)
  const effectiveTextSize = useSettingsStore(s => s.effectiveTextSize)

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
    if (!effectiveTheme.tokens_json) return
    // Normalize first so every contract key resolves to a real color even if
    // the theme predates a key (e.g. custom themes without warning/error) —
    // the runtime half of the R1.2 token contract.
    const tokens = normalizeThemeTokens(effectiveTheme.tokens_json)
    // `setColorVar` sets both the full-color var (consumed by inline styles /
    // index.css) AND a derived `--color-<name>-rgb` channel triple (consumed
    // by the Tailwind utilities so `bg-primary/20` etc. compose alpha). See
    // lib/themeTokens.ts.
    for (const [tokenKey, cssVar] of TOKEN_TO_CSS_VAR) {
      const value = tokens[tokenKey]
      if (typeof value === 'string' && value.length > 0) {
        setColorVar(root, cssVar, value)
      }
    }
    // Mirror `surface` to its light/dark convenience variants so any
    // surface-* utilities (used by older chrome) follow the active theme
    // instead of staying frozen at the index.css defaults.
    setColorVar(root, '--color-surface-light', tokens.surface)
    setColorVar(root, '--color-surface-dark', tokens.background || tokens.surface)

    // Foreground aliases (R1.3): a readable text/icon color for each surface.
    // Neutral surfaces reuse the theme's text token; colored surfaces get the
    // higher-contrast of dark/white (WCAG) so e.g. text on a button is legible.
    for (const [cssVar, tokenKey] of Object.entries(FOREGROUND_TEXT_ALIASES)) {
      setColorVar(root, cssVar, tokens[tokenKey])
    }
    for (const [cssVar, tokenKey] of Object.entries(FOREGROUND_COMPUTED_ALIASES)) {
      setColorVar(root, cssVar, readableForeground(tokens[tokenKey]))
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
    const px = TEXT_SIZE_PX[effectiveTextSize] ?? TEXT_SIZE_PX.medium
    root.style.setProperty('--bh-text-base', `${px}px`)
    // Clear any leftover root font-size override from a previous build —
    // we don't want to scale rem anymore.
    root.style.fontSize = ''
  }, [effectiveTextSize])

  // Global command hotkeys (Cmd/Ctrl+K search, Cmd/Ctrl+Shift+K quick capture)
  // live in ShellLayout now (R3.9), so they work on every section.

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
      {/* All authenticated sections render inside the one app shell (R3.1):
          a layout route whose <Outlet/> hosts the active section. */}
      <Routes>
        <Route element={<ShellLayout />}>
          <Route path="/login" element={<Navigate to="/dashboard" replace />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/admin/*" element={<AdminConsolePage />} />
          <Route path="/quick-capture" element={<QuickCapturePage />} />
          <Route path="/scheduled-prompts" element={<ScheduledPromptsPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/finance" element={<FinanceLayout />}>
            <Route index element={<Navigate to="/finance/transactions" replace />} />
            <Route path="transactions" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><TransactionsPage /></Suspense>} />
            <Route path="ask" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><FinanceQaPage /></Suspense>} />
            <Route path="insights" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><InsightsPage /></Suspense>} />
            <Route path="retirement" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><RetirementPlanner /></Suspense>} />
            <Route path="review" element={<Navigate to="/finance/transactions" replace />} />
            <Route path="recurring" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><RecurringPage /></Suspense>} />
            <Route path="net-worth" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><NetWorthPage /></Suspense>} />
            <Route path="budgets" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><BudgetsPage /></Suspense>} />
          </Route>
          <Route path="/tools/:toolId" element={<ToolFramePage />} />
          <Route path="/db/*" element={<Suspense fallback={<div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading…</div>}><DbBrowserPage /></Suspense>} />
          <Route path="/chat/*" element={<AppShell />} />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/*" element={<AppShell />} />
        </Route>
      </Routes>
    </>
  )
}

export default App
