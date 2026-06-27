import { describe, it, expect } from 'vitest'
import { hexToTriple, setColorVar, RGB_VAR_SUFFIX } from '../themeTokens'

describe('hexToTriple', () => {
  it('converts 6-digit hex to a space-separated channel triple', () => {
    expect(hexToTriple('#6366f1')).toBe('99 102 241')
    expect(hexToTriple('6366f1')).toBe('99 102 241') // no leading #
    expect(hexToTriple('#EF4444')).toBe('239 68 68') // uppercase
  })

  it('expands 3-digit shorthand', () => {
    expect(hexToTriple('#fff')).toBe('255 255 255')
    expect(hexToTriple('#000')).toBe('0 0 0')
    expect(hexToTriple('abc')).toBe('170 187 204')
  })

  it('preserves the full-opacity color (the Dark Navy preset round-trips)', () => {
    // These triples are what `rgb(<triple> / 1)` must equal the original hex.
    expect(hexToTriple('#0f0f1a')).toBe('15 15 26')
    expect(hexToTriple('#1a1a2e')).toBe('26 26 46')
    expect(hexToTriple('#94a3b8')).toBe('148 163 184')
    expect(hexToTriple('#22c55e')).toBe('34 197 94')
  })

  it('returns null for values that are not parseable hex', () => {
    expect(hexToTriple('red')).toBeNull()
    expect(hexToTriple('rgb(1, 2, 3)')).toBeNull()
    expect(hexToTriple('#12')).toBeNull()
    expect(hexToTriple('#zzzzzz')).toBeNull()
    expect(hexToTriple('')).toBeNull()
    // @ts-expect-error — guards against non-string input at runtime
    expect(hexToTriple(undefined)).toBeNull()
  })
})

describe('setColorVar', () => {
  function fakeEl() {
    const props = new Map<string, string>()
    return {
      props,
      el: { style: { setProperty: (n: string, v: string) => void props.set(n, v) } },
    }
  }

  it('sets both the full-color var (for inline/CSS consumers) and the derived -rgb triple (for Tailwind alpha)', () => {
    const { props, el } = fakeEl()
    setColorVar(el, '--color-primary', '#6366f1')
    expect(props.get('--color-primary')).toBe('#6366f1')
    expect(props.get(`--color-primary${RGB_VAR_SUFFIX}`)).toBe('99 102 241')
  })

  it('sets only the full-color var when the value is not hex (so direct consumers keep working, no invalid -rgb)', () => {
    const { props, el } = fakeEl()
    setColorVar(el, '--color-accent', 'currentColor')
    expect(props.get('--color-accent')).toBe('currentColor')
    expect(props.has(`--color-accent${RGB_VAR_SUFFIX}`)).toBe(false)
  })
})
