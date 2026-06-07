/**
 * Tests for `ScheduledPromptForm`'s pure cron helpers.
 *
 * Covers task 28.3 — the "friendly cron preview matches expected output"
 * slice. The helpers are exposed via the `__testing__` export so we can
 * exercise `buildCron`, `describeCron`, `validateCronClient`, and
 * `inferModeFromCron` directly without rendering the form.
 *
 * The form's UI rendering, network round-trip, and error handling are
 * exercised by `pages/__tests__/ScheduledPromptsPage.test.tsx` (28.3
 * page-level tests). Keeping the helper tests in a separate file matches
 * the colocation pattern used elsewhere in this codebase (e.g.
 * `lib/__tests__/contrast.property.test.ts`).
 *
 * _Requirements: R11.2, R11.3, R11.11_
 */

import { describe, expect, it } from 'vitest'
import { __testing__ } from '../ScheduledPromptForm'

const { buildCron, describeCron, validateCronClient, inferModeFromCron } =
  __testing__

// ---- buildCron -----------------------------------------------------------

describe('ScheduledPromptForm.buildCron', () => {
  const baseDaily = {
    name: '',
    workspace_id: null,
    prompt_template: '',
    delivery_method: 'pin' as const,
    scheduleMode: 'daily' as const,
    hour: 7,
    minute: 0,
    weekday: 1,
    monthDay: 1,
    cron_custom: 'ignored when not custom',
  }

  it('emits "minute hour * * *" for daily mode', () => {
    expect(buildCron({ ...baseDaily, hour: 7, minute: 0 })).toBe('0 7 * * *')
    expect(buildCron({ ...baseDaily, hour: 14, minute: 30 })).toBe(
      '30 14 * * *',
    )
    expect(buildCron({ ...baseDaily, hour: 0, minute: 0 })).toBe('0 0 * * *')
  })

  it('emits "minute hour * * <weekday>" for weekly mode', () => {
    expect(
      buildCron({
        ...baseDaily,
        scheduleMode: 'weekly',
        hour: 9,
        minute: 15,
        weekday: 1, // Monday
      }),
    ).toBe('15 9 * * 1')
    expect(
      buildCron({
        ...baseDaily,
        scheduleMode: 'weekly',
        hour: 18,
        minute: 0,
        weekday: 5, // Friday
      }),
    ).toBe('0 18 * * 5')
  })

  it('emits "minute hour <day> * *" for monthly mode', () => {
    expect(
      buildCron({
        ...baseDaily,
        scheduleMode: 'monthly',
        hour: 8,
        minute: 0,
        monthDay: 1,
      }),
    ).toBe('0 8 1 * *')
    expect(
      buildCron({
        ...baseDaily,
        scheduleMode: 'monthly',
        hour: 23,
        minute: 59,
        monthDay: 28,
      }),
    ).toBe('59 23 28 * *')
  })

  it('clamps out-of-range time values into the valid cron range', () => {
    // Negative hour clamps up to 0, oversized minute clamps down to 59.
    expect(
      buildCron({ ...baseDaily, hour: -3 as any, minute: 99 as any }),
    ).toBe('59 0 * * *')
    // Hour 30 clamps to 23.
    expect(
      buildCron({ ...baseDaily, hour: 30 as any, minute: 0 }),
    ).toBe('0 23 * * *')
  })

  it('passes the raw expression through in custom mode', () => {
    expect(
      buildCron({
        ...baseDaily,
        scheduleMode: 'custom',
        cron_custom: '*/5 * * * *',
      }),
    ).toBe('*/5 * * * *')
    // Trims surrounding whitespace.
    expect(
      buildCron({
        ...baseDaily,
        scheduleMode: 'custom',
        cron_custom: '  0 0 1 1 *  ',
      }),
    ).toBe('0 0 1 1 *')
  })
})

// ---- describeCron --------------------------------------------------------

describe('ScheduledPromptForm.describeCron', () => {
  it('describes daily expressions as "Every day at HH:MM"', () => {
    expect(describeCron('0 7 * * *')).toBe('Every day at 07:00')
    expect(describeCron('30 14 * * *')).toBe('Every day at 14:30')
    expect(describeCron('0 0 * * *')).toBe('Every day at 00:00')
  })

  it('describes weekly expressions as "Every <weekday> at HH:MM"', () => {
    expect(describeCron('15 9 * * 1')).toBe('Every Monday at 09:15')
    expect(describeCron('0 18 * * 5')).toBe('Every Friday at 18:00')
    expect(describeCron('0 12 * * 0')).toBe('Every Sunday at 12:00')
    // 7 is also Sunday in cron — describeCron normalizes it.
    expect(describeCron('0 12 * * 7')).toBe('Every Sunday at 12:00')
  })

  it('describes monthly expressions as "On day N of every month at HH:MM"', () => {
    expect(describeCron('0 8 1 * *')).toBe(
      'On day 1 of every month at 08:00',
    )
    expect(describeCron('59 23 28 * *')).toBe(
      'On day 28 of every month at 23:59',
    )
  })

  it('returns the raw expression for non-friendly cron patterns', () => {
    // Step expressions are valid but don't match the daily/weekly/monthly
    // shapes the friendly picker emits; describeCron passes them through.
    expect(describeCron('*/5 * * * *')).toBe('*/5 * * * *')
    expect(describeCron('0 9-17 * * 1-5')).toBe('0 9-17 * * 1-5')
  })

  it('returns an empty string for invalid cron expressions', () => {
    expect(describeCron('')).toBe('')
    expect(describeCron('not a cron')).toBe('')
    // Six fields — invalid 5-field cron.
    expect(describeCron('0 0 0 0 0 0')).toBe('')
  })
})

// ---- validateCronClient --------------------------------------------------

describe('ScheduledPromptForm.validateCronClient', () => {
  it('accepts the cron expressions emitted by the friendly picker', () => {
    for (const ok of [
      '0 7 * * *',
      '30 14 * * *',
      '15 9 * * 1',
      '0 18 * * 5',
      '0 8 1 * *',
      '*/5 * * * *',
      '0 9-17 * * 1-5',
      '0 0 1,15 * *',
    ]) {
      const r = validateCronClient(ok)
      expect(r.ok, `expected "${ok}" to validate`).toBe(true)
    }
  })

  it('rejects empty and malformed expressions with a reason', () => {
    for (const bad of ['', '   ', 'bogus', '* * *', '60 24 32 13 8']) {
      const r = validateCronClient(bad)
      expect(r.ok, `expected "${bad}" to fail validation`).toBe(false)
      if (!r.ok) {
        expect(typeof r.reason).toBe('string')
        expect(r.reason.length).toBeGreaterThan(0)
      }
    }
  })
})

// ---- inferModeFromCron ---------------------------------------------------

describe('ScheduledPromptForm.inferModeFromCron', () => {
  it('reverses a daily expression back into daily mode + hour/minute', () => {
    expect(inferModeFromCron('30 14 * * *')).toMatchObject({
      scheduleMode: 'daily',
      hour: 14,
      minute: 30,
    })
  })

  it('reverses a weekly expression back into weekly mode + weekday', () => {
    expect(inferModeFromCron('15 9 * * 1')).toMatchObject({
      scheduleMode: 'weekly',
      hour: 9,
      minute: 15,
      weekday: 1,
    })
    // Weekday 7 maps back to Sunday (0).
    expect(inferModeFromCron('0 12 * * 7')).toMatchObject({
      scheduleMode: 'weekly',
      hour: 12,
      minute: 0,
      weekday: 0,
    })
  })

  it('reverses a monthly expression back into monthly mode + monthDay', () => {
    expect(inferModeFromCron('0 8 15 * *')).toMatchObject({
      scheduleMode: 'monthly',
      hour: 8,
      minute: 0,
      monthDay: 15,
    })
  })

  it('falls back to custom mode for non-friendly expressions', () => {
    const r = inferModeFromCron('*/5 * * * *')
    expect(r.scheduleMode).toBe('custom')
    expect(r.cron_custom).toBe('*/5 * * * *')
  })

  it('falls back to custom mode for invalid expressions instead of throwing', () => {
    const r = inferModeFromCron('not a cron')
    expect(r.scheduleMode).toBe('custom')
    expect(r.cron_custom).toBe('not a cron')
  })
})

// ---- buildCron ↔ describeCron round-trip --------------------------------

describe('ScheduledPromptForm cron round-trip', () => {
  it('build → describe yields the expected human form', () => {
    const cases: Array<{
      mode: 'daily' | 'weekly' | 'monthly'
      hour: number
      minute: number
      weekday?: number
      monthDay?: number
      expectedCron: string
      expectedHuman: string
    }> = [
      {
        mode: 'daily',
        hour: 7,
        minute: 0,
        expectedCron: '0 7 * * *',
        expectedHuman: 'Every day at 07:00',
      },
      {
        mode: 'weekly',
        hour: 18,
        minute: 30,
        weekday: 5,
        expectedCron: '30 18 * * 5',
        expectedHuman: 'Every Friday at 18:30',
      },
      {
        mode: 'monthly',
        hour: 8,
        minute: 0,
        monthDay: 1,
        expectedCron: '0 8 1 * *',
        expectedHuman: 'On day 1 of every month at 08:00',
      },
    ]
    for (const c of cases) {
      const cron = buildCron({
        name: '',
        workspace_id: null,
        prompt_template: '',
        delivery_method: 'pin',
        scheduleMode: c.mode,
        hour: c.hour,
        minute: c.minute,
        weekday: c.weekday ?? 1,
        monthDay: c.monthDay ?? 1,
        cron_custom: '',
      })
      expect(cron).toBe(c.expectedCron)
      expect(describeCron(cron)).toBe(c.expectedHuman)
    }
  })
})
