/**
 * Property-based tests for the pinned-context budget threshold helper
 * `lib/budget.ts`. The helper drives the warning banner in
 * `<PinnedContextManager>`: at <75% of budget no warning, at ≥75% an
 * amber "approaching" warning, and at ≥100% a red over-budget banner.
 *
 * Property 6: Pinned context budget warning matches the threshold
 * Validates: Requirements R7.8
 *
 * The component path is in the file name because this property is the
 * UI's correctness contract — the helper was extracted from the
 * component for testability — and it lives next to the other component
 * tests so the test discoverer keeps related coverage together.
 *
 * Iterations: 200 per property (above the 100-iteration floor in the
 * design doc).
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'

import {
  budgetTone,
  BUDGET_OVER_RATIO,
  BUDGET_WARN_RATIO,
} from '../../lib/budget'

// --- Generators ---------------------------------------------------------------

// Token estimates are non-negative integers in the entries returned by
// the API; the helper itself accepts any finite number, so the
// generators stay broad enough to exercise both.
const tokenEstimateArb = fc.integer({ min: 0, max: 10_000 })

// Lists of token estimates (the realistic input — sum of these is the
// `total` passed to budgetTone). Empty lists are explicitly included.
const tokenListArb = fc.array(tokenEstimateArb, { minLength: 0, maxLength: 25 })

// Workspace pinned-context budgets — the default per R7.8 is 2000, but
// the API may return any positive value. Zero is exercised separately
// below as an edge case.
const positiveBudgetArb = fc.integer({ min: 1, max: 50_000 })

// --- Reference -----------------------------------------------------------------
//
// Independently coded reference for the threshold table so a regression
// in `budget.ts` cannot silently pass through here. Kept in lock-step
// with R7.8: <75% ok, [75%, 100%) warn, ≥100% over. Treats budget ≤ 0
// as "no budget configured" and returns 'ok' (matches the helper's
// short-circuit, which also matches the prior inline behavior in
// `PinnedContextManager.tsx` — `budgetPct = budget > 0 ? total/budget : 0`).

type Tone = 'ok' | 'warn' | 'over'

function refTone(total: number, budget: number): Tone {
  if (
    !Number.isFinite(total) ||
    !Number.isFinite(budget) ||
    budget <= 0
  ) {
    return 'ok'
  }
  const ratio = total / budget
  if (ratio >= BUDGET_OVER_RATIO) return 'over'
  if (ratio >= BUDGET_WARN_RATIO) return 'warn'
  return 'ok'
}

// --- Tests ---------------------------------------------------------------------

describe('budgetTone — property tests (R7.8)', () => {
  it('Property 6a: tone matches the published thresholds for valid inputs', () => {
    fc.assert(
      fc.property(tokenListArb, positiveBudgetArb, (estimates, budget) => {
        const total = estimates.reduce((a, b) => a + b, 0)
        const got = budgetTone(total, budget)
        const want = refTone(total, budget)
        expect(got).toBe(want)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 6b: empty list is always ok regardless of budget', () => {
    // Sum of an empty list is 0, which is always < 75% of any positive
    // budget. The helper must not raise on empty lists or zero/negative
    // budgets.
    fc.assert(
      fc.property(
        fc.integer({ min: -100, max: 50_000 }),
        (budget) => {
          expect(budgetTone(0, budget)).toBe('ok')
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 6c: zero or negative budget never warns', () => {
    // The component treats budget ≤ 0 as "no budget configured" — the
    // helper must short-circuit to 'ok' instead of dividing by zero or
    // returning a misleading 'over'.
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 1_000_000 }),
        fc.integer({ min: -10_000, max: 0 }),
        (total, budget) => {
          expect(budgetTone(total, budget)).toBe('ok')
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 6d: warn fires iff total ∈ [0.75·budget, 1.0·budget)', () => {
    // Tightening of R7.8: warn must fire on the closed-open interval
    // [75%, 100%), matching `>=75%` and `<100%` in the spec text.
    fc.assert(
      fc.property(positiveBudgetArb, fc.double({ min: 0, max: 2, noNaN: true }), (budget, ratio) => {
        const total = Math.round(ratio * budget)
        const tone = budgetTone(total, budget)
        const actualRatio = total / budget
        if (actualRatio >= 1) {
          expect(tone).toBe('over')
        } else if (actualRatio >= 0.75) {
          expect(tone).toBe('warn')
        } else {
          expect(tone).toBe('ok')
        }
      }),
      { numRuns: 200 },
    )
  })

  it('Property 6e: tone is monotonic in total (ok ≤ warn ≤ over)', () => {
    // For a fixed positive budget, increasing the total can never move
    // the tone "back" toward ok. This is the property the UI relies on
    // when a user adds more pinned entries: the banner only ever gets
    // more severe, never less.
    const order: Record<Tone, number> = { ok: 0, warn: 1, over: 2 }
    fc.assert(
      fc.property(
        positiveBudgetArb,
        fc.integer({ min: 0, max: 100_000 }),
        fc.integer({ min: 0, max: 100_000 }),
        (budget, a, b) => {
          const lo = Math.min(a, b)
          const hi = Math.max(a, b)
          const toneLo = budgetTone(lo, budget)
          const toneHi = budgetTone(hi, budget)
          expect(order[toneHi]).toBeGreaterThanOrEqual(order[toneLo])
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 6f: never raises on any finite numeric input', () => {
    // The helper is on a hot UI render path; it must be total. Any
    // finite (total, budget) pair returns one of the three known tones.
    fc.assert(
      fc.property(
        fc.double({ noNaN: true, noDefaultInfinity: true }),
        fc.double({ noNaN: true, noDefaultInfinity: true }),
        (total, budget) => {
          const tone = budgetTone(total, budget)
          expect(['ok', 'warn', 'over']).toContain(tone)
        },
      ),
      { numRuns: 200 },
    )
  })
})
