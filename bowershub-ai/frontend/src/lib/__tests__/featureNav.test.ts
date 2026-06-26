/**
 * Task 10 (frontend) — role thresholds + nav visibility computed from
 * /me/features ∩ settings_json (never role alone). A self-hidden feature is
 * still routable (visibility is cosmetic — this only governs the nav button).
 */
import { describe, expect, it } from 'vitest'
import {
  roleMeets, roleRank, isFeatureVisible, visibleFeatureKeys, type FeatureAccess,
} from '../featureNav'

const access = (over: Partial<FeatureAccess> = {}): FeatureAccess => ({
  role: 'member',
  capabilities: ['finance.read', 'finance.write'],
  features: [
    { key: 'finance', label: 'Finance', routes: ['/finance'], permitted: true },
    { key: 'database', label: 'Database', routes: ['/database'], permitted: false },
  ],
  hidden_nav: [],
  ...over,
})

describe('roleMeets / roleRank', () => {
  it('orders the ladder viewer < member < admin', () => {
    expect(roleRank('viewer')).toBeLessThan(roleRank('member'))
    expect(roleRank('member')).toBeLessThan(roleRank('admin'))
  })
  it('is fail-closed on unknown/None role and unknown threshold', () => {
    expect(roleMeets(undefined, 'member')).toBe(false)
    expect(roleMeets('ghost', 'member')).toBe(false)
    expect(roleMeets('admin', 'superuser')).toBe(false)
  })
  it('member meets member/viewer but not admin', () => {
    expect(roleMeets('member', 'viewer')).toBe(true)
    expect(roleMeets('member', 'member')).toBe(true)
    expect(roleMeets('member', 'admin')).toBe(false)
  })
})

describe('isFeatureVisible — permitted ∩ not self-hidden', () => {
  it('shows a permitted, un-hidden feature', () => {
    expect(isFeatureVisible(access(), 'finance')).toBe(true)
  })
  it('hides a non-permitted feature regardless of hidden_nav', () => {
    expect(isFeatureVisible(access(), 'database')).toBe(false)
  })
  it('hides a permitted feature the user self-hid (cosmetic)', () => {
    expect(isFeatureVisible(access({ hidden_nav: ['finance'] }), 'finance')).toBe(false)
  })
  it('returns false when access has not loaded yet', () => {
    expect(isFeatureVisible(null, 'finance')).toBe(false)
  })
})

describe('visibleFeatureKeys', () => {
  it('is the permitted set minus self-hidden', () => {
    expect(visibleFeatureKeys(access())).toEqual(new Set(['finance']))
    expect(visibleFeatureKeys(access({ hidden_nav: ['finance'] }))).toEqual(new Set())
  })
})
