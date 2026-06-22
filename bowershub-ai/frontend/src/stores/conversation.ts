import { create } from 'zustand'
import { z } from 'zod'
import { api } from '../services/api'
import { toast } from './toast'
import { parseLoose } from '../lib/validate'
import {
  ConversationSchema,
  MessageSchema,
  type Conversation,
  type Message,
} from '../schemas/conversation'

// Re-exported so existing `import { Conversation, Message } from '.../conversation'`
// call sites keep working; the definitions now live in ../schemas/conversation.
export type { Conversation, Message }

interface ConversationState {
  conversations: Conversation[]
  activeConversation: Conversation | null
  messages: Message[]
  isLoading: boolean
  // Non-null when the last conversation fetch failed (vs. a workspace that
  // legitimately has no conversations yet). Surfaced in the sidebar.
  error: string | null
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
  sendMessage: (content: string, model?: string) => Promise<void>
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
  error: null,
  isStreaming: false,
  streamingContent: '',
  streamingLayer: null,
  skillStatus: null,

  fetchConversations: async (workspaceId) => {
    set({ isLoading: true, error: null })
    try {
      const res = await api.get(`/api/conversations?workspace_id=${workspaceId}`)
      const conversations = parseLoose(
        z.array(ConversationSchema),
        res.data,
        'GET /api/conversations',
      )
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
      set({ isLoading: false, error: 'Could not load conversations.' })
      toast.error('Could not load conversations.')
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
      const messages = parseLoose(
        z.array(MessageSchema),
        res.data?.messages || [],
        'GET /api/conversations/:id',
      )
      set({ messages, isLoading: false })
    } catch (err) {
      // Don't trap the user on a broken conversation — fall back to "none active"
      // and let them pick a different one or start fresh.
      console.error('Failed to load conversation', conversation.id, err)
      set({ activeConversation: null, messages: [], isLoading: false })
    }
  },

  createConversation: async (workspaceId) => {
    const res = await api.post('/api/conversations', { workspace_id: workspaceId })
    const conv = parseLoose(ConversationSchema, res.data, 'POST /api/conversations')
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

  sendMessage: async (content, model = 'auto') => {
    const { activeConversation } = get()
    if (!activeConversation) return

    const convId = activeConversation.id

    // Optimistic: add user message
    const optimisticMsg: Message = {
      id: Date.now(),
      conversation_id: convId,
      role: 'user',
      content,
      attachments: [],
      model_used: null,
      routing_layer: null,
      input_tokens: null,
      output_tokens: null,
      cost_usd: null,
      metadata: {},
      created_at: new Date().toISOString(),
    }
    
    set(state => ({ 
      messages: [...state.messages, optimisticMsg], 
      isStreaming: true,
      streamingContent: '',
      streamingLayer: null
    }))

    // Send via WebSocket
    const { wsClient } = await import('../services/websocket')
    wsClient.sendMessage(convId, content, model)
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
    const older = parseLoose(
      z.array(MessageSchema),
      res.data,
      'GET /api/conversations/:id/messages',
    )
    set(state => ({ messages: [...older, ...state.messages] }))
  },
}))
