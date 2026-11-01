import { type Page, expect, test } from "@playwright/test";
import { AdminApi, loginAdminUI } from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * Staging under a flaky network and impatient clicks: a failed status poll
 * keeps the cards, publish and redo double-clicks send one request each.
 */
async function signedInStaging(
  page: Page,
  moduleTitle: string,
): Promise<{ admin: AdminApi; moduleId: string }> {
  const admin = await AdminApi.login();
  const { moduleId } = await admin.createModule({
    moduleTitle: `${moduleTitle} ${uniqueMarker()}`,
    types: ["report"],
  });
  await loginAdminUI(page, undefined, undefined, { remember: false });
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  await page.goto(`/admin/modules/${moduleId}/staging`);
  return { admin, moduleId };
}

function posts(page: Page, re: RegExp): () => number {
  let n = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && re.test(r.url())) n += 1;
  });
  return () => n;
}

test("a status poll that fails keeps the cards and says so; the next poll recovers", async ({
  page,
}) => {
  const { admin } = await signedInStaging(page, "Flaky poll [fixture:slow=20]");
  await expect(page.getByText("Generating…")).toBeVisible({ timeout: 30_000 });
  let cut = true;
  await page.route("**/api/admin/modules/*/staging", (route) =>
    cut ? route.abort("internetdisconnected") : route.fallback(),
  );
  await expect(page.getByText("Couldn’t refresh the status just now.")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("Generating…")).toBeVisible(); // the cards stay
  cut = false;
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="ready"]')).toHaveCount(1, {
    timeout: 90_000,
  });
  await expect(page.getByText("Couldn’t refresh the status just now.")).toHaveCount(0);
  await admin.dispose();
});

test("double-clicking Publish or Start redo sends one request", async ({ page }) => {
  const { admin, moduleId } = await signedInStaging(page, "Clicky");
  await admin.waitReady(moduleId, ["report"]);
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="ready"]')).toHaveCount(1, {
    timeout: 30_000,
  });

  const redos = posts(page, /\/api\/admin\/artifacts\/[0-9a-f-]+\/redo$/);
  await page.getByRole("button", { name: "Redo Report" }).click();
  await page.getByTestId("btn-sr7").dblclick();
  await expect(page.getByText("rev 2")).toBeVisible({ timeout: 60_000 });
  expect(redos()).toBe(1);

  const publishes = posts(page, /\/api\/admin\/modules\/[0-9a-f-]+\/publish$/);
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="ready"]')).toHaveCount(1, {
    timeout: 60_000,
  });
  await page.getByTestId("btn-sr3").click();
  await page.getByTestId("btn-publish-confirm").dblclick();
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="published"]')).toHaveCount(
    1,
  );
  expect(publishes()).toBe(1);
  await admin.dispose();
});
