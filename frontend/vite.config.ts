import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000' },
    fs: { allow: ['..'] }, // 允许引入仓库根目录 design/tokens.css
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
