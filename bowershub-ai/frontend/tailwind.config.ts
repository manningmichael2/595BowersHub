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
        'on-primary': 'rgb(var(--color-on-primary-rgb) / <alpha-value>)',
        text: {
          DEFAULT: 'rgb(var(--color-text-rgb) / <alpha-value>)',
          muted: 'rgb(var(--color-text-muted-rgb) / <alpha-value>)',
        },
        border: 'rgb(var(--color-border-rgb) / <alpha-value>)',
        danger: 'rgb(var(--color-danger-rgb) / <alpha-value>)',
        success: 'rgb(var(--color-success-rgb) / <alpha-value>)',

        // Existing palette retained for backward compat with components
        // written before the token system. New code should prefer the
        // tokenized colors above.
        brand: {
          50: '#e8eaf6',
          100: '#c5cae9',
          200: '#9fa8da',
          300: '#7986cb',
          400: '#5c6bc0',
          500: '#3f51b5',
          600: '#3949ab',
          700: '#303f9f',
          800: '#283593',
          900: '#1a237e',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
