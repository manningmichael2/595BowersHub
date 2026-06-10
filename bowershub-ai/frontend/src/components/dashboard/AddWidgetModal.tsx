import { useState } from 'react'
import { useDashboardStore, WidgetType } from '../../stores/dashboard'

interface AddWidgetModalProps {
  isOpen: boolean
  onClose: () => void
}

const CATEGORIES = [
  { key: 'general', label: 'General' },
  { key: 'finance', label: 'Finance' },
  { key: 'system', label: 'System' },
]

export default function AddWidgetModal({ isOpen, onClose }: AddWidgetModalProps) {
  const { availableWidgets, activePage, layouts, addWidget } = useDashboardStore()
  const [activeCategory, setActiveCategory] = useState('general')

  if (!isOpen) return null

  const activeLayout = layouts[activePage]
  const currentWidgetKeys = new Set(activeLayout?.widgets.map((w) => w.widget_key) || [])

  // Group widgets by category, filter to those not already on the page
  const filteredWidgets = availableWidgets.filter(
    (w) => w.category === activeCategory && !currentWidgetKeys.has(w.widget_key)
  )

  const handleAdd = async (widget: WidgetType) => {
    await addWidget(activePage, widget.widget_key)
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label="Add widget"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0"
        style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
        onClick={onClose}
      />

      {/* Modal content */}
      <div
        className="relative w-full max-w-md mx-4 rounded-xl shadow-xl overflow-hidden flex flex-col"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          maxHeight: '80vh',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
            Add Widget
          </h2>
          <button
            onClick={onClose}
            className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Category tabs */}
        <div
          className="flex gap-1 px-4 py-3"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          {CATEGORIES.map((cat) => (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(cat.key)}
              className="min-h-[44px] px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors"
              style={{
                backgroundColor: activeCategory === cat.key ? 'var(--color-primary)' : 'transparent',
                color: activeCategory === cat.key ? 'var(--color-on-primary)' : 'var(--color-text-muted)',
              }}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* Widget list */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {filteredWidgets.length === 0 ? (
            <p className="text-sm py-4 text-center" style={{ color: 'var(--color-text-muted)' }}>
              No widgets available in this category.
            </p>
          ) : (
            filteredWidgets.map((widget) => (
              <div
                key={widget.widget_key}
                className="flex items-center gap-3 rounded-lg p-3"
                style={{ border: '1px solid var(--color-border)' }}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                    {widget.display_name}
                  </p>
                  {widget.description && (
                    <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--color-text-muted)' }}>
                      {widget.description}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => handleAdd(widget)}
                  className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-sm font-medium transition-colors"
                  style={{
                    backgroundColor: 'var(--color-primary)',
                    color: 'var(--color-on-primary)',
                  }}
                  aria-label={`Add ${widget.display_name}`}
                >
                  Add
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
