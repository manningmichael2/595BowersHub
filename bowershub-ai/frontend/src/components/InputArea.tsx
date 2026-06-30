import { useCallback, useState, useRef, useEffect, KeyboardEvent, ChangeEvent } from 'react'
import { useConversationStore } from '../stores/conversation'
import { useWorkspaceStore } from '../stores/workspace'
import { useUIStore } from '../stores/ui'
import { wsClient } from '../services/websocket'
import { api } from '../services/api'
import SlashAutocomplete from './SlashAutocomplete'
import VoiceModeButton from './VoiceModeButton'

interface PendingAttachment {
  file: File
  preview: string  // data URL for image preview
  mime: string
  base64: string   // raw base64 (no data: prefix)
  uploading: boolean
  error?: string
}

// Command history — persists across re-renders via sessionStorage
const HISTORY_KEY = 'bh-input-history'
const MAX_HISTORY = 50

function getHistory(): string[] {
  try {
    return JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]')
  } catch { return [] }
}

function pushHistory(msg: string) {
  const hist = getHistory()
  // Don't duplicate the last entry
  if (hist[hist.length - 1] === msg) return
  hist.push(msg)
  if (hist.length > MAX_HISTORY) hist.shift()
  sessionStorage.setItem(HISTORY_KEY, JSON.stringify(hist))
}

// Personal/Shared capture toggle — controls the visibility the Context Harvester
// applies to facts auto-learned from what you type. Sticky per-conversation;
// defaults to 'private' (Personal) so anything lost or unset fails safe to private
// (auto-capture never silently shares).
type CaptureVisibility = 'private' | 'shared'
const CAPTURE_VIS_KEY = 'bh-capture-visibility'

function getStoredVisibility(convId: number | null | undefined): CaptureVisibility {
  if (!convId) return 'private'
  try {
    const map = JSON.parse(sessionStorage.getItem(CAPTURE_VIS_KEY) || '{}')
    return map[convId] === 'shared' ? 'shared' : 'private'
  } catch { return 'private' }
}

function storeVisibility(convId: number | null | undefined, vis: CaptureVisibility) {
  if (!convId) return
  try {
    const map = JSON.parse(sessionStorage.getItem(CAPTURE_VIS_KEY) || '{}')
    map[convId] = vis
    sessionStorage.setItem(CAPTURE_VIS_KEY, JSON.stringify(map))
  } catch { /* sessionStorage unavailable — in-memory state still applies */ }
}

export default function InputArea() {
  const [input, setInput] = useState('')
  const [showSlash, setShowSlash] = useState(false)
  const [attachments, setAttachments] = useState<PendingAttachment[]>([])
  const [captureVisibility, setCaptureVisibility] = useState<CaptureVisibility>('private')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // History navigation state
  const historyIndexRef = useRef(-1)  // -1 = not browsing history
  const draftRef = useRef('')         // saves current draft when entering history

  const { activeConversation, isStreaming, createConversation } = useConversationStore()
  const { activeWorkspace } = useWorkspaceStore()
  const { modelSelection } = useUIStore()

  // Load this conversation's sticky Personal/Shared choice when it changes.
  useEffect(() => {
    setCaptureVisibility(getStoredVisibility(activeConversation?.id))
  }, [activeConversation?.id])

  const toggleCaptureVisibility = () => {
    const next: CaptureVisibility = captureVisibility === 'shared' ? 'private' : 'shared'
    setCaptureVisibility(next)
    storeVisibility(activeConversation?.id, next)
  }
  const composerPrefill = useUIStore(s => s.composerPrefill)
  const setComposerPrefill = useUIStore(s => s.setComposerPrefill)

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 150) + 'px'
    }
  }, [input])

  // Load `fill:` chat-link text into the composer, focus, and place the cursor
  // at the end so the user can finish the command (e.g. pick a category).
  useEffect(() => {
    if (composerPrefill == null) return
    setInput(composerPrefill)
    setComposerPrefill(null)
    const el = textareaRef.current
    if (el) {
      el.focus()
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = el.value.length
      })
    }
  }, [composerPrefill, setComposerPrefill])

  // Show slash autocomplete — only when actively typing (not from history nav)
  const [isFromHistory, setIsFromHistory] = useState(false)
  
  useEffect(() => {
    if (isFromHistory) {
      setShowSlash(false)
      return
    }
    if (!input.startsWith('/')) {
      setShowSlash(false)
      return
    }
    if (!input.includes(' ')) {
      // Still typing the base command name — show matching commands
      setShowSlash(true)
    } else {
      // After the space — show flag suggestions if user is still in flag territory
      const afterSpace = input.slice(input.indexOf(' ') + 1)
      // Show autocomplete when: nothing typed yet (just the space), or typing a dash
      // Don't show when user has typed past a flag (e.g., "/sports --scores tigers")
      const parts = afterSpace.trim().split(/\s+/)
      if (parts.length <= 1 && (afterSpace === '' || afterSpace.trimEnd() === afterSpace)) {
        // Still on first arg — show if it starts with - or is empty
        setShowSlash(!afterSpace.trim() || afterSpace.trim().startsWith('-'))
      } else {
        // Already typed a second word after the flag — hide autocomplete
        setShowSlash(false)
      }
    }
  }, [input, isFromHistory])

  // Intercept "/" key globally to focus textarea (prevents Firefox Quick Find)
  useEffect(() => {
    const handleGlobalSlash = (e: globalThis.KeyboardEvent) => {
      if (e.key !== '/') return
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || (e.target as HTMLElement)?.isContentEditable) return
      e.preventDefault()
      textareaRef.current?.focus()
      setInput('/')
    }
    document.addEventListener('keydown', handleGlobalSlash)
    return () => document.removeEventListener('keydown', handleGlobalSlash)
  }, [])

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const newAttachments: PendingAttachment[] = []

    for (let i = 0; i < Math.min(files.length, 3); i++) {
      const file = files[i]
      // Read as base64
      const base64 = await readFileAsBase64(file)
      const preview = file.type.startsWith('image/') ? URL.createObjectURL(file) : ''
      
      newAttachments.push({
        file,
        preview,
        mime: file.type || 'application/octet-stream',
        base64,
        uploading: false,
      })
    }

    setAttachments(prev => [...prev, ...newAttachments].slice(0, 5))
    // Reset file input so the same file can be re-selected
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const removeAttachment = (idx: number) => {
    setAttachments(prev => {
      const copy = [...prev]
      if (copy[idx]?.preview) URL.revokeObjectURL(copy[idx].preview)
      copy.splice(idx, 1)
      return copy
    })
  }

  const handleSend = async (overrideContent?: string) => {
    const content = (overrideContent ?? input).trim()
    if ((!content && attachments.length === 0) || isStreaming) return

    // Save to command history
    if (content) pushHistory(content)
    historyIndexRef.current = -1
    draftRef.current = ''

    // Create conversation if none active
    let convId = activeConversation?.id
    if (!convId && activeWorkspace) {
      const conv = await createConversation(activeWorkspace.id)
      convId = conv.id
    }
    if (!convId) return

    // Build attachment payloads for the WebSocket message
    const wsAttachments = attachments.map(att => ({
      mime: att.mime,
      base64: att.base64,
      filename: att.file.name,
    }))

    // Also upload to server so files are persisted on disk (for smart capture)
    if (attachments.length > 0) {
      const formData = new FormData()
      formData.append('conversation_id', String(convId))
      attachments.forEach(att => formData.append('files', att.file))
      try {
        await api.post('/api/files/upload', formData)
      } catch (err) {
        console.warn('File upload failed (will still send via WS):', err)
      }
    }

    // Optimistic: add user message to store
    const optimisticMsg = {
      id: Date.now(),
      conversation_id: convId,
      role: 'user' as const,
      content: content || '📷 ' + attachments.map(a => a.file.name).join(', '),
      attachments: wsAttachments.map(a => ({ mime: a.mime, filename: a.filename })),
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

    // Send via WebSocket (includes base64 attachments for vision). capture_visibility
    // tells the Context Harvester whether facts learned from this message are
    // private to the author or shared with the household.
    wsClient.sendMessage(convId, content || 'What is this?', modelSelection, wsAttachments, captureVisibility)

    // Reset model if not locked
    if (!useUIStore.getState().modelLocked) {
      useUIStore.getState().resetModel()
    }

    // Clean up
    attachments.forEach(att => { if (att.preview) URL.revokeObjectURL(att.preview) })
    setAttachments([])
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
      return
    }

    // Up arrow — navigate to previous commands (only when cursor is at position 0)
    if (e.key === 'ArrowUp') {
      const el = textareaRef.current
      if (el && el.selectionStart === 0 && el.selectionEnd === 0) {
        const history = getHistory()
        if (history.length === 0) return

        e.preventDefault()
        if (historyIndexRef.current === -1) {
          // Entering history mode — save current draft
          draftRef.current = input
          historyIndexRef.current = history.length - 1
        } else if (historyIndexRef.current > 0) {
          historyIndexRef.current--
        }
        setIsFromHistory(true)
        setInput(history[historyIndexRef.current])
      }
    }

    // Down arrow — navigate forward through history (only when cursor is at end)
    if (e.key === 'ArrowDown') {
      if (historyIndexRef.current === -1) return  // not in history mode
      const el = textareaRef.current
      const atEnd = el && el.selectionStart === el.value.length
      if (atEnd) {
        e.preventDefault()
        const history = getHistory()
        if (historyIndexRef.current < history.length - 1) {
          historyIndexRef.current++
          setInput(history[historyIndexRef.current])
        } else {
          // Back to the draft
          historyIndexRef.current = -1
          setInput(draftRef.current)
        }
      }
    }
  }

  const handleSlashSelect = (command: string, send?: boolean) => {
    if (send) {
      // Flag selected — send immediately
      setInput(command)
      setShowSlash(false)
      // Use setTimeout to let React update the input state before sending
      setTimeout(() => handleSend(command), 0)
    } else {
      // Command or flag selected — fill input with trailing space for typing args
      setInput(command + ' ')
      setShowSlash(false)
    }
    textareaRef.current?.focus()
  }

  return (
    <div className="border-t border-border bg-background/80 backdrop-blur-sm p-3 relative shrink-0" style={{ paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom))' }}>
      {/* Slash autocomplete */}
      {showSlash && (
        <SlashAutocomplete
          input={input}
          onSelect={handleSlashSelect}
          onClose={() => setShowSlash(false)}
        />
      )}

      <div className="flex items-end gap-2 max-w-4xl mx-auto">
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,.pdf,.doc,.docx,.txt"
          multiple
          className="hidden"
          onChange={handleFileSelect}
        />

        {/* File attach button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          className="p-2 rounded-lg hover:bg-surface text-text-muted hover:text-text shrink-0 mb-0.5 transition-colors"
          title="Attach photo or file"
          disabled={isStreaming}
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>

        {/* Text input + attachment preview */}
        <div className="flex-1 relative">
          {/* Attachment thumbnails */}
          {attachments.length > 0 && (
            <div className="flex gap-2 mb-2 px-1">
              {attachments.map((att, idx) => (
                <div key={idx} className="relative group">
                  {att.preview ? (
                    <img src={att.preview} alt={att.file.name} className="w-16 h-16 rounded-lg object-cover border border-border" />
                  ) : (
                    <div className="w-16 h-16 rounded-lg border border-border bg-surface flex items-center justify-center text-xs text-text-muted">
                      📄
                    </div>
                  )}
                  <button
                    onClick={() => removeAttachment(idx)}
                    className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-danger text-on-primary text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Remove"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => { setIsFromHistory(false); setInput(e.target.value) }}
            onKeyDown={handleKeyDown}
            placeholder={attachments.length > 0 ? "Add a message about this photo..." : (activeConversation ? "Message BowersHub AI..." : "Start a new conversation...")}
            className="w-full bg-surface border border-border rounded-xl px-4 py-2.5 text-sm text-text placeholder-text-muted resize-none focus:outline-none focus:border-primary transition-colors"
            rows={1}
            disabled={isStreaming}
          />
        </div>

        {/* Personal/Shared capture toggle — sets whether facts the assistant
            auto-learns from this message stay private to you or are shared with
            the household. Defaults to Personal. */}
        <button
          onClick={toggleCaptureVisibility}
          className={`p-2 rounded-lg hover:bg-surface shrink-0 mb-0.5 transition-colors ${
            captureVisibility === 'shared' ? 'text-success' : 'text-text-muted hover:text-text'}`}
          title={captureVisibility === 'shared'
            ? 'Shared: facts learned here are visible to the whole household. Click for Personal.'
            : 'Personal: facts learned here stay private to you. Click to Share with the household.'}
          aria-label={captureVisibility === 'shared' ? 'Capture mode: Shared' : 'Capture mode: Personal'}
          aria-pressed={captureVisibility === 'shared'}
        >
          {captureVisibility === 'shared' ? (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a4 4 0 10-3-6.7" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          )}
        </button>

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
            className="p-2.5 rounded-xl bg-danger hover:bg-danger/90 text-on-primary shrink-0 mb-0.5 transition-colors"
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
            disabled={!input.trim() && attachments.length === 0}
            className="p-2.5 rounded-xl bg-primary hover:brightness-110 disabled:bg-surface-light disabled:cursor-not-allowed text-on-primary shrink-0 mb-0.5 transition-colors"
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
          <span className="text-xs text-primary">
            Using: {modelSelection.includes('haiku') ? 'Haiku' : modelSelection.includes('sonnet') ? 'Sonnet' : modelSelection}
          </span>
        </div>
      )}
    </div>
  )
}

/** Read a file as base64 (without the data:... prefix) */
function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // Strip the "data:image/jpeg;base64," prefix
      const base64 = result.split(',')[1] || ''
      resolve(base64)
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}
