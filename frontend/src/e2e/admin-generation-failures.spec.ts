import { type Page, expect, test } from "@playwright/test";
import { AdminApi, type ArtifactType, loginAdminUI } from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * Generation worst cases on the staging page, driven by the fixture provider's
 * fault markers in the module title (backend/app/pipeline/fixture.py):
 * `[fixture:<fault>=N]` fails only the first N attempts, so the recovery is
 * part of the test. Report-only modules keep the worker queue short.
 */
async function openStaging(
  page: Page,
  title: string,
  types: ArtifactType[] = ["report"],
): Promise<{ admin: AdminApi; moduleId: string }> {
  const admin = await AdminApi.login();
  const { moduleId } = await admin.createModule({
    moduleTitle: `${title} ${uniqueMarker()}`,
    types,
  });
  await loginAdminUI(page, undefined, undefined, { remember: false });
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  await page.goto(`/admin/modules/${moduleId}/staging`);
  return { admin, moduleId };
}

function card(page: Page, label: string) {
  return page
    .getByTestId("artifact-grid")
    .locator(":scope > *")
    .filter({ has: page.getByRole("heading", { name: label, exact: true }) });
}

function countPosts(page: Page, fragment: string): () => number {
  let n = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes(fragment)) n += 1;
  });
  return () => n;
}

test("generation rejected → error card → Retry (double-clicked: one request) → ready", async ({
  page,
}) => {
  const { admin } = await openStaging(page, "Fail once [fixture:fail-generate=1]");
  const report = card(page, "Report");
  await expect(report.getByTestId("btn-sr6")).toBeVisible({ timeout: 60_000 });
  await expect(report.locator('[data-status="error"]')).toBeVisible();
  const retries = countPosts(page, "/retry");
  await report.getByTestId("btn-sr6").dblclick();
  await expect(report.locator('[data-status="ready"]')).toBeVisible({ timeout: 60_000 });
  expect(retries()).toBe(1);
  await admin.dispose();
});

test("a transient NotebookLM failure is retried automatically and recovers", async ({ page }) => {
  const { admin, moduleId } = await openStaging(
    page,
    "Transient once [fixture:transient-generate=1]",
  );
  const report = card(page, "Report");
  await expect(report.locator('[data-status="ready"]')).toBeVisible({ timeout: 90_000 });
  await expect(report.getByTestId("btn-sr6")).toHaveCount(0);
  const a = await admin.artifact(moduleId, "report");
  expect(a.last_error).toBeNull();
  expect(a.current_version?.revision).toBe(1);
  await admin.dispose();
});

test("NotebookLM reports the generation failed → Retry generates anew → ready", async ({
  page,
}) => {
  const { admin } = await openStaging(page, "Studio failed once [fixture:studio-failed=1]");
  const report = card(page, "Report");
  await expect(report.getByTestId("btn-sr6")).toBeVisible({ timeout: 60_000 });
  await report.getByTestId("btn-sr6").click();
  await expect(report.locator('[data-status="ready"]')).toBeVisible({ timeout: 60_000 });
  await admin.dispose();
});

test("unparseable output → error says Press Retry → Retry regenerates → ready", async ({
  page,
}) => {
  const { admin } = await openStaging(page, "Malformed once [fixture:malformed=1]");
  const report = card(page, "Report");
  await expect(report.getByTestId("btn-sr6")).toBeVisible({ timeout: 60_000 });
  await expect(report).toContainText(/Press Retry/);
  await report.getByTestId("btn-sr6").click();
  await expect(report.locator('[data-status="ready"]')).toBeVisible({ timeout: 60_000 });
  await expect(report).toContainText(/min read/);
  await admin.dispose();
});

test("sources NotebookLM can't read: every card says so and offers Retry", async ({ page }) => {
  const { admin } = await openStaging(page, "Unreadable [fixture:source-fail]", [
    "report",
    "flashcards",
  ]);
  for (const label of ["Report", "Flashcards"]) {
    const c = card(page, label);
    await expect(c.getByTestId("btn-sr6")).toBeVisible({ timeout: 60_000 });
    await expect(c).toContainText("NotebookLM couldn't read");
  }
  await admin.dispose();
});

test("a slow generation shows Generating… and turns ready without a reload", async ({ page }) => {
  const { admin } = await openStaging(page, "Slow [fixture:slow=20]");
  const report = card(page, "Report");
  await expect(report.getByText("Generating…")).toBeVisible({ timeout: 30_000 });
  await expect(report.locator('[data-status="ready"]')).toBeVisible({ timeout: 90_000 });
  await expect(report.getByText("Generating…")).toHaveCount(0);
  await admin.dispose();
});

test("Cancel asks first; cancelling shows a retryable error; Retry resumes; Redo then works", async ({
  page,
}) => {
  test.slow();
  const { admin } = await openStaging(page, "Hanging [fixture:slow=25]");
  const report = card(page, "Report");
  const cancels = countPosts(page, "/cancel");

  await report.getByTestId("btn-sr21").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Cancel this generation? Any progress is discarded.");
  await page.getByTestId("btn-sr21-dismiss").click();
  await expect(dialog).toHaveCount(0);
  expect(cancels()).toBe(0);
  await expect(report.getByText("Generating…")).toBeVisible();

  await report.getByTestId("btn-sr21").click();
  await page.getByTestId("btn-sr21-confirm").click();
  await expect(report).toContainText("Generation cancelled by an admin. Press Retry to try again.");
  expect(cancels()).toBe(1);

  await report.getByTestId("btn-sr6").click();
  await expect(report.locator('[data-status="ready"]')).toBeVisible({ timeout: 90_000 });

  await report.getByRole("button", { name: "Redo Report" }).click();
  await page.getByTestId("btn-sr7").click();
  await expect(report.getByText("rev 2")).toBeVisible({ timeout: 90_000 });
  await admin.dispose();
});

test("typeset down at first: the report is ready at once, its PDF appears after the retry", async ({
  page,
}) => {
  test.slow();
  const { admin, moduleId } = await openStaging(page, "No typeset [fixture:typeset-down=1]");
  const report = card(page, "Report");
  await expect(report.locator('[data-status="ready"]')).toBeVisible({ timeout: 60_000 });
  const a = await admin.artifact(moduleId, "report");
  expect(a.last_error).toBeNull();
  // the PDF task retries 30 s later; staging stops polling once settled: reload
  await expect(async () => {
    await page.reload();
    await expect(card(page, "Report").getByTestId("btn-sr12")).toHaveAttribute(
      "href",
      /\/api\/media\/.*\.pdf/,
      { timeout: 3_000 },
    );
  }).toPass({ timeout: 150_000 });
  await expect(card(page, "Report").locator('[data-status="ready"]')).toBeVisible();
  await admin.dispose();
});
