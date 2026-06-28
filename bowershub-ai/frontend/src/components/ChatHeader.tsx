import { useWorkspaceStore } from '../stores/workspace'
import { useConversationStore } from '../stores/conversation'
import { useUIStore } from '../stores/ui'
import ModelPicker from './ModelPicker'

export default function ChatHeader() {
  const { activeWorkspace } = useWorkspaceStore()
  const { activeConversation } = useConversationStore()
  const { toggleSidebar } = useUIStore()

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
        {/* Global search lives in the shell chrome (desktop TopBar / mobile
            MobileTopBar) now, so the chat header no longer duplicates it. */}
        <ModelPicker />
      </div>
    </div>
  )
}
