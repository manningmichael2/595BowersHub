import { create } from 'zustand'
import { api } from '../services/api'

export interface Message {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result'
  content: string
  attachments: any[]
  model_used: string | null
  routing_layer: string | null
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
  metadata: Record<string, any>
  created_at: string
}

export interface Conversation {
  id: number
  workspace_id: number
  title: string | null
  parent_id: number | null
  is_archived: boolean
  created_at: string
  updated_at: string
  message_count: number
}

interface ConversationState {
  conversations: Conversation[]
  activeConversation: Conversation | null
  messages: Message[]
  isLoading: boolean
  isStreaming: boolean
  streamingContent: string
  streamingLayer: string | null
  skillStatus: { skill: string; status: string } | null

  fetchConversations: (workspaceId: number) => Promise<void>
  setActive: (conversation: Conversation | null) => Promise<void>
  createConversation: (workspaceId: number) => Promise<Conversation>
  updateTitle: (id: number, title: string) => Promise<void>
  archiveConversation: (id: number) => Promise<void>
  addMessage: (message: Message) => void
  setStreaming: (streaming: boolean, content?: string, layer?: string | null) => void
  appendStreamToken: (token: string) => void
  setSkillStatus: (status: { skill: string; status: string } | null) => void
  loadMoreMessages: (beforeId: number) => Promise<void>
}

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [],
  activeConversation: null,
  messages: [],
  isLoading: false,
  isStreaming: false,
  streamingContent: '',
  streamingLayer: null,
  skillStatus: null,

  fetchConversations: async (workspaceId) => {
    set({ isLoading: true })
    try {
      const res = await api.get(`/api/conversations?workspace_id=${workspaceId}`)
      const conversations = res.data as Conversation[]
      set({ conversations, isLoading: false })

      // Auto-resume the most recently updated conversation when entering a
      // workspace. The list is already sorted by updated_at DESC server-side.
      // Only auto-select when there's no active conversation yet (or it's
      // from a different workspace) — never override an explicit user pick.
      const state = get()
      const current = state.activeConversation
      if (conversations.length && (!current || current.workspace_id !== workspaceId)) {
        const mostRecent = conversations[0]
        await state.setActive(mostRecent)
      }
    } catch {
      set({ isLoading: false })
    }
  },

  setActive: async (conversation) => {
    if (!conversation) {
      set({ activeConversation: null, messages: [] })
      return
    }
    set({ activeConversation: conversation, isLoading: true })
    try {
      const res = await api.get(`/api/conversations/${conversation.id}`)
      set({ messages: res.data.messages || [], isLoading: false })
    } catch (err) {
      // Don't trap the user on a broken conversation — fall back to "none active"
      // and let them pick a different one or start fresh.
      console.error('Failed to load conversation', conversation.id, err)
      set({ activeConversation: null, messages: [], isLoading: false })
    }
  },

  createConversation: async (workspaceId) => {
    const res = await api.post('/api/conversations', { workspace_id: workspaceId })
    const conv = res.data
    set(state => ({
      conversations: [conv, ...state.conversations],
      activeConversation: conv,
      messages: [],
    }))
    return conv
  },

  updateTitle: async (id, title) => {
    await api.patch(`/api/conversations/${id}`, { title })
    set(state => ({
      conversations: state.conversations.map(c => c.id === id ? { ...c, title } : c),
      activeConversation: state.activeConversation?.id === id
        ? { ...state.activeConversation, title }
        : state.activeConversation,
    }))
  },

  archiveConversation: async (id) => {
    await api.patch(`/api/conversations/${id}`, { is_archived: true })
    set(state => ({
      conversations: state.conversations.filter(c => c.id !== id),
      activeConversation: state.activeConversation?.id === id ? null : state.activeConversation,
    }))
  },

  addMessage: (message) => {
    set(state => ({
      messages: [...state.messages, message],
      streamingContent: '',
      isStreaming: false,
      streamingLayer: null,
    }))
  },

  setStreaming: (streaming, content = '', layer = null) => {
    set({ isStreaming: streaming, streamingContent: content, streamingLayer: layer })
  },

  appendStreamToken: (token) => {
    set(state => ({ streamingContent: state.streamingContent + token }))
  },

  setSkillStatus: (status) => {
    set({ skillStatus: status })
  },

  loadMoreMessages: async (beforeId) => {
    const conv = get().activeConversation
    if (!conv) return
    const res = await api.get(`/api/conversations/${conv.id}/messages?before=${beforeId}&limit=50`)
    set(state => ({ messages: [...res.data, ...state.messages] }))
  },
}))
