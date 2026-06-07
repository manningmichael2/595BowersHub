import { create } from 'zustand'
import { api } from '../services/api'

export interface BrandingUrls {
  icon_192: string
  icon_512: string
  icon_maskable_512: string
}

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
      const { version, urls, has_rollback } = res.data
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
