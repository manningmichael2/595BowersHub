/**
 * ToolFramePage — embeds external tools (Dashboard, DB Admin, n8n) as
 * full-height iframes inside the BowersHub AI PWA shell.
 *
 * Goal: "one PWA, all the tools" — user doesn't have to leave the app
 * or manage separate bookmarks for each service.
 */
import { useNavigate, useParams } from 'react-router-dom'

interface ToolConfig {
  label: string
  icon: string
  url: string
}

const TOOLS: Record<string, ToolConfig> = {
  dashboard: {
    label: 'Dashboard',
    icon: '📊',
    url: 'http://100.106.180.101:8080',
  },
  'db-admin': {
    label: 'DB Admin',
    icon: '🗄️',
    url: 'http://100.106.180.101:5002',
  },
  n8n: {
    label: 'n8n Workflows',
    icon: '⚡',
    url: 'http://100.106.180.101:5678',
  },
}

export default function ToolFramePage() {
  const navigate = useNavigate()
  const { toolId } = useParams<{ toolId: string }>()

  const tool = toolId ? TOOLS[toolId] : null

  if (!tool) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-surface text-gray-200">
        <div className="text-center">
          <p className="text-lg">Unknown tool: {toolId}</p>
          <button
            onClick={() => navigate(-1)}
            className="mt-4 px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500"
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
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-800 shrink-0 bg-background">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400 text-sm"
          aria-label="Back to chat"
        >
          ← Back
        </button>
        <span className="text-sm text-gray-200">
          {tool.icon} {tool.label}
        </span>
        <a
          href={tool.url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-xs text-gray-500 hover:text-gray-300"
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
