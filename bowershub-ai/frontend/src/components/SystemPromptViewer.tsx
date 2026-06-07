/**
 * SystemPromptViewer — read-only markdown rendering of a workspace's
 * system prompt.
 *
 * Implements task 22.2:
 *   - Read-only render of `bh_workspaces.system_prompt` using the same
 *     `react-markdown` + `rehype-highlight` setup the chat already uses
 *     (see MessageList.tsx for the chat-side renderer; the same
 *     `markdown-content` class applies the styles defined in index.css).
 *   - Empty-prompt placeholder: "No system prompt set for this workspace"
 *     (R5.4).
 *   - Character count + approximate token count (`ceil(chars / 4)`) shown
 *     below the rendered output (R5.5).
 *
 * Props: `workspaceId`, `prompt`.
 *
 * The parent (WorkspaceSettingsPanel) already handles loading the prompt
 * from the API and access-control errors, so this component is a pure
 * presentational view over the prompt text.
 *
 * _Requirements: R5.1, R5.2, R5.3, R5.4, R5.5
 */
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'

export interface SystemPromptViewerProps {
  workspaceId: number
  prompt: string
}

/**
 * Approximate token count using the 4-characters-per-token heuristic
 * documented in R5.5. Always round up so a non-empty prompt reports at
 * least one token.
 */
function approxTokenCount(text: string): number {
  if (!text) return 0
  return Math.ceil(text.length / 4)
}

export default function SystemPromptViewer({
  workspaceId,
  prompt,
}: SystemPromptViewerProps) {
  const trimmed = prompt ?? ''
  const isEmpty = trimmed.length === 0

  // workspaceId is part of the props contract for parity with the editor
  // and pinned-context manager. We don't fetch in this component (the
  // parent owns loading), but we surface it via a stable data attribute
  // so future tests can target the right viewer instance when multiple
  // workspaces are visited in the same session.
  return (
    <div
      className="space-y-3"
      data-component="system-prompt-viewer"
      data-workspace-id={workspaceId}
    >
      {isEmpty ? (
        <div
          className="rounded-lg border border-gray-800 bg-gray-900/40 p-4"
          role="status"
        >
          <p className="text-sm text-gray-500 italic">
            No system prompt set for this workspace
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
          <div className="markdown-content text-gray-200 text-sm">
            <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
              {trimmed}
            </ReactMarkdown>
          </div>
        </div>
      )}

      <div className="text-xs text-gray-500" aria-live="polite">
        {trimmed.length.toLocaleString()} characters
        <span className="text-gray-600"> · </span>
        ~{approxTokenCount(trimmed).toLocaleString()} tokens
      </div>
    </div>
  )
}
