/**
 * Property-based tests for `lib/morning_card.ts` — the pure helpers driving
 * the MorningCard component's visibility decision and dismissal persistence.
 *
 * Property 7: Morning card visibility follows the truth table
 * Validates: Requirements R8.1, R8.5, R8.6
 *
 * The truth table being asserted is:
 *
 *   is_visible(age, set, date) ≡ (age < 24) AND (date ∉ set)
 *
 * Plus the operational invariants we lean on elsewhere:
 *   - is_visible never throws for any input (NaN, ±Infinity, negatives,
 *     empty / huge dismissal sets, empty date strings).
 *   - dismiss_today(date) + read_dismiss_set() round-trips: every dismissed
 *     date appears in the persisted set on read.
 *   - today_iso() returns a YYYY-MM-DD string for any Date instance.
 *
 * Iterations: 200 per property (above the 100-iteration floor in the design
 * doc; matches the convention used by contrast.property.test.ts).
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import fc from 'fast-check'

import {
  MORNING_CARD_DISMISS_KEY,
  dismiss_today,
  is_visible,
  read_dismiss_set,
  today_iso,
} from '../morning_card'

// --- Generators ---------------------------------------------------------------

// YYYY-MM-DD strings. Year 1900-2099, month 01-12, day 01-28 (avoid month-end
// edge cases — the helpers don't validate dates, they just compare strings).
const dateIsoArb: fc.Arbitrary<string> = fc
  .tuple(
    fc.integer({ min: 1900, max: 2099 }),
    fc.integer({ min: 1, max: 12 }),
    fc.integer({ min: 1, max: 28 }),
  )
  .map(
    ([y, m, d]) =>
      `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`,
  )

// Sets of dismissed dates. Up to 16 entries — enough to cover "card is
// dismissed" and "card is not dismissed" branches plenty of times.
const dismissSetArb: fc.Arbitrary<Set<string>> = fc
  .array(dateIsoArb, { maxLength: 16 })
  .map((arr) => new Set(arr))

// Briefing ages, including NaN, ±Infinity, negatives, and the boundary 24.0.
const ageArb: fc.Arbitrary<number> = fc.oneof(
  fc.double({ noNaN: false }),
  fc.constantFrom(0, 23.999, 24, 24.001, -1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY),
)

// --- localStorage isolation ---------------------------------------------------
//
// The dismiss_today/read_dismiss_set tests touch real localStorage (jsdom
// provides one). Reset between cases so a leak in one property can't mask a
// bug in another.

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  localStorage.clear()
})

// --- Tests --------------------------------------------------------------------

describe('morning_card — property tests', () => {
  it('Property 7a: is_visible matches the truth table for any input', () => {
    fc.assert(
      fc.property(ageArb, dismissSetArb, dateIsoArb, (age, set, date) => {
        // The contract from morning_card.ts:
        //   visible iff `age < 24` AND date is not in the dismiss set.
        // JS's `<` returns false for NaN, which is the desired behavior
        // (NaN ages stay hidden) — so the truth table is total.
        const expected = age < 24 && !set.has(date)
        expect(is_visible(age, set, date)).toBe(expected)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 7b: is_visible never throws for any combination of inputs', () => {
    fc.assert(
      fc.property(ageArb, dismissSetArb, dateIsoArb, (age, set, date) => {
        // Pathological inputs (NaN, ±Infinity, empty dismiss set, empty
        // date string) must not blow up. The component renders this on
        // every chat-area tick, so an exception here would be a hard crash.
        expect(() => is_visible(age, set, date)).not.toThrow()
      }),
      { numRuns: 200 },
    )
    // Empty-string date and a totally empty set are exercised explicitly
    // because the generator's minLength is 0 but won't always sample them.
    expect(() => is_visible(0, new Set(), '')).not.toThrow()
    expect(is_visible(0, new Set(), '')).toBe(true)
  })

  it('Property 7c: dismissed date is always hidden when briefing is fresh', () => {
    // Tightening of 7a: if the date is in the dismiss set, no fresh-briefing
    // age makes the card visible. Encodes R8.5 ("dismiss for the rest of the
    // day").
    fc.assert(
      fc.property(
        fc.double({ min: -1000, max: 23.999, noNaN: true }),
        dismissSetArb,
        dateIsoArb,
        (freshAge, baseSet, date) => {
          const set = new Set(baseSet)
          set.add(date)
          expect(is_visible(freshAge, set, date)).toBe(false)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 7d: stale briefing is always hidden regardless of dismissal', () => {
    // Tightening of 7a from the other side: ages ≥ 24 hide the card whether
    // or not the date is dismissed. Encodes R8.1 ("most recent within 24h").
    fc.assert(
      fc.property(
        fc.double({ min: 24, max: 1e9, noNaN: true }),
        dismissSetArb,
        dateIsoArb,
        (staleAge, set, date) => {
          expect(is_visible(staleAge, set, date)).toBe(false)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 7e: dismiss_today + read_dismiss_set round-trips', () => {
    // For any list of dates, dismissing them all in sequence must result in
    // a persisted set that contains exactly that union. Idempotency is
    // implicit (Set semantics) and is covered by repeated dates appearing
    // in the generator output.
    fc.assert(
      fc.property(fc.array(dateIsoArb, { maxLength: 8 }), (dates) => {
        localStorage.clear()
        for (const d of dates) dismiss_today(d)
        const persisted = read_dismiss_set()
        for (const d of dates) {
          expect(persisted.has(d)).toBe(true)
        }
        // No phantom entries: every persisted entry was something we dismissed.
        for (const d of persisted) {
          expect(dates).toContain(d)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('Property 7f: read_dismiss_set tolerates missing / malformed storage', () => {
    // The contract: read_dismiss_set() never throws. Cover empty storage,
    // non-JSON values, JSON that isn't an array, and arrays containing
    // non-strings (which must be filtered out).
    localStorage.clear()
    expect(read_dismiss_set().size).toBe(0)

    localStorage.setItem(MORNING_CARD_DISMISS_KEY, 'not-json{')
    expect(() => read_dismiss_set()).not.toThrow()
    expect(read_dismiss_set().size).toBe(0)

    localStorage.setItem(MORNING_CARD_DISMISS_KEY, '{"not":"an-array"}')
    expect(read_dismiss_set().size).toBe(0)

    localStorage.setItem(
      MORNING_CARD_DISMISS_KEY,
      JSON.stringify(['2026-05-27', 42, null, '2026-05-28', { x: 1 }]),
    )
    const set = read_dismiss_set()
    expect(set.size).toBe(2)
    expect(set.has('2026-05-27')).toBe(true)
    expect(set.has('2026-05-28')).toBe(true)
  })

  it('Property 7g: today_iso returns a valid YYYY-MM-DD string for any Date', () => {
    fc.assert(
      fc.property(fc.date({ min: new Date(1900, 0, 1), max: new Date(2099, 11, 31) }), (d) => {
        const iso = today_iso(d)
        // Shape: 4-digit year, 2-digit month, 2-digit day, hyphen-separated.
        expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}$/)
        // Components agree with the local-calendar Date the helper claims to use.
        const [y, m, day] = iso.split('-').map(Number)
        expect(y).toBe(d.getFullYear())
        expect(m).toBe(d.getMonth() + 1)
        expect(day).toBe(d.getDate())
        // Length 0..23 for the dismiss key — this string is what we compare
        // against entries in the dismiss set, so it must be stable shape.
        expect(iso.length).toBe(10)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 7h: dismissing today_iso(now) hides the card on the next render', () => {
    // End-to-end glue: the production flow is `dismiss_today(today_iso())`
    // followed by a render that calls `is_visible(age, read_dismiss_set(),
    // today_iso())`. That sequence must yield false for any fresh age.
    fc.assert(
      fc.property(
        fc.double({ min: -1000, max: 23.999, noNaN: true }),
        fc.date({ min: new Date(2000, 0, 1), max: new Date(2099, 11, 31) }),
        (freshAge, now) => {
          localStorage.clear()
          const today = today_iso(now)
          dismiss_today(today)
          const set = read_dismiss_set()
          expect(is_visible(freshAge, set, today)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })
})
