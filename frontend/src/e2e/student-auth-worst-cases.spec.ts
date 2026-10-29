import { expect, request, test } from "@playwright/test";
import {
  BASE_URL,
  RESET_DONE,
  SESSION_ENDED,
  cookieNames,
  loginStudentUI,
  registerStudent,
  resetLinkFor,
} from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * Student sign-in worst cases: lockout countdown, "Remember this device",
 * reset trusting the browser (decisions 1, 2, 9), sessions ended by a reset
 * elsewhere (decision 3), and 429s on register / reset.
 */
const BAD = "definitely-wrong-pw-1";

test("wrong password, then the lockout countdown with Forgot password still offered", async ({
  browser,
  page,
}) => {
  const owner = await browser.newContext();
  const { email } = await registerStudent(owner);
  await owner.close();

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(BAD);
  await page.getByTestId("btn-sl2").click();
  await expect(page.getByRole("alert")).toContainText("Invalid email or password");

  // an attacker elsewhere: 6 more failures, the last after the first 2 s delay
  const attacker = await request.newContext({ baseURL: BASE_URL });
  const guess = () =>
    attacker.post("/api/student/auth/login", { data: { email, password: BAD, remember: false } });
  for (let i = 1; i < 6; i++) expect((await guess()).status()).toBe(401);
  await expect.poll(async () => (await guess()).status(), { timeout: 10_000 }).toBe(401);
  await attacker.dispose();

  await page.getByTestId("btn-sl2").click();
  await expect(page.getByTestId("rate-limit-countdown")).toContainText(
    /Too many attempts — try again in 0:0\d/,
  );
  await expect(page.getByTestId("btn-sl2")).toBeDisabled();
  await expect(page.getByTestId("btn-sl3")).toBeVisible();
  await expect(page.getByTestId("rate-limit-countdown")).toBeHidden({ timeout: 15_000 });
  await expect(page.getByTestId("btn-sl2")).toBeEnabled();
});

test("unticked 'Remember this device': no device cookie, nothing left after Log out", async ({
  browser,
  page,
  context,
}) => {
  const reg = await browser.newContext();
  const { email } = await registerStudent(reg);
  await reg.close();
  await page.goto("/login");
  await expect(page.getByTestId("remember-device")).toBeChecked();
  await loginStudentUI(page, email, undefined, { remember: false });
  await expect(page).toHaveURL(/\/catalog$/);
  expect(await cookieNames(context)).not.toContain("sdp_device_student");
  await page.getByTestId("btn-ct5").click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  const left = await cookieNames(context);
  expect(left).not.toContain("sdp_device_student");
  expect(left).not.toContain("sdp_student");
});

test("reset on this browser: notice, trusted device during an attack, the old device is signed out", async ({
  browser,
  page,
  context,
}) => {
  // the old device: signed in, on Progress
  const laptop = await browser.newContext();
  const { email } = await registerStudent(laptop);
  const laptopPage = await laptop.newPage();
  await laptopPage.goto("/progress");
  await expect(laptopPage.getByRole("heading", { name: "Progress" })).toBeVisible();

  // an attacker delays the email
  const attacker = await request.newContext({ baseURL: BASE_URL });
  const guess = () =>
    attacker.post("/api/student/auth/login", { data: { email, password: BAD, remember: false } });
  for (let i = 0; i < 6; i++) expect((await guess()).status()).toBe(401);

  // the owner resets from this browser
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByTestId("btn-fp1").click();
  await expect(page.getByText(/check your email/i)).toBeVisible();
  const link = await resetLinkFor(email);
  const newPassword = `new-st-pw-${uniqueMarker()}`;
  await page.goto(link);
  await page.getByLabel("New password").fill(newPassword);
  await page.getByLabel("Confirm password").fill(newPassword);
  await page.getByTestId("btn-reset-confirm").click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("status").filter({ hasText: RESET_DONE })).toBeVisible();
  expect(await cookieNames(context)).toContain("sdp_device_student");

  // still delayed for the attacker, not for this browser
  expect((await guess()).status()).toBe(429);
  await attacker.dispose();
  await loginStudentUI(page, email, newPassword);
  await expect(page).toHaveURL(/\/catalog$/);

  // the old device: its next request finds the session gone
  await laptopPage.getByRole("navigation").getByRole("link", { name: "Achievements" }).click();
  await expect(laptopPage).toHaveURL(/\/login$/, { timeout: 20_000 });
  await expect(laptopPage.getByRole("status")).toHaveText(SESSION_ENDED);
  // (signing in again there is subject to the email's delay: it isn't trusted)
  await laptop.close();

  // a used link is refused
  await page.goto(link);
  await page.getByLabel("New password").fill(`other-st-pw-${uniqueMarker()}`);
  await page
    .getByLabel("Confirm password")
    .fill(await page.getByLabel("New password").inputValue());
  await page.getByTestId("btn-reset-confirm").click();
  await expect(page.getByRole("alert")).toContainText(/invalid or has expired/i);
});

test("429 on register and on a reset request: a plain 'try again later'", async ({ page }) => {
  // The real per-IP limits would lock out every parallel spec (one client IP),
  // so the server's 429 is answered here; the limits are covered by the
  // backend suite (test_login_protection: register/reset per IP).
  const tooMany = {
    status: 429,
    contentType: "application/json",
    body: JSON.stringify({
      error: { code: "rate_limited", message: "Too many attempts. Try again later." },
    }),
  };
  await page.route("**/api/student/auth/register", (r) => r.fulfill(tooMany));
  await page.route("**/api/student/auth/password-reset/request", (r) => r.fulfill(tooMany));

  await page.goto("/register");
  await page.getByLabel("Display name").fill("Limited");
  await page.getByLabel("Email").fill(`e2e+lim${uniqueMarker()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("e2e-strong-pw-1234");
  await page.getByLabel("Confirm password").fill("e2e-strong-pw-1234");
  await page.getByTestId("btn-sl1").click();
  await expect(page.getByRole("alert")).toContainText(
    "Too many attempts — please try again later.",
  );
  await expect(page).toHaveURL(/\/register$/);

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(`e2e+lim${uniqueMarker()}@example.com`);
  await page.getByTestId("btn-fp1").click();
  await expect(page.getByRole("alert")).toContainText(
    "Too many attempts — please try again later.",
  );
});

test("a deep link survives the login, query string included", async ({ browser, page }) => {
  const reg = await browser.newContext();
  const { email } = await registerStudent(reg);
  await reg.close();
  await page.goto("/progress?view=all");
  await expect(page).toHaveURL(/\/login$/);
  await loginStudentUI(page, email);
  await expect(page).toHaveURL(/\/progress\?view=all$/);
});
