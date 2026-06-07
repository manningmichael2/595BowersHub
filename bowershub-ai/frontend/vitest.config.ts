import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * Vitest config — kept separate from `vite.config.ts` so the dev server
 * config (proxy, etc.) doesn't leak into test runs and vice versa.
 *
 * jsdom gives us a `document`, `window`, `localStorage`, etc., which the
 * settings store + theme application logic touches directly.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
  },
})
