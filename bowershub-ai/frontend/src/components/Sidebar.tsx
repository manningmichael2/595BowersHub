import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import {
  Settings, Wrench, Plus, MoreHorizontal, Pencil, Trash2,
} from 'lucide-react'
import { useWorkspaceStore } from '../stores/workspace'
import { useConversationStore, Conversation } from '../stores/conversation'
import { useAuthStore } from '../stores/auth'
import { useUIStore } from '../stores/ui'
import { confirm } from '../stores/confirm'
// Lazy: the panel is a modal shown only on demand, and it pulls in heavy
// markdown/editor deps (SystemPromptViewer/Editor, PinnedContextManager). A
// lazy boundary keeps that whole subtree out of the main bundle until first open.
const WorkspaceSettingsPanel = lazy(() => import('./WorkspaceSettingsPanel'))

export default function Sidebar() {
  const { workspaces, activeWorkspace, error: wsError, fetchWorkspaces, setActive: setActiveWorkspace } = useWorkspaceStore()
  const { conversations, activeConversation, error: convError, setActive: setActiveConv, createConversation } = useConversationStore()
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
              className="px-2 flex items-center justify-center rounded-lg border border-border text-text-muted hover:text-text hover:bg-surface transition-colors"
              title="Workspace system prompt"
              aria-label="Workspace settings"
            >
              <Settings size={16} aria-hidden />
            </button>
          )}
        </div>
        {/* Distinguish a real load failure from an empty account: only show
            this when the fetch errored, with a way to recover. */}
        {wsError && workspaces.length === 0 && (
          <div className="mt-2 flex items-center justify-between gap-2 text-xs text-danger">
            <span>{wsError}</span>
            <button
              onClick={() => fetchWorkspaces()}
              className="px-2 py-0.5 rounded border border-border text-text-muted hover:text-text"
            >
              Retry
            </button>
          </div>
        )}
      </div>

      {/* New conversation button */}
      <div className="p-3">
        <button
          onClick={handleNewConversation}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-primary hover:brightness-110 text-on-primary text-sm font-medium transition-[filter]"
        >
          <Plus size={16} aria-hidden />
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
          convError ? (
            <p className="text-center text-danger text-sm py-8">
              {convError}
            </p>
          ) : (
            <p className="text-center text-text-muted text-sm py-8">
              No conversations yet
            </p>
          )
        )}
      </div>

      {/* User menu. Primary app navigation lives in the shell chrome now
          (desktop NavRail / mobile NavDrawer + BottomTabBar), so the old
          per-surface nav-link row that used to sit here was removed. */}
      <div className="p-3 border-t border-border">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-sm font-medium text-on-primary shrink-0">
              {user?.display_name?.[0]?.toUpperCase() || '?'}
            </div>
            <span className="text-sm text-text truncate">{user?.display_name}</span>
          </div>
          <button
            onClick={logout}
            className="text-xs text-text-muted hover:text-text shrink-0 transition-colors"
          >
            Logout
          </button>
        </div>
        <div className="flex gap-2">
          <Link
            to="/settings"
            className="flex-1 flex items-center justify-center gap-1.5 text-xs text-text-muted hover:text-text py-2 rounded hover:bg-background/50 transition-colors"
            onClick={() => setSidebarOpen(false)}
          >
            <Settings size={14} aria-hidden /> Settings
          </Link>
          {user?.role === 'admin' && (
            <Link
              to="/admin"
              className="flex-1 flex items-center justify-center gap-1.5 text-xs text-primary hover:brightness-125 py-2 rounded hover:bg-background/50 transition-colors"
              onClick={() => setSidebarOpen(false)}
            >
              <Wrench size={14} aria-hidden /> Admin
            </Link>
          )}
        </div>
      </div>
    </div>

    {/* Workspace settings panel — portaled to document.body to escape
        the sidebar's CSS transform containing block */}
    {wsSettingsOpen && activeWorkspace && createPortal(
      <Suspense fallback={null}>
        <WorkspaceSettingsPanel
          workspaceId={activeWorkspace.id}
          mode={user?.role === 'admin' ? 'edit' : 'view'}
          onClose={() => setWsSettingsOpen(false)}
        />
      </Suspense>,
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
    setShowMenu(false)
    const ok = await confirm({
      title: 'Delete conversation',
      message: `Delete "${conv.title || 'New conversation'}"? This can't be undone.`,
      confirmLabel: 'Delete',
      danger: true,
    })
    if (ok) await archiveConversation(conv.id)
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
              className="w-full bg-background border border-primary rounded px-1.5 py-0.5 text-sm text-text focus:outline-none"
            />
          ) : (
            <span className="truncate block font-medium">
              {conv.title || 'New conversation'}
            </span>
          )}
          {conv.parent_id && !editing && (
            <span className="text-xs text-text-muted">↳ branch</span>
          )}
        </div>

        {!editing && (
          <>
            {/* Time: always visible on mobile, hidden on desktop hover */}
            <span className="text-xs text-text-muted shrink-0 sm:group-hover:hidden">
              {formatTime(conv.updated_at)}
            </span>
            {/* Action button: always visible on mobile, hover-only on desktop */}
            <div className="flex sm:hidden sm:group-hover:flex items-center gap-1 shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); setShowMenu(!showMenu) }}
                className="p-1 rounded hover:bg-surface text-text-muted hover:text-text transition-colors"
                aria-label="Conversation actions"
                title="More"
              >
                <MoreHorizontal size={16} aria-hidden />
              </button>
            </div>
          </>
        )}
      </div>

      {showMenu && (
        <div
          ref={menuRef}
          className="absolute top-full right-2 mt-1 bg-surface border border-border rounded-lg shadow-xl z-30 overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={(e) => { e.stopPropagation(); setEditing(true); setShowMenu(false) }}
            className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-text hover:bg-background whitespace-nowrap transition-colors"
          >
            <Pencil size={14} aria-hidden /> Rename
          </button>
          <button
            onClick={handleDelete}
            className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-danger hover:bg-background whitespace-nowrap transition-colors"
          >
            <Trash2 size={14} aria-hidden /> Delete
          </button>
        </div>
      )}
    </div>
  )
}
