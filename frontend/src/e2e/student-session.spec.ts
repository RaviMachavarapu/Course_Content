import { type Page, expect, test } from "@playwright/test";
import {
  SESSION_ENDED,
  courseSlug,
  loginStudentUI,
  publishedCourse,
  registerStudent,
} from "./helpers";

/**
 * Student sessions: Log out from every page (owner decisions 4 and 10) and the
 * Back button afterwards, account switch in one tab, CSRF recovery, the
 * session-ended notice, catalog search with no hits and a bad course link.
 * One published report-only course is shared by the tests of this file.
 */
let courseTitle = "";

test.beforeAll(async () => {
  test.setTimeout(180_000);
  const c = await publishedCourse(["report"], "Session Unit");
  courseTitle = c.courseTitle;
  await c.admin.dispose();
});

async function logOutFrom(page: Page, path: string): Promise<void> {
  // a signed-in page in the history first, so Back has somewhere to go
  await page.goto(path === "/progress" ? "/catalog" : "/progress");
  await page.goto(path);
  if (path === "/catalog") {
    await page.getByTestId("btn-ct5").click();
    await page.getByRole("button", { name: "Log out" }).click();
  } else if (path.startsWith("/learn/")) {
    await page.getByTestId("btn-ws9").click();
  } else {
    await page.getByTestId("btn-logout").click();
  }
  await expect(page).toHaveURL(/\/login$/);
  // Back can't reopen a signed-in page
  await page.goBack();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByTestId("btn-sl2")).toBeVisible();
}

test("Log out works on every student page, and Back afterwards goes to the login", async ({
  page,
  context,
}) => {
  const { email } = await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  for (const path of [
    "/catalog",
    `/learn/${slug}`,
    "/progress",
    "/achievements",
    "/my-listening",
  ]) {
    if (!(await context.cookies()).some((c) => c.name === "sdp_student")) {
      await loginStudentUI(page, email);
      // back to where Back left off (the guard kept it as the return path)
      await expect(page).not.toHaveURL(/\/login/);
    }
    await logOutFrom(page, path);
  }
});

test("account switch in one tab: the next student sees none of the previous one's data", async ({
  page,
  context,
  browser,
}) => {
  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/report`);
  await page.getByTestId("btn-rp2").click(); // Complete Module
  await expect(page.getByText("100% Complete")).toBeVisible();
  await page.goto("/progress");
  await expect(
    page.locator('[data-testid="progress-row"]', { hasText: courseTitle }),
  ).toBeVisible();
  await page.getByTestId("btn-logout").click();
  await expect(page).toHaveURL(/\/login$/);

  const other = await browser.newContext();
  const b = await registerStudent(other);
  await other.close();
  await loginStudentUI(page, b.email);
  await expect(page).toHaveURL(/\/catalog$/);
  await page.goto("/progress");
  await expect(page.getByText("Nothing started yet")).toBeVisible();
  await expect(page.locator('[data-testid="progress-row"]', { hasText: courseTitle })).toHaveCount(
    0,
  );
});

test("a lost CSRF cookie is refreshed silently: Complete Module still saves", async ({
  page,
  context,
}) => {
  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/report`);
  await expect(page.getByTestId("btn-rp2")).toBeVisible();
  await context.clearCookies({ name: "sdp_csrf" });
  await page.getByTestId("btn-rp2").click();
  await expect(page.getByText("100% Complete")).toBeVisible();
});

test("session and CSRF cookie both gone: Session ended, then back to the lesson after signing in", async ({
  page,
  context,
}) => {
  const { email } = await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/report`);
  await expect(page.getByTestId("btn-rp2")).toBeVisible();
  await context.clearCookies({ name: "sdp_csrf" });
  await context.clearCookies({ name: "sdp_student" });
  await page.getByTestId("btn-rp2").click();
  await expect(page).toHaveURL(/\/login$/, { timeout: 20_000 });
  await expect(page.getByRole("status")).toHaveText(SESSION_ENDED);
  await loginStudentUI(page, email);
  await expect(page).toHaveURL(new RegExp(`/learn/${slug}/0/report$`));
});

test("a course link that doesn't exist", async ({ page, context }) => {
  await registerStudent(context);
  await page.goto("/learn/no-such-course-slug-e2e");
  await expect(page.getByText("Course not available")).toBeVisible();
});
