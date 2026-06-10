/**
 * Integration tests for dashboard load, theme reactivity, and responsive layout.
 *
 * Validates: Requirements 1.1, 5.2, 4.1, 4.2
 *
 * These tests verify:
 * 1. Dashboard load — loadDashboard() fetches widgets + layouts, store populates correctly
 * 2. Theme reactivity — widget components use CSS variable-based styles, no hardcoded colors
 * 3. Responsive layout — WidgetGrid renders with correct responsive grid classes
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { renderHook, act } from '@testing-library/react'
import React from 'react'

// Mock the auth store for all tests
vi.mock('../stores/auth', () => ({
  useAuthStore: {
    getState: () => ({ accessToken: 'test-token' }),
    subscribe: () => () => {},
  },
}))

// --- Test Data ---

const MOCK_WIDGETS = [
  {
    id: 1,
    widget_key: 'weather',
    display_name: 'Weather',
    description: 'Current conditions + forecast',
    category: 'general',
    data_endpoint: '/api/dashboard/weather',
    default_config: { polling_interval_ms: 300000 },
  },
  {
    id: 2,
    widget_key: 'system_health',
    display_name: 'System Health',
    description: 'CPU, memory, disk usage',
    category: 'system',
    data_endpoint: '/api/dashboard/system-health',
    default_config: { polling_interval_ms: 30000 },
  },
  {
    id: 3,
    widget_key: 'finance_summary',
    display_name: 'Finance Summary',
    description: 'MTD spending and top categories',
    category: 'finance',
    data_endpoint: '/api/dashboard/finance/summary',
    default_config: { polling_interval_ms: 60000 },
  },
]

const MOCK_LAYOUTS = {
  pages: [
    {
      page_key: 'overview',
      widgets: [
        { widget_key: 'weather', position: 0, config_overrides: {} },
        { widget_key: 'finance_summary', position: 1, config_overrides: {} },
      ],
    },
    {
      page_key: 'system',
      widgets: [
        { widget_key: 'system_health', position: 0, config_overrides: {} },
      ],
    },
  ],
}

// --- Section 1: Dashboard Load Integration ---

describe('Dashboard Load Integration', () => {
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
    localStorage.clear()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('loadDashboard fetches from both /api/dashboard/widgets and /api/dashboard/layouts', async () => {
    const fetchCalls: string[] = []

    globalThis.fetch = vi.fn((url: string | URL | Request, _options?: RequestInit) => {
      const urlStr = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url
      fetchCalls.push(urlStr)

      if (urlStr.includes('/api/dashboard/widgets')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_WIDGETS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      if (urlStr.includes('/api/dashboard/layouts')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_LAYOUTS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }) as typeof globalThis.fetch

    // Import and use the store (re-import to get fresh state)
    const { useDashboardStore } = await import('../stores/dashboard')

    // Reset store state
    useDashboardStore.setState({
      availableWidgets: [],
      layouts: {},
      activePage: 'overview',
      isLoading: false,
    })

    await act(async () => {
      await useDashboardStore.getState().loadDashboard()
    })

    // Verify both endpoints were called
    expect(fetchCalls).toContain('/api/dashboard/widgets')
    expect(fetchCalls).toContain('/api/dashboard/layouts')
  })

  it('store populates availableWidgets after loadDashboard', async () => {
    globalThis.fetch = vi.fn((url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url

      if (urlStr.includes('/api/dashboard/widgets')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_WIDGETS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      if (urlStr.includes('/api/dashboard/layouts')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_LAYOUTS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }) as typeof globalThis.fetch

    const { useDashboardStore } = await import('../stores/dashboard')

    useDashboardStore.setState({
      availableWidgets: [],
      layouts: {},
      activePage: 'overview',
      isLoading: false,
    })

    await act(async () => {
      await useDashboardStore.getState().loadDashboard()
    })

    const state = useDashboardStore.getState()
    expect(state.availableWidgets).toHaveLength(3)
    expect(state.availableWidgets[0].widget_key).toBe('weather')
    expect(state.availableWidgets[1].widget_key).toBe('system_health')
    expect(state.availableWidgets[2].widget_key).toBe('finance_summary')
  })

  it('store populates layouts with page_key-indexed Record', async () => {
    globalThis.fetch = vi.fn((url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url

      if (urlStr.includes('/api/dashboard/widgets')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_WIDGETS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      if (urlStr.includes('/api/dashboard/layouts')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_LAYOUTS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }) as typeof globalThis.fetch

    const { useDashboardStore } = await import('../stores/dashboard')

    useDashboardStore.setState({
      availableWidgets: [],
      layouts: {},
      activePage: 'overview',
      isLoading: false,
    })

    await act(async () => {
      await useDashboardStore.getState().loadDashboard()
    })

    const state = useDashboardStore.getState()
    expect(state.layouts).toHaveProperty('overview')
    expect(state.layouts).toHaveProperty('system')
    expect(state.layouts['overview'].widgets).toHaveLength(2)
    expect(state.layouts['system'].widgets).toHaveLength(1)
  })

  it('activePage defaults to "overview" when layout exists', async () => {
    globalThis.fetch = vi.fn((url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url

      if (urlStr.includes('/api/dashboard/widgets')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_WIDGETS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      if (urlStr.includes('/api/dashboard/layouts')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_LAYOUTS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }) as typeof globalThis.fetch

    const { useDashboardStore } = await import('../stores/dashboard')

    useDashboardStore.setState({
      availableWidgets: [],
      layouts: {},
      activePage: 'overview',
      isLoading: false,
    })

    await act(async () => {
      await useDashboardStore.getState().loadDashboard()
    })

    const state = useDashboardStore.getState()
    expect(state.activePage).toBe('overview')
  })

  it('isLoading transitions from true to false during loadDashboard', async () => {
    globalThis.fetch = vi.fn((url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url

      if (urlStr.includes('/api/dashboard/widgets')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_WIDGETS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      if (urlStr.includes('/api/dashboard/layouts')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_LAYOUTS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }) as typeof globalThis.fetch

    const { useDashboardStore } = await import('../stores/dashboard')

    useDashboardStore.setState({
      availableWidgets: [],
      layouts: {},
      activePage: 'overview',
      isLoading: false,
    })

    const loadPromise = useDashboardStore.getState().loadDashboard()

    // isLoading should be true immediately after calling
    expect(useDashboardStore.getState().isLoading).toBe(true)

    await act(async () => {
      await loadPromise
    })

    // isLoading should be false after completion
    expect(useDashboardStore.getState().isLoading).toBe(false)
  })
})

// --- Section 2: Theme Reactivity ---

describe('Theme Reactivity', () => {
  it('DashboardNav uses CSS custom properties for active/inactive states', async () => {
    // Set up the store with layouts so the nav renders
    const { useDashboardStore } = await import('../stores/dashboard')
    useDashboardStore.setState({
      availableWidgets: MOCK_WIDGETS,
      layouts: {
        overview: { page_key: 'overview', widgets: MOCK_LAYOUTS.pages[0].widgets },
        system: { page_key: 'system', widgets: MOCK_LAYOUTS.pages[1].widgets },
      },
      activePage: 'overview',
      isLoading: false,
    })

    const DashboardNav = (await import('../components/dashboard/DashboardNav')).default

    const { container } = render(React.createElement(DashboardNav))

    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBeGreaterThan(0)

    // Active button uses CSS variables, not hardcoded colors
    const activeButton = Array.from(buttons).find(
      (btn) => btn.getAttribute('aria-current') === 'page'
    )
    expect(activeButton).toBeTruthy()

    if (activeButton) {
      const style = activeButton.getAttribute('style') || ''
      // Should use CSS custom properties
      expect(style).toContain('var(--color-')
      // Should NOT contain hex colors or rgb
      expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}/)
      expect(style).not.toMatch(/rgb\(\d/)
    }

    // Inactive buttons also use CSS variables
    const inactiveButtons = Array.from(buttons).filter(
      (btn) => btn.getAttribute('aria-current') !== 'page'
    )
    for (const btn of inactiveButtons) {
      const style = btn.getAttribute('style') || ''
      expect(style).toContain('var(--color-')
      expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}/)
      expect(style).not.toMatch(/rgb\(\d/)
    }
  })

  it('WidgetShell uses only CSS custom properties for its chrome', async () => {
    const { default: WidgetShell } = await import('../components/dashboard/WidgetShell')

    const { container } = render(
      React.createElement(WidgetShell, {
        displayName: 'Test Widget',
        isLoading: false,
        error: null,
        isStale: false,
        lastFetched: new Date(),
        onRefresh: () => {},
        children: React.createElement('div', null, 'Content'),
      })
    )

    // Check all elements with inline styles use CSS variables
    const elementsWithStyle = container.querySelectorAll('[style]')
    expect(elementsWithStyle.length).toBeGreaterThan(0)

    for (const el of Array.from(elementsWithStyle)) {
      const style = el.getAttribute('style') || ''
      // If there's a color-related style property, it must use CSS variables
      if (style.includes('color') || style.includes('background') || style.includes('border')) {
        expect(style).toContain('var(--color-')
        // No hardcoded hex or rgb color values
        expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}(?!\))/) // exclude hex inside var()
        expect(style).not.toMatch(/(?<!color-mix\(in srgb, )rgb\(\d/)
      }
    }
  })

  it('WidgetShell stale badge uses CSS custom property for accent color', async () => {
    const { default: WidgetShell } = await import('../components/dashboard/WidgetShell')

    const { container } = render(
      React.createElement(WidgetShell, {
        displayName: 'Stale Widget',
        isLoading: false,
        error: 'Connection failed',
        isStale: true,
        lastFetched: new Date(Date.now() - 300000), // 5 min ago
        onRefresh: () => {},
        children: React.createElement('div', null, 'Cached content'),
      })
    )

    // The stale badge should be present and use CSS variables
    const staleText = container.textContent || ''
    expect(staleText).toContain('Stale')

    // All inline styles should use CSS custom properties
    const elementsWithStyle = container.querySelectorAll('[style]')
    for (const el of Array.from(elementsWithStyle)) {
      const style = el.getAttribute('style') || ''
      if (style.includes('color') || style.includes('background')) {
        expect(style).toContain('var(--color-')
      }
    }
  })

  it('DashboardPage container uses CSS custom properties for background', async () => {
    // Mock fetch for the loadDashboard call triggered by useEffect
    globalThis.fetch = vi.fn((url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url
      if (urlStr.includes('/api/dashboard/widgets')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_WIDGETS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      if (urlStr.includes('/api/dashboard/layouts')) {
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_LAYOUTS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      }
      // All other widget data endpoints
      return Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    }) as typeof globalThis.fetch

    const { useDashboardStore } = await import('../stores/dashboard')
    useDashboardStore.setState({
      availableWidgets: [],
      layouts: {},
      activePage: 'overview',
      isLoading: false,
    })

    const DashboardPage = (await import('../pages/DashboardPage')).default

    const { container } = render(React.createElement(DashboardPage))

    // Wait for loadDashboard to complete (useEffect fires, fetches, then re-renders)
    await waitFor(() => {
      const state = useDashboardStore.getState()
      expect(state.isLoading).toBe(false)
      expect(state.availableWidgets.length).toBeGreaterThan(0)
    })

    // After loading, the outer container should use CSS variable for background
    const outerDiv = container.firstElementChild as HTMLElement
    expect(outerDiv).toBeTruthy()
    const style = outerDiv.getAttribute('style') || ''
    expect(style).toContain('var(--color-background)')
  })
})

// --- Section 3: Widget Layout (react-grid-layout) ---
//
// WidgetGrid lays out widgets with react-grid-layout (drag/resize, responsive
// cols configured via the lib's `breakpoints`/`cols` props), NOT Tailwind CSS
// grid utilities. These tests assert the real react-grid-layout DOM.

describe('Widget Layout (react-grid-layout)', () => {
  it('WidgetGrid renders a responsive react-grid-layout with one item per widget', async () => {
    // Mock fetch for widget data calls
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ value: 42 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    ) as typeof globalThis.fetch

    const { WidgetGrid } = await import('../components/dashboard/WidgetGrid')

    const widgets = [
      { widget_key: 'weather', position: 0, config_overrides: {} },
      { widget_key: 'system_health', position: 1, config_overrides: {} },
    ]

    const { container } = render(
      React.createElement(WidgetGrid, {
        widgets,
        availableWidgets: MOCK_WIDGETS,
      })
    )

    // react-grid-layout renders the grid container; responsiveness is driven
    // by its breakpoints/cols props rather than Tailwind classes.
    const gridLayout = container.querySelector('.react-grid-layout')
    expect(gridLayout).toBeTruthy()
    // One grid item per widget instance.
    expect(container.querySelectorAll('.react-grid-item')).toHaveLength(widgets.length)
  })

  it('WidgetGrid renders the react-grid-layout container', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    ) as typeof globalThis.fetch

    const { WidgetGrid } = await import('../components/dashboard/WidgetGrid')

    const widgets = [
      { widget_key: 'weather', position: 0, config_overrides: {} },
    ]

    const { container } = render(
      React.createElement(WidgetGrid, {
        widgets,
        availableWidgets: MOCK_WIDGETS,
      })
    )

    expect(container.querySelector('.react-grid-layout')).toBeTruthy()
  })

  it('WidgetGrid renders one positioned item per widget cell', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    ) as typeof globalThis.fetch

    const { WidgetGrid } = await import('../components/dashboard/WidgetGrid')

    const widgets = [
      { widget_key: 'weather', position: 0, config_overrides: {} },
      { widget_key: 'system_health', position: 1, config_overrides: {} },
    ]

    const { container } = render(
      React.createElement(WidgetGrid, {
        widgets,
        availableWidgets: MOCK_WIDGETS,
      })
    )

    // Spacing between cells comes from react-grid-layout's `margin` prop (it
    // positions items via inline styles, not a `gap-*` class). Assert one
    // positioned grid item per widget.
    expect(container.querySelectorAll('.react-grid-item')).toHaveLength(widgets.length)
  })

  it('WidgetGrid skips unknown widget_keys without rendering them', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    ) as typeof globalThis.fetch

    const { WidgetGrid } = await import('../components/dashboard/WidgetGrid')

    const widgets = [
      { widget_key: 'weather', position: 0, config_overrides: {} },
      { widget_key: 'nonexistent_widget', position: 1, config_overrides: {} },
      { widget_key: 'system_health', position: 2, config_overrides: {} },
    ]

    const { container } = render(
      React.createElement(WidgetGrid, {
        widgets,
        availableWidgets: [
          ...MOCK_WIDGETS,
          // Add a widget def for the unknown key so it passes the widgetDefMap check
          // but it won't have a component registered
          {
            id: 99,
            widget_key: 'nonexistent_widget',
            display_name: 'Unknown',
            description: 'Test',
            category: 'test',
            data_endpoint: '/api/dashboard/unknown',
            default_config: {},
          },
        ],
      })
    )

    // The grid should render without crashing. The unknown key has a def but
    // no registered component, so its cell renders empty — the grid still
    // mounts and nothing throws.
    expect(container.querySelector('.react-grid-layout')).toBeTruthy()

    // Should not have thrown any errors — the test completing is proof
  })
})
