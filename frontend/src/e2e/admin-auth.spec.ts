import { expect, test } from "@playwright/test";

/**
 * T012 — admin login + route protection. Requires the stack up and a seeded
 * admin. Provide credentials via env:
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD
 * (defaults match the account seeded during development).
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("anonymous visit to /admin/* redirects to the admin login", async ({ page }) => {
  await page.goto("/admin/review");
  await expect(page).toHaveURL(/\/admin\/login$/);
  await expect(page.getByTestId("btn-al1")).toBeVisible();
});

test("admin can sign in and land on ingestion", async ({ page }) => {
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  await expect(page.getByRole("heading", { name: "Ingestion", level: 1 })).toBeVisible();
});

test("a student is blocked from /admin/* with a student 404 (US-N3)", async ({ page }) => {
  // sign in as a fresh student
  const email = `e2e+adm${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Blocked Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("e2e-strong-pw-1234");
  await page.getByLabel("Confirm password").fill("e2e-strong-pw-1234");
  await page.getByTestId("btn-sl1").click();
  await expect(page).toHaveURL(/\/catalog$/);

  await page.goto("/admin/anything");
  await expect(page.getByText(/page not found/i)).toBeVisible();
  await expect(page).not.toHaveURL(/\/admin\/login$/);
  await expect(page.getByTestId("btn-al1")).toHaveCount(0);
});
