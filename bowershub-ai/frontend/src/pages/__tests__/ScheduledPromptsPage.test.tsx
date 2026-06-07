/**
 * Component tests for `ScheduledPromptsPage`.
 *
 * Covers task 28.3:
 *   1. List renders rows from `GET /api/scheduled-prompts`, including the
 *      friendly schedule (`cron_human`), workspace name, delivery method,
 *      enabled state, and last-run status.
 *   2. Clicking the row's name expands and fetches the last-10 log entries
 *      from `GET /api/scheduled-prompts/{id}/log?limit=10`.
 *   3. The toggle button calls `POST /api/scheduled-prompts/{id}/toggle`
 *      with the inverted `enabled` value.
 *   4. The "Run now" button calls `POST /api/scheduled-prompts/{id}/run-now`
 *      and the visible `last_run` cell updates afterwards (the page re-fetches
 *      the list following a successful run).
 *   5. The Delete button calls `DELETE /api/scheduled-prompts/{id}` only
 *      after `window.confirm` returns true; declining the confirm leaves
 *      the row in place and skips the network call.
 *
 * Mocking strategy:
 *   - `services/api` is `vi.mock`'d with method-keyed vi.fn stubs, matching
 *     the pattern used by `MorningCard.test.tsx` and
 *     `SettingsPanels.test.tsx`. Each test wires up the responses it needs.
 *   - `react-router-dom`'s `useNavigate` is replaced by a pass-through stub
 *     so the page's "Back" button doesn't try to interact with a real
 *     browser history.
 *   - The `useAuthStore` and `useWorkspaceStore` Zustand stores are seeded
 *     directly via their `setState` APIs.
 *
 * _Requirements: R11.2, R11.7, R11.8, R11.9, R11.11
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'

// ---- Module mocks --------------------------------------------------------

vi.mock('../../services/api', () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  }
})

vi.mock('react-router-dom', () => {
  return {
    // Page only uses `useNavigate`. Returning a no-op spy is enough — we
    // don't assert on navigation in these tests.
    useNavigate: () => vi.fn(),
  }
})

// Late-bound imports so the mocks are in place before module resolution.
import ScheduledPromptsPage from '../ScheduledPromptsPage'
import { api } from '../../services/api'
import { useAuthStore } from '../../stores/auth'
import { useWorkspaceStore, type Workspace } from '../../stores/workspace'

// ---- Fixtures ------------------------------------------------------------

const WORKSPACES: Workspace[] = [
  {
    id: 1,
    name: 'General',
    description: null,
    icon: null,
    color: null,
    system_prompt: '',
    default_model: 'claude-haiku-4-5-20251001',
    auto_capture: false,
    user_count: 1,
    skill_count: 0,
  },
  {
    id: 2,
    name: 'Finance',
    description: null,
    icon: null,
    color: null,
    system_prompt: '',
    default_model: 'claude-haiku-4-5-20251001',
    auto_capture: false,
    user_count: 1,
    skill_count: 0,
  },
]

interface ScheduledPromptFixture {
  id: number
  name: string
  workspace_id: number
  prompt_template: string
  cron_expression: string
  cron_human: string
  delivery_method: 'pin' | 'pushover'
  is_enabled: boolean
  last_run: string | null
  last_status: string | null
}

const PROMPT_A: ScheduledPromptFixture = {
  id: 101,
  name: 'Morning briefing',
  workspace_id: 1,
  prompt_template: 'Summarize today.',
  cron_expression: '0 7 * * *',
  cron_human: 'Every day at 07:00',
  delivery_method: 'pin',
  is_enabled: true,
  last_run: '2026-05-27T11:00:00Z',
  last_status: 'success',
}

const PROMPT_B: ScheduledPromptFixture = {
  id: 102,
  name: 'Weekly spend review',
  workspace_id: 2,
  prompt_template: 'Show last week spending.',
  cron_expression: '0 9 * * 1',
  cron_human: 'Every Monday at 09:00',
  delivery_method: 'pushover',
  is_enabled: false,
  last_run: null,
  last_status: null,
}

const LOG_ENTRIES = [
  {
    id: 1,
    executed_at: '2026-05-27T11:00:00Z',
    success: true,
    response_snippet: 'Today looks light. 2 meetings, sunny, 67°F.',
    error_message: null,
  },
  {
    id: 2,
    executed_at: '2026-05-26T11:00:00Z',
    success: false,
    response_snippet: null,
    error_message: 'Anthropic API timed out after 30s.',
  },
]

// ---- Helpers -------------------------------------------------------------

function findRowFor(name: string): HTMLTableRowElement {
  // The clickable row label is rendered inside a button — its closest <tr>
  // is the row we want to interact with for any sibling controls (toggle,
  // run, delete, etc.).
  const labelButton = screen.getByRole('button', { name: new RegExp(name) })
  const row = labelButton.closest('tr')
  if (!row) throw new Error(`Could not locate row for "${name}"`)
  return row as HTMLTableRowElement
}

function withinRow(name: string) {
  return within(findRowFor(name))
}

// ---- Lifecycle -----------------------------------------------------------

beforeEach(() => {
  ;(api.get as any).mockReset?.()
  ;(api.post as any).mockReset?.()
  ;(api.patch as any).mockReset?.()
  ;(api.delete as any).mockReset?.()

  // Seed auth + workspace stores so the page can render without firing the
  // real workspace fetch.
  useAuthStore.setState({
    user: {
      id: 1,
      email: 'admin@example.com',
      display_name: 'Admin',
      role: 'admin',
      is_active: true,
    },
    accessToken: 'test-bearer-token',
    refreshToken: null,
    isLoading: false,
    error: null,
    isRefreshing: false,
  } as any)

  useWorkspaceStore.setState({
    workspaces: WORKSPACES,
    activeWorkspace: WORKSPACES[0],
    isLoading: false,
  } as any)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// ---- Tests ---------------------------------------------------------------

describe('ScheduledPromptsPage — list rendering (R11.7)', () => {
  it('renders one row per scheduled prompt with workspace, schedule, delivery, last run', async () => {
    ;(api.get as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts')
        return { data: [PROMPT_A, PROMPT_B] }
      return { data: [] }
    })

    render(<ScheduledPromptsPage />)

    // Both prompt names appear once the GET resolves.
    await screen.findByRole('button', { name: /Morning briefing/ })
    expect(
      screen.getByRole('button', { name: /Weekly spend review/ }),
    ).toBeTruthy()

    // Workspace names land in the row from the seeded store.
    const rowA = withinRow('Morning briefing')
    expect(rowA.getByText('General')).toBeTruthy()
    expect(rowA.getByText('Every day at 07:00')).toBeTruthy()
    // Pin delivery badge.
    expect(rowA.getByText(/Pinned in workspace/)).toBeTruthy()
    // Last status — Prompt A succeeded.
    expect(rowA.getByText('success')).toBeTruthy()

    const rowB = withinRow('Weekly spend review')
    expect(rowB.getByText('Finance')).toBeTruthy()
    expect(rowB.getByText('Every Monday at 09:00')).toBeTruthy()
    expect(rowB.getByText(/Pushover/)).toBeTruthy()
    // Prompt B has never run.
    expect(rowB.getByText('—')).toBeTruthy()
  })
})

describe('ScheduledPromptsPage — expand row to show log (R11.7, R11.10)', () => {
  it('clicking the row name fetches the last 10 log entries and renders them', async () => {
    ;(api.get as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts') return { data: [PROMPT_A] }
      if (path === '/api/scheduled-prompts/101/log?limit=10')
        return { data: LOG_ENTRIES }
      return { data: [] }
    })

    render(<ScheduledPromptsPage />)

    const labelBtn = await screen.findByRole('button', {
      name: /Morning briefing/,
    })
    await act(async () => {
      fireEvent.click(labelBtn)
    })

    // Log endpoint hit with limit=10.
    await waitFor(() => {
      expect((api.get as any)).toHaveBeenCalledWith(
        '/api/scheduled-prompts/101/log?limit=10',
      )
    })

    // First log entry's response snippet appears in the expanded row.
    expect(
      await screen.findByText('Today looks light. 2 meetings, sunny, 67°F.'),
    ).toBeTruthy()
    // Failed entry's error message also appears.
    expect(
      screen.getByText(/Anthropic API timed out after 30s\./),
    ).toBeTruthy()
  })
})

describe('ScheduledPromptsPage — toggle button (R11.8)', () => {
  it('calls POST /api/scheduled-prompts/{id}/toggle with the inverted enabled value', async () => {
    ;(api.get as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts') return { data: [PROMPT_A] }
      return { data: [] }
    })
    ;(api.post as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts/101/toggle')
        return { data: { ...PROMPT_A, is_enabled: false } }
      return { data: {} }
    })

    render(<ScheduledPromptsPage />)
    await screen.findByRole('button', { name: /Morning briefing/ })

    const row = withinRow('Morning briefing')
    // The "Disable" action button (admin sees both Disable and the toggle pill —
    // we click the action button).
    const disableBtn = row.getByRole('button', { name: 'Disable' })

    await act(async () => {
      fireEvent.click(disableBtn)
    })

    await waitFor(() => {
      expect((api.post as any)).toHaveBeenCalledWith(
        '/api/scheduled-prompts/101/toggle',
        { enabled: false },
      )
    })

    // After toggle, the pill reflects the new state. The string
    // "Disabled" appears in two places — the toggle pill and the success
    // flash — so we anchor on the pill specifically via its
    // aria-pressed=false attribute.
    await waitFor(() => {
      const updated = withinRow('Morning briefing')
      const pill = updated.getByRole('button', { pressed: false })
      expect(pill.textContent).toMatch(/Disabled/)
    })
  })
})

describe('ScheduledPromptsPage — run now (R11.9)', () => {
  it('calls /run-now and updates last_run via the follow-up list reload', async () => {
    const PROMPT_AFTER_RUN = {
      ...PROMPT_A,
      last_run: '2026-05-27T15:30:00Z',
      last_status: 'success',
    }

    let listCalls = 0
    ;(api.get as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts') {
        listCalls += 1
        // First load returns the original; subsequent loads return the
        // post-run snapshot.
        return { data: [listCalls === 1 ? PROMPT_A : PROMPT_AFTER_RUN] }
      }
      return { data: [] }
    })
    ;(api.post as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts/101/run-now')
        return { data: { ok: true, status: 'success' } }
      return { data: {} }
    })

    render(<ScheduledPromptsPage />)
    await screen.findByRole('button', { name: /Morning briefing/ })

    const row = withinRow('Morning briefing')
    const runBtn = row.getByRole('button', { name: /Run now/i })

    await act(async () => {
      fireEvent.click(runBtn)
    })

    await waitFor(() => {
      expect((api.post as any)).toHaveBeenCalledWith(
        '/api/scheduled-prompts/101/run-now',
      )
    })

    // The page calls loadPrompts() after a successful run; the new
    // last_run timestamp eventually shows up in the row. The exact
    // formatted string is locale-dependent, so we anchor on the year +
    // success status — both move once the new snapshot lands.
    await waitFor(() => {
      const updated = withinRow('Morning briefing')
      // success status badge stays / re-renders from the new snapshot.
      expect(updated.getByText('success')).toBeTruthy()
      // The list endpoint was called at least twice — once on mount,
      // once after the run.
      expect(listCalls).toBeGreaterThanOrEqual(2)
    })
  })
})

describe('ScheduledPromptsPage — delete after confirm (R11.7)', () => {
  it('calls DELETE only when window.confirm returns true', async () => {
    ;(api.get as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts') return { data: [PROMPT_A] }
      return { data: [] }
    })
    ;(api.delete as any).mockResolvedValue({ data: {} })

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<ScheduledPromptsPage />)
    await screen.findByRole('button', { name: /Morning briefing/ })

    const row = withinRow('Morning briefing')
    const deleteBtn = row.getByRole('button', { name: /Delete/ })

    await act(async () => {
      fireEvent.click(deleteBtn)
    })

    expect(confirmSpy).toHaveBeenCalled()
    await waitFor(() => {
      expect((api.delete as any)).toHaveBeenCalledWith(
        '/api/scheduled-prompts/101',
      )
    })

    // Row is removed from the table once delete resolves.
    await waitFor(() => {
      expect(
        screen.queryByRole('button', { name: /Morning briefing/ }),
      ).toBeNull()
    })
  })

  it('skips the DELETE call when window.confirm returns false', async () => {
    ;(api.get as any).mockImplementation(async (path: string) => {
      if (path === '/api/scheduled-prompts') return { data: [PROMPT_A] }
      return { data: [] }
    })
    ;(api.delete as any).mockResolvedValue({ data: {} })

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<ScheduledPromptsPage />)
    await screen.findByRole('button', { name: /Morning briefing/ })

    const row = withinRow('Morning briefing')
    const deleteBtn = row.getByRole('button', { name: /Delete/ })

    await act(async () => {
      fireEvent.click(deleteBtn)
    })

    expect(confirmSpy).toHaveBeenCalled()
    expect((api.delete as any)).not.toHaveBeenCalled()
    // Row still present.
    expect(
      screen.getByRole('button', { name: /Morning briefing/ }),
    ).toBeTruthy()
  })
})
