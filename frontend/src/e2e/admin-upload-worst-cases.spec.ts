import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { type Page, type Route, expect, test } from "@playwright/test";
import { loginAdminUI } from "./helpers";
import { uniqueMarker } from "./unique";

/**
 * Ingestion sources and the resumable PDF upload under bad networks: link
 * only, PDF only, both; a chunk lost on the way, a response lost after the
 * server stored it (resume via 409 offset_mismatch), a chunk that keeps failing
 * (row error → Retry), cancelling mid-upload, leaving the page mid-upload, and
 * a file that isn't a PDF.
 */
const SAMPLE = fileURLToPath(new URL("./fixtures/sample.pdf", import.meta.url));
const SAMPLE_BYTES = readFileSync(SAMPLE);
const CHUNK = 8 * 1024 * 1024; // backend/app/schemas/uploads.py CHUNK_SIZE

/** A PDF of two chunks (sample.pdf plus padding after %%EOF). */
function twoChunkPdf(): Buffer {
  return Buffer.concat([SAMPLE_BYTES, Buffer.from("\n%"), Buffer.alloc(CHUNK, 0x41)]);
}

const isChunkPut = (route: Route) =>
  route.request().method() === "PUT" &&
  /\/api\/admin\/uploads\/[0-9a-f-]+\?offset=/.test(route.request().url());

/** True once the page itself aborts the held second-chunk PUT (its AbortController). */
function watchAbort(page: Page): () => boolean {
  let aborted = false;
  page.on("requestfailed", (r) => {
    if (r.method() === "PUT" && r.url().endsWith(`offset=${CHUNK}`)) aborted = true;
  });
  return () => aborted;
}

async function signIn(page: Page): Promise<void> {
  await loginAdminUI(page, undefined, undefined, { remember: false });
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
}

function row(page: Page, name: string) {
  return page.getByRole("listitem").filter({ hasText: name });
}

async function expectUploaded(page: Page, name: string): Promise<void> {
  const r = row(page, name);
  await expect(r).toBeVisible();
  await expect(r.getByRole("progressbar")).toHaveCount(0, { timeout: 60_000 });
  await expect(r.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(r).not.toContainText(/failed|error/i);
}

async function fillModule(page: Page, marker: string, types: string[] = ["report"]): Promise<void> {
  await page.getByLabel("Course title").fill(`Sources E2E ${marker}`);
  await page.getByLabel("Module title").fill("Sources Module");
  for (const t of ["slide_deck", "flashcards", "quiz", "report", "infographic", "audio_overview"]) {
    const box = page.getByTestId(`type-${t}`);
    if (types.includes(t)) await box.check();
    else await box.uncheck();
  }
}

test("link only, PDF only and link + PDF all reach staging with their sources", async ({
  page,
}) => {
  test.slow();
  await signIn(page);

  // link only
  const m1 = uniqueMarker();
  await page.getByLabel("Link (optional)").fill(`https://www.youtube.com/watch?v=lo${m1}`);
  await fillModule(page, m1);
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/, { timeout: 30_000 });
  await expect(page.getByTestId("staging-sources")).toContainText(`lo${m1}`);
  await expect(page.getByTestId("staging-sources")).not.toContainText("PDF");
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="ready"]')).toHaveCount(1, {
    timeout: 60_000,
  });

  // PDF only
  await page.goto("/admin/ingestion");
  const m2 = uniqueMarker();
  await page.getByLabel("PDF files").setInputFiles(SAMPLE);
  await expectUploaded(page, "sample.pdf");
  await fillModule(page, m2);
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/, { timeout: 30_000 });
  await expect(page.getByText("📄 1 PDF")).toBeVisible();
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="ready"]')).toHaveCount(1, {
    timeout: 60_000,
  });

  // link + PDF
  await page.goto("/admin/ingestion");
  const m3 = uniqueMarker();
  await page.getByLabel("Link (optional)").fill(`https://www.youtube.com/watch?v=both${m3}`);
  await page.getByLabel("PDF files").setInputFiles(SAMPLE);
  await expectUploaded(page, "sample.pdf");
  await fillModule(page, m3);
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/modules\/[0-9a-f-]+\/staging$/, { timeout: 30_000 });
  await expect(page.getByTestId("staging-sources")).toContainText(`both${m3}`);
  await expect(page.getByText("📄 1 PDF")).toBeVisible();
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="ready"]')).toHaveCount(1, {
    timeout: 60_000,
  });
  await expect(page.locator('[data-testid="artifact-grid"] [data-status="error"]')).toHaveCount(0);
});

test("a chunk lost on the network is sent again and the upload completes", async ({ page }) => {
  await signIn(page);
  let dropped = 0;
  await page.route("**/api/admin/uploads/**", async (route) => {
    if (isChunkPut(route) && route.request().url().endsWith(`offset=${CHUNK}`) && dropped === 0) {
      dropped += 1;
      return route.abort("connectionreset"); // never reached the server
    }
    return route.fallback();
  });
  await page.getByLabel("PDF files").setInputFiles({
    name: "two-chunks.pdf",
    mimeType: "application/pdf",
    buffer: twoChunkPdf(),
  });
  await expectUploaded(page, "two-chunks.pdf");
  expect(dropped).toBe(1);
});

test("a response lost after the server stored the chunk resumes from the server's offset", async ({
  page,
}) => {
  await signIn(page);
  const puts: string[] = [];
  let lost = 0;
  await page.route("**/api/admin/uploads/**", async (route) => {
    if (!isChunkPut(route)) return route.fallback();
    puts.push(new URL(route.request().url()).searchParams.get("offset")!);
    if (route.request().url().endsWith("offset=0") && lost === 0) {
      lost += 1;
      await route.fetch(); // the server stores the first chunk ...
      return route.abort("connectionreset"); // ... but the browser never hears back
    }
    return route.fallback();
  });
  await page.getByLabel("PDF files").setInputFiles({
    name: "lost-reply.pdf",
    mimeType: "application/pdf",
    buffer: twoChunkPdf(),
  });
  await expectUploaded(page, "lost-reply.pdf");
  // offset 0 twice (the resend got 409 offset_mismatch), then the second chunk
  expect(puts).toEqual(["0", "0", String(CHUNK)]);
});

test("a chunk that keeps failing shows an error with Retry; Retry finishes the upload", async ({
  page,
}) => {
  await signIn(page);
  let failing = true;
  await page.route("**/api/admin/uploads/**", async (route) => {
    if (failing && isChunkPut(route)) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "unavailable", message: "Service unavailable" } }),
      });
    }
    return route.fallback();
  });
  await page.getByLabel("PDF files").setInputFiles(SAMPLE);
  const r = row(page, "sample.pdf");
  // 1 + 3 retries (1, 2, 4 s back-off), then the row gives up
  await expect(r.getByRole("button", { name: "Retry" })).toBeVisible({ timeout: 30_000 });
  await expect(r).toContainText(/Upload failed \(503\)/);
  // while a file is in error, generating is blocked
  await page.getByLabel("Course title").fill(`Blocked ${uniqueMarker()}`);
  await page.getByLabel("Module title").fill("Blocked");
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  await expect(page.getByText(/Retry or remove sample\.pdf/)).toBeVisible();

  failing = false;
  await r.getByRole("button", { name: "Retry" }).click();
  await expectUploaded(page, "sample.pdf");
});

test("cancelling a file mid-upload stops it and removes the row", async ({ page }) => {
  await signIn(page);
  let release: () => void = () => {};
  const held = new Promise<void>((res) => (release = res));
  let after = 0;
  let cancelled = false;
  let secondStarted = false;
  await page.route("**/api/admin/uploads/**", async (route) => {
    if (!isChunkPut(route)) return route.fallback();
    if (cancelled) after += 1;
    if (route.request().url().endsWith(`offset=${CHUNK}`)) {
      secondStarted = true;
      await held; // the second chunk hangs until the test lets go
      return route.abort("aborted").catch(() => {});
    }
    return route.fallback();
  });
  await page.getByLabel("PDF files").setInputFiles({
    name: "cancel-me.pdf",
    mimeType: "application/pdf",
    buffer: twoChunkPdf(),
  });
  const r = row(page, "cancel-me.pdf");
  const abortedByPage = watchAbort(page);
  await expect.poll(() => secondStarted).toBe(true);
  await r.getByRole("button", { name: "Remove cancel-me.pdf" }).click();
  cancelled = true;
  await expect(r).toHaveCount(0);
  // the held request is aborted by the page while still held
  await expect.poll(abortedByPage).toBe(true);
  release();
  // nothing more is sent for that file, and generating needs a source again
  await page.getByLabel("Course title").fill(`Cancelled ${uniqueMarker()}`);
  await page.getByLabel("Module title").fill("Cancelled");
  await page.getByTestId("btn-ig6").click();
  await expect(page).toHaveURL(/\/admin\/ingestion$/);
  expect(after).toBe(0);
});

test("leaving the page mid-upload aborts it", async ({ page }) => {
  await signIn(page);
  let release: () => void = () => {};
  const held = new Promise<void>((res) => (release = res));
  let left = false;
  let putsAfterLeaving = 0;
  let secondStarted = false;
  await page.route("**/api/admin/uploads/**", async (route) => {
    if (!isChunkPut(route)) return route.fallback();
    if (left) putsAfterLeaving += 1;
    if (route.request().url().endsWith(`offset=${CHUNK}`)) {
      secondStarted = true;
      await held;
      return route.abort("aborted").catch(() => {});
    }
    return route.fallback();
  });
  await page.getByLabel("PDF files").setInputFiles({
    name: "leave-me.pdf",
    mimeType: "application/pdf",
    buffer: twoChunkPdf(),
  });
  const abortedByPage = watchAbort(page);
  await expect.poll(() => secondStarted).toBe(true);
  await page.getByRole("navigation").getByRole("link", { name: "Editor" }).click();
  await expect(page).toHaveURL(/\/admin\/editor$/);
  left = true;
  await expect.poll(abortedByPage).toBe(true);
  release();
  // the in-flight request was aborted by the page, not retried
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(putsAfterLeaving).toBe(0);
});

test("a file named .pdf that isn't a PDF is refused with a clear row error", async ({ page }) => {
  await signIn(page);
  await page.getByLabel("PDF files").setInputFiles({
    name: "not-really.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("this is plain text, not a PDF at all\n"),
  });
  const r = row(page, "not-really.pdf");
  await expect(r.getByRole("button", { name: "Retry" })).toBeVisible({ timeout: 30_000 });
  await expect(r).toContainText(/not a PDF/i);
});
