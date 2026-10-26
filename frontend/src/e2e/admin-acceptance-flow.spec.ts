import { expect, test } from "@playwright/test";

/**
 * T042 / spec.md §7 AC4 — the full admin flow, scripted end-to-end in one
 * pass under `FixtureProvider`:
 *   ingest -> 6 generated -> redo one -> publish module -> publish course.
 *
 * Requires the stack up + a seeded admin (E2E_ADMIN_EMAIL/PASSWORD).
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("AC4: ingest -> 6 generated -> redo one -> publish module -> publish course", async ({
  page,
}) => {
  test.setTimeout(240_000); // slide_deck's LibreOffice cold start + a second module

  const courseTitle = `AC4 Acceptance ${Date.now()}`;

  // --- ingest, all six artifact types (default selection) ---
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  await page.getByLabel("Link (optional)").fill(`https://www.youtube.com/watch?v=ac4${Date.now()}`);
  await page.getByLabel("Course title").fill(courseTitle);
  await page.getByLabel("Module title").fill("AC4 Module");
  // all six ARTIFACT_TYPES checkboxes are checked by default — leave them
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);

  // --- 6 generated ---
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 150_000 });
  await expect(page.getByTestId("btn-sr4")).toHaveCount(6); // one Redo button per resolved card

  // --- redo one (Report, with a note) ---
  await page.getByRole("button", { name: "Redo Report" }).click();
  await page.getByRole("textbox").fill("Trim to one page");
  await page.getByTestId("btn-sr7").click();
  await expect(page.getByText("Generating…")).toHaveCount(1);
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText("rev 2")).toBeVisible();

  // --- publish module ---
  await page.getByTestId("btn-sr3").click();
  await expect(page.getByRole("heading", { name: "Publish module" })).toBeVisible();
  await page.getByTestId("btn-publish-confirm").click();
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="published"]')).toHaveCount(6);

  // --- add a second module (report only, for speed) so "publish course"
  // has something of its own left to do beyond the already-published first
  // module (with only one module, "Publish Complete Course" is correctly
  // disabled once nothing is left `ready`) ---
  await page.goto("/admin/editor");
  await page.getByRole("link", { name: courseTitle }).click();
  await expect(page).toHaveURL(/\/admin\/editor\/[0-9a-f-]+$/);
  await page.getByTestId("btn-ce1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion\?course=[0-9a-f-]+$/);

  await page.getByLabel("Link (optional)").fill(`https://www.youtube.com/watch?v=ac4b${Date.now()}`);
  await page.getByLabel("Module title").fill("AC4 Module 2");
  for (const t of ["slide_deck", "flashcards", "quiz", "infographic", "audio_overview"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 30_000 });

  // --- publish complete course: catches module 2's ready report too ---
  await page.getByTestId("btn-sr2").click();
  await expect(page.getByRole("heading", { name: "Publish complete course" })).toBeVisible();
  await expect(page.getByText(/Will publish \(1\)/)).toBeVisible();
  await page.getByTestId("btn-publish-confirm").click();
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="published"]')).toHaveCount(1);

  // the course is now visible, published, to a student
  await page.getByTestId("btn-ig9").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);

  await page.goto("/register");
  await page.getByLabel("Display name").fill("AC4 Checker");
  await page.getByLabel("Email").fill(`ac4+${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("ac4-strong-pw-1234");
  await page.getByLabel("Confirm password").fill("ac4-strong-pw-1234");
  await page.getByTestId("btn-sl1").click();
  await expect(page).toHaveURL(/\/catalog$/);
  await expect(
    page.locator('[data-testid="course-card"]', { hasText: courseTitle }),
  ).toBeVisible();
});
