import { create } from 'zustand'
import { z } from 'zod'
import { api } from '../services/api'
import { parseLoose } from '../lib/validate'
import {
  WidgetTypeSchema,
  PageLayoutSchema,
  LayoutsResponseSchema,
  type WidgetType,
  type WidgetInstance,
  type PageLayout,
} from '../schemas/dashboard'

export type { WidgetType, WidgetInstance, PageLayout }

interface DashboardState {
  availableWidgets: WidgetType[]
  layouts: Record<string, PageLayout>
  activePage: string
  isLoading: boolean

  loadDashboard: () => Promise<void>
  setActivePage: (page: string) => void
  addWidget: (pageKey: string, widgetKey: string) => Promise<void>
  removeWidget: (pageKey: string, widgetKey: string) => Promise<void>
  reorderWidgets: (pageKey: string, widgets: WidgetInstance[]) => Promise<void>
}

export const useDashboardStore = create<DashboardState>((set, get) => ({
  availableWidgets: [],
  layouts: {},
  activePage: 'overview',
  isLoading: false,

  loadDashboard: async () => {
    set({ isLoading: true })
    try {
      const [widgetsRes, layoutsRes] = await Promise.all([
        api.get('/api/dashboard/widgets'),
        api.get('/api/dashboard/layouts'),
      ])

      const availableWidgets = parseLoose(
        z.array(WidgetTypeSchema),
        widgetsRes.data,
        'GET /api/dashboard/widgets'
      )
      const layoutData = parseLoose(
        LayoutsResponseSchema,
        layoutsRes.data,
        'GET /api/dashboard/layouts'
      )
      const pages = layoutData.pages || []

      // Convert pages array into a Record keyed by page_key
      const layouts: Record<string, PageLayout> = {}
      for (const page of pages) {
        layouts[page.page_key] = page
      }

      // Restore active page from localStorage or default to "overview"
      const saved = localStorage.getItem('dashboardActivePage')
      const activePage = saved && layouts[saved] ? saved : (layouts['overview'] ? 'overview' : Object.keys(layouts)[0] || 'overview')

      set({ availableWidgets, layouts, activePage, isLoading: false })
    } catch {
      set({ isLoading: false })
    }
  },

  setActivePage: (page: string) => {
    set({ activePage: page })
    localStorage.setItem('dashboardActivePage', page)
  },

  addWidget: async (pageKey: string, widgetKey: string) => {
    const { layouts } = get()
    const currentLayout = layouts[pageKey] || { page_key: pageKey, widgets: [] }
    const currentWidgets = currentLayout.widgets

    const newWidget: WidgetInstance = {
      widget_key: widgetKey,
      position: currentWidgets.length,
      config_overrides: {},
    }

    const updatedLayout: PageLayout = {
      ...currentLayout,
      widgets: [...currentWidgets, newWidget],
    }

    const updatedLayouts = { ...layouts, [pageKey]: updatedLayout }

    // Optimistic update
    set({ layouts: updatedLayouts })

    // Persist to backend
    try {
      const pages = Object.values(updatedLayouts)
      await api.put('/api/dashboard/layouts', { pages })
    } catch {
      // Revert on failure
      set({ layouts })
    }
  },

  removeWidget: async (pageKey: string, widgetKey: string) => {
    const { layouts } = get()
    const currentLayout = layouts[pageKey]
    if (!currentLayout) return

    // Filter out the widget and reindex positions
    const filteredWidgets = currentLayout.widgets
      .filter((w) => w.widget_key !== widgetKey)
      .map((w, index) => ({ ...w, position: index }))

    const updatedLayout: PageLayout = {
      ...currentLayout,
      widgets: filteredWidgets,
    }

    const updatedLayouts = { ...layouts, [pageKey]: updatedLayout }

    // Optimistic update
    set({ layouts: updatedLayouts })

    // Persist to backend
    try {
      const pages = Object.values(updatedLayouts)
      await api.put('/api/dashboard/layouts', { pages })
    } catch {
      // Revert on failure
      set({ layouts })
    }
  },

  reorderWidgets: async (pageKey: string, widgets: WidgetInstance[]) => {
    const { layouts } = get()
    const currentLayout = layouts[pageKey]
    if (!currentLayout) return

    const updatedLayout: PageLayout = {
      ...currentLayout,
      widgets,
    }

    const updatedLayouts = { ...layouts, [pageKey]: updatedLayout }

    // Optimistic update
    set({ layouts: updatedLayouts })

    // Persist to backend
    try {
      const pages = Object.values(updatedLayouts)
      await api.put('/api/dashboard/layouts', { pages })
    } catch {
      // Revert on failure
      set({ layouts })
    }
  },
}))
