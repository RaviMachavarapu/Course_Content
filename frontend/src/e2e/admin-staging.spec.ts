import { expect, test } from "@playwright/test";
import { uniqueMarker } from "./unique";

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
  await page.getByLabel("Course title").fill(`Staging E2E ${uniqueMarker()}`);
  await page.getByLabel("Module title").fill("Staging Module");
  for (const t of ["slide_deck", "infographic"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);

  // wait for the four requested cards to reach a resolved state
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 30_000 });
  // Redo is disabled while a card generates: all six enabled = nothing in flight
  await expect(page.locator('[data-testid="btn-sr4"]:enabled')).toHaveCount(6);

  // Report card: redo with an instruction
  await page.getByRole("button", { name: "Redo Report" }).click();
  await page.getByRole("textbox").fill("Trim to one page");
  await page.getByTestId("btn-sr7").click();

  // the Report card settles on rev 2 and no other card regenerates. (The
  // fixture provider can finish a redo before the next staging poll, so the
  // transient "Generating…" state is not asserted.)
  const reportCard = page.getByRole("button", { name: "Redo Report" }).locator("xpath=../..");
  await expect(reportCard.getByText("rev 2")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText(/^rev \d+$/)).toHaveCount(1);

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
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="published"]')).toHaveCount(
    4,
  );
});
