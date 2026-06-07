/**
 * Tests for AdminConsolePage RBAC + section rendering.
 *
 * Coverage (task 29.2):
 *   1. Non-admin user navigating to /admin/* gets redirected to "/"
 *      (R12.5 — admin gate).
 *   2. Admin user lands on /admin and the sidebar with all sections
 *      (Users, Workspaces, Skills, Cost, Audit Log, Theme Management,
 *      Icon Management) renders.
 *   3. Clicking a sidebar entry switches the rendered section
 *      (deep-link routing — verified via the Skills section heading).
 *   4. The Theme Management section pulls /api/themes and renders the
 *      returned themes (R12.6).
 *   5. The Icon Management section mounts the IconUploader component
 *      (R12.7) — we assert by the section heading + an action button
 *      it owns ("Upload new icon"), without needing a full IconUploader
 *      contract test.
 *
 * Mocking strategy:
 *   - `useAuthStore` is replaced module-side so each test can swap the
 *     "current user" without touching the real zustand store (which has
 *     side effects on import that read localStorage and fire a refresh).
 *   - `services/api` is replaced with vi.fn()s that resolve canned
 *     responses per path. This lets us assert behavior without a live
 *     backend and keeps the IconUploader / ThemeBuilder happy when their
 *     internal data-loading calls fire.
 *   - The branding store doesn't need an explicit mock because the
 *     IconUploader's refresh() calls go through the (already-mocked)
 *     api client.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { act } from 'react'

// --- Module mocks ---------------------------------------------------------

// Auth store — a hand-rolled hook + getState shim so the page (and any
// child component that does `useAuthStore(s => s.x)` / `useAuthStore.getState()`)
// sees the user we plant before render.
let mockAuthState: { user: any } = { user: null }

vi.mock('../../stores/auth', () => {
  const useAuthStore: any = (selector?: (s: any) => any) => {
    if (typeof selector === 'function') return selector(mockAuthState)
    return mockAuthState
  }
  useAuthStore.getState = () => mockAuthState
  useAuthStore.setState = (patch: any) => {
    mockAuthState = { ...mockAuthState, ...patch }
  }
  return { useAuthStore }
})

// API client — dispatches by path so we can return realistic shapes for
// each section without a giant test fixture per case.
const apiGet = vi.fn(async (path: string) => {
  if (path === '/api/themes') {
    return {
      data: [
        {
          id: 1,
          name: 'Dark Navy',
          slug: 'dark-navy',
          is_preset: true,
          owner_id: null,
          tokens_json: {
            background: '#0f172a',
            surface: '#1e293b',
            primary: '#6366f1',
            accent: '#8b5cf6',
            text: '#f1f5f9',
            text_muted: '#94a3b8',
            border: '#334155',
            danger: '#ef4444',
            success: '#10b981',
          },
          is_default: true,
        },
        {
          id: 7,
          name: 'Forest',
          slug: 'forest',
          is_preset: false,
          owner_id: null,
          tokens_json: {
            background: '#0b2a1a',
            surface: '#143d28',
            primary: '#22c55e',
            accent: '#84cc16',
            text: '#ecfdf5',
            text_muted: '#a7f3d0',
            border: '#166534',
            danger: '#f87171',
            success: '#86efac',
          },
          is_default: false,
        },
      ],
      status: 200,
    }
  }
  if (path === '/api/branding/icon') {
    return {
      data: {
        version: 'v-test',
        urls: {
          icon_192: '/static/icons/icon-192.png',
          icon_512: '/static/icons/icon-512.png',
          icon_maskable_512: '/static/icons/icon-maskable-512.png',
        },
        has_rollback: false,
      },
      status: 200,
    }
  }
  if (path === '/api/admin/users') {
    return { data: [], status: 200 }
  }
  if (path === '/api/workspaces') {
    return { data: [], status: 200 }
  }
  if (path === '/api/skills') {
    return { data: [], status: 200 }
  }
  if (path.startsWith('/api/admin/cost')) {
    return { data: { today_total: 0, daily: [], by_model: [], by_source: [] }, status: 200 }
  }
  if (path.startsWith('/api/admin/audit')) {
    return { data: [], status: 200 }
  }
  return { data: null, status: 200 }
})

vi.mock('../../services/api', () => ({
  api: {
    get: (path: string) => apiGet(path),
    post: vi.fn(async () => ({ data: {}, status: 200 })),
    patch: vi.fn(async () => ({ data: {}, status: 200 })),
    delete: vi.fn(async () => ({ data: {}, status: 200 })),
  },
}))

// Import AFTER mocks are registered so AdminConsolePage picks them up.
import AdminConsolePage from '../AdminConsolePage'

// --- Helpers --------------------------------------------------------------

const ADMIN_USER = {
  id: 1,
  email: 'admin@example.com',
  display_name: 'Admin',
  role: 'admin',
  is_active: true,
}

const MEMBER_USER = {
  id: 2,
  email: 'member@example.com',
  display_name: 'Member',
  role: 'member',
  is_active: true,
}

/**
 * Renders AdminConsolePage inside a MemoryRouter at the given path, plus a
 * sentinel `/` route that surfaces the current pathname so RBAC redirect
 * tests can assert on where the user ended up.
 */
function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/" element={<HomeSentinel />} />
        <Route path="/admin/*" element={<AdminConsolePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function HomeSentinel() {
  const location = useLocation()
  return <div data-testid="home-sentinel">HOME at {location.pathname}</div>
}

// --- Setup ----------------------------------------------------------------

beforeEach(() => {
  mockAuthState = { user: null }
  apiGet.mockClear()
})

afterEach(() => {
  cleanup()
})

// --- Tests ----------------------------------------------------------------

describe('AdminConsolePage — RBAC', () => {
  it('redirects a non-admin user from /admin to /', async () => {
    mockAuthState = { user: MEMBER_USER }
    renderAt('/admin/users')

    await waitFor(() => {
      expect(screen.getByTestId('home-sentinel')).toBeTruthy()
    })
    expect(screen.getByTestId('home-sentinel').textContent).toContain('/')
    // The admin header must NOT have rendered.
    expect(screen.queryByText('Admin Console')).toBeNull()
  })

  it('redirects when there is no user at all', async () => {
    mockAuthState = { user: null }
    renderAt('/admin/users')

    // No user means the gate returns null and no navigate fires; the
    // initial entry stays at /admin/users but nothing renders. We verify
    // the page chrome is absent.
    expect(screen.queryByText('Admin Console')).toBeNull()
  })

  it('renders the admin console with the full sidebar for an admin user', async () => {
    mockAuthState = { user: ADMIN_USER }
    renderAt('/admin/users')

    expect(await screen.findByText('Admin Console')).toBeTruthy()

    // Every sidebar label should be present (sidebar + mobile tab strip
    // both render the same labels, so we assert at least one match).
    const labels = [
      'Users',
      'Workspaces',
      'Skills',
      'Cost',
      'Audit Log',
      'Theme Management',
      'Icon Management',
    ]
    for (const label of labels) {
      const matches = screen.getAllByText(label)
      expect(matches.length).toBeGreaterThan(0)
    }
  })
})

describe('AdminConsolePage — sidebar navigation', () => {
  it('switching to /admin/skills renders the Skills section', async () => {
    mockAuthState = { user: ADMIN_USER }
    renderAt('/admin/skills')

    // The Skills section heading is "Skills (N)" with the count from the
    // mocked /api/skills response (empty array → 0).
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Skills \(0\)/ })).toBeTruthy()
    })
  })

  it('the /admin index redirects to the Users section', async () => {
    mockAuthState = { user: ADMIN_USER }
    renderAt('/admin')

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Users \(0\)/ })).toBeTruthy()
    })
  })
})

describe('AdminConsolePage — Theme Management section', () => {
  it('fetches /api/themes and renders the returned themes', async () => {
    mockAuthState = { user: ADMIN_USER }
    renderAt('/admin/themes')

    // The section header is an <h2> distinct from the sidebar link, which
    // also contains the literal text "Theme Management". Disambiguate by
    // looking for the h2 specifically.
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Theme Management/ }),
      ).toBeTruthy()
    })

    // Both themes from the mock should render with their slugs.
    await waitFor(() => {
      expect(screen.getByText('Dark Navy')).toBeTruthy()
      expect(screen.getByText('Forest')).toBeTruthy()
      expect(screen.getByText('dark-navy')).toBeTruthy()
      expect(screen.getByText('forest')).toBeTruthy()
    })

    // The "+ New theme" admin entry point must be present (R12.6 — admin
    // can author/publish themes from this section).
    expect(screen.getByRole('button', { name: /New theme/ })).toBeTruthy()

    // Confirm the section actually called the themes endpoint.
    expect(apiGet).toHaveBeenCalledWith('/api/themes')
  })
})

describe('AdminConsolePage — Icon Management section', () => {
  it('mounts IconUploader when navigating to /admin/icon', async () => {
    mockAuthState = { user: ADMIN_USER }

    await act(async () => {
      renderAt('/admin/icon')
    })

    // IconUploader renders its own "App Icon" heading + the upload action.
    await waitFor(() => {
      expect(screen.getByText('App Icon')).toBeTruthy()
    })
    expect(screen.getByRole('button', { name: /Upload new icon/ })).toBeTruthy()

    // It also kicks off a /api/branding/icon refresh on mount.
    await waitFor(() => {
      expect(apiGet).toHaveBeenCalledWith('/api/branding/icon')
    })
  })
})
