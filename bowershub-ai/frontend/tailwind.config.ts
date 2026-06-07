import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Theme tokens — backed by CSS custom properties set on :root by
        // the settings store from `effective_theme.tokens_json`.
        // Defaults live in index.css so the very first paint (before the
        // settings API resolves) uses the Dark Navy preset.
        background: 'var(--color-background)',
        surface: {
          DEFAULT: 'var(--color-surface)',
          light: 'var(--color-surface-light)',
          dark: 'var(--color-surface-dark)',
        },
        primary: 'var(--color-primary)',
        accent: 'var(--color-accent)',
        text: {
          DEFAULT: 'var(--color-text)',
          muted: 'var(--color-text-muted)',
        },
        border: 'var(--color-border)',
        danger: 'var(--color-danger)',
        success: 'var(--color-success)',

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
