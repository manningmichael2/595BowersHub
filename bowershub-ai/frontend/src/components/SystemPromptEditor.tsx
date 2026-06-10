/**
 * SystemPromptEditor — markdown editor for `bh_workspaces.system_prompt`
 * with a live preview pane.
 *
 * Implements task 22.3:
 *   - Side-by-side layout (raw markdown <textarea> on the left, rendered
 *     preview on the right). Stacks to a single column on small screens.
 *   - Editor uses a monospace font, soft wrap, gutter line numbers, and
 *     handles Tab / Shift+Tab indentation locally (R6.2).
 *   - Live preview is debounced 300ms — no server call (R6.3).
 *   - Save → `PATCH /api/workspaces/{workspaceId}` with `{system_prompt}`
 *     and shows a transient success toast (R6.4).
 *   - Cancel with unsaved changes → `window.confirm()` before discarding
 *     (R6.5).
 *   - Client-side 50,000-character limit matches the backend (R6.6); the
 *     same length-limit error returned by the backend is rendered inline.
 *
 * Props: `workspaceId`, `initialPrompt`, `canEdit`. The parent
 * `<WorkspaceSettingsPanel>` resolves admin/RBAC and passes `canEdit`;
 * when false the editor is rendered as a read-only textarea so the
 * component is still useful (e.g. for "view raw" mode) — but Save is
 * disabled.
 *
 * _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import { api } from '../services/api'

export interface SystemPromptEditorProps {
  workspaceId: number
  initialPrompt: string
  canEdit: boolean
  /** Optional — fired with the new prompt after a successful save so the
   *  parent panel can update its cached copy. */
  onSaved?: (newPrompt: string) => void
}

const MAX_LEN = 50_000

export default function SystemPromptEditor({
  workspaceId,
  initialPrompt,
  canEdit,
  onSaved,
}: SystemPromptEditorProps) {
  // The text currently in the textarea.
  const [text, setText] = useState<string>(initialPrompt ?? '')
  // The last successfully-saved (or initially-loaded) value. Used to
  // compute `isDirty` and to support Cancel-with-confirm.
  const [savedText, setSavedText] = useState<string>(initialPrompt ?? '')
  // Debounced version of `text` that drives the preview pane.
  const [previewText, setPreviewText] = useState<string>(initialPrompt ?? '')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const lineNumbersRef = useRef<HTMLDivElement | null>(null)

  // ---- Sync if the parent reloads the prompt -----------------------------

  useEffect(() => {
    setText(initialPrompt ?? '')
    setSavedText(initialPrompt ?? '')
    setPreviewText(initialPrompt ?? '')
    setError(null)
  }, [initialPrompt, workspaceId])

  // ---- Debounced preview (R6.3) ------------------------------------------

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setPreviewText(text)
    }, 300)
    return () => window.clearTimeout(handle)
  }, [text])

  // ---- Transient toast auto-dismiss --------------------------------------

  useEffect(() => {
    if (!toast) return
    const handle = window.setTimeout(() => setToast(null), 3000)
    return () => window.clearTimeout(handle)
  }, [toast])

  // ---- Derived state -----------------------------------------------------

  const isDirty = text !== savedText
  const length = text.length
  const overLimit = length > MAX_LEN
  const tokenEstimate = Math.ceil(length / 4)

  const lineCount = useMemo(() => {
    // Count visual lines for the gutter — at least 1.
    if (!text) return 1
    let lines = 1
    for (let i = 0; i < text.length; i++) {
      if (text.charCodeAt(i) === 10) lines++
    }
    return lines
  }, [text])

  const lineNumbers = useMemo(() => {
    const out: number[] = []
    for (let i = 1; i <= lineCount; i++) out.push(i)
    return out
  }, [lineCount])

  // ---- Handlers ----------------------------------------------------------

  const handleScroll = (e: React.UIEvent<HTMLTextAreaElement>) => {
    if (lineNumbersRef.current) {
      lineNumbersRef.current.scrollTop = e.currentTarget.scrollTop
    }
  }

  /**
   * Tab / Shift+Tab handling (R6.2).
   *
   * Tab inserts two spaces at the caret (or, when text is selected,
   * indents every selected line by two spaces). Shift+Tab removes up to
   * two leading spaces from each selected line. We deliberately stop the
   * browser's default tab-out behavior only when the focus is inside the
   * textarea so the rest of the panel remains keyboard-navigable.
   */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Tab') return
    e.preventDefault()
    const ta = e.currentTarget
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const value = ta.value

    if (start === end && !e.shiftKey) {
      // Simple case: no selection, plain Tab — insert two spaces.
      const next = value.slice(0, start) + '  ' + value.slice(end)
      setText(next)
      // Restore the caret on the next tick (after React flushes).
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 2
      })
      return
    }

    // Selection-aware indent / outdent. Operate line by line on the
    // selected range.
    const lineStart = value.lastIndexOf('\n', start - 1) + 1
    const lineEnd = end // we'll keep `end` exclusive of the trailing newline
    const before = value.slice(0, lineStart)
    const target = value.slice(lineStart, lineEnd)
    const after = value.slice(lineEnd)

    let nextTarget: string
    let startDelta = 0
    let endDelta = 0
    if (e.shiftKey) {
      // Outdent: remove up to 2 leading spaces from each line.
      nextTarget = target.replace(/(^|\n)( {1,2})/g, (_, p1, spaces) => {
        if (p1 === '') startDelta -= spaces.length
        endDelta -= spaces.length
        return p1
      })
      // Re-add the offset for the first line, since the regex captured the
      // boundary (^) without consuming chars.
      startDelta = -Math.min(2, target.match(/^ {1,2}/)?.[0].length ?? 0)
    } else {
      // Indent: prepend two spaces to each line in the selection.
      const indented = target.replace(/(^|\n)/g, (_, p1) => {
        endDelta += 2
        return p1 + '  '
      })
      nextTarget = indented
      startDelta = 2
    }

    const next = before + nextTarget + after
    setText(next)
    requestAnimationFrame(() => {
      ta.selectionStart = Math.max(lineStart, start + startDelta)
      ta.selectionEnd = Math.max(lineStart, end + endDelta)
    })
  }

  const handleCancel = () => {
    if (!isDirty) return
    const ok = window.confirm(
      'Discard your unsaved changes to the system prompt?',
    )
    if (!ok) return
    setText(savedText)
    setError(null)
  }

  const handleSave = async () => {
    if (!canEdit || saving) return
    setError(null)

    if (overLimit) {
      // Mirror the backend message so the user sees the same wording
      // whether the check fires client-side or server-side (R6.6).
      setError(
        `System prompt is ${length.toLocaleString()} characters; the limit is ${MAX_LEN.toLocaleString()}.`,
      )
      return
    }

    setSaving(true)
    try {
      await api.patch(`/api/workspaces/${workspaceId}`, {
        system_prompt: text,
      })
      setSavedText(text)
      setToast('System prompt saved')
      onSaved?.(text)
    } catch (err: any) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      if (status === 400 && typeof detail === 'string') {
        // Backend length-limit (or other validation) error.
        setError(detail)
      } else if (status === 403) {
        setError('You need admin permissions to edit this workspace prompt.')
      } else {
        setError(
          typeof detail === 'string'
            ? detail
            : 'Save failed. Try again in a moment.',
        )
      }
    } finally {
      setSaving(false)
    }
  }

  // ---- Render ------------------------------------------------------------

  return (
    <div
      className="space-y-3"
      data-component="system-prompt-editor"
      data-workspace-id={workspaceId}
    >
      {/* Inline error banner (length limit + backend errors) */}
      {error && (
        <div
          className="rounded-lg border border-red-700/40 bg-red-900/20 px-3 py-2 text-sm text-red-300"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Transient success toast — small inline banner, auto-dismiss */}
      {toast && (
        <div
          className="rounded-lg border border-green-700/40 bg-green-900/20 px-3 py-2 text-sm text-green-300"
          role="status"
          aria-live="polite"
        >
          {toast}
        </div>
      )}

      {/* Side-by-side editor + preview */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Editor pane */}
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 overflow-hidden flex flex-col min-h-[24rem]">
          <div className="px-3 py-1.5 border-b border-gray-800 bg-gray-900/60 text-xs uppercase tracking-wider text-gray-500 flex items-center justify-between">
            <span>Markdown</span>
            <span
              className={
                'tabular-nums ' +
                (overLimit ? 'text-red-400' : 'text-gray-500')
              }
              title="Character count / limit"
            >
              {length.toLocaleString()} / {MAX_LEN.toLocaleString()}
            </span>
          </div>
          <div className="relative flex flex-1 min-h-0">
            {/* Line-number gutter */}
            <div
              ref={lineNumbersRef}
              aria-hidden="true"
              className="
                select-none overflow-hidden
                text-right pr-2 pl-3 py-2
                font-mono text-xs leading-5 text-gray-600
                bg-gray-900/30 border-r border-gray-800
              "
              style={{ minWidth: '3rem' }}
            >
              {lineNumbers.map(n => (
                <div key={n}>{n}</div>
              ))}
            </div>
            <textarea
              ref={textareaRef}
              value={text}
              onChange={e => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              onScroll={handleScroll}
              spellCheck={false}
              readOnly={!canEdit}
              wrap="soft"
              aria-label="System prompt markdown editor"
              className="
                flex-1 min-w-0 resize-none
                bg-transparent text-gray-100
                font-mono text-sm leading-5
                px-3 py-2
                focus:outline-none focus:ring-1 focus:ring-indigo-500/40
              "
            />
          </div>
        </div>

        {/* Preview pane */}
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 overflow-hidden flex flex-col min-h-[24rem]">
          <div className="px-3 py-1.5 border-b border-gray-800 bg-gray-900/60 text-xs uppercase tracking-wider text-gray-500">
            Preview
          </div>
          <div className="flex-1 overflow-y-auto px-3 py-2">
            {previewText.length === 0 ? (
              <p className="text-sm text-gray-500 italic">
                Preview will render here as you type.
              </p>
            ) : (
              <div className="markdown-content text-gray-200 text-sm">
                <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
                  {previewText}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Footer: counts + actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div className="text-xs text-gray-500">
          ~{tokenEstimate.toLocaleString()} tokens
          {isDirty && (
            <span className="ml-2 inline-flex items-center gap-1 text-amber-400">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              Unsaved changes
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCancel}
            disabled={!isDirty || saving}
            className="
              px-3 py-1.5 rounded text-sm
              border border-gray-700 text-gray-300
              hover:bg-gray-800
              disabled:opacity-40 disabled:cursor-not-allowed
            "
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canEdit || !isDirty || saving || overLimit}
            className="
              px-3 py-1.5 rounded text-sm font-medium
              bg-indigo-600 text-white
              hover:bg-indigo-500
              disabled:opacity-40 disabled:cursor-not-allowed
            "
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
