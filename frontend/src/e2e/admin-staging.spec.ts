import { expect, test } from "@playwright/test";

/**
 * T026 — Staging Review + Inspect. Requires the stack + a seeded admin.
 * Ingests a fresh module, waits for it to settle, redoes one artifact, and
 * asserts only that artifact regenerated (a new revision, siblings untouched).
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("redo regenerates only the chosen artifact", async ({ page }) => {
  test.slow();

  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  // ingest with only the fast fixture types
  await page.getByLabel("Link (optional)").fill("https://www.youtube.com/watch?v=stg");
  await page.getByLabel("Course title").fill(`Staging E2E ${Date.now()}`);
  await page.getByLabel("Module title").fill("Staging Module");
  for (const t of ["slide_deck", "infographic"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);

  // wait for the four requested cards to reach a resolved state
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 30_000 });

  // Report card: redo with an instruction
  await page.getByRole("button", { name: "Redo Report" }).click();
  await page.getByRole("textbox").fill("Trim to one page");
  await page.getByTestId("btn-sr7").click();

  // it flips to Generating, the others do not
  await expect(page.getByText("Generating…")).toHaveCount(1);

  // after it settles, the Report card shows rev 2
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText("rev 2")).toBeVisible();

  // Inspect the report → version history has two entries, redo note stored
  await page
    .getByRole("button", { name: "Redo Report" })
    .locator("xpath=../..")
    .getByTestId("btn-sr5")
    .click();
  await expect(page).toHaveURL(/\/admin\/artifacts\/[0-9a-f-]+$/);
  await expect(page.getByTestId("btn-ai1")).toContainText("rev 2");
  await expect(page.getByText("Trim to one page").first()).toBeVisible();

  // back to staging and publish the module
  await page.getByTestId("btn-ai2").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);
  await page.getByTestId("btn-sr3").click();
  await expect(page.getByText(/Will publish \(4\)/)).toBeVisible();
  await expect(page.getByText(/Skipped \(2\)/)).toBeVisible();
  await page.getByTestId("btn-publish-confirm").click();

  // the four ready cards now show the Published chip
  await expect(page.locator('[data-status="published"]')).toHaveCount(4);
});
