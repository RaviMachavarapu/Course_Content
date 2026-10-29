import { expect, test } from "@playwright/test";
import { AdminApi, courseSlug, publishedCourse, registerStudent, studentArtifact } from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * Content changing under a student: a flashcard deck republished while open
 * ("This deck was updated — reloading", review backend I1), and a slow redo
 * that must never take the published version away (spec §3.3: students keep
 * the published version until the admin publishes the new one).
 */
test("rating a card of a deck that was republished meanwhile reloads the new deck", async ({
  page,
  context,
}) => {
  test.slow();
  const { admin, courseTitle, moduleId } = await publishedCourse(["flashcards"], "Deck Unit");
  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/flashcards`);
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  const before = await studentArtifact(context, slug, "flashcards");

  // the admin redoes and republishes the deck while the student has it open
  const deck = await admin.artifact(moduleId, "flashcards");
  await admin.redo(deck.id, "Shorter cards");
  await expect
    .poll(async () => (await admin.artifact(moduleId, "flashcards")).current_version?.revision, {
      timeout: 60_000,
    })
    .toBe(2);
  await admin.waitReady(moduleId, ["flashcards"]);
  await admin.publishModule(moduleId);
  await admin.dispose();

  await page.getByTestId("btn-fc1").click(); // flip
  await page.getByTestId("btn-fc4").click(); // Hard → 409 stale_version
  await expect(page.getByText("This deck was updated — reloading")).toBeVisible();
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  const after = await studentArtifact(context, slug, "flashcards");
  expect(after.version_id).not.toBe(before.version_id);
  expect(after.revision).toBe(2);
  // the new deck takes ratings again
  await page.getByTestId("btn-fc1").click();
  await page.getByTestId("btn-fc4").click();
  await expect(page.getByTestId("btn-fc4")).toHaveAttribute("aria-pressed", "true");
});

test("during a slow redo the student keeps the published report; the new one only after publishing", async ({
  page,
  context,
}) => {
  test.slow();
  const admin = await AdminApi.login();
  const { moduleId, courseTitle } = await admin.createModule({
    moduleTitle: `Slow Redo ${uniqueMarker()} [fixture:slow=15]`,
    types: ["report"],
  });
  await admin.waitReady(moduleId, ["report"], 120_000);
  await admin.publishModule(moduleId);

  await registerStudent(context);
  const slug = await courseSlug(context, courseTitle);
  await page.goto(`/learn/${slug}/0/report`);
  await expect(page.getByText(/\d+ min read/)).toBeVisible();
  const published = await studentArtifact(context, slug, "report");
  expect(published.revision).toBe(1);

  const report = await admin.artifact(moduleId, "report");
  await admin.redo(report.id, "Add a summary");
  await expect
    .poll(async () => (await admin.artifact(moduleId, "report")).status, { timeout: 30_000 })
    .toBe("processing");

  // while it regenerates: the student still reads revision 1
  await page.reload();
  await expect(page.getByText(/\d+ min read/)).toBeVisible();
  await expect(page.getByTestId("btn-rp2")).toBeVisible();
  expect((await studentArtifact(context, slug, "report")).version_id).toBe(published.version_id);

  // the redo is ready but not published: still revision 1
  await expect
    .poll(async () => (await admin.artifact(moduleId, "report")).current_version?.revision, {
      timeout: 90_000,
    })
    .toBe(2);
  await page.reload();
  await expect(page.getByText(/\d+ min read/)).toBeVisible();
  expect((await studentArtifact(context, slug, "report")).version_id).toBe(published.version_id);

  // published: now the student gets revision 2
  await admin.waitReady(moduleId, ["report"]);
  await admin.publishModule(moduleId);
  await admin.dispose();
  await expect.poll(async () => (await studentArtifact(context, slug, "report")).revision).toBe(2);
  await page.reload();
  await expect(page.getByText(/\d+ min read/)).toBeVisible();
});
