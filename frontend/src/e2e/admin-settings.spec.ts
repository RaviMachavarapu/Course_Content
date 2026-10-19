import { expect, test } from "@playwright/test";

/**
 * T029 — Settings (A4). Requires the stack + a seeded admin.
 * Edits a generation prompt (new version), then adds and deactivates an admin.
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("edit a prompt version and manage admins", async ({ page }) => {
  test.slow();

  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  await page.goto("/admin/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

  // Generation Prompts — bump the Quiz prompt to a new version
  const quizCard = page
    .locator("div")
    .filter({ has: page.getByRole("heading", { name: "Quiz", exact: true }) })
    .last();
  const versionLabel = quizCard.getByText(/^v\d+ · updated/);
  const startVersion = Number((await versionLabel.textContent())!.match(/v(\d+)/)![1]);

  const quizBox = page.getByLabel("Quiz prompt");
  await quizBox.fill(`${await quizBox.inputValue()}\nExtra guidance ${Date.now()}`);
  await page.getByTestId("btn-st1-quiz").click();

  // the persisted version label bumps (more robust than the transient toast)
  await expect
    .poll(async () => Number((await versionLabel.textContent())!.match(/v(\d+)/)![1]))
    .toBeGreaterThan(startVersion);

  // NotebookLM tab renders the connection card
  await page.getByRole("tab", { name: "NotebookLM" }).click();
  await expect(page.getByTestId("btn-st3")).toBeVisible();

  // Users tab — add an admin, then deactivate it
  await page.getByRole("tab", { name: "Users" }).click();
  const newEmail = `e2e-admin-${Date.now()}@example.com`;
  await page.getByTestId("btn-st5").click();
  await page.getByLabel("Email").fill(newEmail);
  await page.getByLabel("Display name").fill("E2E Admin");
  await page.getByLabel("Temporary password").fill("e2e-temp-pass-9999");
  await page.getByTestId("btn-st5-confirm").click();

  const row = page.locator("tr", { hasText: newEmail });
  await expect(row).toBeVisible();
  await expect(row.getByRole("cell", { name: "Active" })).toBeVisible();

  await row.getByRole("button", { name: "Deactivate" }).click();
  await expect(row.getByRole("cell", { name: "Deactivated" })).toBeVisible();

  // self row cannot be deactivated
  const selfRow = page.locator("tr", { hasText: EMAIL });
  await expect(selfRow.getByRole("button", { name: "Deactivate" })).toBeDisabled();
});
