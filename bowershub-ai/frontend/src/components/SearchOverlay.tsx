import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { useUIStore } from '../stores/ui'
import { useConversationStore } from '../stores/conversation'

interface SearchResult {
  source_type: string
  content: string
  context?: string
  workspace_name?: string
  conversation_title?: string
  conversation_id?: number
  message_id?: number
  topic?: string
  file?: string
  created_at?: string
}

export default function SearchOverlay() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Record<string, SearchResult[]>>({})
  const [isSearching, setIsSearching] = useState(false)
  const [activeTab, setActiveTab] = useState<'all' | 'messages' | 'knowledge' | 'artifacts'>('all')
  const inputRef = useRef<HTMLInputElement>(null)
  const { setSearchOpen } = useUIStore()
  const { setActive } = useConversationStore()
  const navigate = useNavigate()

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Debounced search
  useEffect(() => {
    if (query.length < 2) {
      setResults({})
      return
    }

    const timer = setTimeout(async () => {
      setIsSearching(true)
      try {
        const res = await api.get(`/api/search?q=${encodeURIComponent(query)}&type=${activeTab}`)
        setResults(res.data.results || {})
      } catch {
        setResults({})
      }
      setIsSearching(false)
    }, 300)

    return () => clearTimeout(timer)
  }, [query, activeTab])

  const totalResults = Object.values(results).reduce((sum, arr) => sum + arr.length, 0)

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={() => setSearchOpen(false)} />

      {/* Search panel */}
      <div className="relative w-full max-w-2xl mx-4 bg-surface border border-border rounded-xl shadow-2xl overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <svg className="w-5 h-5 text-text-muted shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search conversations, knowledge, artifacts..."
            className="flex-1 bg-transparent text-text placeholder-text-muted text-sm focus:outline-none"
          />
          <kbd className="text-xs text-text-muted bg-background px-1.5 py-0.5 rounded">Esc</kbd>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-4 py-2 border-b border-border">
          {(['all', 'messages', 'knowledge', 'artifacts'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                activeTab === tab ? 'bg-primary/20 text-accent' : 'text-text-muted hover:text-text'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-y-auto">
          {isSearching && (
            <div className="p-4 text-center text-text-muted text-sm">Searching...</div>
          )}

          {!isSearching && query.length >= 2 && totalResults === 0 && (
            <div className="p-4 text-center text-text-muted text-sm">No results found</div>
          )}

          {/* Message results */}
          {(results.messages || []).map((r, i) => (
            <button
              key={`msg-${i}`}
              onClick={() => {
                // Navigate to the conversation — and route to chat so this
                // works when search is opened from any section (R3.9).
                if (r.conversation_id) {
                  setActive({ id: r.conversation_id } as any)
                  navigate('/chat')
                }
                setSearchOpen(false)
              }}
              className="w-full text-left px-4 py-3 hover:bg-background/50 border-b border-border/50"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs px-1.5 py-0.5 rounded bg-blue-900/30 text-blue-400">message</span>
                <span className="text-xs text-text-muted">{r.workspace_name}</span>
                <span className="text-xs text-text-muted">• {r.conversation_title}</span>
              </div>
              <p className="text-sm text-text line-clamp-2">{r.content}</p>
            </button>
          ))}

          {/* Knowledge results */}
          {(results.knowledge || []).map((r, i) => (
            <div key={`know-${i}`} className="px-4 py-3 border-b border-border/50">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs px-1.5 py-0.5 rounded bg-green-900/30 text-green-400">knowledge</span>
                <span className="text-xs text-text-muted">{r.topic || r.file}</span>
              </div>
              <p className="text-sm text-text">{r.content}</p>
            </div>
          ))}

          {/* Artifact results */}
          {(results.artifacts || []).map((r, i) => (
            <div key={`art-${i}`} className="px-4 py-3 border-b border-border/50">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs px-1.5 py-0.5 rounded bg-accent/20 text-accent">artifact</span>
                <span className="text-xs text-text-muted">{r.workspace_name}</span>
              </div>
              <p className="text-sm text-text line-clamp-2">{r.content}</p>
            </div>
          ))}
        </div>

        {/* Footer */}
        {totalResults > 0 && (
          <div className="px-4 py-2 border-t border-border text-xs text-text-muted">
            {totalResults} result{totalResults !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}
