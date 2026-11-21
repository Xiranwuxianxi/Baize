import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 开发模式下把接口转发给后端；生产模式由后端直接托管 dist
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 18761,
    proxy: {
      '/api': 'http://127.0.0.1:18760',
      '/ws': { target: 'ws://127.0.0.1:18760', ws: true },
    },
  },
})
