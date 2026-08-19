import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    include: ['react-pdf'],
  },
  // pdf.js worker 以经典脚本（iife）形式打包，避免在禁止 module Worker 的受限环境中加载失败
  worker: {
    format: 'iife',
  },
})
