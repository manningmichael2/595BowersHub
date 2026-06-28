/**
 * WorkspaceSettingsPanel — right-side modal panel for managing a workspace's
 * system prompt and pinned context.
 *
 * Implements task 22.1:
 *   - Right-side modal/panel triggered from the workspace settings cog.
 *   - Tabs: "System Prompt", "Pinned Context".
 *   - Mounts <SystemPromptViewer> / <SystemPromptEditor> and
 *     <PinnedContextManager> based on the active tab and the caller's `mode`
 *     prop / admin role.
 *   - Props: workspaceId, mode: 'view' | 'edit'.
 *
 * Mobile: full-screen sheet. Desktop: right-side panel anchored to the
 * viewport edge with a translucent backdrop, matching the pattern used by
 * SearchOverlay.
 *
 * _Requirements: R5.1, R5.2, R6.1
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../services/api'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'
import SystemPromptViewer from './SystemPromptViewer'
import SystemPromptEditor from './SystemPromptEditor'
import PinnedContextManager from './PinnedContextManager'

// ---- Component ------------------------------------------------------------

export interface WorkspaceSettingsPanelProps {
  workspaceId: number
  mode: 'view' | 'edit'
  /** Called when the user dismisses the panel (Escape, backdrop click, ✕). */
  onClose: () => void
}

type TabKey = 'system_prompt' | 'pinned_context'

export default function WorkspaceSettingsPanel({
  workspaceId,
  mode,
  onClose,
}: WorkspaceSettingsPanelProps) {
  const user = useAuthStore(s => s.user)
  const workspaces = useWorkspaceStore(s => s.workspaces)

  const isAdmin = user?.role === 'admin'
  const canEdit = isAdmin && mode === 'edit'

  const [activeTab, setActiveTab] = useState<TabKey>('system_prompt')
  const [prompt, setPrompt] = useState<string>('')
  const [loadingPrompt, setLoadingPrompt] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // ---- Resolve workspace name for the header ----------------------------

  const workspaceName = useMemo(() => {
    const ws = workspaces.find(w => w.id === workspaceId)
    return ws?.name || `Workspace #${workspaceId}`
  }, [workspaces, workspaceId])

  // ---- Load workspace prompt -------------------------------------------

  useEffect(() => {
    let cancelled = false
    setLoadingPrompt(true)
    setError(null)
    api
      .get(`/api/workspaces/${workspaceId}`)
      .then(res => {
        if (cancelled) return
        setPrompt(res.data?.system_prompt || '')
        setLoadingPrompt(false)
      })
      .catch(err => {
        if (cancelled) return
        const status = err?.response?.status
        if (status === 403) {
          setError('You do not have access to this workspace.')
        } else {
          setError(
            err?.response?.data?.detail ||
              'Failed to load workspace settings. Try again.',
          )
        }
        setLoadingPrompt(false)
      })
    return () => {
      cancelled = true
    }
  }, [workspaceId])

  // ---- Escape closes the panel -----------------------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // ---- Render ----------------------------------------------------------

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Right-side panel (full-screen on mobile, centered overlay on desktop) */}
      <div
        className="
          relative mx-auto w-full sm:max-w-4xl bg-surface
          border border-border shadow-2xl rounded-lg sm:rounded-xl
          flex flex-col h-full sm:h-[90vh] sm:my-auto
        "
        role="dialog"
        aria-modal="true"
        aria-label="Workspace settings"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-text-muted shrink-0">⚙</span>
            <h2 className="text-sm font-medium text-text truncate">
              Workspace settings
              <span className="text-text-muted"> · </span>
              <span className="text-text-muted">{workspaceName}</span>
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-surface text-text-muted shrink-0"
            aria-label="Close"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div
          className="flex gap-1 px-4 py-2 border-b border-border shrink-0"
          role="tablist"
          aria-label="Workspace settings tabs"
        >
          <TabButton
            active={activeTab === 'system_prompt'}
            onClick={() => setActiveTab('system_prompt')}
            label="System Prompt"
          />
          <TabButton
            active={activeTab === 'pinned_context'}
            onClick={() => setActiveTab('pinned_context')}
            label="Pinned Context"
          />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-4 min-h-0">
          {error && (
            <div className="mb-4 rounded-lg border border-danger/40 bg-danger/20 px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}

          {activeTab === 'system_prompt' && (
            <SystemPromptTab
              workspaceId={workspaceId}
              prompt={prompt}
              loading={loadingPrompt}
              canEdit={canEdit}
              onSaved={setPrompt}
            />
          )}

          {activeTab === 'pinned_context' && (
            <PinnedContextManager workspaceId={workspaceId} canEdit={canEdit} />
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-border text-xs text-text-muted shrink-0">
          {canEdit ? (
            <>Editing as <span className="text-text-muted">admin</span></>
          ) : (
            <>Read-only view{!isAdmin && ' (admin role required to edit)'}</>
          )}
        </div>
      </div>
    </div>
  )
}

// ---- Tabs ----------------------------------------------------------------

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={
        'px-3 py-1.5 rounded text-sm font-medium transition-colors ' +
        (active
          ? 'bg-primary/20 text-primary'
          : 'text-text-muted hover:text-text-muted')
      }
    >
      {label}
    </button>
  )
}

function SystemPromptTab({
  workspaceId,
  prompt,
  loading,
  canEdit,
  onSaved,
}: {
  workspaceId: number
  prompt: string
  loading: boolean
  canEdit: boolean
  onSaved: (newPrompt: string) => void
}) {
  if (loading) {
    return <div className="text-sm text-text-muted">Loading system prompt…</div>
  }

  // Editor when the caller is in edit mode AND has admin role (canEdit encodes
  // both); otherwise the read-only viewer.
  if (canEdit) {
    return (
      <SystemPromptEditor
        workspaceId={workspaceId}
        initialPrompt={prompt}
        canEdit={canEdit}
        onSaved={onSaved}
      />
    )
  }

  return <SystemPromptViewer workspaceId={workspaceId} prompt={prompt} />
}
