import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: `npm run dev` proxies the API to the Flask server (python -m app.web, port 5050).
// Prod: `npm run build` writes web/dist, which Flask serves.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  build: { chunkSizeWarningLimit: 1000 },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5050',
      '/uploads': 'http://127.0.0.1:5050',
      '/outputs': 'http://127.0.0.1:5050',
    },
  },
})
