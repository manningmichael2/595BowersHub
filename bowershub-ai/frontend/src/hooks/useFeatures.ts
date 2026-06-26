/**
 * useFeatures — the current user's server-computed effective access
 * (GET /api/me/features), loaded into the auth store. Triggers a load if it
 * hasn't been fetched yet. Nav components read this to decide which feature
 * buttons to show — permitted (server) ∩ not self-hidden.
 */
import { useEffect } from 'react'
import { useAuthStore } from '../stores/auth'
import type { FeatureAccess } from '../lib/featureNav'

export function useFeatures(): FeatureAccess | null {
  const access = useAuthStore(s => s.featureAccess)
  const user = useAuthStore(s => s.user)
  const load = useAuthStore(s => s.loadFeatureAccess)
  useEffect(() => {
    if (user && !access) load()
  }, [user, access, load])
  return access
}
