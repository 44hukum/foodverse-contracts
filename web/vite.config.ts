/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The repo-root .env (written by scripts/worktree-init.sh) carries
// VITE_API_BASE_URL and WEB_PORT; only VITE_-prefixed values reach the browser.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  envDir: '..',
  server: {
    port: Number(process.env['WEB_PORT'] ?? 5173),
    strictPort: false,
  },
  define: {
    // `npm run dev:mock` runs Vite in mode "mock" and boots the MSW worker.
    __API_MOCK__: JSON.stringify(mode === 'mock'),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
  },
}));
