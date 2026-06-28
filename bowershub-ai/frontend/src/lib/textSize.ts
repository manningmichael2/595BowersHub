import type { TextSize } from '../schemas/settings'

/**
 * Base font-size (px) per text-size preference — the SINGLE source of truth for
 * both the runtime `--bh-text-base` injection (App.tsx, which all `text-*`
 * utilities compute against) and the Appearance preview tiles. Keeping them in
 * one place stops the preview from drifting out of sync with the real sizing.
 *
 * The scale is intentionally wide at the top: most UI uses `text-sm`/`text-xs`
 * (< base), so "Large"/"Extra Large" need a generous base to actually read large.
 */
export const TEXT_SIZE_PX: Record<TextSize, number> = {
  small: 15,
  medium: 17,
  large: 22,
  extra_large: 26,
}
