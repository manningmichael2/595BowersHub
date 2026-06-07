/**
 * User settings store: theme + text size + voice + morning card prefs.
 *
 * Backed by GET/PATCH /api/settings (with POST /api/settings/reset-theme
 * for clearing the per-user theme override).
 *
 * The resolved effective theme + text size are persisted to localStorage so
 * the very first paint after a reload uses the right colors and font scale,
 * before the network call to /api/settings resolves.
 */

import { create } from 'zustand'
import { api } from '../services/api'

// ---- Types ----------------------------------------------------------------

export interface ThemeTokens {
  background: string
  surface: string
  primary: string
  accent: string
  text: string
  text_muted: string
  border: string
  danger: string
  success: string
  // tolerate forward-compat extras
  [k: string]: string
}

export interface EffectiveTheme {
  id: number | null
  name: string
  slug: string
  tokens_json: ThemeTokens
  is_default: boolean
}

export type TextSize = 'small' | 'medium' | 'large' | 'extra_large'

export interface VoiceSettings {
  // TTS output (assistant reads replies aloud)
  output_enabled?: boolean
  // Preferred SpeechSynthesisVoice.name. Empty string / null = browser default.
  voice_name?: string | null
  // SpeechSynthesisUtterance.rate, valid range 0.5..2.0
  speech_rate?: number
  // Pause threshold (in ms) before STT auto-finalizes + submits
  auto_submit_pause_ms?: number
  // If true, never auto-submit on pause — user must press send manually
  manual_send?: boolean
}

export interface UserSettings {
  theme_id?: number | null
  text_size?: TextSize
  morning_card_workspace_id?: number | null
  morning_card_disabled?: boolean
  voice?: VoiceSettings
  // tolerate any other keys the backend stores
  [k: string]: any
}

interface SettingsState {
  settings: UserSettings
  effectiveTheme: EffectiveTheme
  effectiveTextSize: TextSize
  isLoading: boolean
  isLoaded: boolean
  error: string | null

  loadSettings: () => Promise<void>
  patch: (delta: Partial<UserSettings>) => Promise<void>
  resetTheme: () => Promise<void>
}

// ---- Built-in fallback ----------------------------------------------------

// Mirrors the Dark Navy preset seeded by migration 009. Used only until the
// network call resolves (or if localStorage is empty on first launch).
const FALLBACK_THEME: EffectiveTheme = {
  id: null,
  name: 'Dark Navy',
  slug: 'dark-navy',
  is_default: true,
  tokens_json: {
    background: '#0f172a',
    surface: '#1e293b',
    primary: '#6366f1',
    accent: '#8b5cf6',
    text: '#f1f5f9',
    text_muted: '#94a3b8',
    border: '#334155',
    danger: '#ef4444',
    success: '#10b981',
  },
}

const STORAGE_KEY_THEME = 'bh.effectiveTheme'
const STORAGE_KEY_TEXT_SIZE = 'bh.effectiveTextSize'

// ---- localStorage hydrate -------------------------------------------------

function readCachedTheme(): EffectiveTheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_THEME)
    if (!raw) return FALLBACK_THEME
    const parsed = JSON.parse(raw)
    if (parsed && parsed.tokens_json && typeof parsed.tokens_json === 'object') {
      return { ...FALLBACK_THEME, ...parsed }
    }
    return FALLBACK_THEME
  } catch {
    return FALLBACK_THEME
  }
}

function readCachedTextSize(): TextSize {
  const raw = localStorage.getItem(STORAGE_KEY_TEXT_SIZE)
  if (raw === 'small' || raw === 'medium' || raw === 'large' || raw === 'extra_large') {
    return raw
  }
  return 'medium'
}

function persistTheme(theme: EffectiveTheme) {
  try {
    localStorage.setItem(STORAGE_KEY_THEME, JSON.stringify(theme))
  } catch {
    // localStorage full / disabled — non-fatal
  }
}

function persistTextSize(size: TextSize) {
  try {
    localStorage.setItem(STORAGE_KEY_TEXT_SIZE, size)
  } catch {
    // non-fatal
  }
}

// ---- Store ---------------------------------------------------------------

export const useSettingsStore = create<SettingsState>((set, get) => ({
  settings: {},
  effectiveTheme: readCachedTheme(),
  effectiveTextSize: readCachedTextSize(),
  isLoading: false,
  isLoaded: false,
  error: null,

  loadSettings: async () => {
    set({ isLoading: true, error: null })
    try {
      const res = await api.get('/api/settings')
      const data = res.data || {}
      const settings: UserSettings = data.settings ?? data ?? {}
      const effectiveTheme: EffectiveTheme = data.effective_theme ?? get().effectiveTheme
      const effectiveTextSize: TextSize = data.effective_text_size ?? get().effectiveTextSize

      persistTheme(effectiveTheme)
      persistTextSize(effectiveTextSize)

      set({
        settings,
        effectiveTheme,
        effectiveTextSize,
        isLoading: false,
        isLoaded: true,
      })
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to load settings'
      set({ isLoading: false, error: msg })
    }
  },

  patch: async (delta) => {
    // Optimistic merge — keeps the UI snappy on slow networks.
    const prevSettings = get().settings
    const prevTheme = get().effectiveTheme
    const prevTextSize = get().effectiveTextSize
    const optimisticSettings: UserSettings = { ...prevSettings, ...delta }
    if (delta.voice) {
      optimisticSettings.voice = { ...(prevSettings.voice || {}), ...delta.voice }
    }

    let optimisticTextSize = prevTextSize
    if (delta.text_size === 'small' || delta.text_size === 'medium' || delta.text_size === 'large' || delta.text_size === 'extra_large') {
      optimisticTextSize = delta.text_size
      persistTextSize(optimisticTextSize)
    }

    set({
      settings: optimisticSettings,
      effectiveTextSize: optimisticTextSize,
    })

    try {
      const res = await api.patch('/api/settings', delta)
      const data = res.data || {}
      const settings: UserSettings = data.settings ?? data ?? optimisticSettings
      const effectiveTheme: EffectiveTheme = data.effective_theme ?? get().effectiveTheme
      const effectiveTextSize: TextSize = data.effective_text_size ?? optimisticTextSize

      persistTheme(effectiveTheme)
      persistTextSize(effectiveTextSize)

      set({
        settings,
        effectiveTheme,
        effectiveTextSize,
        error: null,
      })
    } catch (err: any) {
      // Roll back optimistic update on failure.
      persistTextSize(prevTextSize)
      set({
        settings: prevSettings,
        effectiveTheme: prevTheme,
        effectiveTextSize: prevTextSize,
        error: err?.response?.data?.detail || 'Failed to update settings',
      })
      throw err
    }
  },

  resetTheme: async () => {
    const prevSettings = get().settings
    const prevTheme = get().effectiveTheme
    // Optimistic clear of the override; the backend will respond with the
    // platform default theme that the resolver picks.
    set({ settings: { ...prevSettings, theme_id: null } })

    try {
      const res = await api.post('/api/settings/reset-theme')
      const data = res.data || {}
      const settings: UserSettings = data.settings ?? { ...prevSettings, theme_id: null }
      const effectiveTheme: EffectiveTheme = data.effective_theme ?? prevTheme
      const effectiveTextSize: TextSize = data.effective_text_size ?? get().effectiveTextSize

      persistTheme(effectiveTheme)
      persistTextSize(effectiveTextSize)

      set({
        settings,
        effectiveTheme,
        effectiveTextSize,
        error: null,
      })
    } catch (err: any) {
      set({
        settings: prevSettings,
        effectiveTheme: prevTheme,
        error: err?.response?.data?.detail || 'Failed to reset theme',
      })
      throw err
    }
  },
}))
