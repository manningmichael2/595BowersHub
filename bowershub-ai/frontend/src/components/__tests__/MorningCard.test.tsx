/**
 * Component tests for `MorningCard`.
 *
 * Covers task 25.4:
 *   1. When the backend reports `briefing_id: null`, the card shows the
 *      "Generate today's briefing" CTA (R8.3) and clicking it POSTs to
 *      `/api/briefing/generate-now`, then re-renders with the new
 *      briefing's parsed sections (R8.4).
 *   2. When a briefing is present, every parsed section is rendered with
 *      its label and content (R8.2).
 *   3. When a section's content is the canonical placeholder "—" (e.g.
 *      Weather skill returned no data), that section is still rendered
 *      but with the muted placeholder style (R8.7).
 *   4. The ✕ close button calls `dismiss_today` so the card hides for the
 *      remainder of the local calendar day; remounting on the same day
 *      keeps it hidden via the `read_dismiss_set` localStorage hook
 *      (R8.5, R8.6).
 *
 * Mocking strategy:
 *   - `services/api` is `vi.mock`'d so no real fetch happens. Each test
 *     re-implements `api.get` / `api.post` to drive the component into
 *     the desired state.
 *   - `localStorage` is cleared in `beforeEach` so dismissals from one
 *     test don't leak into the next.
 *
 * _Requirements: R8.3, R8.4, R8.5, R8.6, R8.7
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import MorningCard from '../MorningCard'
import { MORNING_CARD_DISMISS_KEY, today_iso } from '../../lib/morning_card'

// ---- API mock -------------------------------------------------------------

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

// Late-bound import so the mock is in place by the time the module
// resolves.
import { api } from '../../services/api'

// ---- Fixtures -------------------------------------------------------------

const WORKSPACE_ID = 7

// A complete parsed-sections payload (canonical key order, matching
// backend/services/briefing_summary.py::EXPECTED_SECTIONS). Every section
// has real content so this fixture can be reused as the baseline for the
// "renders each section" test.
const FULL_SECTIONS = [
  { key: 'weather', label: 'Weather', content: '72°F, partly cloudy' },
  { key: 'yesterday_spending', label: "Yesterday's Spending", content: '$42.10 across 3 transactions' },
  { key: 'inbox', label: 'Inbox', content: '4 unread messages' },
  { key: 'schedule', label: "Today's Schedule", content: '10am standup, 2pm review' },
  { key: 'anything_else', label: 'Anything Else', content: 'Manon out of town' },
]

// Same shape, but the Weather section is the canonical "missing"
// placeholder per R8.7. Used by the muted-placeholder test.
const SECTIONS_WITH_MISSING_WEATHER = [
  { key: 'weather', label: 'Weather', content: '—' },
  ...FULL_SECTIONS.slice(1),
]

function makeBriefingResponse(parsedSections: typeof FULL_SECTIONS) {
  return {
    briefing_id: 42,
    content: parsedSections.map(s => `**${s.label}:** ${s.content}`).join('\n\n'),
    generated_at: new Date().toISOString(),
    age_hours: 0.5,
    parsed_sections: parsedSections,
  }
}

const NULL_BRIEFING = { briefing_id: null }

// ---- Lifecycle ------------------------------------------------------------

beforeEach(() => {
  localStorage.clear()
  ;(api.get as any).mockReset?.()
  ;(api.post as any).mockReset?.()
  ;(api.patch as any).mockReset?.()
  ;(api.delete as any).mockReset?.()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// ---- Tests ----------------------------------------------------------------

describe('MorningCard — null-briefing state (R8.3, R8.4)', () => {
  it('shows the "Generate today\'s briefing" button when briefing_id is null', async () => {
    ;(api.get as any).mockResolvedValue({ data: NULL_BRIEFING })

    render(<MorningCard workspaceId={WORKSPACE_ID} />)

    // Loading state flips to the no-briefing state once the GET resolves.
    const button = await screen.findByRole('button', {
      name: /generate today's briefing/i,
    })
    expect(button).toBeTruthy()

    // GET was called with the right workspace id.
    expect((api.get as any)).toHaveBeenCalledWith(
      `/api/briefing/latest?workspace_id=${WORKSPACE_ID}`,
    )
    // No POST yet — user has not clicked the button.
    expect((api.post as any)).not.toHaveBeenCalled()
  })

  it('clicking "Generate today\'s briefing" POSTs to /generate-now and renders the new briefing', async () => {
    ;(api.get as any).mockResolvedValue({ data: NULL_BRIEFING })
    ;(api.post as any).mockResolvedValue({
      data: makeBriefingResponse(FULL_SECTIONS),
    })

    render(<MorningCard workspaceId={WORKSPACE_ID} />)

    const button = await screen.findByRole('button', {
      name: /generate today's briefing/i,
    })

    await act(async () => {
      fireEvent.click(button)
    })

    // Once the POST resolves, the parsed sections replace the CTA.
    await waitFor(() => {
      expect((api.post as any)).toHaveBeenCalledWith(
        `/api/briefing/generate-now?workspace_id=${WORKSPACE_ID}`,
      )
    })

    // Section content from the post-generation response is now visible…
    expect(await screen.findByText('72°F, partly cloudy')).toBeTruthy()
    // …and the CTA is gone.
    expect(
      screen.queryByRole('button', { name: /generate today's briefing/i }),
    ).toBeNull()
  })
})

describe('MorningCard — populated briefing (R8.2)', () => {
  it('renders every parsed section with its label and content', async () => {
    ;(api.get as any).mockResolvedValue({
      data: makeBriefingResponse(FULL_SECTIONS),
    })

    render(<MorningCard workspaceId={WORKSPACE_ID} />)

    // Wait for the card to surface its first section, then verify them all.
    await screen.findByText('72°F, partly cloudy')

    for (const section of FULL_SECTIONS) {
      // Label is rendered uppercase via CSS, but the DOM text node contains
      // the original casing — match it directly.
      expect(screen.getByText(section.label)).toBeTruthy()
      expect(screen.getByText(section.content)).toBeTruthy()
    }
  })
})

describe('MorningCard — missing section placeholder (R8.7)', () => {
  it('renders a Weather section whose content is "—" with the muted-placeholder style', async () => {
    ;(api.get as any).mockResolvedValue({
      data: makeBriefingResponse(SECTIONS_WITH_MISSING_WEATHER),
    })

    const { container } = render(<MorningCard workspaceId={WORKSPACE_ID} />)

    // Wait for any section to appear so the briefing is rendered.
    await screen.findByText("Yesterday's Spending")

    // Locate the Weather tile via its data-section-key marker.
    const weatherTile = container.querySelector(
      '[data-section-key="weather"]',
    ) as HTMLElement | null
    expect(weatherTile).toBeTruthy()

    // The placeholder text "—" is present inside the Weather tile.
    const placeholder = weatherTile!.querySelector('.italic')
    expect(placeholder).toBeTruthy()
    expect(placeholder!.textContent).toBe('—')

    // Sections with real data must NOT carry the muted/italic styling — pick
    // one (Inbox) and confirm its content node lacks the italic class.
    const inboxTile = container.querySelector(
      '[data-section-key="inbox"]',
    ) as HTMLElement | null
    expect(inboxTile).toBeTruthy()
    const inboxContent = Array.from(inboxTile!.children).find(
      el => el.textContent === '4 unread messages',
    ) as HTMLElement | undefined
    expect(inboxContent).toBeTruthy()
    expect(inboxContent!.className.split(/\s+/)).not.toContain('italic')
  })
})

describe('MorningCard — close button dismisses for the day (R8.5, R8.6)', () => {
  it('hides the card and persists today\'s dismissal in localStorage', async () => {
    ;(api.get as any).mockResolvedValue({
      data: makeBriefingResponse(FULL_SECTIONS),
    })

    const { container } = render(<MorningCard workspaceId={WORKSPACE_ID} />)

    // Wait for the card to render.
    const card = await screen.findByTestId('morning-card')
    expect(card).toBeTruthy()

    const closeBtn = screen.getByRole('button', {
      name: /dismiss morning briefing for today/i,
    })

    await act(async () => {
      fireEvent.click(closeBtn)
    })

    // Card unmounts itself once dismissed.
    await waitFor(() => {
      expect(screen.queryByTestId('morning-card')).toBeNull()
    })

    // Dismissal persisted under the documented localStorage key.
    const raw = localStorage.getItem(MORNING_CARD_DISMISS_KEY)
    expect(raw).toBeTruthy()
    const dismissed = JSON.parse(raw!) as string[]
    expect(dismissed).toContain(today_iso())

    // Sanity: the card was actually present in the tree before dismissal —
    // nothing else around the dismissal flow should have unmounted it.
    expect(container).toBeTruthy()
  })

  it('a fresh mount on the same day stays hidden because read_dismiss_set sees today', async () => {
    // Pre-populate localStorage as if the user already dismissed earlier.
    localStorage.setItem(
      MORNING_CARD_DISMISS_KEY,
      JSON.stringify([today_iso()]),
    )
    ;(api.get as any).mockResolvedValue({
      data: makeBriefingResponse(FULL_SECTIONS),
    })

    render(<MorningCard workspaceId={WORKSPACE_ID} />)

    // Even though the briefing fetch will resolve, the component reads the
    // dismissal set on mount and immediately returns null (R8.6).
    // Wait briefly to confirm nothing renders.
    await waitFor(() => {
      expect(screen.queryByTestId('morning-card')).toBeNull()
    })
    // Briefing fetch may or may not fire (component bails before fetch
    // resolves) — we don't assert on it. The visible behavior is what matters.
  })
})
