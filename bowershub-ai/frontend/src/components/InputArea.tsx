import { useCallback, useState, useRef, useEffect, KeyboardEvent } from 'react'
import { useConversationStore } from '../stores/conversation'
import { useWorkspaceStore } from '../stores/workspace'
import { useUIStore } from '../stores/ui'
import { wsClient } from '../services/websocket'
import SlashAutocomplete from './SlashAutocomplete'
import VoiceModeButton from './VoiceModeButton'

export default function InputArea() {
  const [input, setInput] = useState('')
  const [showSlash, setShowSlash] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { activeConversation, isStreaming, createConversation } = useConversationStore()
  const { activeWorkspace } = useWorkspaceStore()
  const { modelSelection } = useUIStore()

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 150) + 'px'
    }
  }, [input])

  // Show slash autocomplete
  useEffect(() => {
    setShowSlash(input.startsWith('/') && !input.includes(' '))
  }, [input])

  const handleSend = async (overrideContent?: string) => {
    const content = (overrideContent ?? input).trim()
    if (!content || isStreaming) return

    // Create conversation if none active
    let convId = activeConversation?.id
    if (!convId && activeWorkspace) {
      const conv = await createConversation(activeWorkspace.id)
      convId = conv.id
    }
    if (!convId) return

    // Optimistic: add user message to store
    const optimisticMsg = {
      id: Date.now(), // Temporary ID
      conversation_id: convId,
      role: 'user' as const,
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
    useConversationStore.getState().addMessage(optimisticMsg)
    useConversationStore.getState().setStreaming(true)

    // Send via WebSocket
    wsClient.sendMessage(convId, content, modelSelection)

    // Reset model if not locked
    if (!useUIStore.getState().modelLocked) {
      useUIStore.getState().resetModel()
    }

    setInput('')
  }

  // Voice mode wiring: stream the partial transcript into the input field
  // and dispatch a send when the recognizer auto-finalizes.
  const handleVoiceTranscript = useCallback((text: string) => {
    setInput(text)
  }, [])

  const handleVoiceAutoSubmit = useCallback((text: string) => {
    // Submit using the finalized transcript directly. We deliberately
    // bypass React state for `input` because the recognizer's onend
    // event fires before React has had a chance to flush the trailing
    // setInput from the partial-transcript handler — using `text` here
    // guarantees we send what the user actually said.
    setInput('')
    void handleSend(text)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversation, activeWorkspace, isStreaming, modelSelection])

  const handleStop = () => {
    const convId = activeConversation?.id
    if (!convId) return
    wsClient.cancelMessage(convId)
    // Optimistically clear the streaming state — server will also send a
    // "cancelled" event but we want the UI to react immediately.
    useConversationStore.getState().setStreaming(false)
    useConversationStore.getState().setSkillStatus(null)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSlashSelect = (command: string) => {
    setInput(command + ' ')
    setShowSlash(false)
    textareaRef.current?.focus()
  }

  return (
    <div className="border-t border-gray-800 bg-[#0f0f1a]/80 backdrop-blur-sm p-3 relative shrink-0" style={{ paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom))' }}>
      {/* Slash autocomplete */}
      {showSlash && (
        <SlashAutocomplete
          input={input}
          onSelect={handleSlashSelect}
          onClose={() => setShowSlash(false)}
        />
      )}

      <div className="flex items-end gap-2 max-w-4xl mx-auto">
        {/* File attach button */}
        <button
          className="p-2 rounded-lg hover:bg-gray-800 text-gray-400 shrink-0 mb-0.5"
          title="Attach file"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>

        {/* Text input */}
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={activeConversation ? "Message BowersHub AI..." : "Start a new conversation..."}
            className="w-full bg-[#1a1a2e] border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-indigo-500 transition-colors"
            rows={1}
            disabled={isStreaming}
          />
        </div>

        {/* Voice-mode button (mic + stop-speaking). Hidden when STT is
            unavailable in this browser; shows a stop-speaking control when
            the assistant is reading replies aloud. */}
        <VoiceModeButton
          onTranscriptUpdate={handleVoiceTranscript}
          onAutoSubmit={handleVoiceAutoSubmit}
        />

        {/* Send / Stop button — toggles based on streaming state */}
        {isStreaming ? (
          <button
            onClick={handleStop}
            className="p-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-white shrink-0 mb-0.5 transition-colors"
            title="Stop response"
            aria-label="Stop response"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="1" />
            </svg>
          </button>
        ) : (
          <button
            onClick={() => handleSend()}
            disabled={!input.trim()}
            className="p-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white shrink-0 mb-0.5 transition-colors"
            title="Send"
            aria-label="Send message"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19V5m0 0l-7 7m7-7l7 7" />
            </svg>
          </button>
        )}
      </div>

      {/* Model indicator */}
      {modelSelection !== 'auto' && (
        <div className="text-center mt-1">
          <span className="text-xs text-indigo-400">
            Using: {modelSelection.includes('haiku') ? 'Haiku' : modelSelection.includes('sonnet') ? 'Sonnet' : modelSelection}
          </span>
        </div>
      )}
    </div>
  )
}
