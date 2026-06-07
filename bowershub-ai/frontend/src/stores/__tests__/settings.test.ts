/**
 * Unit tests for the settings store + the theme-application contract that
 * App.tsx relies on (writing `effectiveTheme.tokens_json` values to `:root`
 * as CSS custom properties).
 *
 * Coverage:
 *   1. `loadSettings()` populates `settings`, `effectiveTheme`,
 *      `effectiveTextSize` from the GET /api/settings response.
 *   2. `patch({theme_id})` triggers a PATCH and updates the store; the
 *      effective theme tokens reflect the server's response.
 *   3. `patch({text_size: 'large'})` updates `effectiveTextSize`.
 *   4. localStorage gets the new theme + text size persisted on every
 *      successful load/patch.
 *
 * CSS-custom-property assertion choice:
 *   The actual `document.documentElement.style.setProperty(...)` writes are
 *   driven from `App.tsx`, not the store. This test verifies the store-side
 *   contract (`effectiveTheme.tokens_json` updates correctly) AND replays
 *   the same loop App.tsx runs to confirm that, given the store's resolved
 *   theme, the right `--color-*` properties land on `:root`. Rendering the
 *   full `<App>` component (router + auth + websocket wiring) is left to a
 *   separate App-level integration test — out of scope for this file.
 *
 * Mocking: we mock the global `fetch` so no network calls leave the test
 * runner. The api client (`services/api.ts`) reads/writes to the auth store
 * for the bearer token, but with no token in state it simply omits the
 * Authorization header — which is fine for these tests.
 */

import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { useSettingsStore, type EffectiveTheme, type ThemeTokens } from '../settings'

// --- Test fixtures --------------------------------------------------------

const DARK_NAVY_TOKENS: ThemeTokens = {
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

const FOREST_TOKENS: ThemeTokens = {
  background: '#0b2a1a',
  surface: '#143d28',
  primary: '#22c55e',
  accent: '#84cc16',
  text: '#ecfdf5',
  text_muted: '#a7f3d0',
  border: '#166534',
  danger: '#f87171',
  success: '#86efac',
}

const DARK_NAVY_THEME: EffectiveTheme = {
  id: 1,
  name: 'Dark Navy',
  slug: 'dark-navy',
  tokens_json: DARK_NAVY_TOKENS,
  is_default: true,
}

const FOREST_THEME: EffectiveTheme = {
  id: 7,
  name: 'Forest',
  slug: 'forest',
  tokens_json: FOREST_TOKENS,
  is_default: false,
}

/**
 * Mirrors the loop in App.tsx that writes resolved theme tokens to `:root`
 * as CSS custom properties. Inlined here so the test can verify the
 * end-to-end contract without rendering the full `<App>` component.
 */
const TOKEN_TO_CSS_VAR: Array<[keyof ThemeTokens, string]> = [
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

function applyThemeToRoot(theme: EffectiveTheme) {
  const root = document.documentElement
  for (const [tokenKey, cssVar] of TOKEN_TO_CSS_VAR) {
    const value = theme.tokens_json[tokenKey]
    if (typeof value === 'string' && value.length > 0) {
      root.style.setProperty(cssVar, value)
    }
  }
}

// --- Helpers --------------------------------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** Reset the store back to its initial-module state between tests. */
function resetStore() {
  useSettingsStore.setState({
    settings: {},
    effectiveTheme: DARK_NAVY_THEME,
    effectiveTextSize: 'medium',
    isLoading: false,
    isLoaded: false,
    error: null,
  })
}

// --- Test setup -----------------------------------------------------------

beforeEach(() => {
  // Wipe persisted theme/size + reset store + reset DOM.
  localStorage.clear()
  document.documentElement.removeAttribute('style')
  resetStore()
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

// --- Tests ----------------------------------------------------------------

describe('useSettingsStore.loadSettings', () => {
  it('populates settings, effectiveTheme, and effectiveTextSize from GET /api/settings', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      jsonResponse({
        settings: {
          theme_id: 7,
          text_size: 'large',
          morning_card_disabled: false,
        },
        effective_theme: FOREST_THEME,
        effective_text_size: 'large',
      })
    )

    await useSettingsStore.getState().loadSettings()

    const state = useSettingsStore.getState()
    expect(state.isLoaded).toBe(true)
    expect(state.isLoading).toBe(false)
    expect(state.error).toBeNull()
    expect(state.settings.theme_id).toBe(7)
    expect(state.settings.text_size).toBe('large')
    expect(state.effectiveTheme).toEqual(FOREST_THEME)
    expect(state.effectiveTextSize).toBe('large')

    // Verify the GET hit /api/settings exactly once with the right method.
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toBe('/api/settings')
    expect((init as RequestInit).method).toBe('GET')
  })

  it('persists effectiveTheme + effectiveTextSize to localStorage', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      jsonResponse({
        settings: { theme_id: 7, text_size: 'large' },
        effective_theme: FOREST_THEME,
        effective_text_size: 'large',
      })
    )

    await useSettingsStore.getState().loadSettings()

    const cachedTheme = JSON.parse(localStorage.getItem('bh.effectiveTheme') || 'null')
    expect(cachedTheme).toEqual(FOREST_THEME)
    expect(localStorage.getItem('bh.effectiveTextSize')).toBe('large')
  })
})

describe('useSettingsStore.patch — theme_id', () => {
  it('triggers a PATCH /api/settings and updates effectiveTheme from the response', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      jsonResponse({
        settings: { theme_id: 7 },
        effective_theme: FOREST_THEME,
        effective_text_size: 'medium',
      })
    )

    await useSettingsStore.getState().patch({ theme_id: 7 })

    const state = useSettingsStore.getState()
    expect(state.effectiveTheme).toEqual(FOREST_THEME)
    expect(state.settings.theme_id).toBe(7)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toBe('/api/settings')
    expect((init as RequestInit).method).toBe('PATCH')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ theme_id: 7 })
  })

  it('replaying App.tsx token-application yields CSS custom properties matching the new theme', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      jsonResponse({
        settings: { theme_id: 7 },
        effective_theme: FOREST_THEME,
        effective_text_size: 'medium',
      })
    )

    await useSettingsStore.getState().patch({ theme_id: 7 })
    applyThemeToRoot(useSettingsStore.getState().effectiveTheme)

    const root = document.documentElement
    expect(root.style.getPropertyValue('--color-background')).toBe(FOREST_TOKENS.background)
    expect(root.style.getPropertyValue('--color-surface')).toBe(FOREST_TOKENS.surface)
    expect(root.style.getPropertyValue('--color-primary')).toBe(FOREST_TOKENS.primary)
    expect(root.style.getPropertyValue('--color-accent')).toBe(FOREST_TOKENS.accent)
    expect(root.style.getPropertyValue('--color-text')).toBe(FOREST_TOKENS.text)
    expect(root.style.getPropertyValue('--color-text-muted')).toBe(FOREST_TOKENS.text_muted)
    expect(root.style.getPropertyValue('--color-border')).toBe(FOREST_TOKENS.border)
    expect(root.style.getPropertyValue('--color-danger')).toBe(FOREST_TOKENS.danger)
    expect(root.style.getPropertyValue('--color-success')).toBe(FOREST_TOKENS.success)
  })

  it('persists the new effective theme to localStorage on successful patch', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      jsonResponse({
        settings: { theme_id: 7 },
        effective_theme: FOREST_THEME,
        effective_text_size: 'medium',
      })
    )

    await useSettingsStore.getState().patch({ theme_id: 7 })

    const cached = JSON.parse(localStorage.getItem('bh.effectiveTheme') || 'null')
    expect(cached).toEqual(FOREST_THEME)
  })
})

describe('useSettingsStore.patch — text_size', () => {
  it('updates effectiveTextSize and persists it to localStorage', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      jsonResponse({
        settings: { text_size: 'large' },
        effective_theme: DARK_NAVY_THEME,
        effective_text_size: 'large',
      })
    )

    await useSettingsStore.getState().patch({ text_size: 'large' })

    const state = useSettingsStore.getState()
    expect(state.effectiveTextSize).toBe('large')
    expect(state.settings.text_size).toBe('large')
    expect(localStorage.getItem('bh.effectiveTextSize')).toBe('large')
  })

  it('toggling between sizes reflects each value in the store', async () => {
    const fetchMock = vi.spyOn(global, 'fetch')

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        settings: { text_size: 'small' },
        effective_theme: DARK_NAVY_THEME,
        effective_text_size: 'small',
      })
    )
    await useSettingsStore.getState().patch({ text_size: 'small' })
    expect(useSettingsStore.getState().effectiveTextSize).toBe('small')

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        settings: { text_size: 'extra_large' },
        effective_theme: DARK_NAVY_THEME,
        effective_text_size: 'extra_large',
      })
    )
    await useSettingsStore.getState().patch({ text_size: 'extra_large' })
    expect(useSettingsStore.getState().effectiveTextSize).toBe('extra_large')
    expect(localStorage.getItem('bh.effectiveTextSize')).toBe('extra_large')
  })

  it('rolls back optimistic state on a failed PATCH', async () => {
    // Seed the store with a known starting point so we can verify the rollback.
    useSettingsStore.setState({
      settings: { text_size: 'medium' },
      effectiveTextSize: 'medium',
      effectiveTheme: DARK_NAVY_THEME,
    })

    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'nope' }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      })
    )

    await expect(
      useSettingsStore.getState().patch({ text_size: 'large' })
    ).rejects.toBeTruthy()

    const state = useSettingsStore.getState()
    expect(state.effectiveTextSize).toBe('medium')
    expect(state.settings.text_size).toBe('medium')
    expect(state.error).toBe('nope')
  })
})
