import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import tailwindConfig from '../../../tailwind.config'

/**
 * Guards for the non-color design scales (R1.5). These are code-level design
 * constants in tailwind.config.ts / index.css — the test pins their presence
 * and (for z-index) their ordering so the layering contract can't silently
 * regress.
 */
const extend = (tailwindConfig as any).theme.extend

describe('design scales (R1.5)', () => {
  it('z-index scale is ordered base < shell < dropdown < modal < toast', () => {
    const z = extend.zIndex
    const order = ['base', 'shell', 'dropdown', 'modal', 'toast']
    const values = order.map((k) => Number(z[k]))
    for (const k of order) expect(z[k], `zIndex.${k} defined`).toBeDefined()
    const sorted = [...values].sort((a, b) => a - b)
    expect(values).toEqual(sorted)
    expect(new Set(values).size).toBe(values.length) // strictly increasing, no ties
  })

  it('defines the elevation shadow scale (1..4)', () => {
    for (const n of [1, 2, 3, 4]) {
      expect(extend.boxShadow[`elevation-${n}`], `elevation-${n}`).toBeTruthy()
    }
  })

  it('defines the radius family off the --radius var', () => {
    for (const k of ['sm', 'md', 'lg', 'xl']) {
      expect(extend.borderRadius[k], `radius ${k}`).toContain('var(--radius)')
    }
  })

  it('defines motion duration + easing tokens', () => {
    expect(extend.transitionDuration).toMatchObject({
      fast: expect.any(String),
      base: expect.any(String),
      slow: expect.any(String),
    })
    expect(Object.keys(extend.transitionTimingFunction)).toEqual(
      expect.arrayContaining(['standard', 'emphasized']),
    )
  })
})

describe('reduced-motion + radius base (index.css)', () => {
  // vitest runs with cwd at the frontend project root.
  const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

  it('collapses motion under prefers-reduced-motion: reduce', () => {
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
    const block = css.slice(css.indexOf('prefers-reduced-motion'))
    expect(block).toMatch(/transition-duration:\s*0\.01ms\s*!important/)
    expect(block).toMatch(/animation-duration:\s*0\.01ms\s*!important/)
  })

  it('defines the --radius base variable', () => {
    expect(css).toMatch(/--radius:\s*0\.5rem/)
  })
})
