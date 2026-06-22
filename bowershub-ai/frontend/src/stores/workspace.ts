import { create } from 'zustand'
import { z } from 'zod'
import { api } from '../services/api'
import { toast } from './toast'
import { parseLoose } from '../lib/validate'
import { WorkspaceSchema, type Workspace } from '../schemas/workspace'

export type { Workspace }

interface WorkspaceState {
  workspaces: Workspace[]
  activeWorkspace: Workspace | null
  isLoading: boolean
  // Non-null when the last fetch *failed* (network/5xx) — distinct from a
  // successful fetch that simply returned no workspaces. The UI uses this to
  // show "couldn't load — retry" instead of a silent/misleading empty state.
  error: string | null

  fetchWorkspaces: () => Promise<void>
  setActive: (workspace: Workspace) => void
  setActiveById: (id: number) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  workspaces: [],
  activeWorkspace: null,
  isLoading: false,
  error: null,

  fetchWorkspaces: async () => {
    set({ isLoading: true, error: null })
    try {
      const res = await api.get('/api/workspaces')
      const workspaces = parseLoose(
        z.array(WorkspaceSchema),
        res.data,
        'GET /api/workspaces'
      )
      set({ workspaces, isLoading: false })

      // Restore last active workspace, else fall back to the first one.
      // The fallback is important: a stale `activeWorkspaceId` (a workspace
      // that was deleted/renamed, or a different environment) would otherwise
      // leave `activeWorkspace` null forever — which on mobile is a dead-end
      // (no header → no hamburger → no way to open the workspace menu).
      const savedId = localStorage.getItem('activeWorkspaceId')
      const saved = savedId
        ? workspaces.find((w: Workspace) => w.id === parseInt(savedId))
        : undefined
      const active = saved || workspaces[0]
      if (active) {
        set({ activeWorkspace: active })
        // Heal the stale pointer so the next load resolves directly.
        if (!saved) localStorage.setItem('activeWorkspaceId', String(active.id))
      }
    } catch {
      // A genuine failure (network/5xx). Don't leave the UI looking like an
      // empty account — record the error and tell the user.
      set({ isLoading: false, error: 'Could not load workspaces.' })
      toast.error('Could not load your workspaces. Check your connection and retry.')
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
