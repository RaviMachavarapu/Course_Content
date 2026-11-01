import { type Page, expect, test } from "@playwright/test";
import { courseSlug, publishedCourse, registerStudent } from "./helpers";

/**
 * Adaptive quiz beyond the happy path: attempt 1 (the reviewed Studio quiz of
 * `[fixture:quiz=N]` questions, "doubled") → instant feedback → score → retakes
 * with fresh chat questions ("squared") of the same size (owner decision 7),
 * twice; chat failing once → "not available right now" → Try again works;
 * reload mid-attempt resumes at the first unchecked question.
 */
async function answer(page: Page, from: number, to: number, total: number): Promise<void> {
  for (let i = from; i < to; i++) {
    await expect(page.getByText(`Question ${i + 1} of ${total}`)).toBeVisible();
    const fill = page.getByTestId("quiz-fill-input");
    if (await fill.isVisible()) await fill.fill("7");
    else await page.getByTestId("btn-qz1-0").click();
    await page.getByTestId("btn-qz8").click(); // Check
    await expect(page.getByTestId("quiz-feedback")).toBeVisible();
    await expect(page.getByText(`${i + 1}/${total} checked`)).toBeVisible();
    if (i < total - 1) await page.getByTestId("btn-qz3").click(); // Next
  }
}

async function finish(page: Page): Promise<void> {
  await page.getByTestId("btn-qz4").click();
  await expect(page.getByTestId("quiz-score")).toBeVisible();
  await expect(page.getByText(/of \d+ correct/)).toBeVisible();
}

const firstQuestion = (page: Page) => page.getByText(/^Question 1 of \d+$/);

test("attempt 1, then two retakes of fresh questions, each the size of the reviewed quiz", async ({
  page,
  context,
}) => {
  test.slow();
  const { admin, courseTitle } = await publishedCourse(["quiz"], "Quiz Unit [fixture:quiz=6]");
  await admin.dispose();
  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/quiz`);

  await expect(page.getByText("Question 1 of 6")).toBeVisible();
  await expect(page.getByText(/doubled/).first()).toBeVisible(); // the Studio quiz
  await answer(page, 0, 6, 6);
  await finish(page);

  for (const attempt of [2, 3]) {
    // Retake; the first one double-clicked: still one attempt, served normally
    if (attempt === 2) await page.getByTestId("btn-qz5").dblclick();
    else await page.getByTestId("btn-qz5").click();
    await expect(firstQuestion(page)).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText("Question 1 of 6")).toBeVisible();
    await expect(page.getByText(/squared/).first()).toBeVisible(); // fresh chat questions
    await answer(page, 0, 6, 6);
    await finish(page);
    await expect(page.getByText(/Latest \d+%/), `attempt ${attempt}`).toBeVisible();
  }
});

test("chat fails once: the retake says not available, Try again later serves it", async ({
  page,
  context,
}) => {
  test.slow();
  const { admin, courseTitle } = await publishedCourse(
    ["quiz"],
    "Chat Unit [fixture:quiz=3] [fixture:chat-fail=1]",
  );
  await admin.dispose();
  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/quiz`);
  await expect(page.getByText("Question 1 of 3")).toBeVisible();
  await answer(page, 0, 3, 3);
  await finish(page);

  await page.getByTestId("btn-qz5").click();
  await expect(page.getByText(/New questions aren.t available right now/)).toBeVisible({
    timeout: 150_000,
  });
  await expect(page.getByTestId("btn-qz9")).toBeVisible();
  // Try again until the next preparation (chat now answers) is served
  await expect(async () => {
    if (await page.getByTestId("btn-qz9").isVisible()) await page.getByTestId("btn-qz9").click();
    await expect(page.getByText("Question 1 of 3")).toBeVisible({ timeout: 10_000 });
  }).toPass({ timeout: 150_000 });
  await expect(page.getByText(/squared/).first()).toBeVisible();
});

test("a reload mid-attempt resumes at the first unchecked question", async ({ page, context }) => {
  const { admin, courseTitle } = await publishedCourse(["quiz"], "Resume Unit [fixture:quiz=5]");
  await admin.dispose();
  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/quiz`);
  await answer(page, 0, 2, 5);
  await page.reload();
  await expect(page.getByText("Question 3 of 5")).toBeVisible();
  await expect(page.getByText("2/5 checked")).toBeVisible();
  await page.getByTestId("btn-qz2").click(); // Previous: Q2 keeps its feedback
  await expect(page.getByText("Question 2 of 5")).toBeVisible();
  await expect(page.getByTestId("quiz-feedback")).toBeVisible();
});
