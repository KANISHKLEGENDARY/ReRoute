import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Minimal Vite configuration for React SPA
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true
  }
})
