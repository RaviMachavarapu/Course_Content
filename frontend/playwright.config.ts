import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config (T001 scaffold). Specs land from T011 onward; the Button Inventory
 * (spec.md §6) is exercised here in T042.
 */
export default defineConfig({
  testDir: "./src/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // The Celery worker runs concurrency=2; more Playwright workers than that just
  // pile generation jobs (incl. LibreOffice slide renders) into a backlog and
  // make the ingest→publish specs flaky.
  workers: 2,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "student",
      testMatch: /student-.*\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "admin",
      testMatch: /admin-.*\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
