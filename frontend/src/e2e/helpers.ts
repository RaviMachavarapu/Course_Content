import {
  type APIRequestContext,
  type BrowserContext,
  type Page,
  expect,
  request as pwRequest,
} from "@playwright/test";
import { uniqueMarker } from "./unique";

/**
 * Shared set-up for the worst-case specs: admin work goes through the API (a
 * separate request context, so the browser under test keeps its own cookies),
 * students self-register, mail is read from mailhog. Only for the fixture
 * stack (scripts/e2e.sh): module titles carry `[fixture:…]` fault markers.
 */
export const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "dev-admin-password-123";
export const MAILHOG = process.env.E2E_MAILHOG_URL ?? "http://localhost:8025";
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:5173";

export const SESSION_ENDED = "Session ended — please sign in again.";
export const RESET_DONE =
  "Your password has been changed and this device is now trusted. Other devices have been signed out. Please sign in with your new password.";
export const STUDENT_PASSWORD = "e2e-student-pw-1234";

export type ArtifactType =
  "slide_deck" | "flashcards" | "quiz" | "report" | "infographic" | "audio_overview";

export interface StagingArtifact {
  id: string;
  type: ArtifactType;
  status: string;
  last_error: string | null;
  current_version: { id: string; revision: number; media: { kind: string; url: string }[] } | null;
}

function csrfHeader(state: { cookies: { name: string; value: string }[] }): Record<string, string> {
  const csrf = state.cookies.find((c) => c.name === "sdp_csrf")?.value;
  return csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {};
}

/** An admin API client with its own cookie jar. */
export class AdminApi {
  private constructor(readonly ctx: APIRequestContext) {}

  static async login(email = ADMIN_EMAIL, password = ADMIN_PASSWORD): Promise<AdminApi> {
    const ctx = await pwRequest.newContext({ baseURL: BASE_URL });
    const r = await ctx.post("/api/admin/auth/login", {
      data: { email, password, remember: false },
    });
    expect(r.status(), await r.text()).toBe(200);
    return new AdminApi(ctx);
  }

  async dispose(): Promise<void> {
    await this.ctx.dispose();
  }

  private async send(method: "POST" | "PATCH" | "PUT", path: string, data?: unknown) {
    const headers = csrfHeader(await this.ctx.storageState());
    const r = await this.ctx.fetch(path, { method, data, headers });
    expect(r.ok(), `${method} ${path}: ${r.status()} ${await r.text()}`).toBe(true);
    return r.status() === 204 ? null : ((await r.json()) as Record<string, unknown>);
  }

  async get<T>(path: string): Promise<T> {
    const r = await this.ctx.get(path);
    expect(r.ok(), `GET ${path}: ${r.status()}`).toBe(true);
    return (await r.json()) as T;
  }

  /** A course with one module generating `types` from a link (no PDF). The module
   * title becomes the fixture notebook id: make it unique per test when it
   * carries a counted fault (`[fixture:<fault>=N]`). */
  async createModule(opts: {
    moduleTitle: string;
    types: ArtifactType[];
    courseTitle?: string;
    link?: string;
  }): Promise<{ courseId: string; moduleId: string; courseTitle: string }> {
    const marker = uniqueMarker();
    const courseTitle = opts.courseTitle ?? `E2E Course ${marker}`;
    const course = (await this.send("POST", "/api/admin/courses", {
      title: courseTitle,
      category: "E2E Worst Cases",
    })) as { course: { id: string } };
    const created = (await this.send("POST", `/api/admin/courses/${course.course.id}/modules`, {
      source_url: opts.link ?? `https://www.youtube.com/watch?v=wc${marker}`,
      title: opts.moduleTitle,
      types: opts.types,
    })) as { module: { id: string } };
    return { courseId: course.course.id, moduleId: created.module.id, courseTitle };
  }

  async staging(moduleId: string): Promise<StagingArtifact[]> {
    const r = await this.get<{ artifacts: StagingArtifact[] }>(
      `/api/admin/modules/${moduleId}/staging`,
    );
    return r.artifacts;
  }

  async artifact(moduleId: string, type: ArtifactType): Promise<StagingArtifact> {
    const a = (await this.staging(moduleId)).find((x) => x.type === type);
    expect(a, `no ${type} artifact`).toBeTruthy();
    return a!;
  }

  /** Wait until the given artifact types of the module are ready (or published). */
  async waitReady(
    moduleId: string,
    types: ArtifactType[],
    timeout = 90_000,
  ): Promise<StagingArtifact[]> {
    await expect
      .poll(
        async () =>
          (await this.staging(moduleId))
            .filter((a) => types.includes(a.type))
            .map((a) => `${a.type}:${a.status}`)
            .filter((s) => !s.endsWith(":ready") && !s.endsWith(":published")),
        { timeout, message: `${types.join(", ")} ready` },
      )
      .toEqual([]);
    return this.staging(moduleId);
  }

  async publishModule(moduleId: string): Promise<void> {
    await this.send("POST", `/api/admin/modules/${moduleId}/publish`);
  }

  async redo(artifactId: string, note: string | null = null): Promise<void> {
    await this.send("POST", `/api/admin/artifacts/${artifactId}/redo`, { note });
  }

  async createAdmin(email: string, password: string): Promise<string> {
    const u = (await this.send("POST", "/api/admin/users", {
      email,
      display_name: "E2E Admin",
      password,
    })) as { id: string };
    return u.id;
  }

  async setAdminActive(id: string, active: boolean): Promise<void> {
    await this.send("PATCH", `/api/admin/users/${id}`, { is_active: active });
  }
}

/** Ingest + wait + publish a link module; returns what a student needs. */
export async function publishedCourse(
  types: ArtifactType[],
  moduleTitle = "Unit One",
): Promise<{ admin: AdminApi; courseTitle: string; moduleId: string }> {
  const admin = await AdminApi.login();
  // unique: the title is the fixture notebook id, which keys the counted faults
  const { moduleId, courseTitle } = await admin.createModule({
    moduleTitle: `${moduleTitle} ${uniqueMarker()}`,
    types,
  });
  await admin.waitReady(moduleId, types);
  await admin.publishModule(moduleId);
  return { admin, courseTitle, moduleId };
}

/** Register a fresh student in this browser context (signed in afterwards). */
export async function registerStudent(
  context: BrowserContext,
  name = "E2E Student",
): Promise<{ email: string; password: string }> {
  const email = `e2e+st${uniqueMarker()}@example.com`;
  const r = await context.request.post("/api/student/auth/register", {
    data: { email, password: STUDENT_PASSWORD, display_name: name },
  });
  expect(r.status(), await r.text()).toBe(201);
  return { email, password: STUDENT_PASSWORD };
}

/** The workspace slug of a published course, as the student's catalog lists it. */
export async function courseSlug(context: BrowserContext, title: string): Promise<string> {
  let slug = "";
  await expect
    .poll(async () => {
      const r = await context.request.get("/api/student/courses");
      const data = (await r.json()) as { courses: { title: string; slug: string }[] };
      slug = data.courses.find((c) => c.title === title)?.slug ?? "";
      return slug;
    })
    .not.toBe("");
  return slug;
}

export async function studentArtifact(
  context: BrowserContext,
  slug: string,
  type: ArtifactType,
): Promise<{ id: string; revision: number; version_id: string }> {
  const r = await context.request.get(`/api/student/courses/${slug}`);
  const course = (await r.json()) as {
    modules: { artifacts: { id: string; type: ArtifactType }[] }[];
  };
  const id = course.modules.flatMap((m) => m.artifacts).find((a) => a.type === type)!.id;
  const a = await context.request.get(`/api/student/artifacts/${id}`);
  expect(a.status()).toBe(200);
  return (await a.json()) as { id: string; revision: number; version_id: string };
}

export async function loginAdminUI(
  page: Page,
  email = ADMIN_EMAIL,
  password = ADMIN_PASSWORD,
  { remember = true }: { remember?: boolean } = {},
): Promise<void> {
  if (!page.url().includes("/admin/login")) await page.goto("/admin/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const box = page.getByTestId("remember-device");
  if ((await box.isChecked()) !== remember) await box.setChecked(remember);
  await page.getByTestId("btn-al1").click();
}

export async function loginStudentUI(
  page: Page,
  email: string,
  password = STUDENT_PASSWORD,
  { remember = true }: { remember?: boolean } = {},
): Promise<void> {
  if (!page.url().match(/\/login(\?|$)/)) await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const box = page.getByTestId("remember-device");
  if ((await box.isChecked()) !== remember) await box.setChecked(remember);
  await page.getByTestId("btn-sl2").click();
}

// ---------------------------------------------------------------- mailhog

interface MailItem {
  Content: { Headers: Record<string, string[]>; Body: string };
}

function decodeBody(body: string): string {
  // quoted-printable: soft line breaks and =XX escapes
  return body
    .replace(/=\r\n/g, "")
    .replace(/=([0-9A-F]{2})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)));
}

/** Mails to `address` (newest first), decoded subject + body. */
export async function mailsTo(address: string): Promise<{ subject: string; body: string }[]> {
  const res = await fetch(
    `${MAILHOG}/api/v2/search?kind=to&query=${encodeURIComponent(address)}&limit=50`,
  );
  const data = (await res.json()) as { items: MailItem[] };
  return data.items.map((m) => ({
    subject: (m.Content.Headers.Subject ?? [""])[0]!,
    body: decodeBody(m.Content.Body),
  }));
}

/** The newest reset link mailed to `address`, as a path (same origin). */
export async function resetLinkFor(address: string): Promise<string> {
  let link = "";
  await expect
    .poll(
      async () => {
        for (const m of await mailsTo(address)) {
          const match = m.body.match(/https?:\/\/\S*reset-password\?token=[\w-]+/);
          if (match) return (link = match[0]);
        }
        return "";
      },
      { timeout: 20_000, message: `reset mail for ${address}` },
    )
    .not.toBe("");
  return link.replace(/^https?:\/\/[^/]+/, "");
}

/** Request a reset through the API and return the mailed link's path. */
export async function requestReset(
  ctx: APIRequestContext,
  area: "student" | "admin",
  email: string,
): Promise<string> {
  const before = (await mailsTo(email)).length;
  const r = await ctx.post(`/api/${area}/auth/password-reset/request`, { data: { email } });
  expect(r.status(), await r.text()).toBe(202);
  await expect
    .poll(async () => (await mailsTo(email)).length, { timeout: 20_000 })
    .toBe(before + 1);
  return resetLinkFor(email);
}

export async function cookieNames(context: BrowserContext): Promise<string[]> {
  return (await context.cookies()).map((c) => c.name);
}

/** No sideways scroll at the current viewport. */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(0);
}
