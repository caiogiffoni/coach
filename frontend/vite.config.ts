import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Default: backend on :8000. API_PROXY_TARGET overrides for local smoke tests.
      '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
    },
  },
})
