import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

/**
 * PDF-only module: no link, one uploaded PDF. Requires the stack running with
 * CONTENT_PROVIDER=fixture (never run against live NotebookLM) + a seeded admin.
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";
const SAMPLE = fileURLToPath(new URL("./fixtures/sample.pdf", import.meta.url));

test("admin creates a PDF-only module and artifacts become ready", async ({ page }) => {
  test.slow();

  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  await page.getByLabel("PDF files").setInputFiles(SAMPLE);
  const row = page.getByRole("listitem").filter({ hasText: "sample.pdf" });
  await expect(row).toBeVisible();
  // upload finished: the row has no progress bar and no error/retry
  await expect(row.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(row.getByRole("progressbar")).toHaveCount(0, { timeout: 30_000 });

  await page.getByLabel("Course title").fill(`PDF E2E ${Date.now()}`);
  await page.getByLabel("Module title").fill("PDF Module");
  // fast fixture types only: uncheck everything except the ones asserted below
  const wanted = ["flashcards", "quiz", "report"];
  for (const t of ["slide_deck", "infographic", "audio_overview"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  for (const t of wanted) await expect(page.getByTestId(`type-${t}`)).toBeChecked();
  await page.getByTestId("btn-ig6").click();

  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/, { timeout: 30_000 });
  await expect(page.getByText("📄 1 PDF")).toBeVisible();

  // every selected card reaches the Ready chip; none errors
  // (the Ready chip is a span with data-status="ready"; its text includes the icon name)
  const ready = page.locator('[data-status="ready"]');
  await expect(ready).toHaveCount(wanted.length, { timeout: 60_000 });
  for (const chip of await ready.all()) await expect(chip).toContainText(/ready/i);
  await expect(page.locator('[data-status="error"]')).toHaveCount(0);
  await expect(page.getByText("Generating…")).toHaveCount(0);
  await expect(page.getByText("Generation failed.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
});
