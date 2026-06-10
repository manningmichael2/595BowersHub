import { useState, useEffect, useRef } from 'react'
import { useUIStore } from '../stores/ui'
import { api } from '../services/api'

interface Model {
  id: string
  provider: string
  display_name: string
  supports_vision: boolean
  supports_tools: boolean
  input_cost_per_mtok: number | null
  output_cost_per_mtok: number | null
}

export default function ModelPicker() {
  const [open, setOpen] = useState(false)
  const [models, setModels] = useState<Model[]>([])
  const [loading, setLoading] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const { modelSelection, modelLocked, setModel, resetModel } = useUIStore()

  useEffect(() => {
    if (open && models.length === 0) {
      setLoading(true)
      api.get('/api/models')
        .then(res => setModels(res.data || []))
        .catch(() => setModels([]))
        .finally(() => setLoading(false))
    }
  }, [open])

  // Close on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const groupedModels = models.reduce((acc, m) => {
    if (!acc[m.provider]) acc[m.provider] = []
    acc[m.provider].push(m)
    return acc
  }, {} as Record<string, Model[]>)

  const currentLabel = modelSelection === 'auto'
    ? 'Auto'
    : models.find(m => m.id === modelSelection)?.display_name || modelSelection.split('-').slice(1, 3).join(' ') || 'Custom'

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-surface hover:brightness-110 text-text-muted transition-colors"
        title="Select model"
      >
        {modelLocked && <span className="text-yellow-400">🔒</span>}
        <span>{currentLabel}</span>
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-1 w-72 bg-surface border border-border rounded-lg shadow-2xl z-40 max-h-96 overflow-y-auto">
          {/* Auto option */}
          <button
            onClick={() => { resetModel(); setOpen(false) }}
            className={`w-full text-left px-3 py-2 hover:bg-background/50 border-b border-border ${
              modelSelection === 'auto' ? 'bg-primary/20' : ''
            }`}
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-text">Auto</span>
              <span className="text-xs text-text-muted">Smart routing</span>
            </div>
            <div className="text-xs text-text-muted mt-0.5">
              Free for patterns • Haiku for skills • Sonnet for reasoning
            </div>
          </button>

          {loading && (
            <div className="text-center text-gray-500 py-4 text-sm">Loading...</div>
          )}

          {!loading && Object.entries(groupedModels).map(([provider, providerModels]) => (
            <div key={provider}>
              <div className="px-3 py-1.5 text-xs font-medium text-text-muted uppercase tracking-wide bg-background/30">
                {provider}
              </div>
              {providerModels.map(m => (
                <button
                  key={m.id}
                  onClick={() => { setModel(m.id, true); setOpen(false) }}
                  className={`w-full text-left px-3 py-2 hover:bg-background/50 ${
                    modelSelection === m.id ? 'bg-primary/20' : ''
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-text">{m.display_name}</span>
                    {m.supports_vision && <span title="Vision">👁</span>}
                    {m.supports_tools && <span title="Tool use">🔧</span>}
                  </div>
                  {m.input_cost_per_mtok != null && (
                    <div className="text-xs text-text-muted mt-0.5">
                      ${m.input_cost_per_mtok}/Mt in • ${m.output_cost_per_mtok}/Mt out
                    </div>
                  )}
                </button>
              ))}
            </div>
          ))}

          {modelSelection !== 'auto' && (
            <div className="border-t border-border px-3 py-2 bg-background/30">
              <button
                onClick={() => { resetModel(); setOpen(false) }}
                className="text-xs text-text-muted hover:text-text"
              >
                Reset to Auto
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
