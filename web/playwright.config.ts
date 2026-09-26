import { defineConfig } from '@playwright/test';

// Runs the web app in mock mode (MSW in the browser, no backend) and drives
// the signing page in a real Chromium at phone width. Not part of
// scripts/check.sh: run `npx playwright install chromium` once, then
// `npm run test:e2e`.
const PORT = 4173;
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: 0,
  reporter: 'list',
  timeout: 30_000,
  use: {
    baseURL: BASE_URL,
    viewport: { width: 375, height: 812 },
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: `npm run dev:mock -- --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env['CI'],
    timeout: 60_000,
  },
});
