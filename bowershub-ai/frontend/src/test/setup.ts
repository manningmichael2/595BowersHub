/**
 * Global test setup (registered via vitest.config.ts `setupFiles`).
 *
 * jsdom does not implement ResizeObserver, which react-grid-layout's
 * WidthProvider calls on mount. Without a polyfill, mounting the dashboard
 * grid throws "ResizeObserver is not defined" during the passive-effect phase.
 */

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!(globalThis as any).ResizeObserver) {
  ;(globalThis as any).ResizeObserver = ResizeObserverStub
}
