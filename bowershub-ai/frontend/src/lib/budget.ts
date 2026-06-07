/**
 * budget.ts — pure helper for the pinned-context budget UI.
 *
 * Extracted from `PinnedContextManager.tsx` so the threshold logic can be
 * property-tested independently of React. The component renders a colored
 * warning banner based on how much of the workspace's pinned-context
 * budget the current entries consume.
 *
 * Spec (R7.8 in `bowershub-ai-enhancements`):
 *   < 75% of budget   → no warning             ('ok')
 *   ≥ 75% of budget   → amber "approaching"    ('warn')
 *   ≥ 100% of budget  → red over-budget banner ('over')
 *
 * Edge cases:
 *   - `budget <= 0` is treated as "no budget configured" and returns 'ok'
 *     (matches the prior inline behavior, which short-circuited
 *     `budgetPct = budget > 0 ? total / budget : 0`).
 *   - Negative totals never exceed 75% of a positive budget, so they
 *     return 'ok'. The helper does not raise on any finite number input.
 */

export type BudgetTone = 'ok' | 'warn' | 'over'

/** Threshold (as a ratio of total/budget) at which the amber warning fires. */
export const BUDGET_WARN_RATIO = 0.75

/** Threshold (as a ratio of total/budget) at which the red over banner fires. */
export const BUDGET_OVER_RATIO = 1.0

/**
 * Decide which tone the pinned-context budget banner should render.
 *
 * @param total  Sum of token estimates across all pinned entries.
 * @param budget Workspace pinned-context budget (typically 2000).
 * @returns      'ok' | 'warn' | 'over'
 */
export function budgetTone(total: number, budget: number): BudgetTone {
  if (!Number.isFinite(total) || !Number.isFinite(budget) || budget <= 0) {
    return 'ok'
  }
  const ratio = total / budget
  if (ratio >= BUDGET_OVER_RATIO) return 'over'
  if (ratio >= BUDGET_WARN_RATIO) return 'warn'
  return 'ok'
}
