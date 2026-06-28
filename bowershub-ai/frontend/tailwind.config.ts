import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Theme tokens — backed by CSS custom properties set on :root by
        // App.tsx from `effective_theme.tokens_json`. Defaults live in
        // index.css so the very first paint (before the settings API
        // resolves) uses the Dark Navy preset.
        //
        // Each color reads the DERIVED `--color-<name>-rgb` channel triple
        // (set alongside the hex `--color-<name>` by App.tsx via
        // lib/themeTokens.ts) and is wrapped in `rgb(… / <alpha-value>)` so
        // Tailwind opacity modifiers (`bg-primary/20`, `border-border/40`)
        // compose alpha — which is impossible against a hex-valued var in
        // Tailwind v3. Full-opacity colors are unchanged.
        background: 'rgb(var(--color-background-rgb) / <alpha-value>)',
        surface: {
          DEFAULT: 'rgb(var(--color-surface-rgb) / <alpha-value>)',
          light: 'rgb(var(--color-surface-light-rgb) / <alpha-value>)',
          dark: 'rgb(var(--color-surface-dark-rgb) / <alpha-value>)',
        },
        primary: 'rgb(var(--color-primary-rgb) / <alpha-value>)',
        accent: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
        text: {
          DEFAULT: 'rgb(var(--color-text-rgb) / <alpha-value>)',
          muted: 'rgb(var(--color-text-muted-rgb) / <alpha-value>)',
        },
        border: 'rgb(var(--color-border-rgb) / <alpha-value>)',
        danger: 'rgb(var(--color-danger-rgb) / <alpha-value>)',
        success: 'rgb(var(--color-success-rgb) / <alpha-value>)',
        warning: 'rgb(var(--color-warning-rgb) / <alpha-value>)',
        error: 'rgb(var(--color-error-rgb) / <alpha-value>)',

        // Foreground aliases (R1.3): readable text/icon color per surface.
        'on-background': 'rgb(var(--color-on-background-rgb) / <alpha-value>)',
        'on-surface': 'rgb(var(--color-on-surface-rgb) / <alpha-value>)',
        'on-muted': 'rgb(var(--color-on-muted-rgb) / <alpha-value>)',
        'on-primary': 'rgb(var(--color-on-primary-rgb) / <alpha-value>)',
        'on-accent': 'rgb(var(--color-on-accent-rgb) / <alpha-value>)',
        'on-danger': 'rgb(var(--color-on-danger-rgb) / <alpha-value>)',
        'on-success': 'rgb(var(--color-on-success-rgb) / <alpha-value>)',
        'on-warning': 'rgb(var(--color-on-warning-rgb) / <alpha-value>)',
        'on-error': 'rgb(var(--color-on-error-rgb) / <alpha-value>)',
      },

      // ---- Non-color design scales (R1.5) -------------------------------
      // Code-level design constants (NOT user-facing config / DB rows) — the
      // dimensions the app lacked, applied consistently by the primitives so
      // call-sites inherit a coherent rhythm. Distinct from the DB-driven
      // *color* tokens above.

      // Single-knob radius family off `--radius` (index.css). shadcn-pattern,
      // so vendored components inherit it. Chosen so lg/md/xl match the prior
      // Tailwind defaults (8/6/12px); only `sm` shifts 2px→4px (imperceptible).
      borderRadius: {
        sm: 'calc(var(--radius) - 4px)',
        md: 'calc(var(--radius) - 2px)',
        lg: 'var(--radius)',
        xl: 'calc(var(--radius) + 4px)',
      },

      // Elevation scale — additive new keys (shadow-elevation-1..4).
      boxShadow: {
        'elevation-1': '0 1px 2px 0 rgb(0 0 0 / 0.06)',
        'elevation-2': '0 2px 8px -2px rgb(0 0 0 / 0.12)',
        'elevation-3': '0 8px 24px -4px rgb(0 0 0 / 0.18)',
        'elevation-4': '0 16px 48px -8px rgb(0 0 0 / 0.28)',
      },

      // Motion tokens — paired with the prefers-reduced-motion collapse in
      // index.css (durations there go to ~0).
      transitionDuration: {
        fast: '120ms',
        base: '200ms',
        slow: '320ms',
      },
      transitionTimingFunction: {
        standard: 'cubic-bezier(0.2, 0, 0, 1)',
        emphasized: 'cubic-bezier(0.3, 0, 0, 1)',
      },

      // Named layering scale — replaces the scattered z-[9999]/z-[10000]/
      // z-[998]/z-30/z-50 free-for-all. base < shell chrome < portals
      // (dropdown/popover/tooltip) < modals/dialogs < toasts.
      zIndex: {
        base: '0',
        shell: '30',
        dropdown: '40',
        modal: '50',
        toast: '60',
      },

      // Note: `tabular-nums` for monetary/figure alignment is a built-in
      // Tailwind utility (fontVariantNumeric) — no config needed; primitives
      // and finance figure displays apply it directly.

      // Enter animations for the Sheet/drawer (Radix mounts content already-open,
      // so these play on open; close unmounts without an exit animation). Honors
      // the prefers-reduced-motion collapse in index.css.
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-in-left': {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
        'slide-in-right': {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 150ms cubic-bezier(0.2, 0, 0, 1)',
        'slide-in-left': 'slide-in-left 200ms cubic-bezier(0.2, 0, 0, 1)',
        'slide-in-right': 'slide-in-right 200ms cubic-bezier(0.2, 0, 0, 1)',
      },
    },
  },
  plugins: [],
} satisfies Config
