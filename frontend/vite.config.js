import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true
      }
    },
    watch: {
      // Editors and formatters that save through short-lived dot-directories inside
      // src/ make chokidar fail with EBUSY on Windows, which kills the dev server.
      ignored: ['**/.*.tmpdir/**', '**/*.tmp'],
    },
  }
})