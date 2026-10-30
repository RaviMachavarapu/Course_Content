import { expect, test } from "@playwright/test";
import { courseSlug } from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * T042 / spec.md §7 AC5 — the full student flow, scripted end-to-end in one
 * pass under `FixtureProvider`:
 *   register -> catalog -> consume all six -> progress reflected.
 *
 * Deep per-button interaction with each artifact type already lives in
 * student-catalog.spec.ts (5 types) and student-slides.spec.ts (slides); this
 * spec's job is narrower and literal — prove a single course publishing all
 * six types can be opened end-to-end by a brand-new student and that
 * completing it is reflected on /progress.
 */
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("AC5: register -> catalog -> consume all six -> progress reflected", async ({ page }) => {
  test.setTimeout(180_000); // slide_deck's LibreOffice cold start on the worker

  const marker = uniqueMarker();
  const courseTitle = `AC5 Acceptance ${marker}`;

  // --- admin: publish a course with all six artifact types ---
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN_PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  await page.getByLabel("Link (optional)").fill(`https://www.youtube.com/watch?v=ac5${marker}`);
  await page.getByLabel("Course title").fill(courseTitle);
  await page.getByLabel("Module title").fill("AC5 Module");
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 150_000 });

  await page.getByTestId("btn-sr3").click();
  await page.getByTestId("btn-publish-confirm").click();
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="published"]')).toHaveCount(
    6,
  );

  await page.getByTestId("btn-ig9").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);

  // --- student: register + browse ---
  await page.goto("/register");
  await page.getByLabel("Display name").fill("AC5 Student");
  await page.getByLabel("Email").fill(`ac5+${marker}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("ac5-strong-pw-1234");
  await page.getByLabel("Confirm password").fill("ac5-strong-pw-1234");
  await page.getByTestId("btn-sl1").click();
  await expect(page).toHaveURL(/\/catalog$/);

  await page.goto(`/learn/${await courseSlug(page.context(), courseTitle)}`);
  await expect(page).toHaveURL(/\/learn\//);

  // consume all six — a light touch per type (real per-button depth lives
  // elsewhere): open it and confirm its viewer actually rendered.
  await page.getByTestId("btn-ws3").click(); // Audio
  await expect(page.getByTestId("btn-au1")).toBeVisible();

  await page.getByTestId("btn-ws4").click(); // Slides
  await expect(page.getByTestId("slide-image")).toBeVisible();

  await page.getByTestId("btn-ws5").click(); // Flashcards
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();

  await page.getByTestId("btn-ws6").click(); // Quiz
  await expect(page.getByText(/Question 1 of \d+/)).toBeVisible();

  await page.getByTestId("btn-ws7").click(); // Infographic
  await expect(page.getByTestId("infographic-image")).toBeVisible();

  await page.getByTestId("btn-ws8").click(); // Report
  await expect(page.getByText(/\d+ min read/)).toBeVisible();

  // Complete Module (from the report) rolls the whole module up to 100%
  await page.getByTestId("btn-rp2").click();
  await expect(page.getByText("100% Complete")).toBeVisible();

  // progress reflected in the student's record
  // the Progress page lists no courses (owner, 2026-10-30): the record is checked in the API
  await expect
    .poll(async () => {
      const r = await page.request.get("/api/student/me/progress");
      const { courses } = (await r.json()) as {
        courses: { title: string; percent_complete: number }[];
      };
      return courses.find((c) => c.title === courseTitle)?.percent_complete;
    })
    .toBe(100);
});
