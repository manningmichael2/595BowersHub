/**
 * Global test setup (registered via vitest.config.ts `setupFiles`).
 *
 * jsdom is missing a handful of DOM APIs that our component tree relies on:
 *  - ResizeObserver — react-grid-layout's WidthProvider calls it on mount.
 *  - matchMedia — the shell's `useBreakpoint` and Radix primitives read it
 *    (R2.7: tests mock it true/false to drive both responsive branches; jsdom
 *    has no implementation at all, so without this it throws).
 *  - Pointer-capture + scrollIntoView — Radix Select/DropdownMenu/Dialog call
 *    these on interaction; jsdom stubs them out as no-ops.
 */

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!(globalThis as any).ResizeObserver) {
  ;(globalThis as any).ResizeObserver = ResizeObserverStub
}

/**
 * matchMedia stub. Defaults to `matches: false` (mobile-first / the desktop
 * media query is false → mobile branch is the jsdom default). Tests override
 * `window.matchMedia` per-case to drive the other branch. Exposed as a helper
 * so component tests can set a deterministic viewport.
 */
export function setMatchMedia(matches: boolean) {
  ;(window as any).matchMedia = (query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })
}

if (!window.matchMedia) {
  setMatchMedia(false)
}

// Radix interaction shims (no-ops are sufficient for jsdom).
if (!(Element.prototype as any).hasPointerCapture) {
  ;(Element.prototype as any).hasPointerCapture = () => false
  ;(Element.prototype as any).setPointerCapture = () => {}
  ;(Element.prototype as any).releasePointerCapture = () => {}
}
if (!(Element.prototype as any).scrollIntoView) {
  ;(Element.prototype as any).scrollIntoView = () => {}
}
