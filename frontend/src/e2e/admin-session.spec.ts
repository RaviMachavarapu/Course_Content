import { type Page, expect, request, test } from "@playwright/test";
import { AdminApi, BASE_URL, SESSION_ENDED, loginAdminUI, requestReset } from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * Admin sessions that end under the user (owner decision 3), CSRF recovery,
 * deep links and logout. Each test signs in its own fresh admin.
 */
async function freshAdmin(): Promise<{ id: string; email: string; password: string }> {
  const email = `e2e+ses${uniqueMarker()}@example.com`;
  const password = `ses-pw-${uniqueMarker()}`;
  const root = await AdminApi.login();
  const id = await root.createAdmin(email, password);
  await root.dispose();
  return { id, email, password };
}

async function freshAdminSignedIn(page: Page): Promise<{ email: string; password: string }> {
  const a = await freshAdmin();
  await loginAdminUI(page, a.email, a.password);
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  return a;
}

test("a deep link survives the login: back to the page with its query string", async ({ page }) => {
  const { email, password } = await freshAdmin();
  await page.goto("/admin/pipeline?q=nothing-matches-this");
  await expect(page).toHaveURL(/\/admin\/login$/);
  await loginAdminUI(page, email, password);
  await expect(page).toHaveURL(/\/admin\/pipeline\?q=nothing-matches-this$/);
});

test("an admin deactivated while a tab is open lands on the login page: Session ended", async ({
  page,
}) => {
  const { id, email, password } = await freshAdmin();
  await loginAdminUI(page, email, password);
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  // the ingestion page polls the recent jobs: the next poll finds the session gone
  const root = await AdminApi.login();
  await root.setAdminActive(id, false);
  await root.dispose();
  await expect(page).toHaveURL(/\/admin\/login$/, { timeout: 20_000 });
  await expect(page.getByRole("status")).toHaveText(SESSION_ENDED);
});

test("a password reset elsewhere ends this session; signing in again returns to the page", async ({
  page,
}) => {
  const admin = await freshAdminSignedIn(page);
  await page.goto("/admin/settings?tab=users");
  await expect(page.getByTestId("btn-st5")).toBeVisible();

  // another device resets the password: every session is revoked
  const other = await request.newContext({ baseURL: BASE_URL });
  const link = await requestReset(other, "admin", admin.email);
  const token = new URL(link, BASE_URL).searchParams.get("token");
  const newPassword = `reset-pw-${uniqueMarker()}`;
  const r = await other.post("/api/admin/auth/password-reset/confirm", {
    data: { token, password: newPassword },
  });
  expect(r.status()).toBe(204);
  await other.dispose();

  // the next request from this tab (a click) finds the session gone
  await page.getByRole("tab", { name: "Prompts" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/, { timeout: 20_000 });
  await expect(page.getByRole("status")).toHaveText(SESSION_ENDED);
  await loginAdminUI(page, admin.email, newPassword);
  await expect(page).toHaveURL(/\/admin\/settings\?tab=prompts$/);
});

test("a lost CSRF cookie is refreshed silently: adding an admin still works", async ({
  page,
  context,
}) => {
  await freshAdminSignedIn(page);
  await page.goto("/admin/settings?tab=users");
  await context.clearCookies({ name: "sdp_csrf" });
  const newEmail = `e2e+csrf${uniqueMarker()}@example.com`;
  await page.getByTestId("btn-st5").click();
  await page.getByLabel("Email").fill(newEmail);
  await page.getByLabel("Display name").fill("CSRF Admin");
  await page.getByLabel("Temporary password").fill("e2e-temp-pass-9999");
  await page.getByTestId("btn-st5-confirm").click();
  await expect(page.locator("tr", { hasText: newEmail })).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/settings\?tab=users$/);
});

test("session and CSRF cookie both gone: the next save lands on login with the notice", async ({
  page,
  context,
}) => {
  const admin = await freshAdminSignedIn(page);
  await page.goto("/admin/settings?tab=users");
  await expect(page.getByTestId("btn-st5")).toBeVisible();
  await context.clearCookies({ name: "sdp_csrf" });
  await context.clearCookies({ name: "sdp_admin" });
  await page.getByTestId("btn-st5").click();
  await page.getByLabel("Email").fill(`e2e+gone${uniqueMarker()}@example.com`);
  await page.getByLabel("Display name").fill("Never Added");
  await page.getByLabel("Temporary password").fill("e2e-temp-pass-9999");
  await page.getByTestId("btn-st5-confirm").click();
  await expect(page).toHaveURL(/\/admin\/login$/, { timeout: 20_000 });
  await expect(page.getByRole("status")).toHaveText(SESSION_ENDED);
  await loginAdminUI(page, admin.email, admin.password);
  await expect(page).toHaveURL(/\/admin\/settings\?tab=users$/);
});

test("after logout the Back button can't reopen the admin pages", async ({ page }) => {
  await freshAdminSignedIn(page);
  await page.goto("/admin/pipeline");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.getByTestId("btn-ig9").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/admin\/login/);
  await expect(page.getByTestId("btn-al1")).toBeVisible();
});

test("double-clicking Sign in sends one login", async ({ page }) => {
  const { email, password } = await freshAdmin();
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const logins: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/api/admin/auth/login")) logins.push(r.url());
  });
  await page.getByTestId("btn-al1").dblclick();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  expect(logins).toHaveLength(1);
});
