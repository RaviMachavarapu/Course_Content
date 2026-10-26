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
  await expect(page.getByText("sample.pdf")).toBeVisible();

  await page.getByLabel("Course title").fill(`PDF E2E ${Date.now()}`);
  await page.getByLabel("Module title").fill("PDF Module");
  // fast fixture types only
  for (const t of ["slide_deck", "infographic"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  await page.getByTestId("btn-ig6").click();

  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/, { timeout: 30_000 });
  await expect(page.getByText("📄 1 PDF")).toBeVisible();

  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Redo Report" })).toBeVisible();
});
