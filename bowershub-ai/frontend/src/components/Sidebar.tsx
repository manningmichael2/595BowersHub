import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useWorkspaceStore } from '../stores/workspace'
import { useConversationStore, Conversation } from '../stores/conversation'
import { useAuthStore } from '../stores/auth'
import { useUIStore } from '../stores/ui'
import WorkspaceSettingsPanel from './WorkspaceSettingsPanel'

export default function Sidebar() {
  const { workspaces, activeWorkspace, setActive: setActiveWorkspace } = useWorkspaceStore()
  const { conversations, activeConversation, setActive: setActiveConv, createConversation } = useConversationStore()
  const { user, logout } = useAuthStore()
  const { setSidebarOpen } = useUIStore()
  const [wsSettingsOpen, setWsSettingsOpen] = useState(false)

  const handleNewConversation = async () => {
    if (activeWorkspace) {
      await createConversation(activeWorkspace.id)
      setSidebarOpen(false) // Close on mobile
    }
  }

  const handleSelectConversation = (conv: Conversation) => {
    setActiveConv(conv)
    setSidebarOpen(false) // Close on mobile
  }

  return (
    <>
    <div className="h-full flex flex-col bg-background border-r border-border pb-14 sm:pb-0">
      {/* Workspace switcher */}
      <div className="p-3 border-b border-border">
        <div className="flex gap-2">
          <select
            value={activeWorkspace?.id || ''}
            onChange={(e) => {
              const ws = workspaces.find(w => w.id === parseInt(e.target.value))
              if (ws) setActiveWorkspace(ws)
            }}
            className="flex-1 bg-surface text-text border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary transition-colors"
          >
            {workspaces.map(ws => (
              <option key={ws.id} value={ws.id}>
                {ws.icon || '💬'} {ws.name}
              </option>
            ))}
          </select>
          {activeWorkspace && (
            <button
              onClick={() => setWsSettingsOpen(true)}
              className="px-2 rounded-lg border border-border text-text-muted hover:text-text hover:bg-background text-sm"
              title="Workspace system prompt"
              aria-label="Workspace settings"
            >
              ⚙️
            </button>
          )}
        </div>
      </div>

      {/* New conversation button */}
      <div className="p-3">
        <button
          onClick={handleNewConversation}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-primary hover:brightness-110 text-on-primary text-sm font-medium transition-colors"
        >
          <span>+</span>
          <span>New conversation</span>
        </button>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto px-2">
        {conversations.map(conv => (
          <ConversationItem
            key={conv.id}
            conv={conv}
            isActive={activeConversation?.id === conv.id}
            onSelect={() => handleSelectConversation(conv)}
          />
        ))}
        {conversations.length === 0 && (
          <p className="text-center text-gray-500 text-sm py-8">
            No conversations yet
          </p>
        )}
      </div>

      {/* User menu */}
      <div className="p-3 border-t border-border">
        {/* Navigation links */}
        <div className="flex gap-1 mb-2">
          <Link to="/dashboard" className="flex-1 text-center text-xs text-text-muted hover:text-text py-1.5 rounded hover:bg-background/50" title="Dashboard" onClick={() => setSidebarOpen(false)}>📊</Link>
          <Link to="/chat" className="flex-1 text-center text-xs text-text-muted hover:text-text py-1.5 rounded hover:bg-background/50" title="Chat" onClick={() => setSidebarOpen(false)}>💬</Link>
          <a href="http://100.106.180.101:5002" target="_blank" rel="noopener noreferrer" className="flex-1 text-center text-xs text-text-muted hover:text-text py-1.5 rounded hover:bg-background/50" title="DB Admin">🗄️</a>
          <a href="http://100.106.180.101:5678" target="_blank" rel="noopener noreferrer" className="flex-1 text-center text-xs text-text-muted hover:text-text py-1.5 rounded hover:bg-background/50" title="n8n">⚡</a>
        </div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-sm font-medium text-on-primary shrink-0">
              {user?.display_name?.[0]?.toUpperCase() || '?'}
            </div>
            <span className="text-sm text-text truncate">{user?.display_name}</span>
          </div>
          <button
            onClick={logout}
            className="text-xs text-gray-500 hover:text-gray-300 shrink-0"
          >
            Logout
          </button>
        </div>
        <div className="flex gap-2">
          <a
            href="/settings"
            className="flex-1 text-center text-xs text-text-muted hover:text-text py-1.5 rounded hover:bg-background/50"
          >
            ⚙ Settings
          </a>
          <button
            onClick={() => window.location.reload()}
            className="flex-1 text-center text-xs text-text-muted hover:text-text py-1.5 rounded hover:bg-background/50"
            title="Reload to pick up updates"
          >
            🔄 Refresh
          </button>
          {user?.role === 'admin' && (
            <a
              href="/admin"
              className="flex-1 text-center text-xs text-primary hover:brightness-125 py-1.5 rounded hover:bg-gray-800/50"
            >
              🔧 Admin
            </a>
          )}
        </div>
      </div>
    </div>

    {/* Workspace settings panel — portaled to document.body to escape
        the sidebar's CSS transform containing block */}
    {wsSettingsOpen && activeWorkspace && createPortal(
      <WorkspaceSettingsPanel
        workspaceId={activeWorkspace.id}
        mode={user?.role === 'admin' ? 'edit' : 'view'}
        onClose={() => setWsSettingsOpen(false)}
      />,
      document.body,
    )}
    </>
  )
}


interface ConversationItemProps {
  conv: Conversation
  isActive: boolean
  onSelect: () => void
}

function ConversationItem({ conv, isActive, onSelect }: ConversationItemProps) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(conv.title || '')
  const [showMenu, setShowMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const { updateTitle, archiveConversation } = useConversationStore()

  // Close menu on outside click / touch / Escape
  useEffect(() => {
    if (!showMenu) return
    const handleClickAway = (e: MouseEvent | TouchEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false)
      }
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowMenu(false)
    }
    document.addEventListener('mousedown', handleClickAway)
    document.addEventListener('touchstart', handleClickAway)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClickAway)
      document.removeEventListener('touchstart', handleClickAway)
      document.removeEventListener('keydown', handleKey)
    }
  }, [showMenu])

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    if (diff < 60000) return 'now'
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m`
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d`
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  const handleRename = async () => {
    if (title.trim() && title !== conv.title) {
      await updateTitle(conv.id, title.trim())
    }
    setEditing(false)
  }

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (confirm(`Delete conversation "${conv.title || 'New conversation'}"?`)) {
      await archiveConversation(conv.id)
    }
    setShowMenu(false)
  }

  return (
    <div
      className={`
        group relative w-full text-left px-3 py-2.5 rounded-lg mb-0.5 text-sm transition-colors cursor-pointer
        ${isActive
          ? 'bg-primary/20 text-accent'
          : 'text-text-muted hover:bg-background/50 hover:text-text'}
      `}
      onClick={editing ? undefined : onSelect}
    >
      <div className="flex justify-between items-start gap-2">
        <div className="flex-1 min-w-0">
          {editing ? (
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={handleRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRename()
                if (e.key === 'Escape') { setEditing(false); setTitle(conv.title || '') }
              }}
              onClick={(e) => e.stopPropagation()}
              className="w-full bg-gray-900 border border-primary rounded px-1.5 py-0.5 text-sm text-gray-200 focus:outline-none"
            />
          ) : (
            <span className="truncate block font-medium">
              {conv.title || 'New conversation'}
            </span>
          )}
          {conv.parent_id && !editing && (
            <span className="text-xs text-gray-500">↳ branch</span>
          )}
        </div>

        {!editing && (
          <>
            {/* Time: always visible on mobile, hidden on desktop hover */}
            <span className="text-xs text-gray-500 shrink-0 sm:group-hover:hidden">
              {formatTime(conv.updated_at)}
            </span>
            {/* Action button: always visible on mobile, hover-only on desktop */}
            <div className="flex sm:hidden sm:group-hover:flex items-center gap-1 shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); setShowMenu(!showMenu) }}
                className="p-1 rounded hover:bg-gray-700 text-gray-400"
                aria-label="Conversation actions"
                title="More"
              >
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <circle cx="5" cy="12" r="2" />
                  <circle cx="12" cy="12" r="2" />
                  <circle cx="19" cy="12" r="2" />
                </svg>
              </button>
            </div>
          </>
        )}
      </div>

      {showMenu && (
        <div
          ref={menuRef}
          className="absolute top-full right-2 mt-1 bg-surface border border-gray-700 rounded-lg shadow-xl z-30 overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={(e) => { e.stopPropagation(); setEditing(true); setShowMenu(false) }}
            className="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 whitespace-nowrap"
          >
            ✏️ Rename
          </button>
          <button
            onClick={handleDelete}
            className="block w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-gray-800 whitespace-nowrap"
          >
            🗑️ Delete
          </button>
        </div>
      )}
    </div>
  )
}
