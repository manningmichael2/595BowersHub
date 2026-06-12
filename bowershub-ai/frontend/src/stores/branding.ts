import { create } from 'zustand'
import { api } from '../services/api'
import { parseLoose } from '../lib/validate'
import { BrandingResponseSchema, type BrandingUrls } from '../schemas/branding'

export type { BrandingUrls }

interface BrandingState {
  version: string | null
  urls: BrandingUrls | null
  hasRollback: boolean
  isLoading: boolean

  refresh: () => Promise<void>
}

export const useBrandingStore = create<BrandingState>((set) => ({
  version: null,
  urls: null,
  hasRollback: false,
  isLoading: false,

  refresh: async () => {
    set({ isLoading: true })
    try {
      const res = await api.get('/api/branding/icon')
      const { version, urls, has_rollback } = parseLoose(
        BrandingResponseSchema,
        res.data,
        'GET /api/branding/icon'
      )
      set({
        version,
        urls,
        hasRollback: !!has_rollback,
        isLoading: false,
      })
    } catch {
      set({ isLoading: false })
    }
  },
}))
