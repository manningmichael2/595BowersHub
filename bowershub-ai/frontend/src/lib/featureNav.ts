/**
 * Role/feature helpers for role-aware nav (R3.1/R5.5). The server is the source
 * of truth (GET /api/me/features); the frontend NEVER infers permission from
 * role alone — it computes nav from `permitted (server) ∩ not self-hidden`.
 */

export interface FeatureInfo {
  key: string
  label: string
  routes: string[]
  permitted: boolean
}

export interface FeatureAccess {
  role: string
  capabilities: string[]
  features: FeatureInfo[]
  hidden_nav: string[]
}

// Mirrors backend authz.ROLE_RANK (the single ladder). Unknown/None → -1.
export const ROLE_RANK: Record<string, number> = { viewer: 10, member: 20, admin: 100 }

export function roleRank(role: string | null | undefined): number {
  return role ? (ROLE_RANK[role] ?? -1) : -1
}

/** True if `role` meets the `min` threshold. Unknown `min` → unreachable (fail-closed). */
export function roleMeets(role: string | null | undefined, min: string): boolean {
  const threshold = ROLE_RANK[min]
  if (threshold === undefined) return false
  return roleRank(role) >= threshold
}

/** Server-permitted AND not self-hidden — the rule for showing a feature's nav button. */
export function isFeatureVisible(
  access: FeatureAccess | null,
  featureKey: string,
): boolean {
  if (!access) return false
  const f = access.features.find(x => x.key === featureKey)
  if (!f || !f.permitted) return false
  return !access.hidden_nav.includes(featureKey)
}

/**
 * Nav visibility with OPTIMISTIC loading. While the effective-access payload is
 * still unresolved (`access === null` — fetch in flight, or it failed and is
 * retrying), show the item rather than fail-closed-hiding it: the server still
 * enforces access on click, so an unreachable/slow `/api/me/features` no longer
 * silently makes a user's whole gated nav vanish (the exact failure that hid
 * Finance/Database when the features route 404'd). Once access IS resolved, the
 * strict `permitted ∩ not-hidden` rule applies. Ungated items always show.
 *
 * Tradeoff: during the load window a less-privileged user may briefly see a
 * button they can't use (clicking it 403s server-side) — acceptable vs. the
 * "my nav disappeared" failure for the common single-admin case.
 */
export function isNavItemVisible(
  access: FeatureAccess | null,
  featureKey: string | undefined,
): boolean {
  if (!featureKey) return true
  if (access === null) return true
  return isFeatureVisible(access, featureKey)
}

/** The set of feature keys whose nav button should show. */
export function visibleFeatureKeys(access: FeatureAccess | null): Set<string> {
  if (!access) return new Set()
  return new Set(
    access.features
      .filter(f => f.permitted && !access.hidden_nav.includes(f.key))
      .map(f => f.key),
  )
}
