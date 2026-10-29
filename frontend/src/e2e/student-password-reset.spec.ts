import { expect, test } from "@playwright/test";
import { resetLinkFor } from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * O6 — password reset, driven end-to-end through the real UI and the real
 * mailhog inbox (its REST API, exposed on the host at :8025), mirroring the
 * approach in `backend/tests/integration/test_password_reset.py`. Not a
 * mocked mailer: this proves the actual email with a working link is sent
 * and that the link's form actually resets the password.
 */
test("student can request and complete a real password reset", async ({ page }) => {
  const email = `e2e+reset${uniqueMarker()}@example.com`;
  const oldPassword = "e2e-old-strong-pw-1";
  const newPassword = "e2e-new-strong-pw-2";

  await page.goto("/register");
  await page.getByLabel("Display name").fill("Reset Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(oldPassword);
  await page.getByLabel("Confirm password").fill(oldPassword);
  await page.getByTestId("btn-sl1").click();
  await expect(page).toHaveURL(/\/catalog$/);

  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByTestId("btn-sl3").click();
  await expect(page).toHaveURL(/\/forgot-password$/);

  await page.getByLabel("Email").fill(email);
  await page.getByTestId("btn-fp1").click();
  await expect(page.getByText(/check your email/i)).toBeVisible();

  await page.goto(await resetLinkFor(email));

  await page.getByLabel("New password").fill(newPassword);
  await page.getByLabel("Confirm password").fill(newPassword);
  await page.getByTestId("btn-reset-confirm").click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(oldPassword);
  await page.getByTestId("btn-sl2").click();
  await expect(page.getByRole("alert")).toBeVisible();

  await page.getByLabel("Password").fill(newPassword);
  await page.getByTestId("btn-sl2").click();
  await expect(page).toHaveURL(/\/catalog$/);
});
