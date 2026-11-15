import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests (I-3) against the real API, offline: fake models (LLM_MODE=fake), fixture transcript, and a
 * throwaway database that e2e/api_server.py creates from supabase/migrations and drops afterwards.
 * Ports 3010 / 8010 so the usual dev servers on 3000 / 8000 keep running. Run with `make e2e` or `pnpm test:e2e`.
 */
import { API_PORT, API_URL, WEB_PORT, WEB_URL } from "./e2e/ports";

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  // One lecture pipeline at a time keeps the shared API (and its single job worker) predictable.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // `next dev` compiles each page on first visit, which can take a while on a cold start.
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: WEB_URL,
    navigationTimeout: 60_000,
    actionTimeout: 20_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 1000 } } }],
  webServer: [
    {
      command: `uv run --project ../server python e2e/api_server.py --port ${API_PORT} --web-origin ${WEB_URL}`,
      url: `${API_URL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      gracefulShutdown: { signal: "SIGINT", timeout: 15_000 },
    },
    {
      command: `pnpm exec next dev --port ${WEB_PORT}`,
      url: `${WEB_URL}/login`,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_API_MODE: "live",
        NEXT_PUBLIC_API_URL: API_URL,
        NEXT_DIST_DIR: ".next-e2e",
      },
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
  ],
});
