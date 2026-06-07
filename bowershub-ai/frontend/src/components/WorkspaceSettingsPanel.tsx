/**
 * WorkspaceSettingsPanel — right-side modal panel for managing a workspace's
 * system prompt and pinned context.
 *
 * Implements task 22.1:
 *   - Right-side modal/panel triggered from the workspace settings cog.
 *   - Tabs: "System Prompt", "Pinned Context".
 *   - Mounts <SystemPromptViewer> / <SystemPromptEditor> (task 22.2 / 22.3)
 *     and <PinnedContextManager> (task 23.1) based on the active tab and
 *     the caller's `mode` prop / admin role.
 *   - Props: workspaceId, mode: 'view' | 'edit'.
 *
 * Until 22.2/22.3/23.1 ship, the child components are mounted only if
 * already present on disk; otherwise this panel renders inline placeholder
 * content with TODO markers so the orchestrator can wire them up cleanly.
 *
 * Mobile: full-screen sheet. Desktop: right-side panel anchored to the
 * viewport edge with a translucent backdrop, matching the pattern used by
 * SearchOverlay.
 *
 * _Requirements: R5.1, R5.2, R6.1
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../services/api'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'

// ---- Optional child component imports -------------------------------------
//
// These siblings ship in tasks 22.2, 22.3, and 23.1. We attempt to load them
// lazily so this panel works whether or not they exist yet. Vite resolves
// imports at build time, so we use dynamic `import()` and gate rendering on
// whether the module loaded successfully.

type SystemPromptViewerProps = { workspaceId: number; prompt: string }
type SystemPromptEditorProps = {
  workspaceId: number
  initialPrompt: string
  canEdit: boolean
}
type PinnedContextManagerProps = { workspaceId: number; canEdit: boolean }

type LoadedComponent<P> = {
  status: 'loading' | 'ready' | 'missing'
  Component: React.ComponentType<P> | null
}

function useOptionalChild<P>(
  loader: () => Promise<{ default: React.ComponentType<P> }>,
): LoadedComponent<P> {
  const [state, setState] = useState<LoadedComponent<P>>({
    status: 'loading',
    Component: null,
  })
  // Stash the loader in a ref so we don't re-invoke it on every render.
  const loaderRef = useRef(loader)
  useEffect(() => {
    let cancelled = false
    loaderRef
      .current()
      .then(mod => {
        if (cancelled) return
        setState({ status: 'ready', Component: mod.default })
      })
      .catch(() => {
        if (cancelled) return
        setState({ status: 'missing', Component: null })
      })
    return () => {
      cancelled = true
    }
  }, [])
  return state
}

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

  // ---- Optional child components ---------------------------------------
  //
  // The Vite/TypeScript dynamic import will fail at runtime if the module
  // doesn't exist yet. We catch that and fall back to a placeholder.
  //
  // @vite-ignore prevents Vite from trying to statically resolve a path
  // that may not exist on disk yet.
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore — children may not exist until tasks 22.2/22.3/23.1 ship.
  const viewer = useOptionalChild<SystemPromptViewerProps>(
    () => import(/* @vite-ignore */ './SystemPromptViewer'),
  )
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore — children may not exist until tasks 22.2/22.3/23.1 ship.
  const editor = useOptionalChild<SystemPromptEditorProps>(
    () => import(/* @vite-ignore */ './SystemPromptEditor'),
  )
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore — children may not exist until tasks 22.2/22.3/23.1 ship.
  const pinnedManager = useOptionalChild<PinnedContextManagerProps>(
    () => import(/* @vite-ignore */ './PinnedContextManager'),
  )

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
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Right-side panel (full-screen on mobile) */}
      <div
        className="
          relative ml-auto w-full sm:max-w-2xl bg-[#1a1a2e]
          border-l border-gray-700 shadow-2xl
          flex flex-col h-full
        "
        role="dialog"
        aria-modal="true"
        aria-label="Workspace settings"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-gray-400 shrink-0">⚙</span>
            <h2 className="text-sm font-medium text-gray-100 truncate">
              Workspace settings
              <span className="text-gray-500"> · </span>
              <span className="text-gray-300">{workspaceName}</span>
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400 shrink-0"
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
          className="flex gap-1 px-4 py-2 border-b border-gray-800 shrink-0"
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
            <div className="mb-4 rounded-lg border border-red-700/40 bg-red-900/20 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          {activeTab === 'system_prompt' && (
            <SystemPromptTab
              workspaceId={workspaceId}
              prompt={prompt}
              loading={loadingPrompt}
              canEdit={canEdit}
              viewer={viewer}
              editor={editor}
            />
          )}

          {activeTab === 'pinned_context' && (
            <PinnedContextTab
              workspaceId={workspaceId}
              canEdit={canEdit}
              loaded={pinnedManager}
            />
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-gray-800 text-xs text-gray-500 shrink-0">
          {canEdit ? (
            <>Editing as <span className="text-gray-400">admin</span></>
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
          ? 'bg-indigo-600/20 text-indigo-300'
          : 'text-gray-500 hover:text-gray-300')
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
  viewer,
  editor,
}: {
  workspaceId: number
  prompt: string
  loading: boolean
  canEdit: boolean
  viewer: LoadedComponent<SystemPromptViewerProps>
  editor: LoadedComponent<SystemPromptEditorProps>
}) {
  if (loading) {
    return <div className="text-sm text-gray-500">Loading system prompt…</div>
  }

  // Editor path: only when caller is in edit mode AND we have admin role
  // (canEdit prop already encodes that). Falls back to viewer if the editor
  // module isn't available yet.
  if (canEdit && editor.status === 'ready' && editor.Component) {
    const Editor = editor.Component
    return (
      <Editor
        workspaceId={workspaceId}
        initialPrompt={prompt}
        canEdit={canEdit}
      />
    )
  }

  if (viewer.status === 'ready' && viewer.Component) {
    const Viewer = viewer.Component
    return <Viewer workspaceId={workspaceId} prompt={prompt} />
  }

  // ---- Placeholder until tasks 22.2 / 22.3 ship --------------------------
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
        <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">
          {prompt ? 'System prompt (raw)' : 'No system prompt'}
        </div>
        {prompt ? (
          <pre className="whitespace-pre-wrap break-words text-sm text-gray-200 font-mono">
            {prompt}
          </pre>
        ) : (
          <p className="text-sm text-gray-500 italic">
            No system prompt set for this workspace
          </p>
        )}
        <div className="mt-3 text-xs text-gray-500">
          {prompt.length.toLocaleString()} characters · ~
          {Math.ceil(prompt.length / 4).toLocaleString()} tokens
        </div>
      </div>

      <p className="text-xs text-gray-500">
        {/* TODO(task 22.2): replace placeholder with <SystemPromptViewer>. */}
        {/* TODO(task 22.3): replace placeholder with <SystemPromptEditor> when canEdit. */}
        Rich markdown rendering and editor ship with tasks 22.2 and 22.3.
      </p>
    </div>
  )
}

function PinnedContextTab({
  workspaceId,
  canEdit,
  loaded,
}: {
  workspaceId: number
  canEdit: boolean
  loaded: LoadedComponent<PinnedContextManagerProps>
}) {
  if (loaded.status === 'ready' && loaded.Component) {
    const Manager = loaded.Component
    return <Manager workspaceId={workspaceId} canEdit={canEdit} />
  }

  // ---- Placeholder until task 23.1 ships --------------------------------
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
        <div className="text-sm text-gray-300 font-medium mb-1">
          Pinned context
        </div>
        <p className="text-sm text-gray-500">
          Static and dynamic entries that get prepended to every request in
          this workspace.
        </p>
      </div>
      <p className="text-xs text-gray-500">
        {/* TODO(task 23.1): replace placeholder with <PinnedContextManager>. */}
        The full list, add/edit form, and refresh-now control ship with task
        23.1.
      </p>
    </div>
  )
}
