import { defineConfig } from 'vite';

// Build output goes to /dist and is copied into the nginx runtime stage of the
// Dockerfile. `base: '/'` because the SPA is always served from the domain root.
export default defineConfig({
  base: '/',
  build: {
    outDir: 'dist',
    sourcemap: true,
    // Deterministic-ish output keeps image layers small between builds.
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // Local dev only: in-cluster the nginx runtime proxies /api instead.
      '/api': {
        target: process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.js'],
  },
});
