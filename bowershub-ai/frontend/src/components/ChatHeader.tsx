import { useEffect } from 'react'
import { useWorkspaceStore } from '../stores/workspace'
import { useConversationStore } from '../stores/conversation'
import { useUIStore } from '../stores/ui'
import { useCaptureVisibility } from '../stores/captureVisibility'
import ModelPicker from './ModelPicker'

export default function ChatHeader() {
  const { activeWorkspace } = useWorkspaceStore()
  const { activeConversation } = useConversationStore()
  const { toggleSidebar } = useUIStore()

  // Per-conversation Shared/Private capture mode (see stores/captureVisibility).
  const captureVisibility = useCaptureVisibility(s => s.visibility)
  const toggleCapture = useCaptureVisibility(s => s.toggle)
  const syncCapture = useCaptureVisibility(s => s.syncTo)
  useEffect(() => { syncCapture(activeConversation?.id) }, [activeConversation?.id, syncCapture])
  const isShared = captureVisibility === 'shared'

  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-background/80 backdrop-blur-sm shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={toggleSidebar}
          aria-label="Toggle conversation list"
          className="sm:hidden p-1.5 rounded-lg hover:bg-surface text-text-muted shrink-0"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>

        <div className="flex items-center gap-2 min-w-0">
          {activeWorkspace && (
            <>
              <span
                className="w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: activeWorkspace.color || 'var(--color-primary)' }}
              />
              <span className="text-sm font-medium text-text shrink-0">
                {activeWorkspace.name}
              </span>
            </>
          )}
          {activeConversation?.title && (
            <span className="text-sm text-text-muted truncate hidden sm:inline">
              / {activeConversation.title}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {/* Per-conversation capture privacy. A labeled pill (not an input-row
            icon) — it's a conversation mode, and the text makes it self-evident. */}
        <button
          onClick={toggleCapture}
          title={isShared
            ? 'Shared: facts the assistant learns from this conversation are visible to the whole household. Tap for Private.'
            : 'Private: facts learned from this conversation stay private to you. Tap to Share with the household.'}
          aria-label={isShared ? 'Capture: Shared' : 'Capture: Private'}
          aria-pressed={isShared}
          className={`flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium transition-colors ${
            isShared
              ? 'border-success/40 bg-success/10 text-success hover:bg-success/20'
              : 'border-border bg-surface text-text-muted hover:text-text'
          }`}
        >
          {isShared ? (
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a4 4 0 10-3-6.7" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          )}
          <span>{isShared ? 'Shared' : 'Private'}</span>
        </button>

        {/* Global search lives in the shell chrome (desktop TopBar / mobile
            MobileTopBar) now, so the chat header no longer duplicates it. */}
        <ModelPicker />
      </div>
    </div>
  )
}
