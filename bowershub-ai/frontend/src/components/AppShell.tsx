import { useEffect } from 'react'
import { useWorkspaceStore } from '../stores/workspace'
import { useConversationStore } from '../stores/conversation'
import { useUIStore } from '../stores/ui'
import { wsClient } from '../services/websocket'
import Sidebar from './Sidebar'
import ChatArea from './ChatArea'
import SearchOverlay from './SearchOverlay'

export default function AppShell() {
  const { fetchWorkspaces, activeWorkspace } = useWorkspaceStore()
  const { fetchConversations } = useConversationStore()
  const { sidebarOpen, searchOpen, setSearchOpen } = useUIStore()

  // Initialize on mount
  useEffect(() => {
    fetchWorkspaces()
    wsClient.connect()
    return () => wsClient.disconnect()
  }, [])

  // Fetch conversations when workspace changes
  useEffect(() => {
    if (activeWorkspace) {
      fetchConversations(activeWorkspace.id)
    }
  }, [activeWorkspace?.id])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen(!searchOpen)
      }
      if (e.key === 'Escape') {
        setSearchOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [searchOpen])

  return (
    <div
      className="bh-app-shell flex overflow-hidden bg-surface"
      style={{
        position: 'fixed',
        top: 0, left: 0, right: 0, bottom: 0,
      }}
    >
      {/* Sidebar — desktop: always visible; mobile: overlay */}
      <div className={`
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        fixed md:relative md:translate-x-0
        z-30 h-full w-72 transition-transform duration-200
      `}>
        <Sidebar />
      </div>

      {/* Sidebar backdrop on mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/50 md:hidden"
          onClick={() => useUIStore.getState().setSidebarOpen(false)}
        />
      )}

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatArea />
      </div>

      {/* Search overlay */}
      {searchOpen && <SearchOverlay />}
    </div>
  )
}
