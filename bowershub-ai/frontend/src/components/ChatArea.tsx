import { useRef, useEffect } from 'react'
import { useConversationStore } from '../stores/conversation'
import { useWorkspaceStore } from '../stores/workspace'
import { useUIStore } from '../stores/ui'
import ChatHeader from './ChatHeader'
import MessageList from './MessageList'
import InputArea from './InputArea'
import TypingIndicator from './TypingIndicator'

export default function ChatArea() {
  const { activeConversation, messages, isStreaming, streamingContent } = useConversationStore()
  const { activeWorkspace, isLoading: workspacesLoading } = useWorkspaceStore()
  const { toggleSidebar } = useUIStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, streamingContent])

  if (!activeWorkspace) {
    // Empty state. Crucially this must NOT be a dead-end on mobile: the
    // workspace switcher lives in the sidebar, which on mobile is closed by
    // default and only opens via a hamburger. ChatHeader (which owns that
    // hamburger) isn't rendered here, so we provide our own so the user can
    // always open the sidebar and pick a workspace.
    return (
      <div className="flex-1 flex flex-col h-full min-h-0">
        <div className="flex items-center px-4 py-3 border-b border-border bg-background/80 shrink-0 sm:hidden">
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-lg hover:bg-surface text-text-muted"
            aria-label="Open menu"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <div className="text-center px-6">
            <h2 className="text-2xl font-bold text-text mb-2">BowersHub AI</h2>
            <p>
              {workspacesLoading
                ? 'Loading workspaces…'
                : 'Select a workspace to get started — open the menu to choose one.'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col h-full min-h-0">
      <ChatHeader />

      {/* Messages area */}
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
        {!activeConversation ? (
          <div className="flex items-center justify-center h-full text-text-muted">
            <div className="text-center max-w-md">
              <div className="text-4xl mb-4">{activeWorkspace.icon || '💬'}</div>
              <h3 className="text-lg font-medium text-text-muted mb-2">
                {activeWorkspace.name}
              </h3>
              <p className="text-sm">
                Start a new conversation or select one from the sidebar.
              </p>
            </div>
          </div>
        ) : (
          <>
            <MessageList messages={messages} />
            {isStreaming && (
              <div className="mb-4">
                {streamingContent ? (
                  <div className="flex gap-3">
                    <div className="w-7 h-7 rounded-full bg-success flex items-center justify-center text-xs shrink-0 mt-1">
                      AI
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="markdown-content text-text text-sm">
                        {streamingContent}
                        <span className="inline-block w-2 h-4 bg-accent animate-pulse ml-0.5" />
                      </div>
                    </div>
                  </div>
                ) : (
                  <TypingIndicator />
                )}
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input area */}
      <InputArea />
    </div>
  )
}
