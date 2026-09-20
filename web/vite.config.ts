import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发模式：/ws 与 /healthz 代理到本地 FastAPI（8000）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/ws': { target: 'http://localhost:8000', ws: true },
      '/healthz': 'http://localhost:8000',
    },
  },
})
