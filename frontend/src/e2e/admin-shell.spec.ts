import { expect, test } from "@playwright/test";

/**
 * T030 — Admin shell & notifications. Requires the stack + a seeded admin.
 * Checks the persistent nav highlights the active route and the notifications
 * panel opens from the header bell.
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";

test("nav highlights the route and the notifications panel opens", async ({ page }) => {
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByTestId("btn-al1").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  // T043 — persistent header system-health badges
  await expect(page.getByText(/NotebookLM: (Connected|Disconnected|Fixture \(dev\))/)).toBeVisible();
  await expect(page.getByTestId("worker-badge")).toBeVisible();

  // active-route highlighting on the persistent left nav
  const nav = page.getByRole("navigation");
  const ingestionLink = nav.getByRole("link", { name: "Ingestion", exact: true });
  const editorLink = nav.getByRole("link", { name: "Editor", exact: true });
  const reviewLink = nav.getByRole("link", { name: "Review", exact: true });
  const settingsLink = nav.getByRole("link", { name: "Settings", exact: true });
  await expect(ingestionLink).toHaveClass(/font-semibold/);
  await editorLink.click();
  await expect(page).toHaveURL(/\/admin\/editor$/);
  await expect(editorLink).toHaveClass(/font-semibold/);
  await expect(ingestionLink).not.toHaveClass(/font-semibold/);

  // BTN-IG1/IG2/IG4/IG5/IG7: the rest of the left nav + header Settings shortcut route correctly
  await reviewLink.click();
  await expect(page).toHaveURL(/\/admin\/review$/);
  await settingsLink.click();
  await expect(page).toHaveURL(/\/admin\/settings$/);
  await ingestionLink.click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  await page.getByTestId("btn-ig7").click(); // header Settings shortcut
  await expect(page).toHaveURL(/\/admin\/settings$/);
  await page.getByTestId("btn-ig1").click(); // New Artifact -> focuses the ingestion form
  await expect(page).toHaveURL(/\/admin\/ingestion\?focus=form$/);
  await expect(page.getByLabel("Link (optional)")).toBeFocused();

  // notifications panel opens from the header bell and lists activity or an empty state
  await page.getByTestId("btn-ig8").click();
  await expect(page.getByText("Notifications", { exact: true })).toBeVisible();
  const rows = page.getByTestId("notif-row");
  const empty = page.getByText(/No recent generation activity/);
  await expect(async () => {
    expect((await rows.count()) > 0 || (await empty.isVisible())).toBeTruthy();
  }).toPass();
});
