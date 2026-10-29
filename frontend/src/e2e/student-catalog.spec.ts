import { type Page, expect, test } from "@playwright/test";
import { uniqueMarker } from "./unique";

/**
 * Walk an adaptive quiz from question 1: answer (option A, or "x" for a
 * fill-in), Check, see the feedback, then Next — and Finish on the last.
 * `revisitFirst` also goes back to Q1 after Q2 opens (feedback is kept).
 */
async function answerAllQuestions(
  page: Page,
  total: number,
  { revisitFirst = false }: { revisitFirst?: boolean } = {},
): Promise<void> {
  for (let i = 0; i < total; i++) {
    await expect(page.getByText(`Question ${i + 1} of ${total}`)).toBeVisible();
    const fill = page.getByTestId("quiz-fill-input");
    if (await fill.isVisible()) await fill.fill("x");
    else await page.getByTestId("btn-qz1-0").click();
    await page.getByTestId("btn-qz8").click(); // Check
    await expect(page.getByTestId("quiz-feedback")).toBeVisible();
    await expect(page.getByText(`${i + 1}/${total} checked`)).toBeVisible();
    if (i === total - 1) {
      await page.getByTestId("btn-qz4").click(); // Finish
      return;
    }
    await page.getByTestId("btn-qz3").click(); // Next
    if (i === 0 && revisitFirst) {
      await expect(page.getByText(`Question 2 of ${total}`)).toBeVisible();
      await page.getByTestId("btn-qz2").click(); // Previous: Q1 keeps its feedback
      await expect(page.getByText(`Question 1 of ${total}`)).toBeVisible();
      await expect(page.getByTestId("quiz-feedback")).toBeVisible();
      await page.getByTestId("btn-qz3").click();
    }
  }
}

/**
 * T031 — student catalog. Publishes a course as admin, then views it as a
 * freshly registered student: search + category filter + Start Learning.
 */
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("published course shows in the catalog and opens", async ({ page }) => {
  test.slow();
  const marker = uniqueMarker();
  const courseTitle = `Catalog E2E ${marker}`;

  // --- admin: ingest + publish a course ---
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN_PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  await page.getByLabel("Link (optional)").fill(`https://www.youtube.com/watch?v=cat${marker}`);
  await page.getByLabel("Course title").fill(courseTitle);
  await page.getByLabel("Category").fill("E2E Topics");
  await page.getByLabel("Module title").fill("Catalog Module");
  await page.getByTestId("type-slide_deck").uncheck();
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);
  await expect(page.getByText("Generating…")).toHaveCount(0, { timeout: 30_000 });
  await page.getByTestId("btn-sr3").click();
  await page.getByTestId("btn-publish-confirm").click();
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="published"]')).toHaveCount(
    5,
  );

  // --- admin logs out ---
  await page.getByTestId("btn-ig9").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);

  // --- student: register + browse ---
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Catalog Learner");
  await page.getByLabel("Email").fill(`learner+${marker}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("learner-strong-1234");
  await page.getByLabel("Confirm password").fill("learner-strong-1234");
  await page.getByTestId("btn-sl1").click();
  await expect(page).toHaveURL(/\/catalog$/);

  const card = page.locator('[data-testid="course-card"]', { hasText: courseTitle });
  await expect(card).toBeVisible();
  await expect(card.getByText("0% Complete")).toBeVisible();

  // student nav (BTN-CT2..4): Catalog / My Listening / Achievements
  const studentNav = page.getByRole("navigation");
  await studentNav.getByRole("link", { name: "My Listening", exact: true }).click();
  await expect(page).toHaveURL(/\/my-listening$/);
  await studentNav.getByRole("link", { name: "Achievements", exact: true }).click();
  await expect(page).toHaveURL(/\/achievements$/);
  await studentNav.getByRole("link", { name: "Catalog", exact: true }).click();
  await expect(page).toHaveURL(/\/catalog$/);

  // search narrows to our course
  await page.getByLabel("Search courses").first().fill(courseTitle);
  await expect(page.getByTestId("course-card")).toHaveCount(1);

  // category chip filters too
  await page.getByRole("button", { name: "E2E Topics" }).click();
  await expect(card).toBeVisible();

  // Start Learning routes into the workspace shell
  await card.getByTestId("btn-ct7").click();
  await expect(page).toHaveURL(/\/learn\/catalog-e2e-/);
  await expect(page.getByTestId("btn-ws1")).toContainText("Course Overview");
  await expect(page.getByTestId("btn-ws2")).toContainText("Back to Dashboard");
  await expect(page.getByText("Current: Unit 1")).toBeVisible();

  // the five published types are offered; slides alone is not
  await expect(page.getByTestId("btn-ws3")).toBeVisible(); // Audio
  await expect(page.getByTestId("btn-ws5")).toBeVisible(); // Flashcards
  await expect(page.getByTestId("btn-ws6")).toBeVisible(); // Quiz
  await expect(page.getByTestId("btn-ws7")).toBeVisible(); // Infographic
  await expect(page.getByTestId("btn-ws8")).toBeVisible(); // Report
  await expect(page.getByTestId("btn-ws4")).toHaveCount(0); // Slides (not published)

  // Audio (BTN-WS3): player controls, speed cycle, transcript panel
  await page.getByTestId("btn-ws3").click();
  await expect(page.getByTestId("btn-au1")).toBeVisible();
  await page.getByTestId("btn-au2").click(); // -10s
  await page.getByTestId("btn-au3").click(); // +10s
  // the seek input's max is `Math.max(totalDuration, 1)`, i.e. always >= 1 —
  // seeking to exactly "1" is valid regardless of whether real audio
  // metadata or the content_json fallback duration has landed yet.
  await page.getByTestId("btn-au4").fill("1"); // Seek
  // the audio element applies currentTime asynchronously — wait for the real
  // seek to land before relying on it (Next Lesson below saves this position)
  await page.waitForFunction(
    () => ((document.querySelector("audio") as HTMLAudioElement | null)?.currentTime ?? 0) > 0,
  );
  await page.getByTestId("btn-au6").fill("0.5"); // Volume
  await expect(page.getByTestId("btn-au5")).toContainText("1x");
  await page.getByTestId("btn-au5").click();
  await expect(page.getByTestId("btn-au5")).toContainText("1.25x");
  await page.getByTestId("btn-au7").click(); // Transcript
  await expect(page.getByTestId("transcript-panel")).toBeVisible();
  await page.getByTestId("btn-au8").click(); // Next Lesson (also saves the listened position)
  await expect(page).not.toHaveURL(/\/0\/audio_overview$/);

  // My Listening (BTN-ML1): resume deep-links back into this audio lesson
  await page.goto("/my-listening");
  const listeningRow = page.getByTestId("listening-row").filter({ hasText: courseTitle });
  await expect(listeningRow).toBeVisible();
  await listeningRow.getByTestId("btn-ml1").click();
  await expect(page).toHaveURL(/\/0\/audio_overview$/);

  // Infographic (BTN-WS7): zoom, fullscreen affordance, download, mark reviewed
  await page.getByTestId("btn-ws7").click();
  const infographicImg = page.getByTestId("infographic-image");
  await expect(infographicImg).toBeVisible();
  await expect(infographicImg).toHaveCSS("width", /\d/);
  await page.getByTestId("btn-if1").click(); // Zoom in
  await expect(page.getByTestId("btn-if3")).toBeVisible(); // Fullscreen control present
  await expect(page.getByTestId("btn-if4")).toHaveAttribute("href", /\/api\/media\/.*\.png/);
  await page.getByTestId("btn-if5").click(); // Mark reviewed
  await expect(page.getByTestId("btn-if5")).toContainText("Reviewed");

  // Report (BTN-WS8): reading mode with read time, numbered sections, PDF FAB
  await page.getByTestId("btn-ws8").click();
  await expect(page).toHaveURL(/\/learn\/[a-z0-9-]+\/0\/report$/);
  await expect(page.getByText(/\d+ min read/)).toBeVisible();
  await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
  // the PDF is typeset in the background (worker-pdf -> typeset) after
  // generation and may not exist yet on first view: reload until it does
  await expect(async () => {
    await page.reload();
    await expect(page.getByTestId("btn-rp3")).toHaveAttribute("href", /\/api\/media\/.*\.pdf/, {
      timeout: 3_000,
    });
  }).toPass({ timeout: 120_000 });
  await page.getByTestId("btn-rp1").click(); // Previous -> back to overview
  await expect(page).toHaveURL(new RegExp("/learn/[a-z0-9-]+$"));
  await page.getByTestId("btn-ws8").click(); // back into the report for the rest of the walk

  // Flashcards (BTN-WS5): flip + rate + navigate. Note: rating a card re-sorts
  // the hard-first deck, which can slide a *different* card into the same
  // position — so only "Hard" (which stays first) is safe to assert
  // aria-pressed on immediately after; Good/Easy are exercised without that
  // assertion to avoid asserting on a card that just got swapped out.
  await page.getByTestId("btn-ws5").click();
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  await page.getByTestId("btn-fc1").click(); // flip
  await page.getByTestId("btn-fc4").click(); // Hard
  await expect(page.getByTestId("btn-fc4")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("btn-fc3").click(); // Next
  await expect(page.getByText(/^2 of \d+$/)).toBeVisible();
  await page.getByTestId("btn-fc5").click(); // Good
  await page.getByTestId("btn-fc6").click(); // Easy (re-rate the same card)
  await page.getByTestId("btn-fc2").click(); // Prev
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  await page.getByTestId("btn-fc3").click(); // Next again, to leave the deck mid-way as before

  // rating persists across reload and the Hard card leads the deck
  await page.reload();
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  await expect(page.getByTestId("btn-fc4")).toHaveAttribute("aria-pressed", "true");

  // Quiz (BTN-WS6), adaptive: each question is checked on its own (instant
  // feedback) before Next; Finish on the last one shows the score. Retake
  // brings a fresh question set (the fixture chat answer: MCQ + fill-in).
  await page.getByTestId("btn-ws6").click();
  const firstQuestion = page.getByText(/^Question 1 of \d+$/);
  await expect(firstQuestion).toBeVisible();
  const qCount = Number((await firstQuestion.textContent())!.match(/of (\d+)/)![1]);
  await answerAllQuestions(page, qCount, { revisitFirst: true });
  await expect(page.getByTestId("quiz-score")).toBeVisible();
  await expect(page.getByText(/of \d+ correct/)).toBeVisible();

  await page.getByTestId("btn-qz5").click(); // Retake (a fresh set may take a moment to prepare)
  const retakeFirst = page.getByText(/^Question 1 of \d+$/);
  const unavailable = page.getByText(/New questions aren.t available right now/);
  await expect(retakeFirst.or(unavailable)).toBeVisible({ timeout: 60_000 });
  // Soft, so the rest of the walk still runs when the retake set can't be
  // prepared (the test still fails): see .superpowers/e2e-2026-10-29/e2e-infra-report.md
  await expect.soft(retakeFirst, "retake serves a fresh question set").toBeVisible();
  if (await retakeFirst.isVisible()) {
    const retakeCount = Number((await retakeFirst.textContent())!.match(/of (\d+)/)![1]);
    await answerAllQuestions(page, retakeCount);
    await expect(page.getByTestId("quiz-score")).toBeVisible();
  }
  await page.getByTestId("btn-qz6").click(); // Back to module
  await expect(page).toHaveURL(new RegExp(`/learn/[a-z0-9-]+$`));

  // a direct URL to an unpublished type shows a "not available" panel, not an error
  const learnBase = new URL(page.url()).pathname.replace(/\/\d+\/[a-z_]+$/, "");
  await page.goto(`${learnBase}/0/slide_deck`);
  await expect(page.getByText("Not available")).toBeVisible();

  // Complete Module from the report marks the whole module done
  await page.goto(`${learnBase}/0/report`);
  await page.getByTestId("btn-rp2").click();
  await expect(page).toHaveURL(new RegExp(`${learnBase}$`));
  await expect(page.getByText("100% Complete")).toBeVisible();

  // Back to Dashboard returns to the catalog, now at 100%
  await page.getByTestId("btn-ws2").click();
  await expect(page).toHaveURL(/\/catalog$/);
  await expect(
    page
      .locator('[data-testid="course-card"]', { hasText: courseTitle })
      .getByText("100% Complete"),
  ).toBeVisible();

  // Progress dashboard reflects the real record (T039)
  await page.goto("/progress");
  const progressRow = page.locator('[data-testid="progress-row"]', { hasText: courseTitle });
  await expect(progressRow).toBeVisible();
  await expect(progressRow.getByText("100%")).toBeVisible();

  // Completing the course unlocked the Course Complete badge
  await page.goto("/achievements");
  const earnedBadge = page
    .locator('[data-testid="achievement-badge"][data-earned="true"]')
    .filter({ hasText: "Course Complete" });
  await expect(earnedBadge).toBeVisible();
});
