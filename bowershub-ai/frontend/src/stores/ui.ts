import { create } from 'zustand'

interface UIState {
  theme: 'dark' | 'light'
  sidebarOpen: boolean
  artifactPanelOpen: boolean
  searchOpen: boolean
  modelSelection: string // 'auto' or model ID
  modelLocked: boolean

  toggleTheme: () => void
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  setArtifactPanel: (open: boolean) => void
  setSearchOpen: (open: boolean) => void
  setModel: (model: string, locked?: boolean) => void
  resetModel: () => void
}

export const useUIStore = create<UIState>((set) => ({
  theme: (localStorage.getItem('theme') as 'dark' | 'light') || 'dark',
  sidebarOpen: window.innerWidth > 768,
  artifactPanelOpen: false,
  searchOpen: false,
  modelSelection: 'auto',
  modelLocked: false,

  toggleTheme: () => set(state => {
    const next = state.theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem('theme', next)
    document.documentElement.classList.toggle('dark', next === 'dark')
    return { theme: next }
  }),

  toggleSidebar: () => set(state => ({ sidebarOpen: !state.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  setArtifactPanel: (open) => set({ artifactPanelOpen: open }),
  setSearchOpen: (open) => set({ searchOpen: open }),

  setModel: (model, locked = false) => set({ modelSelection: model, modelLocked: locked }),
  resetModel: () => set({ modelSelection: 'auto', modelLocked: false }),
}))
