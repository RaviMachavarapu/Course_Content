import { expect, test } from "@playwright/test";

/**
 * T028 — Course Editor (A3). Requires the stack + a seeded admin.
 * Ingests a course with two modules, opens the structure view, reorders them,
 * and asserts the new order survives a reload (order_index persisted).
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("reorder persists and rename sticks", async ({ page }) => {
  test.slow();
  const courseTitle = `Editor E2E ${Date.now()}`;

  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  // module 1 — new course, report only (fast fixture)
  await page.getByLabel("Link (optional)").fill("https://www.youtube.com/watch?v=ed1");
  await page.getByLabel("Course title").fill(courseTitle);
  await page.getByLabel("Module title").fill("Alpha");
  for (const t of ["slide_deck", "flashcards", "quiz", "infographic", "audio_overview"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);

  // module 2 — same course, via the Editor's scoped "Add New Video Source"
  await page.goto("/admin/editor");
  await page.getByRole("link", { name: courseTitle }).click();
  await expect(page).toHaveURL(/\/admin\/editor\/[0-9a-f-]+$/);
  const courseUrl = page.url();

  await page.getByTestId("btn-ce1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion\?course=[0-9a-f-]+$/);
  await expect(page.getByTestId("scoped-course-hint")).toContainText(courseTitle);
  await page.getByLabel("Link (optional)").fill("https://www.youtube.com/watch?v=ed2");
  await page.getByLabel("Module title").fill("Beta");
  for (const t of ["slide_deck", "flashcards", "quiz", "infographic", "audio_overview"]) {
    await page.getByTestId(`type-${t}`).uncheck();
  }
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);

  // back to structure: order is Alpha, Beta
  await page.goto(courseUrl);
  await expect(page.getByText("Alpha", { exact: true })).toBeVisible();
  const titles = () =>
    page.locator("span.text-label-lg").allTextContents();
  expect(await titles()).toEqual(["Alpha", "Beta"]);

  // move Alpha down
  await page.getByTestId("btn-ce2").first().click();
  await page.getByTestId("btn-ce6").click();
  await expect
    .poll(async () => (await titles()).join(","))
    .toBe("Beta,Alpha");

  // rename Beta -> Gamma
  await page.getByTestId("btn-ce2").first().click();
  await page.getByTestId("btn-ce4").click();
  const box = page.getByLabel("Module title");
  await box.fill("Gamma");
  await page.getByTestId("btn-ce4-confirm").click();
  await expect.poll(async () => (await titles()).join(",")).toBe("Gamma,Alpha");

  // reload: both changes persisted
  await page.reload();
  await expect.poll(async () => (await titles()).join(",")).toBe("Gamma,Alpha");

  // CE9: an artifact tile routes to Inspect
  await page.getByTestId("btn-ce9").first().click();
  await expect(page).toHaveURL(/\/admin\/artifacts\/[0-9a-f-]+$/);

  // CE3: kebab "Open staging" routes to that module's staging page
  await page.goto(courseUrl);
  await page.getByTestId("btn-ce2").first().click();
  await page.getByTestId("btn-ce3").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/);

  // CE5: move Alpha (currently last) back up -> Alpha, Gamma
  await page.goto(courseUrl);
  await page.getByTestId("btn-ce2").nth(1).click();
  await page.getByTestId("btn-ce5").click();
  await expect.poll(async () => (await titles()).join(",")).toBe("Alpha,Gamma");

  // CE7: Re-run all regenerates every artifact in the chosen module
  await page.getByTestId("btn-ce2").first().click();
  await page.getByTestId("btn-ce7").click();
  await expect(page.getByText("Re-run started")).toBeVisible();

  // CE8/CE8-confirm: delete a module permanently
  await page.getByTestId("btn-ce2").nth(1).click();
  await page.getByTestId("btn-ce8").click();
  await page.getByTestId("btn-ce8-confirm").click();
  await expect.poll(async () => (await titles()).join(",")).toBe("Alpha");
});
