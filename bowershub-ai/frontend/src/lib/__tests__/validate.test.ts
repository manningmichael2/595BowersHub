import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { z } from 'zod'
import { parseLoose } from '../validate'
import { ConversationSchema } from '../../schemas/conversation'

// toast is a side-effect on drift; stub it so tests don't depend on the store.
vi.mock('../../stores/toast', () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}))

const Item = z.object({ id: z.number(), name: z.string() }).passthrough()

describe('parseLoose', () => {
  let errSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    errSpy.mockRestore()
  })

  it('returns the parsed value for a matching payload', () => {
    const out = parseLoose(Item, { id: 1, name: 'a' }, 'test')
    expect(out).toEqual({ id: 1, name: 'a' })
    expect(errSpy).not.toHaveBeenCalled()
  })

  it('preserves unknown fields (passthrough) so new backend columns survive', () => {
    const out = parseLoose(Item, { id: 1, name: 'a', extra: 42 }, 'test')
    expect(out).toEqual({ id: 1, name: 'a', extra: 42 })
  })

  it('on drift: logs the mismatch and returns the data anyway (soft, non-breaking)', () => {
    const bad = { id: 'not-a-number', name: 'a' }
    const out = parseLoose(Item, bad, 'GET /thing')
    expect(out).toBe(bad) // app keeps working with the raw data
    expect(errSpy).toHaveBeenCalledOnce()
    expect(String(errSpy.mock.calls[0][0])).toContain('GET /thing')
  })

  it('validates arrays of a schema', () => {
    const out = parseLoose(z.array(Item), [{ id: 1, name: 'a' }], 'list')
    expect(out).toHaveLength(1)
  })

  it('accepts a real conversation payload through ConversationSchema', () => {
    const conv = {
      id: 7,
      workspace_id: 1,
      title: 'Hi',
      parent_id: null,
      is_archived: false,
      created_at: '2026-06-12T00:00:00Z',
      updated_at: '2026-06-12T00:00:00Z',
      message_count: 3,
    }
    expect(parseLoose(ConversationSchema, conv, 'conv')).toMatchObject({ id: 7, title: 'Hi' })
    expect(errSpy).not.toHaveBeenCalled()
  })
})
