import { expect, test } from "@playwright/test";

/**
 * T025 — Ingestion Portal. Requires the stack up + a seeded admin.
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

async function login(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
}

test("admin ingests a new source and lands on staging", async ({ page }) => {
  await login(page);

  await expect(page.getByText(/NotebookLM: (Connected|Disconnected|Fixture \(dev\))/)).toBeVisible();

  const unique = `E2E Course ${Date.now()}`;
  await page.getByLabel("Source URL").fill("https://www.youtube.com/watch?v=e2e");
  await page.getByLabel("Course title").fill(unique);
  await page.getByLabel("Module title").fill("E2E Module");
  // keep all six artifact types checked (default)
  await page.getByTestId("btn-ig6").click();

  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);
});

test("invalid source URL blocks submission", async ({ page }) => {
  await login(page);
  await page.getByLabel("Source URL").fill("not a url");
  await page.getByLabel("Course title").fill("x");
  await page.getByLabel("Module title").fill("x");
  await page.getByTestId("btn-ig6").click();
  await expect(page.getByText(/valid http\(s\) URL/i)).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
});
