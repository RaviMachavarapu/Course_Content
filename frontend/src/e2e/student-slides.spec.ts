import { expect, test } from "@playwright/test";

/**
 * T033 — student slide viewer. Admin publishes a deck (slide_deck + report),
 * a student opens Slides and walks the pages; the last page marks it complete.
 */
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("slide viewer: navigate, notes, complete on last slide", async ({ page }) => {
  test.setTimeout(180_000); // LibreOffice cold start on the worker

  const marker = Date.now();
  const courseTitle = `Slides E2E ${marker}`;

  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN_PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  await page.getByLabel("Source URL").fill(`https://www.youtube.com/watch?v=sld${marker}`);
  await page.getByLabel("Course title").fill(courseTitle);
  await page.getByLabel("Module title").fill("Deck Module");
  for (const t of ["flashcards", "quiz", "infographic", "audio_overview"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);
  // slide rendering runs LibreOffice on the worker — give it room
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 120_000 });
  await page.getByTestId("btn-sr3").click();
  await page.getByTestId("btn-publish-confirm").click();
  await expect(page.locator('[data-status="published"]')).toHaveCount(2);

  await page.getByTestId("btn-ig9").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);

  await page.goto("/register");
  await page.getByLabel("Display name").fill("Deck Learner");
  await page.getByLabel("Email").fill(`deck+${marker}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("deck-strong-1234");
  await page.getByLabel("Confirm password").fill("deck-strong-1234");
  await page.getByTestId("btn-sl1").click();
  await expect(page).toHaveURL(/\/catalog$/);

  await page.locator('[data-testid="course-card"]', { hasText: courseTitle }).getByTestId("btn-ct7").click();
  await expect(page).toHaveURL(/\/learn\/slides-e2e-/);

  // open Slides (BTN-WS4)
  await page.getByTestId("btn-ws4").click();
  await expect(page.getByTestId("slide-image")).toBeVisible();
  await expect(page.getByText(/Slide 1 of \d+/)).toBeVisible();
  await expect(page.getByTestId("btn-sd1")).toBeDisabled(); // Prev gated at start
  await expect(page.getByTestId("btn-sd4")).toHaveAttribute("href", /\/api\/media\/.*\.pptx/);

  // step to the last slide
  const counter = page.getByText(/Slide \d+ of \d+/);
  const total = Number((await counter.textContent())!.match(/of (\d+)/)![1]);
  for (let i = 1; i < total; i++) await page.getByTestId("btn-sd2").click();
  await expect(page.getByText(`Slide ${total} of ${total}`)).toBeVisible();
  await expect(page.getByTestId("btn-sd2")).toBeDisabled(); // Next gated at end

  // completion rolls up — the shell header progress moves off 0%
  // (slides is 1 of 2 published artifacts -> 50%)
  await expect(page.getByText("50% Complete")).toBeVisible({ timeout: 10_000 });

  // Fullscreen control is wired — click last since a real fullscreen element
  // can cover the page and intercept subsequent clicks in headless Chromium.
  await page.getByTestId("btn-sd3").click();
});
