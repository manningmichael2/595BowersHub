/**
 * ToolFramePage — embeds external tools (Dashboard, n8n) as full-height
 * iframes inside the BowersHub AI PWA shell.
 *
 * Goal: "one PWA, all the tools" — user doesn't have to leave the app
 * or manage separate bookmarks for each service.
 *
 * The tools host is NOT hardcoded (C7): it comes from VITE_TOOLS_HOST, falling
 * back to the hostname the app was loaded from (the tools run on the same box).
 * (DB Admin was retired — its features live in the authenticated app now.)
 */
import { useNavigate, useParams } from 'react-router-dom'

interface ToolConfig {
  label: string
  icon: string
  url: string
}

const TOOLS_HOST = import.meta.env.VITE_TOOLS_HOST || window.location.hostname

const TOOLS: Record<string, ToolConfig> = {
  dashboard: {
    label: 'Dashboard',
    icon: '📊',
    url: `http://${TOOLS_HOST}:8080`,
  },
  n8n: {
    label: 'n8n Workflows',
    icon: '⚡',
    url: `http://${TOOLS_HOST}:5678`,
  },
}

export default function ToolFramePage() {
  const navigate = useNavigate()
  const { toolId } = useParams<{ toolId: string }>()

  const tool = toolId ? TOOLS[toolId] : null

  if (!tool) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-surface text-text">
        <div className="text-center">
          <p className="text-lg">Unknown tool: {toolId}</p>
          <button
            onClick={() => navigate(-1)}
            className="mt-4 px-4 py-2 rounded-lg bg-primary text-on-primary hover:bg-primary/90"
          >
            Go back
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 flex flex-col bg-surface">
      {/* Minimal header bar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border shrink-0 bg-background">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-surface text-text-muted text-sm"
          aria-label="Back to chat"
        >
          ← Back
        </button>
        <span className="text-sm text-text">
          {tool.icon} {tool.label}
        </span>
        <a
          href={tool.url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-xs text-text-muted hover:text-text-muted"
          title="Open in new tab"
        >
          ↗ Open in tab
        </a>
      </div>

      {/* Iframe — fills remaining space */}
      <iframe
        src={tool.url}
        className="flex-1 w-full border-none"
        title={tool.label}
        allow="clipboard-write"
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
      />
    </div>
  )
}

// Export the tools config so Sidebar can use it
export { TOOLS }
export type { ToolConfig }
