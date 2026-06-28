import { z } from 'zod'

/**
 * Token contract (R1.2). Replaces the old free-form `z.record(string,string)`
 * with the enumerated keys a theme is expected to carry, so drift is *detected*
 * (parseLoose logs a mismatch) rather than silently producing undefined tokens.
 *
 * Core keys are required (every preset and ThemeBuilder default has had them
 * since launch). `warning`/`error` are `.optional()` because themes authored
 * before migration 0043 (and custom themes) may lack them — they are filled at
 * runtime by `normalizeThemeTokens` (the fallback half of the contract).
 * `.passthrough()` keeps any extra keys a future theme might add.
 */
export const ThemeTokensSchema = z
  .object({
    background: z.string(),
    surface: z.string(),
    primary: z.string(),
    accent: z.string(),
    text: z.string(),
    text_muted: z.string(),
    border: z.string(),
    danger: z.string(),
    success: z.string(),
    warning: z.string().optional(),
    error: z.string().optional(),
  })
  // catchall(string), not passthrough(): a theme may carry extra keys, but they
  // are still colors — this keeps the inferred type string-indexable (used by
  // normalizeThemeTokens / ThemeBuilder) instead of `unknown`.
  .catchall(z.string())

export const EffectiveThemeSchema = z
  .object({
    id: z.number().nullable(),
    name: z.string(),
    slug: z.string(),
    tokens_json: ThemeTokensSchema,
    is_default: z.boolean(),
  })
  .passthrough()

export const TextSizeSchema = z.enum(['small', 'medium', 'large', 'extra_large'])

export const VoiceSettingsSchema = z
  .object({
    output_enabled: z.boolean().optional(),
    voice_name: z.string().nullable().optional(),
    speech_rate: z.number().optional(),
    auto_submit_pause_ms: z.number().optional(),
    manual_send: z.boolean().optional(),
  })
  .passthrough()

export const UserSettingsSchema = z
  .object({
    theme_id: z.number().nullable().optional(),
    text_size: TextSizeSchema.optional(),
    morning_card_workspace_id: z.number().nullable().optional(),
    morning_card_disabled: z.boolean().optional(),
    voice: VoiceSettingsSchema.optional(),
    use_experimental_dashboard: z.boolean().optional(),
    // DB Browser sidebar prefs: "schema.table" keys for favorites/hidden, and
    // the set of expanded schema names (collapse-by-default otherwise).
    db_favorites: z.array(z.string()).optional(),
    db_hidden: z.array(z.string()).optional(),
    db_expanded: z.array(z.string()).optional(),
  })
  .passthrough()

export const SettingsResponseSchema = z
  .object({
    settings: UserSettingsSchema.optional(),
    effective_theme: EffectiveThemeSchema.optional(),
    effective_text_size: TextSizeSchema.optional(),
  })
  .passthrough()

export type ThemeTokens = z.infer<typeof ThemeTokensSchema>
export type EffectiveTheme = z.infer<typeof EffectiveThemeSchema>
export type TextSize = z.infer<typeof TextSizeSchema>
export type VoiceSettings = z.infer<typeof VoiceSettingsSchema>
export type UserSettings = z.infer<typeof UserSettingsSchema>
