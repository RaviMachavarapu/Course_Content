import { type APIRequestContext, expect, request, test } from "@playwright/test";
import {
  AdminApi,
  BASE_URL,
  RESET_DONE,
  cookieNames,
  loginAdminUI,
  mailsTo,
  resetLinkFor,
} from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * Admin sign-in under attack (login protection spec + owner decisions 1, 2, 9):
 * every test uses its own fresh admin, so locking an email never touches the
 * seeded admin the other specs sign in with.
 */
const BAD = "definitely-wrong-pw-1";

async function freshAdmin(): Promise<{ email: string; password: string }> {
  const email = `e2e+adm${uniqueMarker()}@example.com`;
  const password = `adm-pw-${uniqueMarker()}`;
  const root = await AdminApi.login();
  await root.createAdmin(email, password);
  await root.dispose();
  return { email, password };
}

/** An attacker (own cookie jar, no device cookie) guesses until the email is
 * delayed: 7 failures, the 7th after the first 2 s delay; the next wait is 4 s. */
async function lockEmail(email: string, alreadyFailed = 0): Promise<APIRequestContext> {
  const attacker = await request.newContext({ baseURL: BASE_URL });
  const guess = () =>
    attacker.post("/api/admin/auth/login", { data: { email, password: BAD, remember: false } });
  for (let i = alreadyFailed; i < 6; i++) expect((await guess()).status()).toBe(401);
  // the 7th guess must wait out the first delay: keep trying until it is a 401 again
  await expect.poll(async () => (await guess()).status(), { timeout: 10_000 }).toBe(401);
  return attacker;
}

test("wrong password says so; the lockout counts down with the button disabled", async ({
  page,
}) => {
  const { email } = await freshAdmin();
  await page.goto("/admin/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(BAD);
  await page.getByTestId("btn-al1").click();
  await expect(page.getByRole("alert")).toContainText("Invalid email or password");

  const attacker = await lockEmail(email, 1);
  await attacker.dispose();
  await page.getByTestId("btn-al1").click();
  const countdown = page.getByTestId("rate-limit-countdown");
  await expect(countdown).toContainText(/Too many attempts — try again in 0:0\d/);
  await expect(page.getByTestId("btn-al1")).toBeDisabled();
  await expect(page.getByTestId("btn-al2")).toBeVisible(); // Forgot password? stays the way out
  // the wait ends on its own and says so
  await expect(countdown).toBeHidden({ timeout: 15_000 });
  await expect(page.getByTestId("rate-limit-announcement")).toHaveText(
    "You can try signing in again.",
  );
  await expect(page.getByTestId("btn-al1")).toBeEnabled();
});

test("five wrong guesses mail the owner an alert (mailhog)", async () => {
  const { email } = await freshAdmin();
  const attacker = await request.newContext({ baseURL: BASE_URL });
  for (let i = 0; i < 5; i++) {
    const r = await attacker.post("/api/admin/auth/login", {
      data: { email, password: BAD, remember: false },
    });
    expect(r.status()).toBe(401);
  }
  await attacker.dispose();
  await expect
    .poll(async () => (await mailsTo(email)).map((m) => m.subject), { timeout: 20_000 })
    .toContain("Several failed sign-ins to your account");
  const alert = (await mailsTo(email)).find((m) => m.subject.startsWith("Several failed"))!;
  expect(alert.body).toContain("/admin/forgot-password");
});

test("a remembered device signs in at once while an attacker holds the email", async ({
  page,
  context,
}) => {
  const { email, password } = await freshAdmin();
  await loginAdminUI(page, email, password, { remember: true });
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  expect(await cookieNames(context)).toContain("sdp_device_admin");
  await page.getByTestId("btn-ig9").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);
  // remembered: logging out keeps the device cookie
  expect(await cookieNames(context)).toContain("sdp_device_admin");

  const attacker = await lockEmail(email);
  // the attacker is delayed ...
  const r = await attacker.post("/api/admin/auth/login", {
    data: { email, password, remember: false },
  });
  expect(r.status()).toBe(429);
  await attacker.dispose();
  // ... the owner's device is not
  await loginAdminUI(page, email, password);
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
});

test("unticked 'Remember this device' leaves no device cookie, before or after logout", async ({
  page,
  context,
}) => {
  const { email, password } = await freshAdmin();
  await page.goto("/admin/login");
  await expect(page.getByTestId("remember-device")).toBeChecked(); // ticked by default
  await loginAdminUI(page, email, password, { remember: false });
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  expect(await cookieNames(context)).not.toContain("sdp_device_admin");
  await page.getByTestId("btn-ig9").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);
  const left = await cookieNames(context);
  expect(left).not.toContain("sdp_device_admin");
  expect(left).not.toContain("sdp_admin");
});

test("a completed reset trusts this browser: sign in at once during an attack; the link is single-use", async ({
  page,
  context,
}) => {
  const { email } = await freshAdmin();
  const attacker = await lockEmail(email);

  await page.goto("/admin/login");
  await page.getByTestId("btn-al2").click();
  await expect(page).toHaveURL(/\/admin\/forgot-password$/);
  await page.getByLabel("Email").fill(email);
  await page.getByTestId("btn-afp1").click();
  const link = await resetLinkFor(email);
  const newPassword = `new-adm-pw-${uniqueMarker()}`;
  await page.goto(link);
  await page.getByLabel("New password").fill(newPassword);
  await page.getByLabel("Confirm password").fill(newPassword);
  await page.getByTestId("btn-admin-reset-confirm").click();
  await expect(page).toHaveURL(/\/admin\/login$/);
  await expect(page.getByRole("status").filter({ hasText: RESET_DONE })).toBeVisible();
  expect(await cookieNames(context)).toContain("sdp_device_admin");

  // the attacker's email delay still holds for anyone without the device cookie
  const blocked = await attacker.post("/api/admin/auth/login", {
    data: { email, password: newPassword, remember: false },
  });
  expect([401, 429]).toContain(blocked.status());
  await attacker.dispose();

  await loginAdminUI(page, email, newPassword);
  await expect(page).toHaveURL(/\/admin\/ingestion$/);

  // the same link again: invalid now
  await page.context().clearCookies({ name: "sdp_admin" });
  await page.goto(link);
  await page.getByLabel("New password").fill(`other-pw-${uniqueMarker()}`);
  await page
    .getByLabel("Confirm password")
    .fill(await page.getByLabel("New password").inputValue());
  await page.getByTestId("btn-admin-reset-confirm").click();
  await expect(page.getByRole("alert")).toContainText(/invalid or has expired/i);
});
