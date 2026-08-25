import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { honeylog } from './vite-plugins/honeylog';

export default defineConfig({
  plugins: [react(), honeylog()],
  server: {
    host: true,
    port: 5173,
    watch: { usePolling: true, interval: 300 },
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});