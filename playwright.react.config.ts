import { defineConfig } from '@playwright/test';

// Tests for the React frontend (frontend/). The FastAPI backend is mocked
// per-test with page.route, so only the Vite dev server is needed.
export default defineConfig({
  testDir: './tests/react',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
  },
  webServer: {
    command: 'npm --prefix frontend run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
