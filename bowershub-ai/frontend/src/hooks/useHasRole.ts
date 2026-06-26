/**
 * useHasRole — whether the current user's role meets a minimum threshold,
 * using the canonical ladder (viewer < member < admin). Fail-closed on an
 * unknown role/threshold. The backend's require_role/require_capability is the
 * enforcing safety net; this only drives UI affordances.
 */
import { useAuthStore } from '../stores/auth'
import { roleMeets } from '../lib/featureNav'

export function useHasRole(min: string): boolean {
  const user = useAuthStore(s => s.user)
  return roleMeets(user?.role, min)
}
