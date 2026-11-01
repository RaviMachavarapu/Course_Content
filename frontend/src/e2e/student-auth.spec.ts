import { expect, test } from "@playwright/test";
import { uniqueMarker } from "./unique";

/**
 * T011 happy path — register a brand-new student and land on the catalog.
 * Requires the full stack up (`docker compose up`), served at E2E_BASE_URL
 * (default http://localhost:5173).
 */
test("student can register and reach the catalog", async ({ page }) => {
  const email = `e2e+${uniqueMarker()}@example.com`;

  await page.goto("/register");
  await page.getByLabel("Display name").fill("E2E Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("e2e-strong-pw-1234");
  await page.getByLabel("Confirm password").fill("e2e-strong-pw-1234");
  await page.getByTestId("btn-sl1").click();

  await expect(page).toHaveURL(/\/catalog$/);
  await expect(page.getByRole("heading", { name: "Course Catalogs", level: 1 })).toBeVisible();
});

test("login page exposes the register and forgot-password links", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByTestId("btn-sl2")).toBeVisible();
  await expect(page.getByTestId("btn-sl3")).toBeVisible();
  await expect(page.getByTestId("btn-sl4")).toBeVisible();
});
