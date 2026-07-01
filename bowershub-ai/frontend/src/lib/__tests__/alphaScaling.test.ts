import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, join } from 'node:path'
import tailwindConfig from '../../../tailwind.config'

/**
 * Design-system Task 1 verification (R1.1 alpha-composable tokens, R1.6 font
 * scaling) at the level jsdom can actually assert: the token→triple mapping,
 * the single-source text scale, and the "no hardcoded font-size" guard.
 *
 * The *rendered* colour-resolution and overflow-at-four-sizes checks the spec
 * also calls for need a real layout engine (Tailwind utilities don't compile in
 * jsdom, and jsdom has no layout) — those ride with the deferred Playwright
 * visual-parity harness (Task 14). These guards pin the mechanism so the alpha
 * fix and the scaling contract can't silently regress in CI.
 */
const colors = (tailwindConfig as any).theme.extend.colors
const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

describe('alpha-composable colour tokens (R1.1)', () => {
  // These are the tint-bearing tokens consumed via `bg-x/<n>` alpha modifiers;
  // each must resolve through its `-rgb` triple so the modifier renders a tint
  // (the pre-fix hex form silently ignored the alpha — the MessageList /
  // SearchOverlay bug).
  const tintable = ['primary', 'accent', 'danger', 'success', 'warning', 'error']

  it.each(tintable)('maps colour "%s" through its -rgb triple with <alpha-value>', (key) => {
    expect(colors[key]).toBe(`rgb(var(--color-${key}-rgb) / <alpha-value>)`)
  })

  it('the two known-broken call-sites now use bg-primary alpha tints', () => {
    const message = readFileSync(resolve(process.cwd(), 'src/components/MessageList.tsx'), 'utf8')
    const search = readFileSync(resolve(process.cwd(), 'src/components/SearchOverlay.tsx'), 'utf8')
    expect(message).toMatch(/bg-primary\/\d/)
    expect(search).toMatch(/bg-primary\/\d/)
  })
})

describe('font scaling is single-sourced on --bh-text-base (R1.6)', () => {
  it('defines --bh-text-base on :root', () => {
    expect(css).toMatch(/--bh-text-base:\s*\d/)
  })

  it('derives every text-* size from --bh-text-base (one knob scales all)', () => {
    for (const cls of ['text-xs', 'text-sm', 'text-base', 'text-lg', 'text-xl', 'text-2xl', 'text-3xl']) {
      const re = new RegExp(`\\.${cls}\\s*\\{[^}]*font-size:\\s*calc\\(var\\(--bh-text-base\\)`)
      expect(css, `${cls} scales off --bh-text-base`).toMatch(re)
    }
  })
})

describe('no hardcoded font-size in primitives/shell (R1.6)', () => {
  function tsxFiles(dir: string): string[] {
    const out: string[] = []
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name)
      if (e.isDirectory()) out.push(...tsxFiles(p))
      else if (/\.tsx?$/.test(e.name)) out.push(p)
    }
    return out
  }

  it('components/ui + components/shell use the text-* scale, never a literal px/rem font-size', () => {
    const dirs = ['src/components/ui', 'src/components/shell'].map((d) => resolve(process.cwd(), d))
    const offenders: string[] = []
    for (const dir of dirs) {
      for (const file of tsxFiles(dir)) {
        const src = readFileSync(file, 'utf8')
        // Tailwind arbitrary font-size (`text-[13px]`/`text-[0.9rem]`) or an
        // inline `fontSize` style — both bypass the scalable text-* contract.
        if (/text-\[[\d.]+(px|rem)\]/.test(src) || /fontSize\s*:/.test(src)) {
          offenders.push(file.replace(resolve(process.cwd()) + '/', ''))
        }
      }
    }
    expect(offenders, `hardcoded font-size in: ${offenders.join(', ')}`).toEqual([])
  })
})
