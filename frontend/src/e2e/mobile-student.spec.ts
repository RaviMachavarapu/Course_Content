import { expect, test } from "@playwright/test";
import { courseSlug, expectNoHorizontalScroll, publishedCourse, registerStudent } from "./helpers";

/**
 * Phone width smoke (375 px, review S22): every student page is usable without
 * sideways scrolling, the workspace header wraps with Log out reachable, the
 * menu drawer opens and closes.
 */
let courseTitle = "";

test.beforeAll(async () => {
  test.setTimeout(180_000);
  const c = await publishedCourse(["report", "flashcards", "quiz"], "Phone Unit");
  courseTitle = c.courseTitle;
  await c.admin.dispose();
});

test("student pages at 375 px: no sideways scroll, Log out reachable", async ({
  page,
  context,
}) => {
  test.slow();
  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);

  await page.goto("/catalog");
  await expect(page.locator('[data-testid="course-card"]', { hasText: courseTitle })).toBeVisible();
  await expectNoHorizontalScroll(page);

  // the sidebar is a drawer here: open it, navigate, it closes
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("navigation").getByRole("link", { name: "Progress" }).click();
  await expect(page).toHaveURL(/\/progress$/);
  await expect(page.getByRole("button", { name: "Close menu" })).toHaveCount(0);
  await expect(page.getByTestId("btn-logout")).toBeInViewport();
  await expectNoHorizontalScroll(page);

  for (const path of ["/achievements", "/my-listening"]) {
    await page.goto(path);
    await expect(page.getByTestId("btn-logout")).toBeInViewport();
    await expectNoHorizontalScroll(page);
  }

  await page.goto(`/learn/${slug}`);
  await expect(page.getByTestId("btn-ws9")).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.goto(`/learn/${slug}/0/report`);
  await expect(page.getByText(/\d+ min read/)).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.goto(`/learn/${slug}/0/flashcards`);
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  await page.getByTestId("btn-fc1").click();
  await expect(page.getByTestId("btn-fc4")).toBeInViewport();
  await expectNoHorizontalScroll(page);

  await page.goto(`/learn/${slug}/0/quiz`);
  await expect(page.getByText(/^Question 1 of \d+$/)).toBeVisible();
  await page.getByTestId("btn-qz1-0").click();
  await page.getByTestId("btn-qz8").click();
  await expect(page.getByTestId("quiz-feedback")).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.getByTestId("btn-ws9").click();
  await expect(page).toHaveURL(/\/login$/);
  await expectNoHorizontalScroll(page);
});
