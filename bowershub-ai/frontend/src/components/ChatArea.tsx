import { useRef, useEffect } from 'react'
import { useConversationStore } from '../stores/conversation'
import { useWorkspaceStore } from '../stores/workspace'
import ChatHeader from './ChatHeader'
import MessageList from './MessageList'
import InputArea from './InputArea'
import TypingIndicator from './TypingIndicator'

export default function ChatArea() {
  const { activeConversation, messages, isStreaming, streamingContent } = useConversationStore()
  const { activeWorkspace } = useWorkspaceStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, streamingContent])

  if (!activeWorkspace) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-300 mb-2">BowersHub AI</h2>
          <p>Select a workspace to get started</p>
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
          <div className="flex items-center justify-center h-full text-gray-500">
            <div className="text-center max-w-md">
              <div className="text-4xl mb-4">{activeWorkspace.icon || '💬'}</div>
              <h3 className="text-lg font-medium text-gray-300 mb-2">
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
                    <div className="w-7 h-7 rounded-full bg-emerald-600 flex items-center justify-center text-xs shrink-0 mt-1">
                      AI
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="markdown-content text-gray-200 text-sm">
                        {streamingContent}
                        <span className="inline-block w-2 h-4 bg-indigo-400 animate-pulse ml-0.5" />
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
