import { useConversationStore } from '../stores/conversation'

export default function TypingIndicator() {
  const { skillStatus } = useConversationStore()

  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 rounded-full bg-emerald-600 flex items-center justify-center text-xs shrink-0">
        AI
      </div>
      <div className="flex items-center gap-2">
        {skillStatus ? (
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span>Calling {skillStatus.skill}...</span>
          </div>
        ) : (
          <div className="flex gap-1 py-3 px-1">
            <span className="typing-dot w-2 h-2 rounded-full bg-gray-400" />
            <span className="typing-dot w-2 h-2 rounded-full bg-gray-400" />
            <span className="typing-dot w-2 h-2 rounded-full bg-gray-400" />
          </div>
        )}
      </div>
    </div>
  )
}
