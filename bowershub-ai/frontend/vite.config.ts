import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:5003',
      '/ws': {
        target: 'ws://localhost:5003',
        ws: true,
      },
    },
  },
})
