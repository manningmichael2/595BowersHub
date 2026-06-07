/**
 * Pure helpers for morning-card visibility.
 *
 * The MorningCard component delegates its visibility decision and dismissal
 * persistence to these functions so the logic is trivially testable (see
 * Property 7 — frontend/src/lib/__tests__/morning_card.property.test.ts).
 *
 * Design contract:
 *   - is_visible(briefing_age_hours, dismiss_set, current_date_iso)
 *       returns true iff:
 *         briefing_age_hours < 24
 *       AND
 *         current_date_iso ∉ dismiss_set
 *
 *   - dismiss_set is a Set<string> of YYYY-MM-DD calendar-day strings.
 *
 * Persistence:
 *   - Dismissals live in localStorage under MORNING_CARD_DISMISS_KEY as a
 *     JSON array of YYYY-MM-DD strings.
 *   - read_dismiss_set() and dismiss_today(date) are tolerant of missing /
 *     malformed storage; both never throw.
 *
 * No React, no fetches, no I/O beyond localStorage. The functions match the
 * (snake_case) names called out in tasks.md §25.1.
 */

export const MORNING_CARD_DISMISS_KEY = 'bh.morningCard.dismissedDates'

/**
 * Pure visibility predicate. Returns true when the briefing is fresh enough
 * to show AND the user has not dismissed the card for `current_date_iso`.
 *
 * `briefing_age_hours` is treated literally — negative values (clock skew)
 * still satisfy `< 24`, which is the desired behavior (a briefing dated
 * slightly in the future is just a fresh briefing).
 *
 * NaN ages are never considered fresh, so the card stays hidden in that
 * pathological case rather than flickering on.
 */
export function is_visible(
  briefing_age_hours: number,
  dismiss_set: Set<string>,
  current_date_iso: string,
): boolean {
  if (Number.isNaN(briefing_age_hours)) return false
  return briefing_age_hours < 24 && !dismiss_set.has(current_date_iso)
}

/**
 * Read the set of YYYY-MM-DD dismissal markers from localStorage. Returns
 * an empty Set when storage is unavailable, missing, or contains malformed
 * JSON. Non-string entries are filtered out so callers can rely on a
 * uniformly-typed `Set<string>`.
 */
export function read_dismiss_set(): Set<string> {
  try {
    const raw = localStorage.getItem(MORNING_CARD_DISMISS_KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    const out = new Set<string>()
    for (const entry of parsed) {
      if (typeof entry === 'string') out.add(entry)
    }
    return out
  } catch {
    return new Set()
  }
}

/**
 * Persist a dismissal for the given calendar day. The date is stored as-is
 * (no parsing or validation) so callers control the date format; the
 * convention used by MorningCard is YYYY-MM-DD.
 *
 * Idempotent: dismissing the same day twice is a no-op. localStorage errors
 * (quota exceeded, disabled by the browser) are swallowed — dismissal is a
 * best-effort UX hint, not data we're willing to surface failures for.
 */
export function dismiss_today(date: string): void {
  try {
    const set = read_dismiss_set()
    set.add(date)
    localStorage.setItem(MORNING_CARD_DISMISS_KEY, JSON.stringify(Array.from(set)))
  } catch {
    // localStorage unavailable / quota exceeded — non-fatal
  }
}

/**
 * Helper for tests and for the unlikely "user wants to see today's card
 * again after dismissing" path. Removes a single date entry from the
 * persisted set; no-op when the date isn't dismissed.
 */
export function clear_dismiss(date: string): void {
  try {
    const set = read_dismiss_set()
    if (!set.delete(date)) return
    localStorage.setItem(MORNING_CARD_DISMISS_KEY, JSON.stringify(Array.from(set)))
  } catch {
    // non-fatal
  }
}

/**
 * Format a Date into the YYYY-MM-DD string the dismissal set is keyed on.
 * Uses the local calendar day (not UTC), matching the user's expectation
 * that "today" means today where they're sitting. Exposed as a helper so
 * MorningCard.tsx and its tests share one definition.
 */
export function today_iso(now: Date = new Date()): string {
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
