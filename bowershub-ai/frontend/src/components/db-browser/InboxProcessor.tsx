/**
 * InboxProcessor — page-level component for processing inbox files into
 * inventory records or knowledge notes.
 *
 * Features:
 * - Thumbnail grid of inbox files with click-to-select (numbered selection)
 * - Mode toggle: "Inventory Record" vs "Knowledge Note"
 * - Target table dropdown (from /api/db/inbox/tables)
 * - Form fields loaded dynamically based on selected table's columns
 * - "AI Fill" button that calls ai-extract and populates form fields (highlights AI-filled)
 * - "Fill from URL" button that accepts a URL and calls url-extract
 * - Save button that calls /api/db/inbox/process (or /api/db/inbox/knowledge for note mode)
 * - After successful save, selected photos disappear from the grid
 *
 * _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 20.1, 20.2, 20.3, 20.4, 20.5_
 */

import { useEffect, useState, useCallback } from 'react'
import { api } from '../../services/api'
import { useDbBrowserStore, type ColumnMeta } from '../../stores/db-browser'
import { useIsAdmin } from '../../hooks/useIsAdmin'
import SmartFieldRenderer from './SmartFieldRenderer'

// ---- Types ----------------------------------------------------------------

interface InboxFile {
  name: string
  size: number
  modified_at: string
  is_image: boolean
}

interface InboxTable {
  schema: string
  table: string
  full_name: string
}

type ProcessingMode = 'inventory' | 'knowledge'

// ---- Component ------------------------------------------------------------

export default function InboxProcessor() {
  const isAdmin = useIsAdmin()

  // ---- Inbox files state ----
  const [files, setFiles] = useState<InboxFile[]>([])
  const [filesLoading, setFilesLoading] = useState(true)
  const [selectedFiles, setSelectedFiles] = useState<string[]>([])

  // ---- Tables state ----
  const [tables, setTables] = useState<InboxTable[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('')

  // ---- Columns for selected table ----
  const [columns, setColumns] = useState<ColumnMeta[]>([])

  // ---- Mode ----
  const [mode, setMode] = useState<ProcessingMode>('inventory')

  // ---- Form values (inventory mode) ----
  const [formValues, setFormValues] = useState<Record<string, any>>({})
  const [aiFilledFields, setAiFilledFields] = useState<Set<string>>(new Set())

  // ---- Knowledge note fields ----
  const [knowledgeTopic, setKnowledgeTopic] = useState('')
  const [knowledgeTitle, setKnowledgeTitle] = useState('')
  const [knowledgeNotes, setKnowledgeNotes] = useState('')

  // ---- AI / URL extraction ----
  const [urlInput, setUrlInput] = useState('')
  const [showUrlInput, setShowUrlInput] = useState(false)
  const [extracting, setExtracting] = useState(false)

  // ---- Save state ----
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  // ---- Field hints (from store) ----
  const loadFieldHints = useDbBrowserStore(s => s.loadFieldHints)

  // ---- Load inbox files ----
  const loadFiles = useCallback(async () => {
    setFilesLoading(true)
    try {
      const res = await api.get('/api/db/inbox/files')
      setFiles(res.data)
    } catch {
      setFiles([])
    } finally {
      setFilesLoading(false)
    }
  }, [])

  // ---- Load tables with image support ----
  const loadTables = useCallback(async () => {
    try {
      const res = await api.get('/api/db/inbox/tables')
      setTables(res.data)
    } catch {
      setTables([])
    }
  }, [])

  useEffect(() => {
    loadFiles()
    loadTables()
    loadFieldHints()
  }, [loadFiles, loadTables, loadFieldHints])

  // ---- Load columns when table selection changes ----
  useEffect(() => {
    if (!selectedTable || mode !== 'inventory') {
      setColumns([])
      setFormValues({})
      setAiFilledFields(new Set())
      return
    }

    const [schema, table] = selectedTable.split('.')
    if (!schema || !table) return

    async function fetchColumns() {
      try {
        const res = await api.get(`/api/db/${schema}/${table}/columns`)
        const cols: ColumnMeta[] = res.data
        // Filter out PK, timestamps, and auto-generated columns
        const editableCols = cols.filter(c =>
          !c.is_pk &&
          c.column_name !== 'created_at' &&
          c.column_name !== 'updated_at' &&
          c.column_name !== 'archived_at'
        )
        setColumns(editableCols)
        // Initialize form values with defaults
        const defaults: Record<string, any> = {}
        for (const col of editableCols) {
          defaults[col.column_name] = col.column_default ?? ''
        }
        setFormValues(defaults)
        setAiFilledFields(new Set())
      } catch {
        setColumns([])
        setFormValues({})
      }
    }

    fetchColumns()
  }, [selectedTable, mode])

  // ---- File selection ----
  const toggleFileSelection = (filename: string) => {
    setSelectedFiles(prev => {
      if (prev.includes(filename)) {
        return prev.filter(f => f !== filename)
      }
      return [...prev, filename]
    })
  }

  // ---- AI Fill ----
  const handleAiFill = async () => {
    if (selectedFiles.length === 0) return

    const firstImage = selectedFiles.find(name => {
      const file = files.find(f => f.name === name)
      return file?.is_image
    })

    if (!firstImage) {
      showToast('No image selected for AI extraction.', 'error')
      return
    }

    setExtracting(true)
    try {
      // Determine domain hint from selected table
      const domainHint = selectedTable ? selectedTable.split('.')[1] : undefined

      const res = await api.post('/api/db/inbox/ai-extract', {
        image_path: `inbox/${firstImage}`,
        domain_hint: domainHint,
      })

      const data = res.data
      // Smart Capture returns intents with payload
      if (data && data.intents && data.intents.length > 0) {
        const payload = data.intents[0].payload || {}
        populateFormFromExtraction(payload)
      } else if (data && typeof data === 'object') {
        // Fallback: treat the response itself as field values
        populateFormFromExtraction(data)
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'AI extraction failed.'
      showToast(detail, 'error')
    } finally {
      setExtracting(false)
    }
  }

  // ---- Fill from URL ----
  const handleUrlFill = async () => {
    if (!urlInput.trim()) return

    setExtracting(true)
    try {
      const columnNames = columns.map(c => c.column_name)
      const domainHint = selectedTable ? selectedTable.split('.')[1] : undefined

      const res = await api.post('/api/db/inbox/url-extract', {
        url: urlInput.trim(),
        columns: columnNames,
        domain_hint: domainHint,
      })

      const data = res.data
      if (data && data.intents && data.intents.length > 0) {
        const payload = data.intents[0].payload || {}
        populateFormFromExtraction(payload)
      } else if (data && typeof data === 'object') {
        populateFormFromExtraction(data)
      }

      setShowUrlInput(false)
      setUrlInput('')
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'URL extraction failed.'
      showToast(detail, 'error')
    } finally {
      setExtracting(false)
    }
  }

  // ---- Populate form from extraction result ----
  const populateFormFromExtraction = (payload: Record<string, any>) => {
    const newValues = { ...formValues }
    const newAiFields = new Set(aiFilledFields)

    for (const [key, value] of Object.entries(payload)) {
      // Skip internal/meta fields
      if (key.startsWith('_')) continue
      // Only fill if column exists in the form
      const col = columns.find(c => c.column_name === key)
      if (col && value != null && value !== '') {
        newValues[key] = value
        newAiFields.add(key)
      }
    }

    setFormValues(newValues)
    setAiFilledFields(newAiFields)
    showToast('Fields populated from extraction.', 'success')
  }

  // ---- Save (inventory mode) ----
  const handleSaveInventory = async () => {
    if (!selectedTable) {
      showToast('Please select a target table.', 'error')
      return
    }

    // Filter out empty values
    const cleanValues: Record<string, any> = {}
    for (const [key, value] of Object.entries(formValues)) {
      if (value !== '' && value != null) {
        cleanValues[key] = value
      }
    }

    if (Object.keys(cleanValues).length === 0) {
      showToast('Please fill in at least one field.', 'error')
      return
    }

    setSaving(true)
    try {
      await api.post('/api/db/inbox/process', {
        table: selectedTable,
        values: cleanValues,
        photos: selectedFiles,
      })

      showToast('Record saved successfully!', 'success')

      // Remove processed files from view
      setFiles(prev => prev.filter(f => !selectedFiles.includes(f.name)))
      setSelectedFiles([])
      setFormValues({})
      setAiFilledFields(new Set())
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Save failed.'
      showToast(detail, 'error')
    } finally {
      setSaving(false)
    }
  }

  // ---- Save (knowledge mode) ----
  const handleSaveKnowledge = async () => {
    if (!knowledgeTopic.trim()) {
      showToast('Please enter a topic.', 'error')
      return
    }
    if (!knowledgeTitle.trim()) {
      showToast('Please enter a title.', 'error')
      return
    }

    setSaving(true)
    try {
      await api.post('/api/db/inbox/knowledge', {
        topic: knowledgeTopic.trim(),
        title: knowledgeTitle.trim(),
        notes: knowledgeNotes.trim(),
        photos: selectedFiles,
      })

      showToast('Knowledge note saved!', 'success')

      // Remove processed files from view
      setFiles(prev => prev.filter(f => !selectedFiles.includes(f.name)))
      setSelectedFiles([])
      setKnowledgeTopic('')
      setKnowledgeTitle('')
      setKnowledgeNotes('')
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Save failed.'
      showToast(detail, 'error')
    } finally {
      setSaving(false)
    }
  }

  // ---- Toast helper ----
  const showToast = (msg: string, type: 'success' | 'error') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 4000)
  }

  // ---- Format file size ----
  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  // ---- Render ----

  // Non-admin users see a read-only message (Req 21.3)
  if (!isAdmin) {
    return (
      <div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>
        <div className="text-center">
          <p className="text-sm">Inbox processing requires admin access.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toast notification */}
      {toast && (
        <div
          className="fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium"
          style={{
            backgroundColor: toast.type === 'success'
              ? 'var(--color-primary)'
              : 'var(--color-error)',
            color: 'var(--color-on-primary)',
          }}
        >
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-surface)',
        }}
      >
        <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
          📥 Inbox Processor
        </h1>
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {files.length} file{files.length !== 1 ? 's' : ''} in inbox
          </span>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6" style={{ backgroundColor: 'var(--color-background)' }}>
        {/* ---- File thumbnail grid ---- */}
        <section>
          <h2 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-muted)' }}>
            Select Files
          </h2>

          {filesLoading ? (
            <div className="flex items-center justify-center py-8">
              <div
                className="animate-spin w-6 h-6 border-2 rounded-full"
                style={{
                  borderColor: 'var(--color-border)',
                  borderTopColor: 'var(--color-primary)',
                }}
              />
            </div>
          ) : files.length === 0 ? (
            <div
              className="text-center py-8 rounded-lg border border-dashed"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            >
              No files in inbox.
            </div>
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2">
              {files.map(file => {
                const isSelected = selectedFiles.includes(file.name)
                const selectionIndex = isSelected
                  ? selectedFiles.indexOf(file.name) + 1
                  : null

                return (
                  <button
                    key={file.name}
                    type="button"
                    onClick={() => toggleFileSelection(file.name)}
                    className="relative aspect-square rounded-lg overflow-hidden border-2 transition-all"
                    style={{
                      borderColor: isSelected
                        ? 'var(--color-primary)'
                        : 'var(--color-border)',
                      backgroundColor: 'var(--color-surface)',
                    }}
                    title={`${file.name} (${formatSize(file.size)})`}
                  >
                    {/* Thumbnail or file icon */}
                    {file.is_image ? (
                      <img
                        src={`/api/db/inbox/files/${file.name}`}
                        alt={file.name}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <div
                        className="w-full h-full flex flex-col items-center justify-center p-1"
                        style={{ color: 'var(--color-text-muted)' }}
                      >
                        <span className="text-2xl">📄</span>
                        <span className="text-[10px] truncate w-full text-center mt-1">
                          {file.name}
                        </span>
                      </div>
                    )}

                    {/* Selection indicator (numbered circle) */}
                    {isSelected && (
                      <div
                        className="absolute top-1 right-1 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                        style={{
                          backgroundColor: 'var(--color-primary)',
                          color: 'var(--color-on-primary)',
                        }}
                      >
                        {selectionIndex}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          {selectedFiles.length > 0 && (
            <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
            </p>
          )}
        </section>

        {/* ---- Mode toggle ---- */}
        <section>
          <div className="flex items-center gap-1 p-1 rounded-lg w-fit" style={{ backgroundColor: 'var(--color-surface)' }}>
            <button
              type="button"
              onClick={() => setMode('inventory')}
              className="px-4 py-2 rounded-md text-sm font-medium transition-colors"
              style={{
                backgroundColor: mode === 'inventory' ? 'var(--color-primary)' : 'transparent',
                color: mode === 'inventory' ? 'var(--color-on-primary)' : 'var(--color-text-muted)',
              }}
            >
              🗄️ Inventory Record
            </button>
            <button
              type="button"
              onClick={() => setMode('knowledge')}
              className="px-4 py-2 rounded-md text-sm font-medium transition-colors"
              style={{
                backgroundColor: mode === 'knowledge' ? 'var(--color-primary)' : 'transparent',
                color: mode === 'knowledge' ? 'var(--color-on-primary)' : 'var(--color-text-muted)',
              }}
            >
              📝 Knowledge Note
            </button>
          </div>
        </section>

        {/* ---- Inventory Record Mode ---- */}
        {mode === 'inventory' && (
          <section className="space-y-4">
            {/* Target table dropdown */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
                Target Table
              </label>
              <select
                value={selectedTable}
                onChange={e => setSelectedTable(e.target.value)}
                className="px-3 py-2 rounded-lg border text-sm"
                style={{
                  borderColor: 'var(--color-border)',
                  backgroundColor: 'var(--color-surface)',
                  color: 'var(--color-text)',
                }}
              >
                <option value="">— Select a table —</option>
                {tables.map(t => (
                  <option key={t.full_name} value={t.full_name}>
                    {t.full_name}
                  </option>
                ))}
              </select>
            </div>

            {/* AI Fill and URL Fill buttons */}
            {selectedTable && columns.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  onClick={handleAiFill}
                  disabled={extracting || selectedFiles.length === 0}
                  className="px-3 py-2 rounded-lg text-sm font-medium border transition-opacity disabled:opacity-50"
                  style={{
                    borderColor: 'var(--color-primary)',
                    color: 'var(--color-primary)',
                    backgroundColor: 'transparent',
                  }}
                >
                  {extracting ? '⏳ Extracting...' : '🤖 AI Fill'}
                </button>

                {!showUrlInput ? (
                  <button
                    type="button"
                    onClick={() => setShowUrlInput(true)}
                    disabled={extracting}
                    className="px-3 py-2 rounded-lg text-sm font-medium border transition-opacity disabled:opacity-50"
                    style={{
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-muted)',
                      backgroundColor: 'transparent',
                    }}
                  >
                    🔗 Fill from URL
                  </button>
                ) : (
                  <div className="flex items-center gap-2 flex-1 min-w-[200px]">
                    <input
                      type="url"
                      placeholder="https://example.com/product"
                      value={urlInput}
                      onChange={e => setUrlInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') handleUrlFill()
                        if (e.key === 'Escape') { setShowUrlInput(false); setUrlInput('') }
                      }}
                      className="flex-1 px-3 py-2 rounded-lg border text-sm"
                      style={{
                        borderColor: 'var(--color-border)',
                        backgroundColor: 'var(--color-surface)',
                        color: 'var(--color-text)',
                      }}
                      autoFocus
                    />
                    <button
                      type="button"
                      onClick={handleUrlFill}
                      disabled={extracting || !urlInput.trim()}
                      className="px-3 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
                      style={{
                        backgroundColor: 'var(--color-primary)',
                        color: 'var(--color-on-primary)',
                      }}
                    >
                      Extract
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowUrlInput(false); setUrlInput('') }}
                      className="px-2 py-2 rounded text-sm"
                      style={{ color: 'var(--color-text-muted)' }}
                    >
                      ✕
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Form fields */}
            {selectedTable && columns.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {columns.map(col => (
                  <div
                    key={col.column_name}
                    className="relative rounded-lg p-3 border"
                    style={{
                      borderColor: aiFilledFields.has(col.column_name)
                        ? 'var(--color-success)'
                        : 'var(--color-border)',
                      backgroundColor: aiFilledFields.has(col.column_name)
                        ? 'color-mix(in srgb, var(--color-success) 5%, transparent)'
                        : 'transparent',
                    }}
                  >
                    {/* AI-filled indicator */}
                    {aiFilledFields.has(col.column_name) && (
                      <span
                        className="absolute top-1 right-2 text-[10px] font-medium"
                        style={{ color: 'var(--color-success)' }}
                      >
                        AI
                      </span>
                    )}

                    <SmartFieldRenderer
                      column={col}
                      value={formValues[col.column_name] ?? ''}
                      onChange={(val) => {
                        setFormValues(prev => ({ ...prev, [col.column_name]: val }))
                        // Clear AI highlight when user manually edits
                        if (aiFilledFields.has(col.column_name)) {
                          setAiFilledFields(prev => {
                            const next = new Set(prev)
                            next.delete(col.column_name)
                            return next
                          })
                        }
                      }}
                      schema={selectedTable.split('.')[0]}
                      table={selectedTable.split('.')[1]}
                    />
                  </div>
                ))}
              </div>
            )}

            {/* Save button */}
            {selectedTable && columns.length > 0 && (
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleSaveInventory}
                  disabled={saving}
                  className="px-6 py-3 rounded-lg text-sm font-medium transition-opacity disabled:opacity-50"
                  style={{
                    backgroundColor: 'var(--color-primary)',
                    color: 'var(--color-on-primary)',
                  }}
                >
                  {saving ? '⏳ Saving...' : '💾 Save Record'}
                </button>
              </div>
            )}
          </section>
        )}

        {/* ---- Knowledge Note Mode ---- */}
        {mode === 'knowledge' && (
          <section className="space-y-4">
            {/* Topic */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
                Topic
              </label>
              <input
                type="text"
                placeholder="e.g., woodshop, cooking/tips, household"
                value={knowledgeTopic}
                onChange={e => setKnowledgeTopic(e.target.value)}
                className="px-3 py-2 rounded-lg border text-sm"
                style={{
                  borderColor: 'var(--color-border)',
                  backgroundColor: 'var(--color-surface)',
                  color: 'var(--color-text)',
                }}
              />
            </div>

            {/* Title */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
                Title
              </label>
              <input
                type="text"
                placeholder="Note title"
                value={knowledgeTitle}
                onChange={e => setKnowledgeTitle(e.target.value)}
                className="px-3 py-2 rounded-lg border text-sm"
                style={{
                  borderColor: 'var(--color-border)',
                  backgroundColor: 'var(--color-surface)',
                  color: 'var(--color-text)',
                }}
              />
            </div>

            {/* Notes textarea */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
                Notes
              </label>
              <textarea
                placeholder="Write your notes here (supports markdown)..."
                value={knowledgeNotes}
                onChange={e => setKnowledgeNotes(e.target.value)}
                rows={8}
                className="px-3 py-2 rounded-lg border text-sm resize-y"
                style={{
                  borderColor: 'var(--color-border)',
                  backgroundColor: 'var(--color-surface)',
                  color: 'var(--color-text)',
                }}
              />
            </div>

            {/* Save button */}
            <div className="pt-2">
              <button
                type="button"
                onClick={handleSaveKnowledge}
                disabled={saving}
                className="px-6 py-3 rounded-lg text-sm font-medium transition-opacity disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: 'var(--color-on-primary)',
                }}
              >
                {saving ? '⏳ Saving...' : '💾 Save Knowledge Note'}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
