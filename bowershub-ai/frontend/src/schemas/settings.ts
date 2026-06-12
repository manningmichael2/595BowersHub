import { z } from 'zod'

export const ThemeTokensSchema = z.record(z.string(), z.string())

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
