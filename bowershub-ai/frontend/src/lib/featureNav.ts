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

/** The set of feature keys whose nav button should show. */
export function visibleFeatureKeys(access: FeatureAccess | null): Set<string> {
  if (!access) return new Set()
  return new Set(
    access.features
      .filter(f => f.permitted && !access.hidden_nav.includes(f.key))
      .map(f => f.key),
  )
}
