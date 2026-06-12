import { useEffect, useState } from 'react'
import { useDashboardStore } from '../stores/dashboard'
import { useSettingsStore } from '../stores/settings'
import { WidgetGrid } from '../components/dashboard/WidgetGrid'
import DashboardNav from '../components/dashboard/DashboardNav'
import AddWidgetModal from '../components/dashboard/AddWidgetModal'
import DashboardV2 from '../components/dashboard/DashboardV2'

export default function DashboardPage() {
  const { loadDashboard, layouts, activePage, availableWidgets, isLoading, removeWidget } = useDashboardStore()
  const useExperimental = useSettingsStore(s => s.settings.use_experimental_dashboard)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)

  useEffect(() => {
    loadDashboard()
  }, [loadDashboard])

  if (isLoading) {
    return <div className="flex items-center justify-center h-full" style={{ color: 'var(--color-text-muted)' }}>Loading dashboard...</div>
  }

  if (useExperimental) {
    return <DashboardV2 />
  }

  const activeLayout = layouts[activePage]
  const widgets = activeLayout?.widgets || []

  return (
    <div className="flex flex-col h-full overflow-y-auto overflow-x-hidden pb-14 sm:pb-0 sm:pt-11" style={{ backgroundColor: 'var(--color-background)' }}>
      {/* Header: nav tabs + action buttons in one row */}
      <div className="flex items-center gap-2 px-3 py-2 shrink-0" style={{ borderBottom: '1px solid var(--color-border)' }}>
        <div className="flex-1 overflow-x-auto">
          <DashboardNav />
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setIsEditMode(!isEditMode)}
            className="h-9 px-3 rounded-lg text-xs font-medium transition-colors whitespace-nowrap"
            style={{
              backgroundColor: isEditMode ? 'var(--color-primary)' : 'transparent',
              color: isEditMode ? 'var(--color-on-primary)' : 'var(--color-text-muted)',
              border: isEditMode ? 'none' : '1px solid var(--color-border)',
            }}
          >
            {isEditMode ? 'Done' : 'Edit'}
          </button>
          <button
            onClick={() => setIsAddModalOpen(true)}
            className="h-9 w-9 flex items-center justify-center rounded-lg text-sm font-medium"
            style={{ backgroundColor: 'var(--color-primary)', color: 'var(--color-on-primary)' }}
          >
            +
          </button>
        </div>
      </div>

      <WidgetGrid
        widgets={widgets}
        availableWidgets={availableWidgets}
        editMode={isEditMode}
        onRemove={(key) => removeWidget(activePage, key)}
      />

      <AddWidgetModal isOpen={isAddModalOpen} onClose={() => setIsAddModalOpen(false)} />
    </div>
  )
}
