/**
 * Component tests for AppearancePanel + VoicePanel.
 *
 * Coverage (task 19.4):
 *   - AppearancePanel: clicking a theme card calls `useSettingsStore.patch`
 *     with the matching `theme_id`.
 *   - AppearancePanel: the four text-size buttons render their labels as a
 *     live preview, each at its own (strictly increasing) inline font size so
 *     the preview visually reflects each size (R4.2). The size is applied via
 *     an inline `font-size`, which intentionally beats the inert `.bh-text-*`
 *     marker classes — see the note in index.css.
 *   - VoicePanel: when the browser does not expose `SpeechRecognition`
 *     (or `webkitSpeechRecognition`), the panel surfaces the
 *     "Voice unavailable" notice and hides the STT-only controls
 *     (Auto-submit pause, Manual send) (R10.8).
 *
 * _Requirements: R3.1, R4.2, R10.8
 *
 * Mocking:
 *   - `services/api` is mocked so no network requests leave the test
 *     runner. `api.get('/api/themes')` returns a small fixed catalog;
 *     `api.patch`/`api.post` are stubs.
 *   - `useSettingsStore` is reset and seeded before each test. The
 *     store's `patch` method is replaced with a vitest spy so the
 *     AppearancePanel test can assert the click handler called it
 *     without exercising the optimistic-update path or the real PATCH.
 *   - jsdom does not implement Web Speech APIs by default. We
 *     additionally `delete` `SpeechRecognition` / `webkitSpeechRecognition`
 *     in the VoicePanel test to guarantee the capability detector
 *     reports `false` regardless of any earlier test setup.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import AppearancePanel from '../AppearancePanel'
import VoicePanel from '../VoicePanel'
import { useSettingsStore, type EffectiveTheme, type ThemeTokens } from '../../stores/settings'

// ---- API mock ------------------------------------------------------------

vi.mock('../../services/api', () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  }
})

// Late-bound import so the mock above is in place by the time the test
// resolves the module.
import { api } from '../../services/api'

// ---- Theme mock data -----------------------------------------------------

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

const THEMES_FIXTURE = [
  {
    id: 1,
    name: 'Dark Navy',
    slug: 'dark-navy',
    is_preset: true,
    owner_id: null,
    tokens_json: DARK_NAVY_TOKENS,
    is_default: true,
  },
  {
    id: 2,
    name: 'Forest',
    slug: 'forest',
    is_preset: true,
    owner_id: null,
    tokens_json: FOREST_TOKENS,
    is_default: false,
  },
]

// ---- Shared setup --------------------------------------------------------

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('style')

  // Default api mocks — overridden inside individual tests as needed.
  ;(api.get as any).mockReset?.()
  ;(api.post as any).mockReset?.()
  ;(api.patch as any).mockReset?.()
  ;(api.delete as any).mockReset?.()

  ;(api.get as any).mockImplementation(async (path: string) => {
    if (path === '/api/themes') return { data: THEMES_FIXTURE }
    return { data: {} }
  })
  ;(api.post as any).mockResolvedValue({ data: {} })
  ;(api.patch as any).mockResolvedValue({ data: {} })
  ;(api.delete as any).mockResolvedValue({ data: {} })

  // Reset the store to a known shape AND swap in spy implementations for
  // the methods the panels invoke. We assert against these spies directly
  // — that's enough to prove the click handler does the right thing,
  // without relying on the store's optimistic-update internals.
  useSettingsStore.setState({
    settings: {},
    effectiveTheme: DARK_NAVY_THEME,
    effectiveTextSize: 'medium',
    isLoading: false,
    isLoaded: true,
    error: null,
    patch: vi.fn().mockResolvedValue(undefined),
    resetTheme: vi.fn().mockResolvedValue(undefined),
    loadSettings: vi.fn().mockResolvedValue(undefined),
  } as any)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// ---- AppearancePanel -----------------------------------------------------

describe('AppearancePanel', () => {
  it('clicking a theme card calls useSettingsStore.patch with that theme_id', async () => {
    render(<AppearancePanel />)

    // Wait for the themes fetch to populate the grid.
    const forestCard = await screen.findByRole('button', { name: /Forest/ })
    expect(forestCard).toBeTruthy()

    await act(async () => {
      fireEvent.click(forestCard)
    })

    const patchSpy = useSettingsStore.getState().patch as ReturnType<typeof vi.fn>
    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith({ theme_id: 2 })
    })
  })

  it('renders each text-size button label at its own preview font size (R4.2)', async () => {
    render(<AppearancePanel />)

    // Wait for the themes fetch to resolve so the trailing async state
    // update doesn't trigger an `act(...)` warning before our assertions.
    await screen.findByRole('button', { name: /Forest/ })

    // The live preview renders each label at its own inline font size (the
    // `.bh-text-*` classes are inert markers — actual sizing is the inline
    // `font-size`, per index.css). Verify the four previews are present and
    // their sizes strictly increase, so the preview reflects each size.
    const sizes = ['Small', 'Medium', 'Large', 'Extra Large'].map(label => {
      const node = screen.getByText(label) as HTMLElement
      const px = parseFloat(node.style.fontSize)
      expect(px).toBeGreaterThan(0)
      return px
    })

    for (let i = 1; i < sizes.length; i++) {
      expect(sizes[i]).toBeGreaterThan(sizes[i - 1])
    }
  })
})

// ---- VoicePanel ----------------------------------------------------------

describe('VoicePanel', () => {
  it('shows the "Voice unavailable" notice and hides STT controls when SpeechRecognition is undefined', () => {
    // Force capability detection to fail. jsdom omits these by default,
    // but be explicit so an unrelated test cannot leak state into ours.
    delete (window as any).SpeechRecognition
    delete (window as any).webkitSpeechRecognition

    render(<VoicePanel />)

    // Capability badge present.
    expect(
      screen.getByText(/Voice unavailable in this browser\./i),
    ).toBeTruthy()

    // STT-only sections must not be in the DOM (R10.8 — controls hidden,
    // not just disabled, when speech recognition is missing).
    expect(screen.queryByText(/Auto-submit pause/i)).toBeNull()
    expect(screen.queryByLabelText(/Auto-submit pause threshold/i)).toBeNull()
    expect(screen.queryByText(/^Manual send$/i)).toBeNull()
    expect(
      screen.queryByRole('switch', { name: /Manual send/i }),
    ).toBeNull()
  })
})
