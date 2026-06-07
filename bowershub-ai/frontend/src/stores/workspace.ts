import { create } from 'zustand'
import { api } from '../services/api'

export interface Workspace {
  id: number
  name: string
  description: string | null
  icon: string | null
  color: string | null
  system_prompt: string
  default_model: string
  auto_capture: boolean
  user_count: number
  skill_count: number
}

interface WorkspaceState {
  workspaces: Workspace[]
  activeWorkspace: Workspace | null
  isLoading: boolean

  fetchWorkspaces: () => Promise<void>
  setActive: (workspace: Workspace) => void
  setActiveById: (id: number) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  workspaces: [],
  activeWorkspace: null,
  isLoading: false,

  fetchWorkspaces: async () => {
    set({ isLoading: true })
    try {
      const res = await api.get('/api/workspaces')
      const workspaces = res.data
      set({ workspaces, isLoading: false })

      // Restore last active workspace or default to first
      const savedId = localStorage.getItem('activeWorkspaceId')
      const active = savedId
        ? workspaces.find((w: Workspace) => w.id === parseInt(savedId))
        : workspaces[0]
      if (active) set({ activeWorkspace: active })
    } catch {
      set({ isLoading: false })
    }
  },

  setActive: (workspace) => {
    const previous = useWorkspaceStore.getState().activeWorkspace
    set({ activeWorkspace: workspace })
    localStorage.setItem('activeWorkspaceId', String(workspace.id))

    // Clear active conversation when switching workspaces
    if (!previous || previous.id !== workspace.id) {
      // Import dynamically to avoid circular deps
      import('./conversation').then(({ useConversationStore }) => {
        useConversationStore.setState({
          activeConversation: null,
          messages: [],
          conversations: [],
        })
        useConversationStore.getState().fetchConversations(workspace.id)
      })
    }
  },

  setActiveById: (id) => {
    const ws = get().workspaces.find(w => w.id === id)
    if (ws) get().setActive(ws)
  },
}))
